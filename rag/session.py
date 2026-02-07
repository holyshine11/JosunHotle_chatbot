"""
세션 기반 대화 컨텍스트 관리
- 서버 메모리에 세션별 대화 상태 저장
- TTL 기반 자동 정리
- 대화 주제 추적, 검색 결과 캐시
"""

import time
import uuid
import threading
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ConversationContext:
    """대화 컨텍스트 (세션당 1개)"""
    session_id: str
    current_topic: Optional[str] = None      # 현재 대화 주제 (카테고리)
    current_hotel: Optional[str] = None       # 현재 호텔
    last_chunks: list = field(default_factory=list)  # 마지막 답변에 사용된 청크
    last_query: str = ""                      # 이전 질문
    topic_turn_count: int = 0                 # 같은 주제 연속 턴 수
    last_active: float = 0.0                  # 마지막 활동 시각

    def updateTopic(self, topic: Optional[str], hotel: Optional[str]):
        """주제 업데이트

        - 같은 주제면 턴 카운트 증가
        - 새 주제면 교체
        - topic이 None이면 이전 주제 유지 (후속 질문 핵심 로직)
        """
        if topic and topic == self.current_topic:
            self.topic_turn_count += 1
        elif topic:
            self.current_topic = topic
            self.topic_turn_count = 1
        # topic이 None이면 이전 주제 유지

        if hotel:
            self.current_hotel = hotel
        self.last_active = time.time()

    def cacheChunks(self, chunks: list, query: str):
        """검색 결과 캐시"""
        self.last_chunks = chunks
        self.last_query = query
        self.last_active = time.time()

    def reset(self):
        """세션 초기화 (새 대화)"""
        self.current_topic = None
        self.current_hotel = None
        self.last_chunks = []
        self.last_query = ""
        self.topic_turn_count = 0


class SessionStore:
    """세션 저장소 (인메모리, TTL 자동 정리)"""

    TTL_SECONDS = 1800  # 30분 비활동 시 세션 만료
    CLEANUP_INTERVAL = 300  # 5분마다 정리
    MAX_SESSIONS = 1000  # 최대 세션 수

    def __init__(self):
        self._sessions: dict[str, ConversationContext] = {}
        self._lock = threading.Lock()
        self._startCleanupTimer()

    def getOrCreate(self, sessionId: Optional[str] = None) -> ConversationContext:
        """세션 조회 또는 생성"""
        with self._lock:
            if sessionId and sessionId in self._sessions:
                ctx = self._sessions[sessionId]
                ctx.last_active = time.time()
                return ctx

            # 최대 세션 수 초과 시 오래된 세션 정리
            if len(self._sessions) >= self.MAX_SESSIONS:
                self._evictOldest()

            # 새 세션 생성
            newId = sessionId or str(uuid.uuid4())
            ctx = ConversationContext(session_id=newId)
            ctx.last_active = time.time()
            self._sessions[newId] = ctx
            return ctx

    def cleanup(self):
        """만료 세션 정리"""
        now = time.time()
        with self._lock:
            expired = [
                sid for sid, ctx in self._sessions.items()
                if now - ctx.last_active > self.TTL_SECONDS
            ]
            for sid in expired:
                del self._sessions[sid]
            if expired:
                print(f"[세션 정리] {len(expired)}개 만료 세션 삭제, 현재 {len(self._sessions)}개")

    def _evictOldest(self):
        """가장 오래된 세션 제거 (lock 내부에서 호출)"""
        if not self._sessions:
            return
        oldest = min(self._sessions.items(), key=lambda x: x[1].last_active)
        del self._sessions[oldest[0]]

    def _startCleanupTimer(self):
        """정리 타이머 시작"""
        def _run():
            self.cleanup()
            self._timer = threading.Timer(self.CLEANUP_INTERVAL, _run)
            self._timer.daemon = True
            self._timer.start()

        self._timer = threading.Timer(self.CLEANUP_INTERVAL, _run)
        self._timer.daemon = True
        self._timer.start()


# 싱글톤 인스턴스
sessionStore = SessionStore()
