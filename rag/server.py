"""
RAG API 서버
- FastAPI 기반 REST API
- /chat 엔드포인트 제공
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from rag.graph import createRAGGraph


# FastAPI 앱 생성
app = FastAPI(
    title="조선호텔 FAQ 챗봇 API",
    description="조선호텔 FAQ 기반 RAG 챗봇",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RAG 그래프 (지연 로딩)
ragGraph = None


def getRAG():
    """RAG 그래프 싱글톤"""
    global ragGraph
    if ragGraph is None:
        print("[서버] RAG 그래프 초기화 중...")
        ragGraph = createRAGGraph()
        print("[서버] RAG 그래프 초기화 완료")
    return ragGraph


# 요청/응답 모델
class ChatRequest(BaseModel):
    query: str
    hotel: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "query": "체크인 시간이 어떻게 되나요?",
                "hotel": "josun_palace"
            }
        }


class ChatResponse(BaseModel):
    answer: str
    hotel: Optional[str]
    category: Optional[str]
    evidence_passed: bool
    sources: list[str]
    score: float

    class Config:
        json_schema_extra = {
            "example": {
                "answer": "[조선 팰리스] 체크인 시간은 오후 3시, 체크아웃 시간은 오후 12시입니다.",
                "hotel": "josun_palace",
                "category": "체크인/아웃",
                "evidence_passed": True,
                "sources": ["https://jpg.josunhotel.com/about/faq.do"],
                "score": 0.815
            }
        }


class HealthResponse(BaseModel):
    status: str
    version: str


# 엔드포인트
@app.get("/", response_model=HealthResponse)
async def root():
    """헬스 체크"""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health", response_model=HealthResponse)
async def health():
    """헬스 체크"""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """채팅 API"""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="query는 필수입니다.")

    try:
        rag = getRAG()
        result = rag.chat(request.query, request.hotel)
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/hotels")
async def listHotels():
    """호텔 목록"""
    return {
        "hotels": [
            {"key": "josun_palace", "name": "조선 팰리스", "phone": "02-727-7200"},
            {"key": "grand_josun_busan", "name": "그랜드 조선 부산", "phone": "051-922-5000"},
            {"key": "grand_josun_jeju", "name": "그랜드 조선 제주", "phone": "064-735-8000"},
            {"key": "lescape", "name": "레스케이프", "phone": "02-317-4000"},
            {"key": "gravity_pangyo", "name": "그래비티 판교", "phone": "031-539-4800"},
        ]
    }


def main():
    """서버 실행"""
    import uvicorn
    print("\n[조선호텔 FAQ 챗봇 서버]")
    print("=" * 40)
    print("URL: http://localhost:8000")
    print("Docs: http://localhost:8000/docs")
    print("=" * 40)

    # 서버 시작 전 RAG 초기화
    getRAG()

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
