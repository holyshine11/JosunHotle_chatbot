"""
FastAPI 기반 RAG 챗봇 서버
- CORS 도메인 제한 (환경변수 ALLOWED_ORIGINS)
- POST /chat 엔드포인트
- 정적 파일 제공 (UI)
- 헬스 체크 (LLM/Chroma/세션 상태)
"""

import os
import sys
import io
import json
import asyncio
import traceback
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

from rag.graph import createRAGGraph

# 환경변수에서 포트 가져오기 (Render 호환)
PORT = int(os.getenv("PORT", 8000))

# CORS 허용 도메인 (환경변수 ALLOWED_ORIGINS 설정 시 제한, 미설정 시 전체 허용)
_envOrigins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = _envOrigins.split(",") if _envOrigins else ["*"]

app = FastAPI(title="Josun Hotel 챗봇 API")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True if ALLOWED_ORIGINS != ["*"] else False,
    allow_methods=["GET", "POST", "OPTIONS"],
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
    message: str = ""
    history: Optional[List[dict]] = None
    sessionId: Optional[str] = None  # 세션 ID (없으면 자동 생성)

    def hasValidMessage(self) -> bool:
        return bool(self.message and self.message.strip())


class ChatResponse(BaseModel):
    answer: str
    score: Optional[float] = None
    sources: Optional[List[str]] = None
    needsClarification: Optional[bool] = False  # 명확화 필요 여부
    clarificationOptions: Optional[List[str]] = None  # 선택지 목록
    clarificationType: Optional[str] = None  # 명확화 타입 (시간/가격/예약/위치/반려동물/어린이)
    originalQuery: Optional[str] = None  # 명확화 트리거된 원본 질문
    sessionId: Optional[str] = None  # 세션 ID 반환


@app.get("/health")
async def health():
    """헬스 체크 (LLM/Chroma/세션 상태 포함)"""
    status = {"status": "ok"}

    # LLM 상태 확인
    try:
        from rag.llm_provider import checkLLMAvailable
        llmOk, llmProvider = checkLLMAvailable()
        status["llm"] = {"available": llmOk, "provider": llmProvider}
    except Exception:
        status["llm"] = {"available": False, "provider": "error"}

    # Chroma 상태 확인
    try:
        rag = getRagGraph()
        chunkCount = rag.collection.count() if hasattr(rag, 'collection') else -1
        status["chroma"] = {"available": True, "chunks": chunkCount}
    except Exception:
        status["chroma"] = {"available": False, "chunks": 0}

    # 세션 상태 확인
    try:
        from rag.session import sessionStore
        sessionCount = len(sessionStore._sessions)
        status["sessions"] = {"active": sessionCount, "max": sessionStore.MAX_SESSIONS}
    except Exception:
        status["sessions"] = {"active": 0, "max": 0}

    # 전체 상태 판정
    if not status.get("llm", {}).get("available") or not status.get("chroma", {}).get("available"):
        status["status"] = "degraded"

    return status


@app.post("/chat/stream")
async def chatStream(request: ChatRequest):
    """SSE 스트리밍 채팅 엔드포인트"""
    async def eventGenerator():
        try:
            from rag.session import sessionStore
            sessionCtx = sessionStore.getOrCreate(request.sessionId)

            # 즉시 status 이벤트 전송 (체감 속도 향상)
            yield f"data: {json.dumps({'event': 'status', 'stage': 'analyzing', 'message': '질문을 분석하고 있습니다...'}, ensure_ascii=False)}\n\n"

            rag = getRagGraph()

            # asyncio.to_thread로 이벤트 루프 블로킹 방지
            result = await asyncio.to_thread(
                rag.chat,
                query=request.message,
                hotel=request.hotelId,
                history=request.history,
                sessionCtx=sessionCtx
            )

            answer = result.get("answer", "응답을 생성할 수 없습니다.")
            needsClarification = result.get("needs_clarification", False)

            if needsClarification:
                yield f"data: {json.dumps({'event': 'clarification', 'answer': answer, 'options': result.get('clarification_options', []), 'type': result.get('clarification_type'), 'originalQuery': result.get('original_query')}, ensure_ascii=False)}\n\n"
            else:
                # 답변을 단어 단위로 스트리밍 (타이핑 효과)
                words = answer.split()
                for i, word in enumerate(words):
                    separator = ' ' if i < len(words) - 1 else ''
                    yield f"data: {json.dumps({'event': 'token', 'text': word + separator}, ensure_ascii=False)}\n\n"
                    if i % 3 == 0:
                        await asyncio.sleep(0.02)

            # 완료 이벤트 (출처, 점수 등 메타데이터)
            yield f"data: {json.dumps({'event': 'done', 'sources': result.get('sources', []), 'score': result.get('score'), 'sessionId': sessionCtx.session_id}, ensure_ascii=False)}\n\n"

        except Exception as e:
            print(f"[스트리밍 에러] {e}")
            traceback.print_exc()
            yield f"data: {json.dumps({'event': 'error', 'message': '요청을 처리하는 중 오류가 발생했습니다.'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        eventGenerator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """채팅 엔드포인트"""
    try:
        from rag.session import sessionStore

        # 세션 컨텍스트 조회/생성
        sessionCtx = sessionStore.getOrCreate(request.sessionId)

        rag = getRagGraph()

        # asyncio.to_thread로 이벤트 루프 블로킹 방지
        result = await asyncio.to_thread(
            rag.chat,
            query=request.message,
            hotel=request.hotelId,
            history=request.history,
            sessionCtx=sessionCtx
        )

        return ChatResponse(
            answer=result.get("answer", "응답을 생성할 수 없습니다."),
            score=result.get("score"),
            sources=result.get("sources", []),
            needsClarification=result.get("needs_clarification", False),
            clarificationOptions=result.get("clarification_options", []),
            clarificationType=result.get("clarification_type"),
            originalQuery=result.get("original_query"),
            sessionId=sessionCtx.session_id,
        )
    except Exception as e:
        # 내부 에러 상세는 서버 로그에만 기록, 클라이언트에는 일반 메시지
        print(f"[에러] {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="요청을 처리하는 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
        )


# ========== TTS 엔드포인트 (Edge TTS) ==========
TTS_VOICE = "ko-KR-HyunsuMultilingualNeural"  # 젊고 부드러운 남성 음성

class TTSRequest(BaseModel):
    text: str
    rate: Optional[str] = "+0%"  # 속도 조절 (-50%~+100%)


@app.post("/tts")
async def tts(request: TTSRequest):
    """텍스트를 음성(MP3)으로 변환"""
    try:
        import edge_tts

        text = request.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="텍스트가 비어 있습니다.")
        if len(text) > 2000:
            text = text[:2000]  # 너무 긴 텍스트 제한

        communicate = edge_tts.Communicate(text, TTS_VOICE, rate=request.rate)

        # 메모리에 MP3 생성
        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])

        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"}
        )
    except ImportError:
        raise HTTPException(status_code=501, detail="edge-tts 패키지가 설치되지 않았습니다.")
    except Exception as e:
        print(f"[TTS 에러] {e}")
        raise HTTPException(status_code=500, detail="음성 생성에 실패했습니다.")


# 정적 파일 제공 (UI)
UI_DIR = PROJECT_ROOT / "ui"
if UI_DIR.exists():
    # CSS, JS, assets 등 정적 파일 (존재하는 경우만 마운트)
    if (UI_DIR / "css").exists():
        app.mount("/css", StaticFiles(directory=UI_DIR / "css"), name="css")
    if (UI_DIR / "js").exists():
        app.mount("/js", StaticFiles(directory=UI_DIR / "js"), name="js")
    if (UI_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=UI_DIR / "assets"), name="assets")
    if (UI_DIR / "static").exists():
        app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")

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
    print(f"CORS 허용: {ALLOWED_ORIGINS}")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
