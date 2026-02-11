"""
LangGraph 기반 RAG 플로우
- No Retrieval, No Answer 정책 적용
- 7개 노드: preprocess → retrieve → evidence_gate → answer_compose → answer_verify → policy_filter → log
- 답변 검증으로 할루시네이션 방지
- Grounding Gate로 문장 단위 근거 검증
- Ollama LLM (qwen2.5:7b)으로 자연어 답변 생성
"""

import re
import json
import os
from datetime import datetime
from typing import TypedDict, Literal, Optional
from pathlib import Path

from langgraph.graph import StateGraph, END

# LLM Provider (Ollama 또는 Groq)
from rag.llm_provider import callLLM

# Grounding Gate import
from rag.grounding import groundingGate, categoryChecker
# 답변 검증 모듈
from rag.verify import answerVerifier
from rag.constants import (
    EVIDENCE_THRESHOLD, RERANKER_ENABLED, VALID_QUERY_KEYWORDS,
    MIN_CHUNKS_REQUIRED, LLM_MODEL, LLM_ENABLED,
    HOTEL_KEYWORDS, CATEGORY_KEYWORDS, SYNONYM_DICT,
    FORBIDDEN_KEYWORDS, AMBIGUOUS_PATTERNS, CONTEXT_CLARIFICATION,
    INVALID_QUERY_PATTERNS, MIN_QUERY_LENGTH, HOTEL_INFO,
    SUSPICIOUS_PATTERNS,
)
from rag.entity import extractRestaurantEntity


class RAGState(TypedDict):
    """RAG 상태 정의"""
    # 입력
    query: str
    hotel: Optional[str]
    history: Optional[list[dict]]  # 대화 히스토리 [{role, content}, ...]

    # 쿼리 재작성 결과
    rewritten_query: str  # 맥락이 반영된 재작성 쿼리

    # 전처리 결과
    language: str
    detected_hotel: Optional[str]
    category: Optional[str]
    normalized_query: str
    is_valid_query: bool  # 호텔 관련 질문인지 여부

    # 명확화 질문 (모호한 질문 처리)
    needs_clarification: bool  # 명확화 필요 여부
    clarification_question: str  # 사용자에게 되물을 질문
    clarification_options: list[str]  # 선택지 목록
    clarification_type: Optional[str]  # 명확화 타입 (시간/가격/예약/위치/반려동물/어린이)
    clarification_subject: Optional[str]  # 추출된 주체 엔티티 (예: "스타벅스")

    # 검색 결과
    retrieved_chunks: list[dict]
    top_score: float

    # 근거 검증
    evidence_passed: bool
    evidence_reason: str

    # 답변
    answer: str
    sources: list[str]

    # 답변 검증
    verification_passed: bool
    verification_issues: list[str]
    verified_answer: str

    # Grounding Gate 결과
    grounding_result: Optional[dict]  # GroundingResult를 dict로 저장
    query_intents: list[str]  # 질문 의도 분류 결과

    # 대화 주제 추적 (컨텍스트 오염 방지)
    conversation_topic: Optional[str]  # 히스토리에서 추출한 현재 주제
    effective_category: Optional[str]  # 검색에 사용된 카테고리

    # 레스토랑 엔티티 추출 결과
    restaurant_entity: Optional[dict]      # extractRestaurantEntity() 결과
    restaurant_redirect_msg: Optional[str]  # 리다이렉트/명확화 안내 메시지

    # 세션 컨텍스트 (서버 세션 참조)
    session_context: Optional[object]  # ConversationContext 객체 참조

    # 정책 필터
    policy_passed: bool
    policy_reason: str
    final_answer: str

    # 로그
    log: dict


class RAGGraph:
    """LangGraph RAG 그래프"""

    # 상수는 rag/constants.py에서 import
    EVIDENCE_THRESHOLD = EVIDENCE_THRESHOLD
    RERANKER_ENABLED = RERANKER_ENABLED
    VALID_QUERY_KEYWORDS = VALID_QUERY_KEYWORDS
    MIN_CHUNKS_REQUIRED = MIN_CHUNKS_REQUIRED
    LLM_MODEL = LLM_MODEL
    LLM_ENABLED = LLM_ENABLED
    HOTEL_KEYWORDS = HOTEL_KEYWORDS
    CATEGORY_KEYWORDS = CATEGORY_KEYWORDS
    SYNONYM_DICT = SYNONYM_DICT
    FORBIDDEN_KEYWORDS = FORBIDDEN_KEYWORDS
    AMBIGUOUS_PATTERNS = AMBIGUOUS_PATTERNS
    CONTEXT_CLARIFICATION = CONTEXT_CLARIFICATION
    INVALID_QUERY_PATTERNS = INVALID_QUERY_PATTERNS
    MIN_QUERY_LENGTH = MIN_QUERY_LENGTH
    HOTEL_INFO = HOTEL_INFO

    def __init__(self, indexer):
        self.indexer = indexer
        self.basePath = Path(__file__).parent.parent
        self.logPath = self.basePath / "data" / "logs"
        self.logPath.mkdir(parents=True, exist_ok=True)

        # 그래프 생성
        self.graph = self._buildGraph()

    def _buildGraph(self) -> StateGraph:
        """LangGraph 그래프 구성"""
        workflow = StateGraph(RAGState)

        # 노드 추가
        workflow.add_node("query_rewrite", self.queryRewriteNode)  # 쿼리 재작성 노드
        workflow.add_node("preprocess", self.preprocessNode)
        workflow.add_node("clarification_check", self.clarificationCheckNode)  # 명확화 체크 노드
        workflow.add_node("retrieve", self.retrieveNode)
        workflow.add_node("evidence_gate", self.evidenceGateNode)
        workflow.add_node("answer_compose", self.answerComposeNode)
        workflow.add_node("answer_verify", self.answerVerifyNode)  # 답변 검증 노드
        workflow.add_node("policy_filter", self.policyFilterNode)
        workflow.add_node("log", self.logNode)

        # 엣지 정의
        workflow.set_entry_point("query_rewrite")  # 쿼리 재작성부터 시작
        workflow.add_edge("query_rewrite", "preprocess")
        workflow.add_edge("preprocess", "clarification_check")

        # 명확화 필요 여부에 따른 분기
        workflow.add_conditional_edges(
            "clarification_check",
            self._clarificationRouter,
            {
                "clarify": "log",      # 명확화 필요 → 바로 로그로 (질문 반환)
                "proceed": "retrieve"  # 명확화 불필요 → 검색 진행
            }
        )

        workflow.add_edge("retrieve", "evidence_gate")

        # evidence_gate 조건부 분기
        workflow.add_conditional_edges(
            "evidence_gate",
            self._evidenceRouter,
            {
                "pass": "answer_compose",
                "fail": "policy_filter"  # fail시에도 policy_filter 거쳐서 기본 답변 생성
            }
        )

        workflow.add_edge("answer_compose", "answer_verify")  # 답변 → 검증
        workflow.add_edge("answer_verify", "policy_filter")   # 검증 → 정책필터
        workflow.add_edge("policy_filter", "log")
        workflow.add_edge("log", END)

        return workflow.compile()

    def _evidenceRouter(self, state: RAGState) -> Literal["pass", "fail"]:
        """근거 검증 결과에 따른 라우팅"""
        return "pass" if state["evidence_passed"] else "fail"

    def _clarificationRouter(self, state: RAGState) -> Literal["clarify", "proceed"]:
        """명확화 필요 여부에 따른 라우팅"""
        return "clarify" if state.get("needs_clarification", False) else "proceed"

    def queryRewriteNode(self, state: RAGState) -> RAGState:
        """쿼리 재작성 노드: 대화 맥락을 반영하여 질문을 완전한 형태로 재작성"""
        query = state["query"]
        history = state.get("history") or []

        # 히스토리가 없거나 비어있으면 원본 쿼리 유지
        if not history:
            return {
                **state,
                "rewritten_query": query,
            }

        # 맥락 참조 패턴 감지 (대명사, 지시어, 암시적 후속 질문)
        contextPatterns = [
            r'^그럼\s*',      # "그럼 ..."
            r'^그러면\s*',    # "그러면 ..."
            r'^그래서\s*',    # "그래서 ..."
            r'^그것\s*',      # "그것 ..."
            r'^그거\s*',      # "그거 ..."
            r'^이것\s*',      # "이것 ..."
            r'^이거\s*',      # "이거 ..."
            r'^거기\s*',      # "거기 ..."
            r'^위에\s*',      # "위에 ..."
            r'^아까\s*',      # "아까 ..."
            r'도\s*알려',     # "~도 알려줘"
            r'는\s*어때',     # "~는 어때"
            r'는\s*어떻게',   # "~는 어떻게"
            r'^더\s*',        # "더 ..."
            r'^다른\s*',      # "다른 ..."
            r'대략|대충|약|정도',  # 추가 정보 요청
            r'할\s*수\s*있',  # "~할 수 있어?"
            r'되나요|돼나요',  # "~되나요?"
            r'가능한가|가능해',  # "~가능한가요?"
            r'안\s*되나|안\s*돼나',  # "~안 되나요?"
            r'얼마|비용|가격',  # 비용 질문
            r'어디|위치|장소',  # 위치 질문
            r'몇\s*시|언제',  # 시간 질문
        ]

        needsRewrite = any(re.search(p, query, re.IGNORECASE) for p in contextPatterns)

        # 질문이 짧으면 맥락 필요할 가능성 높음
        if len(query.strip()) < 20:
            needsRewrite = True

        if not needsRewrite:
            return {
                **state,
                "rewritten_query": query,
            }

        # === 주제 전환 감지: 현재 질문이 이전 대화와 다른 주제면 재작성 차단 ===
        topicGroups = {
            "객실": ["객실", "방", "룸", "room", "suite", "스위트", "디럭스", "키즈룸"],
            "다이닝": ["레스토랑", "식당", "다이닝", "조식", "런치", "디너", "뷔페", "카페", "바"],
            "시설": ["수영장", "풀", "피트니스", "헬스", "사우나", "스파", "키즈클럽"],
            "교통": ["교통", "택시", "지하철", "버스", "공항", "셔틀", "리무진"],
            "주차": ["주차"],
            "반려동물": ["강아지", "반려", "펫", "pet", "개"],
            "예약": ["예약", "취소", "변경", "환불"],
            "체크인": ["체크인", "체크아웃", "입실", "퇴실"],
            "위치": ["위치", "주소", "어디", "오시는길", "찾아오"],
            "연락처": ["전화", "연락", "번호", "문의"],
            "웨딩": ["웨딩", "연회", "결혼"],
        }

        queryLower = query.lower()
        currentTopic = None
        # 복합 주제 감지: "레스토랑 위치" → "다이닝" + "위치"
        # 구체적 대상(다이닝, 시설 등)이 우선하도록 전체 매칭 후 우선순위 적용
        allMatchedTopics = []
        for topic, keywords in topicGroups.items():
            if any(kw in queryLower for kw in keywords):
                allMatchedTopics.append(topic)

        # 우선순위: 구체적 대상 > 일반 속성 (위치/교통은 수식어일 수 있음)
        generalTopics = {"위치", "교통", "연락처"}
        specificMatches = [t for t in allMatchedTopics if t not in generalTopics]
        if specificMatches:
            currentTopic = specificMatches[0]
        elif allMatchedTopics:
            currentTopic = allMatchedTopics[0]

        # 현재 질문에 명확한 주제가 있으면 히스토리 주제와 비교
        if currentTopic:
            historyTopics = set()
            for msg in history[-4:]:
                if msg.get("role") == "user":
                    msgLower = msg.get("content", "").lower()
                    for topic, keywords in topicGroups.items():
                        if any(kw in msgLower for kw in keywords):
                            historyTopics.add(topic)

            # 현재 주제가 히스토리에 없으면 → 주제 전환, 재작성 불필요
            if historyTopics and currentTopic not in historyTopics:
                print(f"[주제 전환 감지] 히스토리 '{historyTopics}' → 현재 '{currentTopic}', 재작성 건너뜀")
                return {
                    **state,
                    "rewritten_query": query,
                }

        # 최근 대화 맥락 구성 (최대 3턴)
        recentHistory = history[-6:] if len(history) > 6 else history  # Q&A 각각이므로 6개 = 3턴

        historyText = ""
        for msg in recentHistory:
            role = "사용자" if msg.get("role") == "user" else "챗봇"
            content = msg.get("content", "")[:200]  # 너무 긴 내용 자르기
            historyText += f"{role}: {content}\n"

        # LLM으로 쿼리 재작성
        rewritePrompt = f"""당신은 대화 맥락을 이해하여 질문을 재작성하는 전문가입니다.

[이전 대화]
{historyText}

[현재 질문]
{query}

[작업]
현재 질문이 이전 대화의 맥락을 참조하는 경우, 맥락을 포함한 완전한 질문으로 재작성하세요.
- 이전 대화에서 언급된 주제(장소, 물건, 서비스 등)를 명시적으로 포함
- 질문의 의도를 명확하게 유지
- 재작성이 필요 없으면 원본 질문 그대로 출력

[중요 규칙]
- 현재 질문이 이전 대화와 완전히 다른 주제(예: 이전에 교통편→지금 객실)면 절대 이전 맥락을 섞지 마세요
- 현재 질문에 이전 대화에 없던 새로운 고유명사(인물명, 브랜드명)가 등장하면, 이전 맥락과 무관한 새 질문으로 처리하세요
- 이전 대화 내용을 답변에 포함하지 마세요. 질문만 재작성하세요
- 교통편, 지하철 노선, 버스 번호 등의 구체적 정보를 질문에 추가하지 마세요

[재작성된 질문]"""

        try:
            # LLM Provider를 통한 쿼리 재작성
            rewrittenQuery = callLLM(
                prompt=rewritePrompt,
                temperature=0.0
            ).strip()

            # 빈 응답이나 너무 긴 응답 방지
            if not rewrittenQuery or len(rewrittenQuery) > 200:
                rewrittenQuery = query

            # 불필요한 접두사 제거
            rewrittenQuery = re.sub(r'^(재작성된\s*질문[:\s]*|질문[:\s]*)', '', rewrittenQuery).strip()

            print(f"[쿼리 재작성] '{query}' → '{rewrittenQuery}'")

        except Exception as e:
            print(f"[쿼리 재작성 오류] {e}")
            rewrittenQuery = query

        return {
            **state,
            "rewritten_query": rewrittenQuery,
        }

    def clarificationCheckNode(self, state: RAGState) -> RAGState:
        """명확화 체크 노드: 모호한 질문 감지 및 명확화 질문 생성

        Phase 13: 맥락 인식 명확화 시스템
        - 반려동물, 어린이 등 특정 맥락 감지 시 맥락 맞춤 후속 질문
        - direct_triggers가 있으면 바로 검색 (질문형인 경우)
        - 없으면 맥락 맞춤 옵션 제시

        Phase 16: 명확화 루프 방지 + 구체적 대상 우선 체크
        - 히스토리에서 이미 명확화가 발생한 맥락은 재명확화 차단
        - 구체적 대상(시설, 정책 등)이 있으면 명확화보다 검색 우선
        """
        # 모호성 판단은 원본 쿼리 기준 (LLM 재작성이 추가한 키워드 무시)
        originalQuery = state.get("query", "").strip()
        originalQueryLower = originalQuery.lower()
        # 맥락 감지/구체적 대상 체크는 재작성 쿼리 (맥락 보강 상태)
        query = state.get("normalized_query") or state.get("rewritten_query") or state["query"]
        queryLower = query.lower()
        hotel = state.get("detected_hotel")

        # 호텔 정보 (명확화 질문에 포함)
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        hotelName = hotelInfo.get("name", "")

        # ========================================
        # 엔티티 기반 명확화 (레스토랑이 여러 호텔에 존재)
        # ========================================
        entityResult = state.get("restaurant_entity")
        if entityResult and entityResult.get("action") == "clarify":
            clarifyMsg = state.get("restaurant_redirect_msg", "")
            clarifyOptions = entityResult.get("clarify_options", [])
            print(f"[엔티티 명확화] {clarifyMsg}")
            return {
                **state,
                "needs_clarification": True,
                "clarification_question": clarifyMsg,
                "clarification_options": clarifyOptions,
                "clarification_type": "restaurant_entity",
                "evidence_passed": True,
                "final_answer": clarifyMsg,
            }

        # ========================================
        # Phase 16-1: 명확화 루프 방지
        # 히스토리에서 이미 동일 맥락 명확화가 발생했으면 바로 검색
        # ========================================
        history = state.get("history") or []
        previousClarificationContexts = set()
        for msg in history:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                # 이전 명확화 응답에서 맥락 키워드 감지
                for contextKey in self.CONTEXT_CLARIFICATION:
                    contextInfo = self.CONTEXT_CLARIFICATION[contextKey]
                    if contextInfo["question"] in content:
                        previousClarificationContexts.add(contextKey)

        if previousClarificationContexts:
            print(f"[루프 방지] 이전 명확화 감지: {previousClarificationContexts}")
            # 이미 명확화가 발생한 맥락이면 바로 검색 진행
            for contextKey in previousClarificationContexts:
                keywords = self.CONTEXT_CLARIFICATION[contextKey]["keywords"]
                if any(kw in queryLower for kw in keywords):
                    print(f"[루프 방지] '{query}' → {contextKey} 맥락 재명확화 차단, 직접 검색")
                    return {
                        **state,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "clarification_options": [],
                        "detected_context": contextKey,
                    }

        # ========================================
        # Phase 16-2: 구체적 대상이 명시된 맥락 질문은 바로 검색
        # "반려동물 객실 투숙 정책" → 맥락(반려동물) + 구체적 대상(객실, 정책) → 검색
        # ========================================
        contextSpecificTargets = [
            "객실", "방", "투숙", "숙박", "레스토랑", "다이닝", "로비",
            "수영장", "풀", "피트니스", "스파", "사우나",
            "정책", "규정", "패키지", "프로모션", "혜택",
            "비용", "요금", "가격", "얼마", "무게", "kg", "킬로",
        ]

        for contextKey, contextInfo in self.CONTEXT_CLARIFICATION.items():
            keywords = contextInfo["keywords"]
            if any(kw in queryLower for kw in keywords):
                # 맥락은 감지됨 — 추가로 구체적 대상도 있는지 확인
                if any(target in queryLower for target in contextSpecificTargets):
                    print(f"[맥락+구체적 대상] '{query}' → {contextKey} 맥락 + 구체적 대상, 직접 검색")
                    return {
                        **state,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "clarification_options": [],
                        "detected_context": contextKey,
                    }

        # ========================================
        # Phase 13: 맥락 인식 명확화 (맥락O + 구체적 대상X 일 때만)
        # ========================================
        for contextKey, contextInfo in self.CONTEXT_CLARIFICATION.items():
            keywords = contextInfo["keywords"]
            directTriggers = contextInfo.get("direct_triggers", [])

            # 맥락 키워드 매칭
            if any(kw in queryLower for kw in keywords):
                # 직접 답변 트리거 확인 (질문형이면 바로 검색)
                if any(trigger in queryLower for trigger in directTriggers):
                    print(f"[맥락 감지] '{query}' → {contextKey} 맥락, 직접 검색")
                    return {
                        **state,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "clarification_options": [],
                        "detected_context": contextKey,
                    }

                # 맥락 맞춤 명확화 질문 (트리거 없는 경우)
                question = contextInfo["question"]
                if hotelName:
                    question = f"[{hotelName}] {question}"

                print(f"[맥락 명확화] '{query}' → {contextKey} 맥락, 추가 질문 필요")
                return {
                    **state,
                    "needs_clarification": True,
                    "clarification_question": question,
                    "clarification_options": contextInfo["options"],
                    "clarification_context": contextKey,
                    "clarification_type": contextKey,  # "반려동물", "어린이" 등
                    "evidence_passed": True,
                    "final_answer": question,
                }

        # ========================================
        # 기존 로직: 구체적 대상 체크
        # ========================================
        # 이미 구체적인 대상이 있는지 확인하는 키워드들
        specificTargets = [
            # 체크인/아웃
            "체크인", "체크아웃", "checkin", "checkout",
            # 조식/다이닝
            "조식", "아침식사", "아침밥", "아침", "브런치", "breakfast",
            "중식", "점심", "석식", "저녁",
            "뷔페", "buffet",
            # 시설
            "수영장", "풀", "pool", "피트니스", "헬스", "gym", "운동",
            "스파", "spa", "마사지", "사우나", "찜질",
            "레스토랑", "다이닝", "라운지", "키즈", "연회", "객실", "방",
            # 서비스명
            "주차", "발렛", "와이파이", "세탁", "컨시어지", "룸서비스",
            # 다이닝 구체적
            "홍연", "아리아", "콘스탄스", "팔레",
            # 정책 관련 (명확한 질문)
            "취소", "환불", "취소정책", "환불정책", "노쇼", "정책", "규정",
            # 투숙/숙박
            "투숙", "숙박", "묵", "예약",
            # 패키지/프로모션
            "패키지", "프로모션", "혜택", "할인", "이벤트", "특가",
            # 반려동물/어린이 구체적
            "반려동물", "애견", "강아지", "펫", "어린이", "키즈클럽",
        ]

        # 질문에 이미 구체적인 대상이 있으면 명확화 불필요
        # 단, "교통" AMBIGUOUS_PATTERNS 키워드가 원본 쿼리에 있으면 교통 명확화 우선
        transportKeywords = self.AMBIGUOUS_PATTERNS.get("교통", {}).get("keywords", [])
        transportExcludes = self.AMBIGUOUS_PATTERNS.get("교통", {}).get("excludes", [])
        hasTransportKeyword = any(kw in originalQueryLower for kw in transportKeywords)
        hasTransportExclude = any(exc in originalQueryLower for exc in transportExcludes)
        isTransportAmbiguous = hasTransportKeyword and not hasTransportExclude

        hasSpecificTarget = any(target in queryLower for target in specificTargets)

        if hasSpecificTarget and not isTransportAmbiguous:
            return {
                **state,
                "needs_clarification": False,
                "clarification_question": "",
                "clarification_options": [],
            }

        # ========================================
        # Phase 14: 모호한 패턴 검사 (원본 쿼리 기준)
        # 원칙: 주체(entity)가 있으면 모호하지 않음 → 검색으로 진행
        #       주체가 없을 때만 명확화 질문 (예: "시간이 어떻게 돼?")
        # ========================================
        needsClarification = False
        clarificationQuestion = ""
        clarificationOptions = []

        for patternKey, patternInfo in self.AMBIGUOUS_PATTERNS.items():
            keywords = patternInfo["keywords"]
            excludes = patternInfo.get("excludes", [])

            # 제외 패턴 체크 (원본 + 재작성 쿼리 모두)
            if any(exc in originalQueryLower for exc in excludes):
                continue
            if any(exc in queryLower for exc in excludes):
                continue

            # ★ 원본 쿼리에서 모호 키워드 매칭 (LLM 재작성 결과 무시)
            matchedKeywords = [kw for kw in keywords if kw in originalQueryLower]

            if matchedKeywords:
                # ★ 주체 추출: 모호 키워드 제거 후 남는 엔티티
                subjectEntity = self._extractSubjectEntity(originalQuery, matchedKeywords)

                # 교통 패턴: "호텔"은 주체가 아님 (출발지가 핵심)
                if patternKey == "교통" and subjectEntity:
                    transportNonSubjects = ["호텔", "숙소", "리조트", "호텔로", "호텔까지", "호텔에"]
                    if any(ns in subjectEntity for ns in transportNonSubjects):
                        subjectEntity = None

                if subjectEntity:
                    # 주체가 있음 → 모호하지 않음 → 명확화 불필요, 바로 검색
                    # 예: "스타벅스 위치 알려줘" → 스타벅스 검색 → 결과 반환 또는 "확인 어렵습니다"
                    print(f"[주체 감지] '{originalQuery}' → 주체: '{subjectEntity}', 명확화 건너뜀 → 검색 진행")
                    return {
                        **state,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "clarification_options": [],
                    }
                else:
                    # 주체 없음 → 진짜 모호 → 기존 일반 질문
                    needsClarification = True
                    clarificationQuestion = patternInfo["question"]
                    clarificationOptions = patternInfo["options"]

                    if hotelName:
                        clarificationQuestion = f"[{hotelName}] {clarificationQuestion}"

                    print(f"[일반 명확화] '{originalQuery}' → {clarificationQuestion}")
                    break

        if needsClarification:
            return {
                **state,
                "needs_clarification": True,
                "clarification_question": clarificationQuestion,
                "clarification_options": clarificationOptions,
                "clarification_type": patternKey,
                "evidence_passed": True,
                "final_answer": clarificationQuestion,
            }

        return {
            **state,
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
        }

    def preprocessNode(self, state: RAGState) -> RAGState:
        """전처리 노드: 입력 정규화, 언어/호텔/카테고리 감지"""
        # 재작성된 쿼리 사용 (없으면 원본)
        query = (state.get("rewritten_query") or state["query"]).strip()
        userHotel = state.get("hotel")

        # 언어 감지
        koreanChars = len(re.findall(r'[가-힣]', query))
        language = "ko" if koreanChars > len(query) * 0.3 else "en"

        # 호텔 감지 (사용자 지정 우선)
        detectedHotel = userHotel
        if not detectedHotel:
            queryLower = query.lower()
            for hotelKey, keywords in self.HOTEL_KEYWORDS.items():
                for keyword in keywords:
                    if keyword.lower() in queryLower:
                        detectedHotel = hotelKey
                        break
                if detectedHotel:
                    break

        # 카테고리 감지
        detectedCategory = None
        queryLower = query.lower()
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in queryLower:
                    detectedCategory = category
                    break
            if detectedCategory:
                break

        # Phase 2: 블랙리스트 패턴 검사 (최우선)
        isValidQuery = True
        for pattern in self.INVALID_QUERY_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                isValidQuery = False
                break

        # 최소 길이 검사
        if isValidQuery and len(query.strip()) < self.MIN_QUERY_LENGTH:
            isValidQuery = False

        # 호텔 관련 키워드 검사 (블랙리스트 통과 시에만)
        # 후속 질문(히스토리 존재)은 키워드 검사 우회 - 이전 질문이 이미 통과함
        history = state.get("history") or []
        if isValidQuery and history:
            # 대화 히스토리가 있으면 후속 질문으로 간주, 키워드 검사 생략
            pass
        elif isValidQuery:
            hasValidKeyword = False
            # 단어 경계 기반 매칭으로 개선 (ex: "방구"가 "방" 키워드에 매칭되지 않도록)
            for keyword in self.VALID_QUERY_KEYWORDS:
                # 한글 키워드: 단어 경계 없이 포함 여부 확인 (단, 최소 2글자)
                # 영문 키워드: 대소문자 무시 포함 여부
                keywordLower = keyword.lower()
                if len(keyword) >= 2 and keywordLower in queryLower:
                    # "방" 같은 1글자 키워드는 정확한 단어 경계 확인
                    if len(keyword) == 1:
                        # 1글자 키워드는 앞뒤에 다른 한글이 없어야 함
                        pattern = rf'(?<![가-힣]){re.escape(keyword)}(?![가-힣])'
                        if re.search(pattern, query):
                            hasValidKeyword = True
                            break
                    else:
                        hasValidKeyword = True
                        break
            isValidQuery = hasValidKeyword

        # 레스토랑 엔티티 추출 및 호텔 맥락 검증
        entityResult = extractRestaurantEntity(query, detectedHotel)
        restaurantRedirectMsg = None

        if entityResult["action"] == "redirect":
            # 다른 호텔 1곳에만 존재 → 호텔 자동 전환 + 안내 메시지
            detectedHotel = entityResult["redirect_hotel"]
            restaurantRedirectMsg = entityResult["message"]
            print(f"[엔티티 리다이렉트] {entityResult['matched_alias']} → {detectedHotel}")

        elif entityResult["action"] == "clarify":
            # 2곳 이상 → 명확화 질문으로 전환
            restaurantRedirectMsg = entityResult["message"]
            print(f"[엔티티 명확화] {entityResult['matched_alias']} → 호텔 선택 필요")

        return {
            **state,
            "language": language,
            "detected_hotel": detectedHotel,
            "category": detectedCategory,
            "normalized_query": query,
            "is_valid_query": isValidQuery,
            "restaurant_entity": entityResult,
            "restaurant_redirect_msg": restaurantRedirectMsg,
        }

    def retrieveNode(self, state: RAGState) -> RAGState:
        """검색 노드: Vector DB에서 관련 청크 검색 (쿼리 확장 + 카테고리 필터)

        - 세션 컨텍스트 기반 주제 폴백
        - 같은 주제 후속 질문 시 캐시 우선 검색
        - 카테고리 필터는 후속 질문에서만 적용 (컨텍스트 오염 방지)
        """
        query = state["normalized_query"]
        hotel = state["detected_hotel"]
        detectedCategory = state.get("category")
        history = state.get("history", [])
        sessionCtx = state.get("session_context")

        # === 호텔명 제거: 벡터 임베딩 왜곡 방지 ===
        # 호텔 필터는 Chroma 메타데이터로 적용되므로 쿼리 텍스트에서 제거
        searchQuery = self._stripHotelName(query, hotel)

        # === 주제 추출: 키워드 기반 + 세션 폴백 ===
        conversationTopic = self._extractConversationTopic(history)

        # 키워드 추출 실패 시 세션의 현재 주제 사용
        if not conversationTopic and sessionCtx and sessionCtx.current_topic and history:
            conversationTopic = sessionCtx.current_topic
            print(f"[세션 주제] 키워드 추출 실패 → 세션 주제 사용: {conversationTopic}")

        # 효과적 카테고리 결정 (리랭커가 있으므로 후속 질문에서는 필터 제거)
        # 카테고리 필터는 인덱스 카테고리명과 불일치 위험이 높아 리랭커에 의존
        effectiveCategory = None
        if history and conversationTopic:
            if detectedCategory and detectedCategory != conversationTopic:
                print(f"[주제 전환] 히스토리 '{conversationTopic}' → 현재 쿼리 '{detectedCategory}'")
            # 후속 질문에서는 카테고리 필터 없이 검색 (리랭커가 정확도 보장)

        # === 세션 주제 기반 쿼리 보강 ===
        # 현재 쿼리에 명확한 카테고리가 없고, 히스토리 주제와 세션 주제가 일치할 때만 보강
        if (conversationTopic and history and sessionCtx
                and not detectedCategory
                and conversationTopic == sessionCtx.current_topic):
            topicKeywords = {
                "조식": "조식", "다이닝": "레스토랑 다이닝", "수영장": "수영장",
                "피트니스": "피트니스", "스파": "스파", "주차": "주차",
                "체크인/아웃": "체크인 체크아웃", "객실": "객실",
                "요금/결제": "요금 결제", "반려동물": "반려동물"
            }
            topicKw = topicKeywords.get(conversationTopic, conversationTopic)
            # 쿼리에 주제 키워드가 없으면 추가
            if not any(kw in searchQuery for kw in topicKw.split()):
                searchQuery = f"{searchQuery} {topicKw}"
                print(f"[세션 보강] 쿼리에 주제 키워드 추가: '{topicKw}' → '{searchQuery}'")

        # === 캐시 우선 검색 (같은 주제 후속 질문) ===
        cachedResults = None
        if (sessionCtx and sessionCtx.last_chunks and
                history and conversationTopic and
                conversationTopic == sessionCtx.current_topic):
            cachedResults = self._searchCachedChunks(searchQuery, sessionCtx.last_chunks,
                                                     conversationTopic)

        # 쿼리 확장 (동의어 추가)
        expandedQuery = self._expandQuery(searchQuery)

        # 캐시 결과가 충분하면 DB 검색 생략
        if cachedResults and len(cachedResults) >= 2 and cachedResults[0].get("score", 0) >= 0.7:
            print(f"[캐시 히트] 이전 청크에서 {len(cachedResults)}개 관련 결과 발견")
            results = cachedResults
        else:
            # 1차 검색
            results = self.indexer.search(
                query=expandedQuery,
                hotel=hotel,
                category=effectiveCategory,
                topK=5
            )

            # 캐시 결과와 병합 (캐시에만 있는 관련 청크 추가)
            if cachedResults:
                results = self._mergeResults(results, cachedResults, topK=5)

        # 폴백: 결과가 2개 미만이면 필터 완화하여 재검색
        if len(results) < 2 and effectiveCategory:
            fallbackResults = self.indexer.search(
                query=expandedQuery,
                hotel=hotel,
                category=None,  # 필터 제거
                topK=5
            )
            # 폴백 결과가 더 많으면 사용
            if len(fallbackResults) > len(results):
                results = fallbackResults
                effectiveCategory = None  # 폴백으로 변경됨

        # === 리랭킹 (Cross-Encoder) ===
        if self.RERANKER_ENABLED and results and len(results) >= 2:
            try:
                from rag.reranker import getReranker
                reranker = getReranker()
                if reranker.isAvailable:
                    results = reranker.rerank(
                        query=searchQuery,
                        chunks=results,
                        topK=5
                    )
                    # 리랭킹은 순서/필터만 변경, 점수 기준은 original_score 유지
                    for chunk in results:
                        if "original_score" in chunk:
                            chunk["score"] = chunk["original_score"]
            except Exception as e:
                print(f"[리랭커 오류] {e}")

        # 최고 점수 계산: 리랭킹 후 순서가 바뀌므로 전체 결과 중 최고 점수 사용
        topScore = max((r["score"] for r in results), default=0.0) if results else 0.0

        return {
            **state,
            "retrieved_chunks": results,
            "top_score": topScore,
            "conversation_topic": conversationTopic,
            "effective_category": effectiveCategory,
        }

    def evidenceGateNode(self, state: RAGState) -> RAGState:
        """근거 검증 노드: 검색 결과 품질 확인"""
        chunks = state["retrieved_chunks"]
        topScore = state["top_score"]
        isValidQuery = state.get("is_valid_query", True)

        # 질문 유효성 검사 (호텔 관련 키워드 없으면 실패)
        if not isValidQuery:
            return {
                **state,
                "evidence_passed": False,
                "evidence_reason": "호텔 관련 질문이 아닙니다.",
            }

        # 검증 조건
        hasEnoughChunks = len(chunks) >= self.MIN_CHUNKS_REQUIRED
        hasGoodScore = topScore >= self.EVIDENCE_THRESHOLD

        passed = hasEnoughChunks and hasGoodScore

        if not passed:
            if not hasEnoughChunks:
                reason = "관련 정보를 찾을 수 없습니다."
            else:
                reason = f"검색 결과의 관련성이 낮습니다. (점수: {topScore:.2f})"
        else:
            reason = "근거 검증 통과"

        return {
            **state,
            "evidence_passed": passed,
            "evidence_reason": reason,
        }

    def answerComposeNode(self, state: RAGState) -> RAGState:
        """답변 생성 노드: LLM을 사용해 자연어 답변 생성

        개선사항:
        - 복수 청크 교차 참조 조합 (중복 제거 + 정보 병합)
        - URL 메타데이터에서 핵심 상세 정보 추출하여 컨텍스트에 포함
        - 청크 간 보완 관계 분석으로 완성도 높은 답변 생성
        """
        chunks = state["retrieved_chunks"]
        query = state["normalized_query"]
        hotel = state.get("detected_hotel")

        if not chunks:
            return {
                **state,
                "answer": "",
                "sources": [],
            }

        # === Phase 1: 청크 중복 제거 및 정보 병합 ===
        mergedChunks = self._mergeChunkInfo(chunks[:5])

        # 컨텍스트 구성 + 출처 수집 (병합된 청크, 번호/URL 포함)
        contextParts = []
        sources = []
        seenUrls = set()

        for i, chunk in enumerate(mergedChunks, 1):
            hotelName = chunk["metadata"].get("hotel_name", "")
            url = chunk["metadata"].get("url", "")
            text = chunk["text"]

            # === Phase 2: URL 메타데이터에서 핵심 정보 추출 ===
            urlDetails = self._extractUrlDetails(url, chunk)
            urlDetailText = f"\n[URL 상세: {urlDetails}]" if urlDetails else ""

            # 컨텍스트에 청크 번호와 URL + 상세정보 포함
            contextParts.append(
                f"[참조{i}] [{hotelName}] (출처: {url}){urlDetailText}\n{text}"
            )

            # 출처 수집 (중복 제거)
            if url and url not in seenUrls:
                sources.append({"index": i, "url": url, "hotel": hotelName})
                seenUrls.add(url)

        # === Phase 3: 교차 참조 힌트 생성 ===
        crossRefHint = self._buildCrossRefHint(mergedChunks, query)

        context = "\n\n".join(contextParts)
        if crossRefHint:
            context += f"\n\n[교차 참조 가이드]\n{crossRefHint}"

        # === 맥락 충분성 사전 검증 ===
        # 질문이 구체적 정보(시설명, 시간, 가격 등)를 요구하는데
        # 청크에는 일반론만 있는 경우 LLM 호출 없이 "확인 어렵습니다" 반환
        insufficiencyResult = self._checkContextSufficiency(query, chunks, hotel)
        if insufficiencyResult:
            return {
                **state,
                "answer": insufficiencyResult,
                "sources": [src["url"] for src in sources],
            }

        # LLM 사용 여부에 따라 분기
        usedRefs = []
        if self.LLM_ENABLED:
            answer = self._generateWithLLM(query, context, hotel)

            # [REF:1,3] 형태의 참조 번호 파싱
            refMatch = re.search(r'\[REF:([0-9,\s]+)\]', answer)
            if refMatch:
                refStr = refMatch.group(1)
                usedRefs = [int(r.strip()) for r in refStr.split(',') if r.strip().isdigit()]
                # 답변에서 [REF:...] 제거 (사용자에게는 보이지 않도록)
                answer = re.sub(r'\s*\[REF:[0-9,\s]+\]', '', answer).strip()
        else:
            # LLM 미사용 시 검색 결과 직접 반환
            topChunk = chunks[0]
            answer = topChunk["text"]
            if "A:" in answer:
                answer = answer.split("A:")[-1].strip()
            hotelName = topChunk["metadata"].get("hotel_name", "")
            if hotelName:
                answer = f"[{hotelName}] {answer}"
            usedRefs = [1]  # LLM 미사용시 첫번째 청크만 사용

        # 사용된 참조의 URL만 필터링
        usedSources = []
        if usedRefs:
            for src in sources:
                if src["index"] in usedRefs:
                    usedSources.append(src["url"])
        else:
            # 참조 번호가 없으면 모든 소스 사용 (fallback)
            usedSources = [src["url"] for src in sources]

        # 레스토랑 리다이렉트 메시지가 있으면 답변 앞에 추가
        redirectMsg = state.get("restaurant_redirect_msg")
        if redirectMsg and answer:
            answer = f"{redirectMsg}\n\n{answer}"

        return {
            **state,
            "answer": answer,
            "sources": usedSources,  # 사용된 URL만 전달
        }

    def _mergeChunkInfo(self, chunks: list) -> list:
        """복수 청크의 중복 제거 및 정보 병합

        동일 URL/주제의 청크들을 병합하여 정보를 통합하고,
        중복 문장을 제거하여 LLM에 전달하는 컨텍스트 품질을 향상.

        Args:
            chunks: 상위 N개 청크 리스트

        Returns:
            병합된 청크 리스트 (원본 구조 유지)
        """
        if len(chunks) <= 1:
            return chunks

        # URL 기반 그룹핑 (동일 페이지에서 온 청크 병합)
        urlGroups = {}
        standalone = []

        for chunk in chunks:
            url = chunk.get("metadata", {}).get("url", "")
            if url:
                if url not in urlGroups:
                    urlGroups[url] = []
                urlGroups[url].append(chunk)
            else:
                standalone.append(chunk)

        merged = []
        seenSentences = set()

        for url, group in urlGroups.items():
            if len(group) == 1:
                # 단독 청크: 중복 문장만 제거
                deduped = self._deduplicateSentences(group[0]["text"], seenSentences)
                if deduped.strip():
                    mergedChunk = {**group[0], "text": deduped}
                    merged.append(mergedChunk)
            else:
                # 동일 URL 복수 청크: 텍스트 병합 후 중복 제거
                combinedTexts = []
                bestScore = 0
                bestMetadata = group[0].get("metadata", {})

                for c in group:
                    deduped = self._deduplicateSentences(c["text"], seenSentences)
                    if deduped.strip():
                        combinedTexts.append(deduped)
                    chunkScore = c.get("score", 0)
                    if chunkScore > bestScore:
                        bestScore = chunkScore
                        bestMetadata = c.get("metadata", {})

                if combinedTexts:
                    mergedText = "\n".join(combinedTexts)
                    mergedChunk = {
                        **group[0],
                        "text": mergedText,
                        "metadata": bestMetadata,
                        "score": bestScore,
                        "_merged_count": len(group),
                    }
                    merged.append(mergedChunk)

        # standalone 청크 추가
        for chunk in standalone:
            deduped = self._deduplicateSentences(chunk["text"], seenSentences)
            if deduped.strip():
                merged.append({**chunk, "text": deduped})

        # 점수순 정렬 유지
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)

        # 최대 5개 반환 (병합으로 줄어든 경우 그대로)
        return merged[:5]

    def _deduplicateSentences(self, text: str, seenSentences: set) -> str:
        """텍스트 내 중복 문장 제거 (교차 청크 중복 포함)

        Args:
            text: 원본 텍스트
            seenSentences: 이미 등장한 문장 셋 (교차 청크 추적용, 부작용으로 업데이트)

        Returns:
            중복 제거된 텍스트
        """
        lines = text.split('\n')
        uniqueLines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                uniqueLines.append(line)
                continue

            # Q: / A: 라인은 항상 유지 (FAQ 구조 보존)
            if stripped.startswith("Q:") or stripped.startswith("A:"):
                uniqueLines.append(line)
                seenSentences.add(stripped)
                continue

            # 정규화된 문장으로 중복 체크 (공백/구두점 차이 무시)
            normalized = re.sub(r'\s+', ' ', stripped).lower()
            if len(normalized) < 10:
                # 짧은 라인은 중복 체크 건너뜀 (제목, 구분선 등)
                uniqueLines.append(line)
                continue

            if normalized not in seenSentences:
                seenSentences.add(normalized)
                uniqueLines.append(line)

        return '\n'.join(uniqueLines)

    def _extractUrlDetails(self, url: str, chunk: dict) -> str:
        """URL 메타데이터에서 핵심 상세 정보 추출

        URL 경로를 분석하여 해당 페이지의 컨텍스트 힌트를 생성.
        단순히 URL을 전달하는 대신 페이지의 성격을 LLM에 안내.

        Args:
            url: 청크의 원본 URL
            chunk: 청크 데이터 (metadata 포함)

        Returns:
            URL 상세 정보 문자열 (빈 문자열이면 생략)
        """
        if not url:
            return ""

        details = []
        urlLower = url.lower()
        metadata = chunk.get("metadata", {})

        # URL 경로에서 페이지 유형 추출
        pageTypeMap = {
            "/dining/": "다이닝 정보 페이지",
            "/room/": "객실 정보 페이지",
            "/package/": "패키지 상품 페이지",
            "/facilities/": "부대시설 정보 페이지",
            "/about/location": "위치/교통 안내 페이지",
            "/event/": "이벤트/프로모션 페이지",
            "/activity/": "액티비티 안내 페이지",
            "/spa/": "스파/웰니스 페이지",
            "/wedding/": "웨딩/연회 페이지",
        }

        for pathKey, pageDesc in pageTypeMap.items():
            if pathKey in urlLower:
                details.append(pageDesc)
                break

        # 메타데이터에서 카테고리/페이지 타입 추출
        pageType = metadata.get("page_type", "")
        if pageType and pageType not in ["faq", "general"]:
            typeLabels = {
                "dining_menu": "메뉴 상세",
                "package": "패키지 상품",
                "event": "이벤트",
                "activity": "액티비티",
                "pet_policy": "반려동물 정책",
                "contact": "연락처",
                "breakfast": "조식 정보",
            }
            label = typeLabels.get(pageType, pageType)
            details.append(label)

        # 호텔별 도메인 코드 추출 (jpg, gjb, gjj, les, grp)
        hotelDomainMap = {
            "jpg.josunhotel.com": "조선 팰리스",
            "gjb.josunhotel.com": "그랜드 조선 부산",
            "gjj.josunhotel.com": "그랜드 조선 제주",
            "les.josunhotel.com": "레스케이프",
            "grp.josunhotel.com": "그래비티 판교",
        }
        for domain, name in hotelDomainMap.items():
            if domain in urlLower:
                details.append(f"출처 호텔: {name}")
                break

        return ", ".join(details) if details else ""

    def _buildCrossRefHint(self, chunks: list, query: str) -> str:
        """교차 참조 힌트 생성: 복수 청크의 보완 관계를 LLM에 안내

        각 청크가 어떤 정보를 담고 있는지 요약하여
        LLM이 정보를 조합할 수 있도록 가이드 제공.

        Args:
            chunks: 병합된 청크 리스트
            query: 정규화된 질문

        Returns:
            교차 참조 가이드 텍스트 (빈 문자열이면 생략)
        """
        if len(chunks) <= 1:
            return ""

        # 청크별 정보 유형 감지
        chunkInfoTypes = []
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text", "")
            infoTypes = []

            # 시간 정보
            if re.search(r'\d{1,2}:\d{2}', text):
                infoTypes.append("운영시간")

            # 가격 정보
            if re.search(r'[\d,]+\s*원', text):
                infoTypes.append("가격")

            # 메뉴/서비스 항목
            if re.search(r'[-•]\s*[가-힣]', text) or text.count('\n') > 5:
                infoTypes.append("항목목록")

            # 위치/교통
            if re.search(r'(역|정류장|출구|도보|차량|층)', text):
                infoTypes.append("위치/접근")

            # 정책/규정
            if re.search(r'(가능|불가|금지|허용|필수|제한)', text):
                infoTypes.append("정책/규정")

            # 패키지/이벤트
            metadata = chunk.get("metadata", {})
            pageType = metadata.get("page_type", "")
            if pageType in ["package", "event", "activity"]:
                infoTypes.append(f"{pageType}상세")

            # FAQ 형태
            if "Q:" in text and "A:" in text:
                infoTypes.append("FAQ")

            if infoTypes:
                chunkInfoTypes.append(f"참조{i}: {', '.join(infoTypes)}")

        if not chunkInfoTypes:
            return ""

        hint = "아래 참조들은 서로 보완적인 정보를 포함합니다. 관련 정보를 조합하여 완성도 높은 답변을 작성하세요:\n"
        hint += "\n".join(f"- {info}" for info in chunkInfoTypes)

        return hint

    def _checkContextSufficiency(self, query: str, chunks: list, hotel: str = None) -> Optional[str]:
        """맥락 충분성 검증: 질문이 구체적 정보를 요구하는데 청크가 일반론만 제공하는지 확인

        Returns:
            None: 충분함 (LLM 호출 진행)
            str: 불충분 시 대체 응답 문자열
        """
        if not chunks:
            return None  # evidenceGateNode에서 이미 처리

        queryLower = query.lower()

        # 구체적 정보를 요구하는 질문 패턴
        specificInfoPatterns = [
            # 특정 시설의 이름/위치/시간을 묻는 패턴
            (["레스토랑", "식당", "다이닝"], ["이름", "뭐", "어떤", "점심", "저녁", "런치", "디너", "메뉴"]),
            (["카페", "바"], ["이름", "뭐", "어떤", "메뉴"]),
        ]

        needsSpecificInfo = False
        for facilityKws, detailKws in specificInfoPatterns:
            hasFacility = any(kw in queryLower for kw in facilityKws)
            hasDetail = any(kw in queryLower for kw in detailKws)
            if hasFacility and hasDetail:
                needsSpecificInfo = True
                break

        if not needsSpecificInfo:
            return None

        # 청크에 구체적 정보가 있는지 확인
        # 구체적 정보 지표: 시간 패턴, 구체적 시설명, 가격 패턴 등
        allChunkText = " ".join([c.get("text", "") for c in chunks[:5]])

        hasSpecificTime = bool(re.search(r'\d{1,2}:\d{2}', allChunkText))
        hasSpecificName = bool(re.search(
            r'[가-힣]{2,}(?:\s+[가-힣]+)*\s*(?:레스토랑|식당|카페|바|라운지|다이닝)',
            allChunkText
        ))
        hasSpecificPrice = bool(re.search(r'[\d,]+\s*원', allChunkText))

        # FAQ Q&A 형식인지 확인 (Q: ... A: ... 패턴)
        hasFaqFormat = bool(re.search(r'[QA]:|\?.*\n', allChunkText))

        # 구체적 정보가 하나라도 있으면 충분
        if hasSpecificTime or hasSpecificName or hasSpecificPrice or hasFaqFormat:
            return None

        # 일반론만 있는 경우 → LLM 없이 직접 응답
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        hotelName = hotelInfo.get("name", "")
        hotelPhone = hotelInfo.get("phone", "")
        contactInfo = f"{hotelName} ({hotelPhone})" if hotelPhone else "호텔 고객센터"

        print(f"[맥락 충분성] 구체적 정보 부족 — 일반론만 존재, LLM 호출 생략")
        return f"죄송합니다, 해당 내용에 대한 구체적인 정보를 현재 자료에서 확인하기 어렵습니다.\n자세한 사항은 {contactInfo}로 문의 부탁드립니다."

    def _generateWithLLM(self, query: str, context: str, hotel: str = None) -> str:
        """Ollama LLM으로 답변 생성"""
        # 호텔 정보 조회
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        hotelName = hotelInfo.get("name", "")
        hotelPhone = hotelInfo.get("phone", "")

        contactInfo = f"{hotelName} ({hotelPhone})" if hotelPhone else "호텔 고객센터"

        # 현재 세션 호텔 정보
        currentHotelNotice = ""
        if hotelName:
            currentHotelNotice = f"""
[현재 호텔] {hotelName}
- 다른 호텔 정보를 섞지 마세요
- 문의 안내 시: {contactInfo}"""

        systemPrompt = f"""당신은 조선호텔앤리조트의 프리미엄 AI 컨시어지입니다. 하이엔드 고객을 응대합니다.
{currentHotelNotice}

[핵심 원칙]
1. 컨텍스트에 있는 정보만 사용
2. 정보가 없으면: "정확한 정보 확인을 위해 {contactInfo}로 문의 부탁드립니다"
3. 가격, 시간, 전화번호는 정확히 인용
4. 추측 금지 ("약", "대략", "아마" 사용 금지)
5. 여러 참조에 흩어진 관련 정보를 교차 참조하여 통합된 답변 작성
6. URL에 담긴 상세 정보(메뉴, 가격, 운영시간 등)가 있으면 핵심 내용을 답변에 포함

[고유명사/시설명 규칙 - 최우선]
- 컨텍스트에 있는 정보는 적극 활용하여 답변하세요
- 컨텍스트에 없는 시설명/레스토랑명을 새로 만들어내지 마세요 (예: 가공의 레스토랑명)
- 컨텍스트에 부분적 정보만 있으면 그 부분만 답변하고, 없는 부분은 문의 안내

[답변 형식 - 매우 중요]
- 반드시 완성된 문장으로 답변 (단어만 나열 금지!)
- 존댓말 (~입니다, ~드립니다, ~있습니다)
- 질문에 직접 답변하는 첫 문장 필수 (예: "가장 가까운 역은 역삼역입니다.")
- 추가 정보가 있으면 불릿포인트(-) 사용
- 마지막에 정보 나열 후 자연스럽게 종료

[답변 예시]
질문: "가까운 역 알려줘"
좋은 답변: "호텔에서 가장 가까운 역은 역삼역이며, 도보 약 5분 거리에 위치해 있습니다."
나쁜 답변: "역삼역" (단어만 던지면 안됨!)

질문: "조식 시간 알려줘"
좋은 답변: "조식은 오전 7시부터 10시 30분까지 운영됩니다."
나쁜 답변: "07:00 - 10:30" (시간만 던지면 안됨!)

질문: "레스토랑 점심 정보 알려줘" (컨텍스트에 구체적 레스토랑 정보 없을 때)
좋은 답변: "죄송합니다, 해당 레스토랑의 점심 운영에 대한 구체적인 정보를 찾을 수 없습니다. 정확한 정보 확인을 위해 {contactInfo}로 문의 부탁드립니다."
나쁜 답변: "그랜드 셰프 레스토랑에서 오전 12시부터..." (컨텍스트에 없는 이름/시간 날조!)

[정보 조합 금지]
- 질문에서 언급되지 않은 주제의 정보는 절대 답변에 포함하지 마세요
- 컨텍스트에 해당 정보가 없으면: "해당 정보를 찾을 수 없습니다. {contactInfo}로 문의 부탁드립니다."

[절대 금지]
- "궁금하신가요?" 금지
- "더 필요하신 것이 있으신가요?" 금지
- 답변 끝에 질문 형태 문장 금지
- 단어/숫자만 던지는 불친절한 답변 금지
- 컨텍스트에 없는 시설명/레스토랑명/브랜드명 창작 금지
- 컨텍스트에 없는 운영시간/가격 창작 금지
- 참고 정보에 없는 인물명(셰프, 대표, 오너 등) 언급 금지
- 지하철 노선(N호선), 버스 번호, 교통 경로 정보를 절대 창작하지 마세요
- 교통편(택시 요금, 소요 시간, 환승 경로) 정보는 반드시 컨텍스트에 있는 내용만 답변하세요
- 출발지별 경로 정보가 컨텍스트에 없으면 "정확한 교통 정보를 찾을 수 없습니다"라고 답변하세요
- 질문 주제와 무관한 정보를 답변에 포함하지 마세요 (예: 객실 질문에 교통편 정보 혼합 금지)"""

        userPrompt = f"""[참고 정보]
{context}

[질문]
{query}

[지시사항]
1. 반드시 완성된 문장으로 정중하게 답변하세요
2. 단어나 숫자만 던지지 마세요 (예: "역삼역" X → "가장 가까운 역은 역삼역입니다" O)
3. 참고 정보만 사용하세요. 참고 정보에 없는 내용은 절대 추가하지 마세요
4. 특히 시설명, 레스토랑명, 프로그램명은 참고 정보에 명시된 것만 사용하세요
5. 참고 정보에 구체적 답변이 없으면: "해당 정보를 찾을 수 없습니다"라고 솔직히 답변하세요
6. "궁금하신가요?" 같은 추가 질문은 절대 하지 마세요
7. 여러 참조에 관련 정보가 분산되어 있으면 교차 참조하여 하나의 통합된 답변으로 조합하세요
8. URL 상세 정보(메뉴, 가격, 시간 등)가 있으면 단순 URL 안내 대신 핵심 내용을 답변에 포함하세요
9. 답변 마지막에 반드시 사용한 참조 번호를 표시하세요. 형식: [REF:1,3] (쉼표로 구분)

[답변 형식 예시]
조식은 오전 7시부터 10시까지 운영됩니다. [REF:2]
체크인은 15시, 체크아웃은 11시입니다. [REF:1,3]"""

        try:
            # LLM Provider를 통한 답변 생성
            answer = callLLM(
                prompt=userPrompt,
                system=systemPrompt,
                temperature=0.0
            ).strip()

            # 후처리: 중국어/일본어 문자 제거 (qwen 모델의 할루시네이션 방지)
            # 중국어 한자 범위: \u4e00-\u9fff
            # 일본어 히라가나/가타카나: \u3040-\u30ff

            # 1) 3글자 이상 연속 한자 → 해당 지점부터 잘라내기
            chinesePart = re.search(r'[\u4e00-\u9fff]{3,}', answer)
            if chinesePart:
                cutIndex = chinesePart.start()
                answer = answer[:cutIndex].strip()
                if answer and not answer.endswith(('.', '다', '요', '!')):
                    answer = answer.rstrip(',.;:')
                    if answer:
                        answer += "."

            # 2) 개별 한자/일본어 문자를 한글 대체어로 치환
            chineseToKorean = {
                '휴': '휴식', '憩': '', '息': '', '食': '식',
                '堂': '당', '館': '관', '室': '실', '場': '장',
                '時': '시', '分': '분', '間': '간', '日': '일',
                '月': '월', '年': '년', '名': '명', '人': '인',
                '無': '무', '有': '유', '可': '가', '不': '불',
            }
            for char, replacement in chineseToKorean.items():
                answer = answer.replace(char, replacement)

            # 3) 남은 한자/일본어 문자 일괄 제거
            answer = re.sub(r'[\u4e00-\u9fff\u3040-\u30ff]+', '', answer)
            # 중국어 문장부호 → 한국어 문장부호
            answer = answer.replace('。', '.').replace('，', ', ').replace('！', '!').replace('？', '?')
            # 연속 공백/마침표 정리
            answer = re.sub(r'\s{2,}', ' ', answer).strip()
            answer = re.sub(r'\.{2,}', '.', answer)

            return answer
        except Exception as e:
            # LLM 실패 시 에러 로깅 후 컨텍스트 요약 반환
            import traceback
            print(f"[LLM 에러] {type(e).__name__}: {e}")
            traceback.print_exc()
            return f"[시스템 오류] LLM 응답 실패. 검색된 정보: {context[:200]}..."

    def _extractConversationTopic(self, history: list[dict]) -> Optional[str]:
        """대화 히스토리에서 현재 주제 추출 (컨텍스트 오염 방지)

        user 메시지만 분석 (봇 답변 노이즈 제거).
        최근 user 메시지부터 역순으로 검사하여 현재 대화 주제 우선.
        """
        if not history:
            return None

        # 카테고리별 키워드 매칭 (우선순위 순서)
        topicPriority = [
            ("조식", ["조식", "breakfast", "아침식사", "뷔페", "아침밥", "모닝"]),
            ("다이닝", ["레스토랑", "식당", "다이닝", "저녁", "점심", "런치", "디너",
                      "아리아", "홍연", "콘스탄스", "팔레"]),
            ("수영장", ["수영", "pool", "풀", "swimming", "수영장"]),
            ("피트니스", ["피트니스", "헬스", "gym", "fitness", "운동"]),
            ("스파", ["스파", "spa", "마사지", "massage", "사우나"]),
            ("주차", ["주차", "parking", "발렛", "valet", "파킹"]),
            ("체크인/아웃", ["체크인", "체크아웃", "입실", "퇴실", "check-in", "check-out"]),
            ("객실", ["객실", "방", "room", "침대", "bed", "뷰", "전망"]),
            ("요금/결제", ["요금", "가격", "결제", "비용", "금액"]),
            ("반려동물", ["강아지", "반려견", "pet", "펫", "반려동물", "애견"]),
        ]

        # user 메시지만 추출 (봇 답변 노이즈 제거)
        userMessages = [
            msg.get("content", "") for msg in history
            if msg.get("role") == "user"
        ]

        if not userMessages:
            return None

        # 최근 user 메시지부터 역순 검사 (현재 대화 주제 우선)
        for msg in reversed(userMessages[-3:]):
            msgLower = msg.lower()
            for topic, keywords in topicPriority:
                if any(kw.lower() in msgLower for kw in keywords):
                    return topic

        return None

    def _stripHotelName(self, query: str, hotel: str) -> str:
        """검색 쿼리에서 호텔명/지역명을 제거하여 벡터 임베딩 왜곡 방지.
        호텔 필터는 이미 Chroma 메타데이터로 적용되므로 쿼리 텍스트에 불필요.
        """
        if not hotel or hotel not in self.HOTEL_KEYWORDS:
            return query

        # 해당 호텔의 모든 키워드 수집
        hotelKws = self.HOTEL_KEYWORDS[hotel]
        # HOTEL_INFO의 정식 이름도 추가
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        if hotelInfo.get("name"):
            hotelKws = list(hotelKws) + [hotelInfo["name"]]

        # 긴 키워드부터 제거 (부분 매칭 방지: "그랜드 조선 부산"을 "부산"보다 먼저)
        sortedKws = sorted(hotelKws, key=len, reverse=True)

        stripped = query
        for kw in sortedKws:
            # 호텔명 + 뒤따르는 조사까지 함께 제거
            pattern = re.escape(kw) + r'(에서|에서의|에|의|은|는|이|가|을|를|으로|로|과|와|도)?'
            stripped = re.sub(pattern, '', stripped)

        # 문장 시작의 잔여 조사 정리
        stripped = re.sub(r'^\s*(에서|에|의|은|는|이|가|을|를|으로|로|과|와|도)\s+', '', stripped)
        # "인 의" 같은 잔여 패턴 정리
        stripped = re.sub(r'\s+(에서|에|의|은|는|이|가|을|를|으로|로|과|와|도)\s+', ' ', stripped)
        # 중복 공백 제거
        stripped = re.sub(r'\s+', ' ', stripped).strip()

        if stripped != query.strip():
            print(f"[호텔명 제거] '{query}' → '{stripped}'")

        # 제거 후 쿼리가 너무 짧으면 원본 반환
        if len(stripped) < 3:
            return query

        return stripped

    def _extractSubjectEntity(self, query: str, ambiguousKeywords: list[str]) -> Optional[str]:
        """모호한 질문에서 주체 엔티티 추출.
        모호 키워드와 조사를 제거한 뒤 남는 2글자 이상 단어를 주체로 반환.
        예: "스타벅스 어디야?" → 주체: "스타벅스"
        """
        subject = query.lower()

        # 모호 키워드 제거
        for kw in ambiguousKeywords:
            subject = subject.replace(kw.lower(), "")

        # 조사/어미 제거
        subject = re.sub(
            r'(에서|인가요|나요|은|는|이|가|의|에|를|을|도|만|야|요|까|어요|해|돼|되)',
            '', subject
        )
        # 특수문자/공백 정리
        subject = re.sub(r'[?!.,~\s]+', ' ', subject).strip()

        # 일반어/동작어 필터 (주체가 아닌 단어)
        genericWords = {
            # 일반 명사
            "운영", "이용", "시설", "서비스", "정보", "안내", "문의",
            "호텔", "여기", "거기", "저기", "뭐", "무엇", "어떻게", "얼마",
            "그것", "이것", "그거", "이거", "좀", "혹시", "그런데",
            # 동작어 (주체가 아닌 서술어)
            "알려줘", "알려", "해줘", "보여줘", "말해줘", "찾아줘", "가르쳐줘",
            "알고", "싶어", "싶어요", "싶은데", "궁금", "궁금해", "있나",
            "없나", "하고", "싶다", "있어", "없어", "될까", "되나",
        }

        words = [w for w in subject.split() if len(w) >= 2 and w not in genericWords]

        if words:
            return max(words, key=len)  # 가장 긴 단어 = 가장 구체적

        return None

    def _expandQuery(self, query: str) -> str:
        """쿼리 확장 (동의어 추가)"""
        expandedTerms = []
        queryLower = query.lower()

        for term, synonyms in self.SYNONYM_DICT.items():
            if term.lower() in queryLower:
                expandedTerms.extend(synonyms)

        if expandedTerms:
            # 중복 제거 후 원본 쿼리에 추가
            uniqueTerms = list(set(expandedTerms))
            return f"{query} {' '.join(uniqueTerms[:5])}"  # 최대 5개 동의어

        return query

    def _searchCachedChunks(self, query: str, cachedChunks: list,
                            sessionTopic: str = None) -> list:
        """캐시된 청크에서 쿼리 관련성 검색 (키워드 오버랩 + 주제 부스팅)"""
        queryLower = query.lower()
        # 한글 2글자 이상 토큰 + 영문 토큰
        queryTokens = set(re.findall(r'[가-힣]{2,}', queryLower))
        queryTokens.update(re.findall(r'[a-z]{2,}', queryLower))

        if not queryTokens:
            return []

        # 세션 주제 관련 키워드 (부스팅용)
        topicBoostKeywords = set()
        if sessionTopic:
            topicMap = {
                "조식": {"조식", "breakfast", "아침식사", "뷔페", "아침밥"},
                "다이닝": {"레스토랑", "식당", "다이닝", "dinner", "lunch"},
                "수영장": {"수영", "pool", "수영장"},
                "피트니스": {"피트니스", "헬스", "gym", "fitness"},
                "스파": {"스파", "spa", "마사지"},
                "주차": {"주차", "parking", "발렛"},
                "체크인/아웃": {"체크인", "체크아웃", "입실", "퇴실"},
                "객실": {"객실", "room", "침대"},
                "반려동물": {"반려동물", "반려견", "pet", "강아지"},
            }
            topicBoostKeywords = topicMap.get(sessionTopic, {sessionTopic})

        scored = []
        for chunk in cachedChunks:
            text = chunk.get("text", "").lower()
            chunkTokens = set(re.findall(r'[가-힣]{2,}', text))
            chunkTokens.update(re.findall(r'[a-z]{2,}', text))

            # 키워드 오버랩 점수
            overlap = queryTokens & chunkTokens
            overlapScore = len(overlap) / len(queryTokens) if queryTokens else 0

            # 주제 부스팅: 청크가 세션 주제와 관련있으면 점수 부스팅
            topicBoost = 0.0
            if topicBoostKeywords:
                topicOverlap = topicBoostKeywords & chunkTokens
                if topicOverlap:
                    topicBoost = 0.4  # 주제 일치 시 0.4 부스트

            # 원본 하이브리드 점수를 가중치로 반영
            originalScore = chunk.get("original_score", chunk.get("score", 0.5))
            combinedScore = overlapScore * 0.3 + originalScore * 0.3 + topicBoost

            scored.append({**chunk, "score": combinedScore, "source": "cache"})

        # 점수순 정렬
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:5]

    def _mergeResults(self, primary: list, secondary: list, topK: int = 5) -> list:
        """두 검색 결과 병합 (중복 제거, 점수순 정렬)"""
        seen = {r.get("chunk_id") for r in primary if r.get("chunk_id")}
        merged = list(primary)

        for r in secondary:
            chunkId = r.get("chunk_id")
            if chunkId and chunkId not in seen:
                merged.append(r)
                seen.add(chunkId)

        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[:topK]

    def answerVerifyNode(self, state: RAGState) -> RAGState:
        """답변 검증 노드: Grounding Gate 기반 문장 단위 근거 검증 + 할루시네이션 탐지"""
        answer = state.get("answer", "")
        query = state.get("query", "")
        chunks = state.get("retrieved_chunks", [])
        hotel = state.get("detected_hotel")

        # 호텔 연락처 정보
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        hotelName = hotelInfo.get("name", "")
        hotelPhone = hotelInfo.get("phone", "")
        contactGuide = f"{hotelName} ({hotelPhone})" if hotelPhone else "호텔 고객센터"

        allIssues = []

        # Phase 0: 쿼리-컨텍스트 관련성 검증 (최우선)
        relevancePassed, relevanceReason = answerVerifier.checkQueryContextRelevance(query, chunks)
        if not relevancePassed:
            allIssues.append(f"관련성 부족: {relevanceReason}")
            return {
                **state,
                "verification_passed": False,
                "verification_issues": allIssues,
                "verified_answer": f"죄송합니다, 해당 내용으로 정확한 정보를 찾을 수 없습니다.\n자세한 사항은 {contactGuide}로 문의 부탁드립니다.",
                "grounding_result": None,
                "query_intents": [],
            }

        # Phase 1: 응답 품질 검사 (비정상 문자, 언어 혼합)
        qualityPassed, qualityIssues = answerVerifier.checkResponseQuality(answer, query)
        allIssues.extend(qualityIssues)

        onlyForbiddenIssues = all("금지패턴" in i for i in qualityIssues) if qualityIssues else True
        if not qualityPassed and not onlyForbiddenIssues:
            return {
                **state,
                "verification_passed": False,
                "verification_issues": allIssues,
                "verified_answer": f"죄송합니다, 해당 내용으로 정확한 정보를 찾을 수 없습니다.\n자세한 사항은 {contactGuide}로 문의 부탁드립니다.",
                "grounding_result": None,
                "query_intents": [],
            }

        # 컨텍스트 구성
        context = "\n".join([chunk["text"] for chunk in chunks[:5]])

        # ========================================
        # Phase 2: Grounding Gate 검증 (문장 단위 근거 검증)
        # ========================================
        queryIntents = groundingGate.classifyIntent(query)
        groundingResult = groundingGate.verify(answer, context, query)

        # Grounding 결과를 dict로 변환 (상태 저장용)
        groundingDict = {
            "passed": groundingResult.passed,
            "confidence": groundingResult.confidence,
            "reason": groundingResult.reason,
            "verified_count": len(groundingResult.verified_claims),
            "rejected_count": len(groundingResult.rejected_claims),
            "rejected_claims": [
                {
                    "text": c.text[:100],
                    "score": c.evidence_score,
                    "has_numeric": c.has_numeric,
                    "numeric_verified": c.numeric_verified,
                }
                for c in groundingResult.rejected_claims
            ],
        }

        # Grounding 실패 시 이슈 추가
        if not groundingResult.passed:
            allIssues.append(f"Grounding 실패: {groundingResult.reason}")

        # 수치 토큰 미검증 시 경고
        for claim in groundingResult.rejected_claims:
            if claim.has_numeric and not claim.numeric_verified:
                allIssues.append(f"수치 검증 실패: '{claim.text[:30]}...'")

        # ========================================
        # Phase 3: 기존 할루시네이션 검사
        # ========================================
        hallucinationPassed, hallucinationIssues = answerVerifier.checkHallucination(answer, context)
        allIssues.extend(hallucinationIssues)

        # ========================================
        # Phase 3.3: 고유명사 할루시네이션 검사 (시설명/레스토랑명 교차검증)
        # ========================================
        properNounPassed, properNounIssues, properNounCleaned = answerVerifier.checkProperNounHallucination(answer, context)
        allIssues.extend(properNounIssues)
        if not properNounPassed:
            answer = properNounCleaned  # 검증 실패 문장 제거된 답변 사용
            print(f"[고유명사 검증] 할루시네이션 감지: {properNounIssues}")

        # ========================================
        # Phase 3.35: 쿼리 내 인물명 검증 (데이터에 없는 인물 질문 차단)
        # ========================================
        queryPersonRejected = False
        queryPersonPattern = re.compile(r'([가-힣]{2,4})\s*(셰프|쉐프|대표|오너|총괄|매니저|소믈리에)')
        queryPersonMatch = queryPersonPattern.search(query)
        if queryPersonMatch:
            personName = queryPersonMatch.group(1)
            contextLower = context.lower()
            if personName.lower() not in contextLower:
                properNounPassed = False
                queryPersonRejected = True
                allIssues.append(f"쿼리 인물명 미검증: '{queryPersonMatch.group(0)}' — 컨텍스트에 없음")
                print(f"[인물명 검증] 쿼리 내 '{queryPersonMatch.group(0)}' 컨텍스트 미검증 → 거부")

        # ========================================
        # Phase 3.4: 교통편/노선 날조 검사
        # ========================================
        transportPassed, transportIssues, transportCleaned = answerVerifier.checkTransportationHallucination(answer, context, query)
        allIssues.extend(transportIssues)
        if not transportPassed:
            answer = transportCleaned if len(transportCleaned) >= 10 else answer

        # ========================================
        # Phase 3.5: 카테고리 교차 오염 검사 (컨텍스트 오염 방지)
        # ========================================
        # 대화 주제 또는 감지된 카테고리 기반 검사
        targetCategory = state.get("conversation_topic") or state.get("effective_category") or state.get("category")
        categoryConsistencyResult = categoryChecker.verifyCategoryConsistency(answer, targetCategory, chunks)

        if not categoryConsistencyResult.passed:
            allIssues.append(f"카테고리 오염: {categoryConsistencyResult.reason}")
            # 오염된 문장 제거한 정제된 답변 사용
            if categoryConsistencyResult.cleaned_answer and len(categoryConsistencyResult.cleaned_answer) >= 10:
                answer = categoryConsistencyResult.cleaned_answer

        # 검증 결과 종합 (Grounding 결과 포함)
        passed = qualityPassed and hallucinationPassed and groundingResult.passed and properNounPassed and transportPassed

        # 금지 패턴 제거 (data/config/forbidden_patterns.json에서 로딩)
        cleanedAnswer = answerVerifier.removeForbiddenPhrases(answer)

        # 금지 패턴 제거 후 남은 내용이 유효한지 확인
        # (실제 정보가 포함되어 있으면 통과)
        verifiedAnswer = cleanedAnswer

        # ========================================
        # Phase 4: Grounding 기반 답변 재구성
        # ========================================
        if groundingResult.confidence == "근거없음":
            # 근거 없음: 폴백 응답
            verifiedAnswer = groundingGate._buildFallbackResponse(
                groundingResult, hotelName, contactGuide
            )
        elif groundingResult.confidence == "불확실" and groundingResult.rejected_claims:
            # 불확실: 검증된 claim만 사용
            if groundingResult.verified_claims:
                verifiedAnswer = cleanedAnswer
                # 검증 실패한 수치 문장 제거
                for rejected in groundingResult.rejected_claims:
                    if rejected.has_numeric and not rejected.numeric_verified:
                        verifiedAnswer = verifiedAnswer.replace(rejected.text, "")
                verifiedAnswer = re.sub(r'\n{3,}', '\n\n', verifiedAnswer).strip()
                if len(verifiedAnswer) < 10:
                    verifiedAnswer = groundingGate._buildFallbackResponse(
                        groundingResult, hotelName, contactGuide
                    )
            else:
                verifiedAnswer = groundingGate._buildFallbackResponse(
                    groundingResult, hotelName, contactGuide
                )
        else:
            # 확실: 정제된 답변 사용
            verifiedAnswer = cleanedAnswer

        # 심각한 이슈 (추정/추측/수치 검증 실패) 최종 체크
        hasSeriousIssue = any(
            "추정" in i or "추측" in i or "비정상" in i or "수치 검증 실패" in i
            for i in allIssues
        )

        if hasSeriousIssue:
            verifiedAnswer = f"정확한 정보 확인을 위해 {contactGuide}로 문의 부탁드립니다."
        elif not passed and len(verifiedAnswer) < 10:
            verifiedAnswer = f"정확한 정보 확인을 위해 {contactGuide}로 문의 부탁드립니다."
        # 할루시네이션 감지 후 잔여 답변이 짧고 모호한 경우 거부 처리
        elif not passed and (not properNounPassed or not transportPassed) and len(verifiedAnswer) < 80:
            verifiedAnswer = f"해당 정보를 확인하기 어렵습니다. {contactGuide}로 문의 부탁드립니다."

        # ========================================
        # Phase 4.1: Fallback 답변 개선 — top chunk 직접 추출
        # ========================================
        # 거부 응답이지만 실제로 관련 데이터가 있는 경우 top chunk에서 직접 추출
        refusalPatterns = ["찾지 못했습니다", "찾을 수 없습니다", "확인하기 어렵습니다",
                          "정확한 정보 확인을 위해", "문의 부탁드립니다"]
        isFallback = (
            len(verifiedAnswer) < 100
            and any(p in verifiedAnswer for p in refusalPatterns)
        )
        # 교통편 날조 또는 쿼리 인물명 미검증으로 거부된 경우 Fallback 차단
        # (LLM 답변 내 고유명사 오류는 Fallback과 무관: 청크에서 직접 추출하므로 안전)
        hallucinationRejected = not transportPassed or queryPersonRejected

        # Phase 4.1a: 연락처/전화번호 질문 시 HOTEL_INFO 단축 경로
        phoneKeywords = ["전화", "연락처", "대표번호", "전화번호", "번호"]
        isPhoneQuery = any(kw in query for kw in phoneKeywords)
        if isFallback and isPhoneQuery and hotel and hotelPhone:
            verifiedAnswer = f"{hotelName}의 대표 전화번호는 {hotelPhone}입니다."
            locationUrl = hotelInfo.get("locationUrl", "")
            if locationUrl:
                verifiedAnswer += f"\n\n참고 정보: {locationUrl}"
            print(f"[Fallback 연락처] HOTEL_INFO 단축 경로: {hotelName} {hotelPhone}")
            isFallback = False  # 단축 경로 사용 시 추가 Fallback 불필요

        if isFallback and chunks and state.get("evidence_passed") and not hallucinationRejected:
            # Phase 4.1b: chunk에서 전화번호 패턴 우선 추출
            phonePatternMatch = None
            if isPhoneQuery:
                for chunk in chunks[:5]:
                    chunkText = chunk.get("text", "")
                    phoneMatch = re.search(r'(\d{2,4}[-.]?\d{3,4}[-.]?\d{4})', chunkText)
                    if phoneMatch:
                        phonePatternMatch = phoneMatch.group(1)
                        chunkUrl = chunk.get("metadata", {}).get("url", chunk.get("url", ""))
                        verifiedAnswer = f"{hotelName}의 대표 전화번호는 {phonePatternMatch}입니다."
                        if chunkUrl:
                            verifiedAnswer += f"\n\n참고 정보: {chunkUrl}"
                        print(f"[Fallback 전화번호] chunk에서 전화번호 추출: {phonePatternMatch}")
                        break

            # Phase 4.1c: 일반 chunk 직접 추출
            if not phonePatternMatch:
                directAnswer = None
                bestUrl = ""
                for chunk in chunks[:3]:
                    chunkText = chunk.get("text", "")
                    chunkUrl = chunk.get("metadata", {}).get("url", chunk.get("url", ""))
                    extracted = answerVerifier.extractDirectAnswer(chunkText, query)
                    if extracted and len(extracted) >= 10:
                        directAnswer = extracted
                        bestUrl = chunkUrl
                        break

                if directAnswer:
                    if bestUrl:
                        directAnswer += f"\n\n참고 정보: {bestUrl}"
                    print(f"[Fallback 직접 추출] 거부 → chunk에서 답변 추출: {directAnswer[:80]}...")
                    verifiedAnswer = directAnswer

        # 금지 패턴만 있던 경우 통과 처리
        onlyForbiddenPatternIssues = all(
            "금지패턴" in i for i in allIssues
        ) if allIssues else False

        if onlyForbiddenPatternIssues and len(verifiedAnswer) >= 10:
            passed = True
            allIssues = []

        verifiedAnswer = re.sub(r'\n{3,}', '\n\n', verifiedAnswer).strip()

        return {
            **state,
            "verification_passed": passed,
            "verification_issues": allIssues,
            "verified_answer": verifiedAnswer,
            "grounding_result": groundingDict,
            "query_intents": queryIntents,
        }

    def policyFilterNode(self, state: RAGState) -> RAGState:
        """정책 필터 노드: 금지 주제 및 개인정보 필터링"""
        # 검증된 답변 사용 (없으면 원본 답변)
        answer = state.get("verified_answer") or state.get("answer", "")
        query = state["query"]
        hotel = state.get("detected_hotel")

        # 호텔 정보 조회
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        hotelName = hotelInfo.get("name", "")
        hotelPhone = hotelInfo.get("phone", "")

        # 연락처 안내 문구 생성
        if hotelName and hotelPhone:
            contactGuide = f"{hotelName} ({hotelPhone})"
        else:
            # 호텔 미지정 시 전체 호텔 연락처 안내
            allContacts = ", ".join([
                f"{info['name']} ({info['phone']})"
                for info in self.HOTEL_INFO.values()
            ])
            contactGuide = f"각 호텔 대표번호({allContacts})"

        # 금지 키워드 체크 (질문에서)
        for keyword in self.FORBIDDEN_KEYWORDS:
            if keyword in query:
                return {
                    **state,
                    "policy_passed": False,
                    "policy_reason": f"개인정보 관련 문의",
                    "final_answer": f"고객님의 소중한 개인정보(예약번호, 카드번호 등) 관련 문의는 보안상 챗봇에서 처리가 어렵습니다.\n자세한 사항은 {contactGuide}로 문의 부탁드립니다.",
                }

        # 근거 검증 실패 시 기본 답변
        if not state["evidence_passed"]:
            fallbackAnswer = f"죄송합니다, 해당 내용으로 정확한 정보를 찾을 수 없습니다.\n자세한 사항은 {contactGuide}로 문의 부탁드립니다."

            # 교통 관련 질문이면 위치 안내 URL 추가
            transportKeywords = ["가는 방법", "오시는 길", "오시는길", "어떻게 가", "찾아가는", "교통편", "가는 길", "가는길"]
            queryLower = query.lower()
            isTransportQuery = any(kw in queryLower for kw in transportKeywords)
            if isTransportQuery:
                locationUrl = hotelInfo.get("locationUrl", "")
                if locationUrl:
                    fallbackAnswer = f"죄송합니다, 해당 출발지에서의 정확한 교통 정보를 찾을 수 없습니다.\n호텔 위치 및 오시는 길 안내 페이지를 참고해 주세요: {locationUrl}\n추가 문의는 {contactGuide}로 부탁드립니다."

            return {
                **state,
                "policy_passed": True,
                "policy_reason": "근거 부족으로 기본 답변",
                "final_answer": fallbackAnswer,
            }

        # 출처 추가
        sources = state.get("sources", [])
        finalAnswer = answer
        # 사용된 모든 출처 URL 표시 (중복 제거)
        if sources:
            uniqueSources = list(dict.fromkeys(sources))  # 순서 유지하며 중복 제거
            if len(uniqueSources) == 1:
                finalAnswer += f"\n\n참고 정보: {uniqueSources[0]}"
            else:
                sourceList = "\n".join([f"- {url}" for url in uniqueSources])
                finalAnswer += f"\n\n참고 정보:\n{sourceList}"

        return {
            **state,
            "policy_passed": True,
            "policy_reason": "정상 처리",
            "final_answer": finalAnswer,
        }

    def logNode(self, state: RAGState) -> RAGState:
        """로그 노드: 대화 기록 저장"""
        logEntry = {
            "timestamp": datetime.now().isoformat(),
            "query": state["query"],
            "hotel": state.get("detected_hotel"),
            "category": state.get("category"),
            "evidence_passed": bool(state["evidence_passed"]),
            "verification_passed": bool(state.get("verification_passed", True)),
            "verification_issues": state.get("verification_issues", []),
            "top_score": float(state["top_score"]),
            "chunks_count": len(state["retrieved_chunks"]),
            "final_answer": state["final_answer"],
            # Grounding Gate 결과 추가
            "grounding_result": state.get("grounding_result"),
            "query_intents": state.get("query_intents", []),
        }

        # 파일에 로그 저장
        logFile = self.logPath / f"chat_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(logFile, "a", encoding="utf-8") as f:
            f.write(json.dumps(logEntry, ensure_ascii=False) + "\n")

        return {
            **state,
            "log": logEntry,
        }

    def chat(self, query: str, hotel: str = None, history: list = None,
             sessionCtx=None) -> dict:
        """채팅 실행

        Args:
            query: 사용자 질문
            hotel: 호텔 ID (선택)
            history: 대화 히스토리 (선택)
            sessionCtx: 세션 컨텍스트 객체 (선택, ConversationContext)
        """
        initialState: RAGState = {
            "query": query,
            "hotel": hotel,
            "history": history,  # 대화 히스토리
            "rewritten_query": "",  # 쿼리 재작성 결과
            "language": "",
            "detected_hotel": None,
            "category": None,
            "normalized_query": "",
            "is_valid_query": True,  # 기본값 True, preprocess에서 판단
            # 명확화 관련 필드
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "clarification_type": None,
            "retrieved_chunks": [],
            "top_score": 0.0,
            "evidence_passed": False,
            "evidence_reason": "",
            "answer": "",
            "sources": [],
            "verification_passed": True,
            "verification_issues": [],
            "verified_answer": "",
            "grounding_result": None,
            "query_intents": [],
            # 대화 주제 추적 (컨텍스트 오염 방지)
            "conversation_topic": None,
            "effective_category": None,
            # 세션 컨텍스트
            "session_context": sessionCtx,
            "policy_passed": False,
            "policy_reason": "",
            "final_answer": "",
            "log": {},
        }

        # 그래프 실행
        result = self.graph.invoke(initialState)

        # 세션 업데이트 (그래프 실행 후)
        if sessionCtx:
            # 현재 쿼리 기반 카테고리를 히스토리 기반 주제보다 우선
            detectedTopic = result.get("category") or result.get("conversation_topic")
            sessionCtx.updateTopic(detectedTopic, result.get("detected_hotel"))
            sessionCtx.cacheChunks(
                result.get("retrieved_chunks", []),
                query
            )

        return {
            "answer": result["final_answer"],
            "hotel": result["detected_hotel"],
            "category": result["category"],
            "evidence_passed": result["evidence_passed"],
            "verification_passed": result.get("verification_passed", True),
            "sources": result["sources"],
            "score": result["top_score"],
            # 명확화 관련 필드
            "needs_clarification": result.get("needs_clarification", False),
            "clarification_question": result.get("clarification_question", ""),
            "clarification_options": result.get("clarification_options", []),
            "clarification_type": result.get("clarification_type"),
            "clarification_subject": result.get("clarification_subject"),
            "original_query": query,  # 명확화 트리거된 원본 질문
        }


def createRAGGraph():
    """RAG 그래프 생성 헬퍼"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from pipeline.indexer import Indexer

    indexer = Indexer()
    return RAGGraph(indexer)


if __name__ == "__main__":
    # 테스트
    rag = createRAGGraph()

    testQueries = [
        "체크인 시간이 어떻게 되나요?",
        "조선팰리스 주차 요금 알려주세요",
        "제주 수영장 운영시간",
        "환불 정책이 어떻게 되나요?",
    ]

    for query in testQueries:
        print(f"\n{'='*50}")
        print(f"Q: {query}")
        result = rag.chat(query)
        print(f"A: {result['answer']}")
        print(f"호텔: {result['hotel']}, 점수: {result['score']:.3f}")
