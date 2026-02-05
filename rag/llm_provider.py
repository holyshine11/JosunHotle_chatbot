"""
LLM Provider 추상화
- 로컬: Ollama
- 클라우드: Groq API (무료 tier)
"""

import os
from typing import Optional

# Groq 사용 여부 (환경변수로 제어)
USE_GROQ = os.getenv("USE_GROQ", "false").lower() == "true"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


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
        return _callOllama(prompt, system, temperature)


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
    except:
        return False, "None"
