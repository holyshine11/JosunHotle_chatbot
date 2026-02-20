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
import threading
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Optional, Callable

# Groq 사용 여부 (환경변수로 제어)
USE_GROQ = os.getenv("USE_GROQ", "false").lower() == "true"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Ollama timeout (초)
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_RETRIES = 2

# Ollama 성능 최적화 설정
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "exaone3.5:7.8b")  # LG EXAONE 3.5 한국어 최적화 모델
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))  # 기본 32768 → 4096 (KV 캐시 1/8)
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "60m")  # 60분 메모리 상주 (기본 5분)
OLLAMA_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", "8"))  # CPU 스레드 수 (M5 10코어)

# LLM 응답 캐시 설정
LLM_CACHE_ENABLED = os.getenv("LLM_CACHE_ENABLED", "true").lower() == "true"
LLM_CACHE_SIZE = int(os.getenv("LLM_CACHE_SIZE", "100"))  # 최대 100개 쿼리 캐싱

# 스트리밍 콜백 (스레드별 독립)
_streamLocal = threading.local()


def setStreamCallback(callback: Callable[[str], None]):
    """현재 스레드의 토큰 스트리밍 콜백 설정"""
    _streamLocal.callback = callback


def clearStreamCallback():
    """현재 스레드의 토큰 스트리밍 콜백 해제"""
    _streamLocal.callback = None


def _getStreamCallback() -> Optional[Callable]:
    return getattr(_streamLocal, 'callback', None)


def _generateCacheKey(prompt: str, system: str, temperature: float, maxTokens: int = 512) -> str:
    """캐시 키 생성 (프롬프트 + 시스템 + temperature + maxTokens 해시)"""
    content = f"{prompt}|{system}|{temperature}|{maxTokens}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()


# LRU 캐시 데코레이터를 사용한 내부 호출 함수
@lru_cache(maxsize=LLM_CACHE_SIZE)
def _cachedLLMCall(cacheKey: str, prompt: str, system: str, temperature: float, maxTokens: int = 512) -> str:
    """캐시 가능한 LLM 호출 (내부용)"""
    if USE_GROQ and GROQ_API_KEY:
        return _callGroq(prompt, system, temperature, maxTokens)
    else:
        return _callOllamaWithTimeout(prompt, system, temperature, maxTokens)


def callLLM(prompt: str, system: str = "", temperature: float = 0.1, maxTokens: int = 512, numCtx: int = None) -> str:
    """
    LLM 호출 (Ollama 또는 Groq) - 캐싱 지원

    Args:
        prompt: 사용자 프롬프트
        system: 시스템 프롬프트
        temperature: 생성 온도 (0.0 ~ 1.0)
        maxTokens: 최대 생성 토큰 수 (기본 512)
        numCtx: 컨텍스트 윈도우 크기 (None이면 기본값 OLLAMA_NUM_CTX 사용)

    Returns:
        생성된 텍스트
    """
    startTime = time.time()
    effectiveCtx = numCtx or OLLAMA_NUM_CTX

    # 스트리밍 콜백 활성 → 캐시 우회, 직접 스트리밍
    streamCallback = _getStreamCallback()
    if streamCallback:
        try:
            result = _callOllamaStream(prompt, system, temperature, maxTokens, streamCallback, effectiveCtx)
            elapsed = time.time() - startTime
            print(f"[LLM 스트리밍] 완료 ({elapsed:.1f}s, maxTokens={maxTokens}, numCtx={effectiveCtx})")
            return result
        except Exception as e:
            print(f"[LLM 스트리밍] 실패, 일반 호출로 전환: {e}")
            # 스트리밍 실패 시 일반 호출로 폴백

    if not LLM_CACHE_ENABLED:
        if USE_GROQ and GROQ_API_KEY:
            result = _callGroq(prompt, system, temperature, maxTokens)
        else:
            result = _callOllamaWithTimeout(prompt, system, temperature, maxTokens, effectiveCtx)
        elapsed = time.time() - startTime
        print(f"[LLM] 호출 완료 ({elapsed:.1f}s, maxTokens={maxTokens}, numCtx={effectiveCtx})")
        return result

    # 캐싱 활성화 시
    cacheKey = _generateCacheKey(prompt, system, temperature, maxTokens)

    try:
        result = _cachedLLMCall(cacheKey, prompt, system, temperature, maxTokens)
        elapsed = time.time() - startTime
        cacheInfo = _cachedLLMCall.cache_info()
        hitRate = (cacheInfo.hits / (cacheInfo.hits + cacheInfo.misses) * 100) if (cacheInfo.hits + cacheInfo.misses) > 0 else 0

        if cacheInfo.hits > 0:
            print(f"[LLM 캐시] HIT ({elapsed:.1f}s, 적중률: {hitRate:.1f}%)")

        return result
    except (TimeoutError, FuturesTimeout) as e:
        # LLM 타임아웃은 재시도 무의미 (Ollama 과부하) → 즉시 전파
        print(f"[LLM] 타임아웃 — 재시도 없이 즉시 실패: {e}")
        raise
    except Exception as e:
        print(f"[LLM 캐시] 오류, 직접 호출로 전환: {e}")
        if USE_GROQ and GROQ_API_KEY:
            return _callGroq(prompt, system, temperature, maxTokens)
        else:
            return _callOllamaWithTimeout(prompt, system, temperature, maxTokens, effectiveCtx)


def _callOllamaWithTimeout(prompt: str, system: str, temperature: float, maxTokens: int = 512, numCtx: int = None) -> str:
    """Ollama 호출 (timeout + retry, shutdown 대기 없음)"""
    effectiveCtx = numCtx or OLLAMA_NUM_CTX
    lastError = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_callOllama, prompt, system, temperature, maxTokens, effectiveCtx)
            result = future.result(timeout=LLM_TIMEOUT)
            executor.shutdown(wait=False)
            return result
        except FuturesTimeout:
            lastError = f"Ollama 응답 시간 초과 ({LLM_TIMEOUT}초)"
            print(f"[LLM] timeout (시도 {attempt}/{LLM_MAX_RETRIES})")
            # shutdown(wait=False): 타임아웃된 스레드 대기하지 않음
            executor.shutdown(wait=False)
        except Exception as e:
            lastError = str(e)
            print(f"[LLM] 오류 (시도 {attempt}/{LLM_MAX_RETRIES}): {e}")
            executor.shutdown(wait=False)
        if attempt < LLM_MAX_RETRIES:
            time.sleep(1)

    raise TimeoutError(f"LLM 호출 실패 ({LLM_MAX_RETRIES}회 시도): {lastError}")


def _callOllama(prompt: str, system: str, temperature: float, maxTokens: int = 512, numCtx: int = None) -> str:
    """Ollama 로컬 LLM 호출"""
    import ollama

    effectiveCtx = numCtx or OLLAMA_NUM_CTX
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=messages,
        options={
            "temperature": temperature,
            "num_predict": maxTokens,
            "num_ctx": effectiveCtx,
            "num_thread": OLLAMA_NUM_THREAD,
            "num_gpu": -1,       # GPU(Metal) 전체 레이어 오프로드
            "num_batch": 512,    # 프롬프트 처리 배치 크기 (기본 128→512)
        },
        keep_alive=OLLAMA_KEEP_ALIVE,
    )

    return response["message"]["content"]


def _callOllamaStream(prompt: str, system: str, temperature: float,
                       maxTokens: int, callback: Callable[[str], None],
                       numCtx: int = None) -> str:
    """Ollama 스트리밍 호출 (토큰 단위 콜백)"""
    import ollama

    effectiveCtx = numCtx or OLLAMA_NUM_CTX
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=messages,
        options={
            "temperature": temperature,
            "num_predict": maxTokens,
            "num_ctx": effectiveCtx,
            "num_thread": OLLAMA_NUM_THREAD,
            "num_gpu": -1,       # GPU(Metal) 전체 레이어 오프로드
            "num_batch": 512,    # 프롬프트 처리 배치 크기 (기본 128→512)
        },
        keep_alive=OLLAMA_KEEP_ALIVE,
        stream=True,
    )

    fullResponse = ""
    for chunk in response:
        token = chunk["message"]["content"]
        fullResponse += token
        callback(token)

    return fullResponse


def _callGroq(prompt: str, system: str, temperature: float, maxTokens: int = 512) -> str:
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
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": maxTokens
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
        return True, f"Groq API ({GROQ_MODEL})"

    try:
        import ollama
        ollama.list()
        return True, f"Ollama ({OLLAMA_MODEL})"
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
