"""
LLM Provider 추상화
- 로컬: Ollama (timeout 30초)
- 클라우드: Groq API (무료 tier)
- 최대 2회 재시도
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Optional

# Groq 사용 여부 (환경변수로 제어)
USE_GROQ = os.getenv("USE_GROQ", "false").lower() == "true"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Ollama timeout (초)
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_RETRIES = 2


def callLLM(prompt: str, system: str = "", temperature: float = 0.1) -> str:
    """
    LLM 호출 (Ollama 또는 Groq)

    Args:
        prompt: 사용자 프롬프트
        system: 시스템 프롬프트
        temperature: 생성 온도 (0.0 ~ 1.0)

    Returns:
        생성된 텍스트
    """
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
