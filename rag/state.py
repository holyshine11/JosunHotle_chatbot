"""RAG 파이프라인 상태 정의 (TypedDict)"""

from typing import TypedDict, Optional


class RAGState(TypedDict):
    """RAG 파이프라인 상태"""
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

    # 내부 플래그
    _pipeline_start: float  # 파이프라인 시작 시간
    llm_failed: bool  # queryRewrite LLM 실패 여부
    detected_context: Optional[str]  # 감지된 맥락 키 (반려동물, 어린이 등)
    clarification_context: Optional[str]  # 명확화 맥락 키

    # 로그
    log: dict
