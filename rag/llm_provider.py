"""
LLM Provider 추상화
- 로컬: Ollama (timeout 30초)
- 클라우드: Groq API (무료 tier)
- 최대 2회 재시도
- LRU 캐싱: 동일/유사 쿼리 재사용으로 응답 속도 향상
"""

import os
import time
import hashlib
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Optional

# Groq 사용 여부 (환경변수로 제어)
USE_GROQ = os.getenv("USE_GROQ", "false").lower() == "true"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Ollama timeout (초)
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_RETRIES = 2

# LLM 응답 캐시 설정
LLM_CACHE_ENABLED = os.getenv("LLM_CACHE_ENABLED", "true").lower() == "true"
LLM_CACHE_SIZE = int(os.getenv("LLM_CACHE_SIZE", "100"))  # 최대 100개 쿼리 캐싱


def _generateCacheKey(prompt: str, system: str, temperature: float) -> str:
    """캐시 키 생성 (프롬프트 + 시스템 + temperature 해시)"""
    content = f"{prompt}|{system}|{temperature}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()


# LRU 캐시 데코레이터를 사용한 내부 호출 함수
@lru_cache(maxsize=LLM_CACHE_SIZE)
def _cachedLLMCall(cacheKey: str, prompt: str, system: str, temperature: float) -> str:
    """캐시 가능한 LLM 호출 (내부용)"""
    if USE_GROQ and GROQ_API_KEY:
        return _callGroq(prompt, system, temperature)
    else:
        return _callOllamaWithTimeout(prompt, system, temperature)


def callLLM(prompt: str, system: str = "", temperature: float = 0.1) -> str:
    """
    LLM 호출 (Ollama 또는 Groq) - 캐싱 지원

    Args:
        prompt: 사용자 프롬프트
        system: 시스템 프롬프트
        temperature: 생성 온도 (0.0 ~ 1.0)

    Returns:
        생성된 텍스트
    """
    if not LLM_CACHE_ENABLED:
        # 캐싱 비활성화 시 직접 호출
        if USE_GROQ and GROQ_API_KEY:
            return _callGroq(prompt, system, temperature)
        else:
            return _callOllamaWithTimeout(prompt, system, temperature)

    # 캐싱 활성화 시
    cacheKey = _generateCacheKey(prompt, system, temperature)

    # 캐시 히트 체크
    try:
        result = _cachedLLMCall(cacheKey, prompt, system, temperature)
        cacheInfo = _cachedLLMCall.cache_info()
        hitRate = (cacheInfo.hits / (cacheInfo.hits + cacheInfo.misses) * 100) if (cacheInfo.hits + cacheInfo.misses) > 0 else 0

        if cacheInfo.hits > 0:
            print(f"[LLM 캐시] HIT (적중률: {hitRate:.1f}%, {cacheInfo.hits}/{cacheInfo.hits + cacheInfo.misses})")

        return result
    except Exception as e:
        # 캐시 오류 시 직접 호출로 폴백
        print(f"[LLM 캐시] 오류, 직접 호출로 전환: {e}")
        if USE_GROQ and GROQ_API_KEY:
            return _callGroq(prompt, system, temperature)
        else:
            return _callOllamaWithTimeout(prompt, system, temperature)


def _callOllamaWithTimeout(prompt: str, system: str, temperature: float) -> str:
    """Ollama 호출 (timeout + retry)"""
    lastError = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_callOllama, prompt, system, temperature)
                result = future.result(timeout=LLM_TIMEOUT)
                return result
        except FuturesTimeout:
            lastError = f"Ollama 응답 시간 초과 ({LLM_TIMEOUT}초)"
            print(f"[LLM] timeout (시도 {attempt}/{LLM_MAX_RETRIES})")
        except Exception as e:
            lastError = str(e)
            print(f"[LLM] 오류 (시도 {attempt}/{LLM_MAX_RETRIES}): {e}")
        if attempt < LLM_MAX_RETRIES:
            time.sleep(1)

    raise TimeoutError(f"LLM 호출 실패 ({LLM_MAX_RETRIES}회 시도): {lastError}")


def _callOllama(prompt: str, system: str, temperature: float) -> str:
    """Ollama 로컬 LLM 호출"""
    import ollama

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = ollama.chat(
        model="qwen2.5:7b",
        messages=messages,
        options={"temperature": temperature}
    )

    return response["message"]["content"]


def _callGroq(prompt: str, system: str, temperature: float) -> str:
    """Groq API 호출 (클라우드 배포용)"""
    import requests

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    data = {
        "model": "llama-3.1-8b-instant",  # 무료 tier에서 사용 가능
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024
    }

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=data,
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(f"Groq API 오류: {response.status_code} - {response.text}")

    result = response.json()
    return result["choices"][0]["message"]["content"]


def checkLLMAvailable() -> tuple[bool, str]:
    """
    LLM 사용 가능 여부 확인

    Returns:
        (사용 가능 여부, 사용 중인 provider 이름)
    """
    if USE_GROQ and GROQ_API_KEY:
        return True, "Groq API (llama-3.1-8b)"

    try:
        import ollama
        ollama.list()
        return True, "Ollama (qwen2.5:7b)"
    except Exception:
        return False, "None"


def getCacheStats() -> dict:
    """캐시 통계 반환"""
    if not LLM_CACHE_ENABLED:
        return {"enabled": False}

    cacheInfo = _cachedLLMCall.cache_info()
    hitRate = (cacheInfo.hits / (cacheInfo.hits + cacheInfo.misses) * 100) if (cacheInfo.hits + cacheInfo.misses) > 0 else 0

    return {
        "enabled": True,
        "hits": cacheInfo.hits,
        "misses": cacheInfo.misses,
        "hit_rate": round(hitRate, 2),
        "current_size": cacheInfo.currsize,
        "max_size": cacheInfo.maxsize,
    }


def clearCache():
    """캐시 초기화"""
    if LLM_CACHE_ENABLED:
        _cachedLLMCall.cache_clear()
        print("[LLM 캐시] 초기화 완료")
