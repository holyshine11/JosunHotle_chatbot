"""
LangGraph 기반 RAG 플로우
- No Retrieval, No Answer 정책 적용
- 7개 노드: preprocess → retrieve → evidence_gate → answer_compose → answer_verify → policy_filter → log
- 답변 검증으로 할루시네이션 방지
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
    is_valid_query: bool  # 호텔 관련 질문인지 여부

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

    # 정책 필터
    policy_passed: bool
    policy_reason: str
    final_answer: str

    # 로그
    log: dict


class RAGGraph:
    """LangGraph RAG 그래프"""

    # 근거 검증 임계값 (높을수록 엄격)
    EVIDENCE_THRESHOLD = 0.65  # 최소 유사도 점수 (질문 유효성 검사로 보완)

    # 질문 유효성 검사용 키워드 (호텔 관련 질문인지 판단)
    VALID_QUERY_KEYWORDS = [
        # 시설
        "체크인", "체크아웃", "check", "룸", "room", "객실", "스위트", "suite",
        "수영", "풀", "pool", "피트니스", "헬스", "fitness", "gym", "사우나", "스파",
        # 다이닝
        "레스토랑", "restaurant", "식당", "조식", "breakfast", "뷔페", "buffet",
        "다이닝", "dining", "식사", "아침", "점심", "저녁", "런치", "디너",
        # 서비스
        "주차", "parking", "발렛", "valet", "와이파이", "wifi", "인터넷",
        "어메니티", "amenity", "세탁", "laundry", "룸서비스",
        # 예약/정책
        "예약", "reservation", "취소", "cancel", "환불", "refund", "가격", "price", "요금",
        "정책", "policy", "규정", "이용",
        # 위치/연락처
        "위치", "location", "주소", "address", "전화", "phone", "연락", "contact",
        "찾아가", "교통", "지하철", "버스",
        # 기타 시설
        "웨딩", "wedding", "연회", "banquet", "회의", "meeting", "비즈니스",
        "키즈", "kids", "어린이", "반려", "pet", "강아지", "동물",
        "아트", "art", "컬렉션", "collection", "전시", "갤러리", "gallery",
        "라운지", "lounge", "바", "bar", "클럽", "club",
        # 일반
        "시간", "운영", "오픈", "영업", "몇시", "언제", "어디", "뭐", "무엇", "얼마", "how", "what", "where", "when",
        "안내", "소개", "정보", "알려", "가능",
    ]
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
        workflow.add_node("answer_verify", self.answerVerifyNode)  # 답변 검증 노드
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

        workflow.add_edge("answer_compose", "answer_verify")  # 답변 → 검증
        workflow.add_edge("answer_verify", "policy_filter")   # 검증 → 정책필터
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

        # 질문 유효성 검사 (호텔 관련 키워드 포함 여부)
        isValidQuery = False
        for keyword in self.VALID_QUERY_KEYWORDS:
            if keyword.lower() in queryLower:
                isValidQuery = True
                break

        return {
            **state,
            "language": language,
            "detected_hotel": detectedHotel,
            "category": detectedCategory,
            "normalized_query": query,
            "is_valid_query": isValidQuery,
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

        # 현재 세션 호텔 정보
        currentHotelNotice = ""
        if hotelName:
            currentHotelNotice = f"""
[현재 호텔] {hotelName}
- 다른 호텔 정보를 섞지 마세요
- 문의 안내 시: {contactInfo}"""

        systemPrompt = f"""당신은 조선호텔앤리조트의 AI 컨시어지입니다.
{currentHotelNotice}

[핵심 원칙]
1. 컨텍스트에 있는 정보만 사용
2. 정보가 없으면: "정확한 정보 확인을 위해 {contactInfo}로 문의 부탁드립니다"
3. 가격, 시간, 전화번호는 정확히 인용
4. 추측 금지 ("약", "대략", "아마" 사용 금지)

[답변 형식]
- 존댓말 (~입니다, ~드립니다)
- 목록은 불릿포인트(-) 사용
- 핵심 정보만 간결하게 전달
- 정보 나열 후 바로 종료

[절대 금지 - 반드시 지켜야 함]
- "궁금하신가요?" 금지
- "더 필요하신 것이 있으신가요?" 금지
- "어떤 것이 궁금하신가요?" 금지
- "문의해 주세요" 외의 추가 문장 금지
- 답변 끝에 질문 형태 문장 금지"""

        userPrompt = f"""[참고 정보]
{context}

[질문]
{query}

참고 정보만 사용해서 답변하세요. 정보 나열 후 바로 끝내세요. "궁금하신가요?" 같은 추가 질문은 절대 하지 마세요."""

        try:
            response = ollama.chat(
                model=self.LLM_MODEL,
                messages=[
                    {"role": "system", "content": systemPrompt},
                    {"role": "user", "content": userPrompt}
                ],
                options={
                    "temperature": 0.1,  # 매우 낮은 온도로 일관된 답변
                    "num_predict": 512,  # 토큰 수 증가 (긴 답변 대응)
                }
            )
            return response["message"]["content"].strip()
        except Exception as e:
            # LLM 실패 시 에러 로깅 후 컨텍스트 요약 반환
            import traceback
            print(f"[LLM 에러] {type(e).__name__}: {e}")
            traceback.print_exc()
            return f"[시스템 오류] LLM 응답 실패. 검색된 정보: {context[:200]}..."

    def _extractNumbers(self, text: str) -> set[str]:
        """텍스트에서 숫자 정보 추출 (가격, 시간, 전화번호)"""
        numbers = set()

        # 가격 패턴: 1,000원, 50000원, 1,234,567원
        prices = re.findall(r'[\d,]+\s*원', text)
        numbers.update(prices)

        # 시간 패턴: 15:00, 06:30, 오후 3시
        times = re.findall(r'\d{1,2}:\d{2}', text)
        numbers.update(times)

        # 전화번호 패턴: 02-727-7200, 051-922-5000
        phones = re.findall(r'\d{2,4}[-.]?\d{3,4}[-.]?\d{4}', text)
        numbers.update(phones)

        # 퍼센트: 20%, 30%
        percents = re.findall(r'\d+\s*%', text)
        numbers.update(percents)

        # 층수: 26층, 36층
        floors = re.findall(r'\d+\s*층', text)
        numbers.update(floors)

        # 인원: 2인, 4인
        persons = re.findall(r'\d+\s*인', text)
        numbers.update(persons)

        return numbers

    def _checkHallucination(self, answer: str, context: str) -> tuple[bool, list[str]]:
        """할루시네이션 검사: 답변의 숫자가 컨텍스트에 있는지 확인"""
        issues = []

        # 답변과 컨텍스트에서 숫자 추출
        answerNumbers = self._extractNumbers(answer)
        contextNumbers = self._extractNumbers(context)

        # 의심 패턴 검사
        suspiciousPatterns = [
            (r'약\s*[\d,]+\s*원', "추정 가격"),
            (r'대략\s*[\d,]+\s*원', "추정 가격"),
            (r'보통\s*[\d,]+\s*원', "추정 가격"),
            (r'평균\s*[\d,]+\s*원', "추정 가격"),
            (r'예상\s*[\d,]+', "추정 숫자"),
            (r'아마\s*\d+', "추측"),
        ]

        for pattern, issueType in suspiciousPatterns:
            if re.search(pattern, answer):
                issues.append(f"의심: {issueType} 발견")

        # 답변에만 있고 컨텍스트에 없는 숫자 검사
        for num in answerNumbers:
            # 정규화 (공백, 쉼표 제거)
            numNorm = re.sub(r'[\s,]', '', num)

            # 컨텍스트에서 찾기
            found = False
            for ctxNum in contextNumbers:
                ctxNorm = re.sub(r'[\s,]', '', ctxNum)
                if numNorm in ctxNorm or ctxNorm in numNorm:
                    found = True
                    break

            # 일반적인 숫자는 제외 (1, 2, 3 등)
            if not found and len(numNorm) > 2:
                # 컨텍스트 원문에서도 검색
                if numNorm not in context.replace(',', '').replace(' ', ''):
                    issues.append(f"검증실패: '{num}' - 컨텍스트에 없음")

        return len(issues) == 0, issues

    def answerVerifyNode(self, state: RAGState) -> RAGState:
        """답변 검증 노드: 할루시네이션 탐지 및 수정"""
        answer = state.get("answer", "")
        chunks = state.get("retrieved_chunks", [])
        hotel = state.get("detected_hotel")

        # 컨텍스트 구성
        context = "\n".join([chunk["text"] for chunk in chunks[:5]])

        # 할루시네이션 검사
        passed, issues = self._checkHallucination(answer, context)

        # 검증 실패 시 답변 수정
        verifiedAnswer = answer
        if not passed and issues:
            # 호텔 연락처 정보
            hotelInfo = self.HOTEL_INFO.get(hotel, {})
            hotelName = hotelInfo.get("name", "")
            hotelPhone = hotelInfo.get("phone", "")
            contactGuide = f"{hotelName} ({hotelPhone})" if hotelPhone else "호텔 고객센터"

            # 심각한 할루시네이션인 경우 (추정 가격 등)
            hasSeriousIssue = any("추정" in i or "추측" in i for i in issues)

            if hasSeriousIssue:
                # 답변 전체 교체
                verifiedAnswer = f"정확한 정보 확인을 위해 {contactGuide}로 문의 부탁드립니다."
            else:
                # 경미한 경우 경고 추가
                verifiedAnswer = answer + f"\n\n※ 정확한 정보는 {contactGuide}에서 확인해주세요."

        return {
            **state,
            "verification_passed": passed,
            "verification_issues": issues,
            "verified_answer": verifiedAnswer,
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
            "evidence_passed": bool(state["evidence_passed"]),
            "verification_passed": bool(state.get("verification_passed", True)),
            "verification_issues": state.get("verification_issues", []),
            "top_score": float(state["top_score"]),
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
            "is_valid_query": True,  # 기본값 True, preprocess에서 판단
            "retrieved_chunks": [],
            "top_score": 0.0,
            "evidence_passed": False,
            "evidence_reason": "",
            "answer": "",
            "sources": [],
            "verification_passed": True,
            "verification_issues": [],
            "verified_answer": "",
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
            "verification_passed": result.get("verification_passed", True),
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
