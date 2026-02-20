"""
FastAPI 기반 RAG 챗봇 서버
- CORS 도메인 제한 (환경변수 ALLOWED_ORIGINS)
- POST /chat 엔드포인트
- 정적 파일 제공 (UI)
- 헬스 체크 (LLM/Chroma/세션 상태)
"""

import os
import sys
import json
import time
import asyncio
import threading
import traceback
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import re as _re

from fastapi import FastAPI, HTTPException, Query
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


@app.on_event("startup")
async def warmup():
    """서버 시작 시 모든 모델 사전 로딩 (cold start 제거)"""
    import time
    print("[Warm-up] 모델 사전 로딩 시작...")
    t0 = time.time()

    # 1. RAG 그래프 초기화 (Embedding 모델 + Chroma + BM25)
    getRagGraph()

    # 2. 리랭커 모델 사전 로딩
    try:
        from rag.reranker import getReranker
        reranker = getReranker()
        reranker._loadModel()
        print(f"[Warm-up] 리랭커 로딩 완료")
    except Exception as e:
        print(f"[Warm-up] 리랭커 로딩 실패: {e}")

    # 3. Ollama LLM 모델 warm-up (keep_alive=-1로 메모리 상주)
    try:
        from rag.llm_provider import callLLM
        await asyncio.to_thread(callLLM, prompt="안녕", system="", temperature=0.0, maxTokens=5)
        print(f"[Warm-up] LLM 모델 로딩 완료")
    except Exception as e:
        print(f"[Warm-up] LLM warm-up 실패 (서버는 정상 작동): {e}")

    elapsed = time.time() - t0
    print(f"[Warm-up] 전체 완료 ({elapsed:.1f}s)")

    # TTS는 브라우저 Web Speech API로 전환됨 (서버 측 Edge TTS 제거)


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
    """SSE 스트리밍 채팅 엔드포인트 (실시간 LLM 토큰 + TTS 병렬 생성)"""

    # 노드 완료 → 다음 단계 시작 메시지 (forward-looking)
    STAGE_MESSAGES = {
        "clarification_check": "관련 정보를 검색하고 있습니다...",  # → retrieve 시작
        "evidence_gate": "답변을 생성하고 있습니다...",            # → answer_compose 시작
        "answer_compose": "답변을 검증하고 있습니다...",           # → answer_verify 시작
    }

    async def eventGenerator():
        try:
            from rag.session import sessionStore
            from rag.llm_provider import setStreamCallback, clearStreamCallback
            sessionCtx = sessionStore.getOrCreate(request.sessionId)

            # 즉시 첫 상태 이벤트 전송
            yield f"data: {json.dumps({'event': 'status', 'stage': 'analyzing', 'message': '질문을 분석하고 있습니다...'}, ensure_ascii=False)}\n\n"

            rag = getRagGraph()
            loop = asyncio.get_running_loop()
            progressQueue = asyncio.Queue()
            gotRealTokens = [False]  # 실시간 LLM 토큰 수신 여부
            streamedTokens = []  # 스트리밍된 토큰 추적 (검증 후 비교용)

            # LLM 토큰 콜백 (answerCompose에서만 호출됨)
            def onToken(token):
                gotRealTokens[0] = True
                streamedTokens.append(token)
                loop.call_soon_threadsafe(
                    progressQueue.put_nowait, ("token", token)
                )

            # 노드 진행 상황 콜백 (파이프라인 스레드에서 호출)
            def onProgress(nodeName):
                # evidence_gate 완료 → answerCompose 시작 직전에만 스트리밍 활성화
                if nodeName == "evidence_gate":
                    setStreamCallback(onToken)
                # answer_compose 완료 → 스트리밍 비활성화 (queryRewrite 등 다른 LLM은 캐시 유지)
                elif nodeName == "answer_compose":
                    clearStreamCallback()

                msg = STAGE_MESSAGES.get(nodeName)
                if msg:
                    loop.call_soon_threadsafe(
                        progressQueue.put_nowait, ("stage", msg)
                    )

            # 파이프라인 실행 (별도 스레드, 스트리밍은 onProgress에서 동적 제어)
            def runPipeline():
                try:
                    result = rag.chatWithProgress(
                        query=request.message,
                        hotel=request.hotelId,
                        history=request.history,
                        sessionCtx=sessionCtx,
                        progressCallback=onProgress
                    )
                    clearStreamCallback()  # 안전 정리
                    loop.call_soon_threadsafe(
                        progressQueue.put_nowait, ("result", result)
                    )
                except Exception as e:
                    clearStreamCallback()
                    print(f"[파이프라인 에러] {e}")
                    traceback.print_exc()
                    loop.call_soon_threadsafe(
                        progressQueue.put_nowait, ("error", str(e))
                    )

            thread = threading.Thread(target=runPipeline, daemon=True)
            thread.start()

            # 진행 상황 + 토큰 이벤트 전달 (파이프라인 완료까지)
            result = None
            lastMsg = "질문을 분석하고 있습니다..."  # 초기 메시지 중복 방지
            while True:
                event = await asyncio.wait_for(progressQueue.get(), timeout=60)
                eventType, data = event

                if eventType == "stage":
                    if data != lastMsg:
                        lastMsg = data
                        yield f"data: {json.dumps({'event': 'status', 'stage': 'processing', 'message': data}, ensure_ascii=False)}\n\n"
                elif eventType == "token":
                    yield f"data: {json.dumps({'event': 'token', 'text': data}, ensure_ascii=False)}\n\n"
                elif eventType == "result":
                    result = data
                    break
                elif eventType == "error":
                    yield f"data: {json.dumps({'event': 'error', 'message': '요청을 처리하는 중 오류가 발생했습니다.'}, ensure_ascii=False)}\n\n"
                    return

            answer = result.get("answer", "응답을 생성할 수 없습니다.")
            needsClarification = result.get("needs_clarification", False)

            if needsClarification:
                yield f"data: {json.dumps({'event': 'clarification', 'answer': answer, 'options': result.get('clarification_options', []), 'type': result.get('clarification_type'), 'originalQuery': result.get('original_query')}, ensure_ascii=False)}\n\n"
            elif not gotRealTokens[0]:
                # FAQ 직접 추출 등 LLM 미사용 → 기존 단어 단위 스트리밍
                words = answer.split()
                for i, word in enumerate(words):
                    separator = ' ' if i < len(words) - 1 else ''
                    yield f"data: {json.dumps({'event': 'token', 'text': word + separator}, ensure_ascii=False)}\n\n"
                    if i % 3 == 0:
                        await asyncio.sleep(0.02)
            elif gotRealTokens[0]:
                # LLM 토큰이 스트리밍되었으나, 검증 후 답변이 크게 변경된 경우
                import re as _re
                streamedText = ''.join(streamedTokens)
                streamedClean = _re.sub(r'\s*\[REF:[\d,\s]+\]', '', streamedText).strip()
                answerCore = _re.split(r'\n\n참고\s*정보', answer)[0].strip()

                # 스트리밍 텍스트와 최종 답변의 첫 50자 비교
                isReplaced = (
                    len(streamedClean) > 0 and len(answerCore) > 0
                    and not answerCore.startswith(streamedClean[:min(50, len(streamedClean))])
                )

                if isReplaced:
                    # 검증에서 거부됨 → replace 이벤트로 스트리밍 텍스트 초기화 후 재전송
                    print(f"[스트리밍] 검증 후 답변 변경 감지 → replace 이벤트 전송")
                    yield f"data: {json.dumps({'event': 'replace'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.05)
                    words = answer.split()
                    for i, word in enumerate(words):
                        separator = ' ' if i < len(words) - 1 else ''
                        yield f"data: {json.dumps({'event': 'token', 'text': word + separator}, ensure_ascii=False)}\n\n"
                        if i % 3 == 0:
                            await asyncio.sleep(0.02)

            # done 이벤트 즉시 전송 (TTS 대기 없이 UI 즉시 업데이트)
            doneData = {
                'event': 'done',
                'answer': answer,
                'sources': result.get('sources', []),
                'score': result.get('score'),
                'sessionId': sessionCtx.session_id,
            }
            yield f"data: {json.dumps(doneData, ensure_ascii=False)}\n\n"

        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'event': 'error', 'message': '응답 시간이 초과되었습니다.'}, ensure_ascii=False)}\n\n"
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



# ========== TTS (Edge TTS 문장 단위 스트리밍) ==========
# 허용 음성 화이트리스트 (ko-KR Neural)
EDGE_TTS_VOICES = {
    "ko-KR-SunHiNeural", "ko-KR-InJoonNeural",
    "ko-KR-BongJinNeural", "ko-KR-GookMinNeural",
    "ko-KR-JiMinNeural", "ko-KR-SeoHyeonNeural",
    "ko-KR-SoonBokNeural", "ko-KR-YuJinNeural",
}
# rate/pitch 형식 검증 (예: "+0%", "-30%", "+20Hz")
_RATE_PITCH_RE = _re.compile(r'^[+-]\d{1,3}(%|Hz)$')


@app.get("/tts")
async def tts(
    text: str = Query(..., max_length=500),
    voice: str = Query("ko-KR-SunHiNeural"),
    rate: str = Query("+0%"),
    pitch: str = Query("+0Hz"),
):
    """Edge TTS 문장 단위 음성 합성 (audio/mpeg 스트리밍)"""
    if voice not in EDGE_TTS_VOICES:
        raise HTTPException(400, "허용되지 않는 음성입니다.")
    if not _RATE_PITCH_RE.match(rate) or not _RATE_PITCH_RE.match(pitch):
        raise HTTPException(400, "rate/pitch 형식이 올바르지 않습니다.")

    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)

    async def audioStream():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(
        audioStream(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


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
