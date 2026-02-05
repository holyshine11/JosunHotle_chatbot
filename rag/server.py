"""
FastAPI 기반 RAG 챗봇 서버
- CORS 허용 (로컬 개발용)
- POST /chat 엔드포인트
- 정적 파일 제공 (UI)
"""

import os
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

from rag.graph import createRAGGraph

# 환경변수에서 포트 가져오기 (Render 호환)
PORT = int(os.getenv("PORT", 8000))

app = FastAPI(title="Josun Hotel 챗봇 API")

# CORS 설정 (로컬 개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RAG 그래프 인스턴스 (싱글톤)
ragGraph = None

def getRagGraph():
    global ragGraph
    if ragGraph is None:
        print("[서버] RAG 그래프 초기화 중...")
        ragGraph = createRAGGraph()
        print("[서버] RAG 그래프 초기화 완료")
    return ragGraph


class ChatRequest(BaseModel):
    hotelId: str
    message: str
    history: Optional[List[dict]] = None


class ChatResponse(BaseModel):
    answer: str
    score: Optional[float] = None
    sources: Optional[List[str]] = None
    needsClarification: Optional[bool] = False  # 명확화 필요 여부
    clarificationOptions: Optional[List[str]] = None  # 선택지 목록


@app.get("/health")
async def health():
    """헬스 체크"""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """채팅 엔드포인트"""
    try:
        rag = getRagGraph()
        result = rag.chat(
            query=request.message,
            hotel=request.hotelId,
            history=request.history  # 대화 히스토리 전달
        )

        return ChatResponse(
            answer=result.get("answer", "응답을 생성할 수 없습니다."),
            score=result.get("score"),
            sources=result.get("sources", []),
            needsClarification=result.get("needs_clarification", False),
            clarificationOptions=result.get("clarification_options", [])
        )
    except Exception as e:
        print(f"[에러] {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 정적 파일 제공 (UI)
UI_DIR = PROJECT_ROOT / "ui"
if UI_DIR.exists():
    # CSS, JS, assets 등 정적 파일
    app.mount("/css", StaticFiles(directory=UI_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=UI_DIR / "js"), name="js")
    app.mount("/assets", StaticFiles(directory=UI_DIR / "assets"), name="assets")

    @app.get("/")
    async def serveIndex():
        """메인 페이지"""
        return FileResponse(UI_DIR / "index.html")

    @app.get("/{path:path}")
    async def serveFallback(path: str):
        """SPA 라우팅 지원 - 모든 경로에서 index.html 반환"""
        filePath = UI_DIR / path
        if filePath.exists() and filePath.is_file():
            return FileResponse(filePath)
        return FileResponse(UI_DIR / "index.html")


if __name__ == "__main__":
    print("=" * 50)
    print("Josun Hotel 챗봇 서버 시작")
    print(f"포트: {PORT}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
