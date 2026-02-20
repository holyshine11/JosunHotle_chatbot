# ============================================================
# 조선호텔 챗봇 - Production Dockerfile
# 구성: Python 3.11 slim + PyTorch CPU + ML 모델 프리로드
# 예상 이미지 크기: ~3.5GB (ML 모델 포함)
# ============================================================

FROM python:3.11-slim AS base

WORKDIR /app

# 시스템 패키지 (빌드 도구 + curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

# PyTorch CPU-only (CUDA 제외 → 이미지 ~1.5GB 절감)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Python 의존성
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ML 모델 사전 다운로드 (빌드 캐시 레이어 활용)
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('intfloat/multilingual-e5-small'); \
print('[빌드] Embedding 모델 다운로드 완료')"

RUN python -c "\
from sentence_transformers import CrossEncoder; \
CrossEncoder('BAAI/bge-reranker-v2-m3'); \
print('[빌드] Reranker 모델 다운로드 완료')"

# 앱 코드 복사 (런타임에 필요한 것만)
COPY rag/ rag/
COPY pipeline/__init__.py pipeline/__init__.py
COPY pipeline/indexer.py pipeline/indexer.py
COPY data/index/ data/index/
COPY data/supplementary/ data/supplementary/
COPY ui/ ui/

# 로그 디렉토리 생성
RUN mkdir -p data/logs

# 환경변수 기본값
ENV PORT=8000
ENV USE_GROQ=true
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000

# 헬스체크 (60초 유예 → 모델 로딩 대기)
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "rag/server.py"]
