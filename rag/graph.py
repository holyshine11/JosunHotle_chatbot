"""
LangGraph 기반 RAG 플로우
- No Retrieval, No Answer 정책 적용
- 6개 노드: preprocess → retrieve → evidence_gate → answer_compose → policy_filter → log
- Ollama LLM (qwen2.5:7b)으로 자연어 답변 생성
"""

import re
import json
from datetime import datetime
from typing import TypedDict, Literal, Optional
from pathlib import Path

import ollama
from langgraph.graph import StateGraph, END


class RAGState(TypedDict):
    """RAG 상태 정의"""
    # 입력
    query: str
    hotel: Optional[str]

    # 전처리 결과
    language: str
    detected_hotel: Optional[str]
    category: Optional[str]
    normalized_query: str

    # 검색 결과
    retrieved_chunks: list[dict]
    top_score: float

    # 근거 검증
    evidence_passed: bool
    evidence_reason: str

    # 답변
    answer: str
    sources: list[str]

    # 정책 필터
    policy_passed: bool
    policy_reason: str
    final_answer: str

    # 로그
    log: dict


class RAGGraph:
    """LangGraph RAG 그래프"""

    # 근거 검증 임계값 (높을수록 엄격)
    EVIDENCE_THRESHOLD = 0.7  # 최소 유사도 점수 (0.5 → 0.7로 상향)
    MIN_CHUNKS_REQUIRED = 1   # 최소 필요 청크 수

    # LLM 설정
    LLM_MODEL = "qwen2.5:7b"
    LLM_ENABLED = True  # LLM 사용 여부 (False면 검색 결과 직접 반환)

    # 호텔 키워드 매핑 (오타/변형 포함)
    HOTEL_KEYWORDS = {
        "josun_palace": ["조선팰리스", "조선 팰리스", "조선펠리스", "조선 펠리스", "팰리스", "펠리스", "palace", "강남"],
        "grand_josun_busan": ["그랜드조선부산", "그랜드 조선 부산", "부산", "해운대", "busan"],
        "grand_josun_jeju": ["그랜드조선제주", "그랜드 조선 제주", "제주", "jeju"],
        "lescape": ["레스케이프", "레스 케이프", "l'escape", "lescape", "명동", "중구"],
        "gravity_pangyo": ["그래비티", "그레비티", "gravity", "판교", "pangyo"],
    }

    # 카테고리 키워드
    CATEGORY_KEYWORDS = {
        "체크인/아웃": ["체크인", "체크아웃", "입실", "퇴실", "check-in", "check-out"],
        "주차": ["주차", "parking", "발렛", "valet"],
        "조식": ["조식", "아침", "breakfast", "뷔페", "buffet"],
        "객실": ["객실", "방", "room", "침대", "bed", "인원"],
        "부대시설": ["피트니스", "수영", "사우나", "스파", "헬스", "gym", "pool", "fitness"],
        "환불/취소": ["환불", "취소", "cancel", "refund", "위약금"],
        "반려동물": ["반려동물", "애완", "pet", "강아지", "고양이"],
        "위치/교통": ["위치", "교통", "지하철", "버스", "택시", "공항"],
    }

    # 금지 키워드 (정책 필터)
    FORBIDDEN_KEYWORDS = [
        "예약번호", "카드번호", "비밀번호", "주민등록", "여권번호",
        "계좌번호", "신용카드", "결제정보"
    ]

    # 호텔 정보 (이름, 연락처)
    HOTEL_INFO = {
        "josun_palace": {"name": "조선 팰리스", "phone": "02-727-7200"},
        "grand_josun_busan": {"name": "그랜드 조선 부산", "phone": "051-922-5000"},
        "grand_josun_jeju": {"name": "그랜드 조선 제주", "phone": "064-735-8000"},
        "lescape": {"name": "레스케이프", "phone": "02-317-4000"},
        "gravity_pangyo": {"name": "그래비티 판교", "phone": "031-539-4800"},
    }

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
        workflow.add_node("preprocess", self.preprocessNode)
        workflow.add_node("retrieve", self.retrieveNode)
        workflow.add_node("evidence_gate", self.evidenceGateNode)
        workflow.add_node("answer_compose", self.answerComposeNode)
        workflow.add_node("policy_filter", self.policyFilterNode)
        workflow.add_node("log", self.logNode)

        # 엣지 정의
        workflow.set_entry_point("preprocess")
        workflow.add_edge("preprocess", "retrieve")
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

        workflow.add_edge("answer_compose", "policy_filter")
        workflow.add_edge("policy_filter", "log")
        workflow.add_edge("log", END)

        return workflow.compile()

    def _evidenceRouter(self, state: RAGState) -> Literal["pass", "fail"]:
        """근거 검증 결과에 따른 라우팅"""
        return "pass" if state["evidence_passed"] else "fail"

    def preprocessNode(self, state: RAGState) -> RAGState:
        """전처리 노드: 입력 정규화, 언어/호텔/카테고리 감지"""
        query = state["query"].strip()
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

        return {
            **state,
            "language": language,
            "detected_hotel": detectedHotel,
            "category": detectedCategory,
            "normalized_query": query,
        }

    def retrieveNode(self, state: RAGState) -> RAGState:
        """검색 노드: Vector DB에서 관련 청크 검색"""
        query = state["normalized_query"]
        hotel = state["detected_hotel"]
        category = state.get("category")

        # 검색 실행
        results = self.indexer.search(
            query=query,
            hotel=hotel,
            category=None,  # 카테고리 필터는 선택적
            topK=5
        )

        # 최고 점수 계산
        topScore = results[0]["score"] if results else 0.0

        return {
            **state,
            "retrieved_chunks": results,
            "top_score": topScore,
        }

    def evidenceGateNode(self, state: RAGState) -> RAGState:
        """근거 검증 노드: 검색 결과 품질 확인"""
        chunks = state["retrieved_chunks"]
        topScore = state["top_score"]

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
        """답변 생성 노드: LLM을 사용해 자연어 답변 생성"""
        chunks = state["retrieved_chunks"]
        query = state["normalized_query"]
        hotel = state.get("detected_hotel")

        if not chunks:
            return {
                **state,
                "answer": "",
                "sources": [],
            }

        # 출처 수집 (중복 제거)
        sources = []
        seenUrls = set()
        for chunk in chunks[:3]:
            url = chunk["metadata"].get("url", "")
            if url and url not in seenUrls:
                sources.append(url)
                seenUrls.add(url)

        # 컨텍스트 구성 (상위 5개 청크 포함)
        contextParts = []
        for i, chunk in enumerate(chunks[:5], 1):
            hotelName = chunk["metadata"].get("hotel_name", "")
            text = chunk["text"]
            contextParts.append(f"[{hotelName}]\n{text}")

        context = "\n\n".join(contextParts)

        # LLM 사용 여부에 따라 분기
        if self.LLM_ENABLED:
            answer = self._generateWithLLM(query, context, hotel)
        else:
            # LLM 미사용 시 검색 결과 직접 반환
            topChunk = chunks[0]
            answer = topChunk["text"]
            if "A:" in answer:
                answer = answer.split("A:")[-1].strip()
            hotelName = topChunk["metadata"].get("hotel_name", "")
            if hotelName:
                answer = f"[{hotelName}] {answer}"

        return {
            **state,
            "answer": answer,
            "sources": sources,
        }

    def _generateWithLLM(self, query: str, context: str, hotel: str = None) -> str:
        """Ollama LLM으로 답변 생성"""
        # 호텔 정보 조회
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        hotelName = hotelInfo.get("name", "")
        hotelPhone = hotelInfo.get("phone", "")

        contactInfo = f"{hotelName} ({hotelPhone})" if hotelPhone else "호텔 고객센터"

        # 호텔 정식 명칭 목록
        hotelNames = ", ".join([info["name"] for info in self.HOTEL_INFO.values()])

        # 현재 세션 호텔 강조
        currentHotelNotice = ""
        if hotelName:
            currentHotelNotice = f"""
[중요] 현재 고객님은 "{hotelName}" 호텔에 대해 문의 중입니다.
- 반드시 "{hotelName}"으로 답변을 시작하세요
- 다른 호텔명(그랜드 조선 제주, 그랜드 조선 부산 등)을 언급하지 마세요
- 연락처 안내 시: {contactInfo}"""

        systemPrompt = f"""당신은 조선호텔앤리조트의 AI 컨시어지입니다.
{currentHotelNotice}

[답변 원칙]
1. 질문의 핵심 키워드(스위트, 수영장, 조식 등)와 정확히 일치하는 정보를 컨텍스트에서 찾으세요
2. "스위트룸" 질문시 → (SUITE) 표시된 객실 정보 사용
3. "객실" 일반 질문시 → 여러 객실 타입 정보 제공
4. 가격/운영시간 등 구체적 정보는 컨텍스트 그대로 인용
5. 교통편, 거리, 소요시간 등 컨텍스트에 없는 정보는 추측 금지

[금지 사항]
- 컨텍스트에 없는 정보 추측 금지
- 다른 호텔 정보 혼동 금지

[답변 형식]
- 2-3문장으로 간결하게
- 존댓말 사용 (~입니다, ~드립니다)
- 가격/시간 등 구체적 정보는 그대로 인용"""

        userPrompt = f"""[현재 문의 호텔: {hotelName or "미지정"}]

[참고 정보]
{context}

[질문]
{query}

[답변]"""

        try:
            response = ollama.chat(
                model=self.LLM_MODEL,
                messages=[
                    {"role": "system", "content": systemPrompt},
                    {"role": "user", "content": userPrompt}
                ],
                options={
                    "temperature": 0.3,  # 낮은 온도로 일관된 답변
                    "num_predict": 256,  # 최대 토큰 수
                }
            )
            return response["message"]["content"].strip()
        except Exception as e:
            # LLM 실패 시 에러 로깅 후 컨텍스트 요약 반환
            import traceback
            print(f"[LLM 에러] {type(e).__name__}: {e}")
            traceback.print_exc()
            return f"[시스템 오류] LLM 응답 실패. 검색된 정보: {context[:200]}..."

    def policyFilterNode(self, state: RAGState) -> RAGState:
        """정책 필터 노드: 금지 주제 및 개인정보 필터링"""
        answer = state.get("answer", "")
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
            return {
                **state,
                "policy_passed": True,
                "policy_reason": "근거 부족으로 기본 답변",
                "final_answer": f"죄송합니다, 해당 내용으로 정확한 정보를 찾을 수 없습니다.\n자세한 사항은 {contactGuide}로 문의 부탁드립니다.",
            }

        # 출처 추가
        sources = state.get("sources", [])
        finalAnswer = answer
        if sources:
            finalAnswer += f"\n\n참고 정보: {sources[0]}"

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
            "evidence_passed": state["evidence_passed"],
            "top_score": state["top_score"],
            "chunks_count": len(state["retrieved_chunks"]),
            "final_answer": state["final_answer"],
        }

        # 파일에 로그 저장
        logFile = self.logPath / f"chat_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(logFile, "a", encoding="utf-8") as f:
            f.write(json.dumps(logEntry, ensure_ascii=False) + "\n")

        return {
            **state,
            "log": logEntry,
        }

    def chat(self, query: str, hotel: str = None) -> dict:
        """채팅 실행"""
        initialState: RAGState = {
            "query": query,
            "hotel": hotel,
            "language": "",
            "detected_hotel": None,
            "category": None,
            "normalized_query": "",
            "retrieved_chunks": [],
            "top_score": 0.0,
            "evidence_passed": False,
            "evidence_reason": "",
            "answer": "",
            "sources": [],
            "policy_passed": False,
            "policy_reason": "",
            "final_answer": "",
            "log": {},
        }

        # 그래프 실행
        result = self.graph.invoke(initialState)

        return {
            "answer": result["final_answer"],
            "hotel": result["detected_hotel"],
            "category": result["category"],
            "evidence_passed": result["evidence_passed"],
            "sources": result["sources"],
            "score": result["top_score"],
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
