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
from datetime import datetime
from typing import TypedDict, Literal, Optional
from pathlib import Path

import ollama
from langgraph.graph import StateGraph, END

# Grounding Gate import
from rag.grounding import groundingGate, GroundingResult, categoryChecker


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
        # === 객실 관련 ===
        "체크인", "체크아웃", "check-in", "check-out", "checkout", "checkin",
        "룸", "room", "객실", "방", "스위트", "suite", "디럭스", "deluxe", "프리미어", "premier",
        "슈페리어", "superior", "스탠다드", "standard", "스테이트", "state", "마스터", "master",
        "침대", "베드", "bed", "싱글", "single", "더블", "double", "트윈", "twin", "킹", "king", "퀸", "queen",
        "뷰", "view", "전망", "오션", "ocean", "시티", "city", "마운틴", "mountain", "가든", "garden",
        "금연", "흡연", "smoking", "non-smoking", "nonsmoking",
        "연결", "커넥팅", "connecting", "어드조인", "adjoining",
        "인원", "추가", "엑스트라", "extra", "베이비", "baby", "유아", "크립", "crib", "요람",

        # === 시설/부대시설 ===
        "수영", "수영장", "풀", "pool", "swimming", "워터", "water", "자쿠지", "jacuzzi",
        "피트니스", "헬스", "헬스장", "fitness", "gym", "운동", "체육", "트레이닝",
        "사우나", "sauna", "찜질", "한증", "스팀", "steam",
        "스파", "spa", "마사지", "massage", "테라피", "therapy", "트리트먼트", "treatment",
        "라운지", "lounge", "로비", "lobby", "대기",
        "비즈니스", "business", "센터", "center", "회의", "회의실", "미팅", "meeting", "컨퍼런스", "conference",
        "연회", "연회장", "banquet", "볼룸", "ballroom", "홀", "hall",
        "웨딩", "wedding", "결혼", "예식", "신부", "신랑", "웨딩홀",
        "키즈", "kids", "어린이", "아이", "놀이", "키즈클럽", "키즈룸", "놀이방", "게임",
        "아트", "art", "컬렉션", "collection", "전시", "갤러리", "gallery", "작품",
        "도서", "라이브러리", "library", "북",
        "클럽", "club", "멤버", "member", "회원",
        "테라스", "terrace", "발코니", "balcony", "루프탑", "rooftop", "옥상",
        "정원", "가든", "garden", "조경",

        # === 다이닝/식음료 ===
        "레스토랑", "restaurant", "식당", "음식점",
        "조식", "breakfast", "아침", "모닝", "morning",
        "중식", "lunch", "점심", "런치",
        "석식", "dinner", "저녁", "디너",
        "뷔페", "buffet", "부페",
        "다이닝", "dining", "식사", "밥", "먹",
        "바", "bar", "주류", "술", "와인", "wine", "칵테일", "cocktail", "맥주", "beer",
        "카페", "cafe", "커피", "coffee", "티", "tea", "베이커리", "bakery", "디저트", "dessert",
        "룸서비스", "room service", "인룸", "in-room",
        "델리", "deli", "테이크아웃", "takeout", "포장",
        "중식당", "일식", "한식", "양식", "이탈리안", "프렌치", "차이니즈", "chinese", "일본", "japanese", "korean",
        "미슐랭", "michelin", "파인다이닝", "fine dining",
        "아리아", "aria", "콘스탄스", "constans", "홍연", "팔레", "palais",

        # === 서비스 ===
        "주차", "parking", "발렛", "valet", "파킹", "셀프", "self",
        "와이파이", "wifi", "wi-fi", "인터넷", "internet", "무선",
        "어메니티", "amenity", "amenities", "비품", "용품", "칫솔", "치약", "샴푸", "린스", "바디워시",
        "세탁", "laundry", "드라이", "dry", "클리닝", "cleaning", "다림", "iron",
        "컨시어지", "concierge", "안내", "도움",
        "벨", "bell", "포터", "porter", "짐", "수하물", "luggage", "baggage", "보관",
        "픽업", "pickup", "드롭", "drop", "셔틀", "shuttle", "리무진", "limousine", "공항",
        "환전", "exchange", "외화",
        "모닝콜", "wake-up", "wakeup", "알람",
        "턴다운", "turndown", "turn-down",
        "미니바", "minibar", "mini-bar", "냉장고",
        "금고", "safe", "세이프", "귀중품",
        "슬리퍼", "가운", "robe", "타월", "towel",

        # === 예약/정책/결제 ===
        "예약", "reservation", "booking", "부킹",
        "취소", "cancel", "cancellation", "변경", "modify", "수정",
        "환불", "refund", "위약", "패널티", "penalty", "노쇼", "no-show", "noshow",
        "가격", "price", "요금", "비용", "cost", "금액", "원", "달러", "dollar",
        "결제", "payment", "카드", "card", "현금", "cash", "계좌", "이체",
        "정책", "policy", "규정", "약관", "조건", "terms",
        "보증", "guarantee", "deposit", "디파짓", "선결제", "후결제",
        "할인", "discount", "프로모션", "promotion", "이벤트", "event", "특가", "패키지", "package",
        "멤버십", "membership", "포인트", "point", "적립", "마일리지", "mileage",
        "쿠폰", "coupon", "바우처", "voucher", "상품권", "기프트", "gift",
        "영수증", "receipt", "인보이스", "invoice", "세금계산서",

        # === 위치/교통/연락처 ===
        "위치", "location", "어디", "어딨", "장소",
        "주소", "address", "도로명", "지번",
        "찾아가", "오시는", "가는", "길",
        "교통", "대중교통", "transportation",
        "지하철", "subway", "metro", "역",
        "버스", "bus", "정류장",
        "택시", "taxi", "콜택시",
        "네비", "내비", "네비게이션", "navigation",
        "전화", "phone", "연락", "contact", "번호", "tel", "문의",
        "이메일", "email", "e-mail", "메일",
        "팩스", "fax",

        # === 고객 유형 ===
        "반려", "pet", "펫", "강아지", "개", "고양이", "동물", "애완",
        "장애", "disabled", "휠체어", "wheelchair", "배리어프리", "barrier-free",
        "노약자", "어르신", "시니어", "senior",
        "임산부", "pregnant", "산모",
        "외국인", "foreigner", "영어", "english", "일본어", "japanese", "중국어", "chinese",

        # === 특수 서비스 ===
        "생일", "birthday", "기념일", "anniversary", "프로포즈", "propose", "허니문", "honeymoon",
        "케이크", "cake", "꽃", "flower", "풍선", "balloon", "장식", "decoration",
        "촬영", "photo", "사진", "포토",
        "의료", "medical", "약국", "pharmacy", "병원", "hospital", "응급",

        # === 일반 질문 패턴 ===
        "시간", "운영", "오픈", "open", "클로즈", "close", "영업", "휴무", "휴관", "휴일",
        "몇시", "언제", "when", "몇분", "얼마나",
        "어디", "where", "어느",
        "뭐", "무엇", "what", "뭔가", "어떤", "which",
        "얼마", "how much", "비싸", "싼", "저렴",
        "있", "없", "되", "안되", "가능", "불가", "허용", "금지",
        "포함", "include", "제외", "exclude", "별도", "추가",
        "무료", "free", "유료", "paid", "공짜",
        "최대", "최소", "max", "min", "제한", "limit",
        "추천", "recommend", "베스트", "best", "인기", "popular",
        "안내", "소개", "정보", "info", "알려", "설명",
        "문의", "질문", "ask", "question",

        # === 호텔 브랜드/이름 ===
        "조선", "josun", "팰리스", "palace", "그랜드", "grand",
        "레스케이프", "lescape", "l'escape",
        "그래비티", "gravity", "판교", "pangyo",
        "부산", "busan", "해운대",
        "제주", "jeju",
        "호텔", "hotel", "리조트", "resort", "숙소", "숙박", "투숙",

        # =========================
        # (A) 예약/투숙 플로우 실사용 표현
        # =========================
        "예약해", "예약하고", "예약하려", "예약할래", "예약가능", "예약 가능", "예약 되나", "예약 돼", "예약되", "예약이 돼",
        "예약확인", "예약 확인", "예약조회", "예약 조회", "예약내역", "예약 내역", "내 예약", "예약서", "예약서류",
        "예약변경", "예약 변경", "예약취소", "예약 취소", "취소가능", "취소 가능", "취소해", "취소할래",
        "날짜변경", "날짜 변경", "일정변경", "일정 변경", "인원변경", "인원 변경", "객실변경", "객실 변경",
        "체크인시간", "체크인 시간", "체크아웃시간", "체크아웃 시간", "얼리체크인", "early check-in", "early check in",
        "레이트체크아웃", "late check-out", "late check out", "조기입실", "늦은퇴실", "늦퇴실", "빠른입실",
        "데이유즈", "day use", "데이유스", "당일사용", "당일 이용",
        "연박", "연박할인", "장기투숙", "장기 투숙", "롱스테이", "long stay",
        "패키지", "패키지상품", "패키지 상품", "프로모션", "프로모션코드", "프로모션 코드", "프로모코드", "쿠폰코드", "쿠폰 코드",
        "멤버", "멤버십", "회원가", "회원가 적용", "포인트사용", "포인트 사용", "포인트적립", "포인트 적립",

        # =========================
        # (B) 요금/결제/증빙 (현장 질문 TOP)
        # =========================
        "세금", "봉사료", "부가세", "VAT", "tax", "service charge",
        "보증금", "디파짓", "보증", "선결제", "후불", "후결제", "현장결제", "현장 결제",
        "카드결제", "카드 결제", "간편결제", "간편 결제", "애플페이", "Apple Pay", "삼성페이", "Samsung Pay",
        "페이코", "PAYCO", "카카오페이", "KakaoPay", "네이버페이", "Naver Pay",
        "영수증", "영수증 발급", "세금계산서", "세금 계산서", "인보이스", "invoice", "증빙", "증빙서류", "증빙 서류",
        "환불규정", "환불 규정", "취소규정", "취소 규정", "위약금", "패널티", "노쇼", "noshow", "no show",

        # =========================
        # (C) 객실/침구/기준인원/뷰/옵션
        # =========================
        "룸타입", "룸 타입", "객실타입", "객실 타입", "타입", "객실 업그레이드", "업글", "업그레이드", "upgrade",
        "침구", "베딩", "bedding", "침대사이즈", "침대 사이즈", "킹베드", "퀸베드", "트윈베드",
        "엑스트라베드", "엑스트라 베드", "extra bed", "침대추가", "침대 추가", "토퍼", "topper",
        "가드레일", "bed rail", "아기침대", "베이비침대", "유아침대", "baby cot", "cot", "유아용품", "키즈용품",
        "기준인원", "기준 인원", "최대인원", "최대 인원", "추가인원", "추가 인원", "추가요금", "추가 요금", "인원추가",
        "뷰좋은", "뷰 좋은", "오션뷰", "오션 뷰", "씨뷰", "시뷰", "sea view", "오션프론트", "oceanfront",
        "시티뷰", "시티 뷰", "파크뷰", "파크 뷰", "가든뷰", "가든 뷰", "마운틴뷰", "마운틴 뷰",
        "고층", "저층", "높은층", "낮은층", "층수", "코너룸", "코너 룸", "corner room",
        "흡연룸", "흡연 룸", "금연룸", "금연 룸", "smoking room", "non smoking", "non-smoking",
        "커넥팅룸", "커넥팅 룸", "connecting room", "연결객실", "연결 객실", "인접객실", "인접 객실", "adjoining room",

        # =========================
        # (D) 부대시설/운영시간/이용조건
        # =========================
        "운영시간", "운영 시간", "이용시간", "이용 시간", "몇시까지", "몇 시까지", "언제까지", "언제부터",
        "오픈시간", "오픈 시간", "마감시간", "마감 시간",
        "휴무", "휴관", "쉬는날", "쉬는 날", "정기휴무", "정기 휴무",
        "수영복", "수모", "수영모", "수영캡", "수모필수", "수모 필수",
        "사우나이용", "사우나 이용", "스파이용", "스파 이용", "피트니스이용", "피트니스 이용",
        "락커", "라커", "locker", "샤워", "shower", "탈의실", "탈의 실",
        "키즈존", "키즈 존", "키즈클럽", "키즈 클럽", "어린이풀", "키즈풀", "kids pool",
        "라운지", "이그제큐티브", "이그제큐티브 라운지", "executive lounge", "클럽라운지", "club lounge",

        # =========================
        # (E) 다이닝 (예약/가격/메뉴/드레스코드/라스트오더/룸차지)
        # =========================
        "레스토랑예약", "레스토랑 예약", "식당예약", "식당 예약", "다이닝예약", "다이닝 예약",
        "브런치", "brunch", "애프터눈티", "애프터눈 티", "afternoon tea",
        "라스트오더", "라스트 오더", "last order", "LO",
        "드레스코드", "드레스 코드", "dress code", "복장", "복장규정", "복장 규정",
        "메뉴", "menu", "가격", "가격대", "코스", "course", "코스요리", "코스 요리",
        "룸차지", "룸 차지", "room charge",
        "알레르기", "allergy", "채식", "비건", "vegan", "글루텐프리", "gluten free", "할랄", "halal",
        "케이크", "케이크 예약", "케이크 주문", "생일케이크", "기념일케이크",

        # =========================
        # (F) 위치/교통/주차 (자주 나오는 표현)
        # =========================
        "주차요금", "주차 요금", "주차무료", "주차 무료", "무료주차", "무료 주차",
        "발렛요금", "발렛 요금", "발렛비", "발렛 비", "발렛가능", "발렛 가능",
        "입차", "출차", "주차장", "주차 타워", "주차타워", "지하주차", "지하 주차",
        "대중교통", "지하철", "역에서", "역에서 어떻게", "버스 노선", "공항버스", "공항 버스",
        "픽업", "픽업서비스", "픽업 서비스", "셔틀", "셔틀버스", "셔틀 버스", "리무진", "공항리무진",
        "길찾기", "길 찾기", "네비주소", "네비 주소", "내비", "네비", "주변", "근처",

        # =========================
        # (G) 정책/규정/요청사항 (현장 민원성 표현)
        # =========================
        "미성년자", "보호자", "동반", "동반가능", "동반 가능",
        "반려동물가능", "반려동물 가능", "펫동반", "펫 동반", "동물동반", "동물 동반",
        "유모차", "아기", "유아", "아동", "키즈",
        "휠체어", "장애인", "배리어프리", "배리어 프리", "장애인 편의",
        "짐보관", "짐 보관", "수하물", "러기지", "luggage",
        "조용한방", "조용한 방", "엘리베이터 가까운", "엘베 가까운", "고층 요청", "저층 요청",
        "얼음", "ice", "어댑터", "adapter", "충전기", "charger", "변압기", "transformer",
    ]
    MIN_CHUNKS_REQUIRED = 1   # 최소 필요 청크 수

    # LLM 설정
    LLM_MODEL = "qwen2.5:7b"
    LLM_ENABLED = True  # LLM 사용 여부 (False면 검색 결과 직접 반환)

    # 호텔 키워드 매핑 (오타/변형/지역명 포함)
    HOTEL_KEYWORDS = {
        "josun_palace": [
            "조선팰리스", "조선 팰리스", "조선펠리스", "조선 펠리스", "팰리스", "펠리스", "palace", "강남",
            "조선팰리스강남", "조선 팰리스 강남", "josun palace", "josunpalace",
            "더조선팰리스", "더 조선 팰리스", "the josun palace", "thejosunpalace",
            "강남조선", "강남 조선", "역삼", "역삼역", "테헤란로"
        ],
        "grand_josun_busan": [
            "그랜드조선부산", "그랜드 조선 부산", "부산", "해운대", "busan",
            "그조부", "그조 부산", "grand josun busan", "grandjosunbusan",
            "그랜드조선 해운대", "그랜드 조선 해운대", "해운대 조선", "센텀", "해운대해수욕장"
        ],
        "grand_josun_jeju": [
            "그랜드조선제주", "그랜드 조선 제주", "제주", "jeju",
            "그조제", "그조 제주", "grand josun jeju", "grandjosunjeju",
            "그랜드조선 서귀포", "그랜드 조선 서귀포", "중문", "중문관광단지"
        ],
        "lescape": [
            "레스케이프", "레스 케이프", "l'escape", "lescape", "명동", "중구",
            "레스케이프명동", "레스케이프 명동", "호텔레스케이프", "호텔 레스케이프",
            "lescape hotel", "l escape", "엘이스케이프", "을지로", "을지로입구", "충무로"
        ],
        "gravity_pangyo": [
            "그래비티", "그레비티", "gravity", "판교", "pangyo",
            "그래비티판교", "그래비티 판교", "호텔그래비티", "호텔 그래비티",
            "gravity hotel", "그라비티", "분당", "야탑", "서현", "판교역"
        ],
    }

    # 카테고리 키워드 (확장)
    CATEGORY_KEYWORDS = {
        "체크인/아웃": [
            "체크인", "체크아웃", "입실", "퇴실", "check-in", "check-out",
            "얼리체크인", "레이트체크아웃", "checkin", "checkout", "early", "late"
        ],
        "예약/조회": [
            "예약확인", "예약조회", "예약내역", "내예약", "booking", "reservation", "confirm"
        ],
        "요금/결제": [
            "요금", "가격", "금액", "결제", "선결제", "현장결제", "보증금", "디파짓",
            "영수증", "세금계산서", "invoice", "세금", "봉사료", "VAT"
        ],
        "주차": [
            "주차", "parking", "발렛", "valet", "주차요금", "무료주차", "발렛요금"
        ],
        "조식": [
            "조식", "아침", "breakfast", "뷔페", "buffet", "모닝"
        ],
        "다이닝": [
            "레스토랑", "식당", "다이닝", "레스토랑예약", "애프터눈티", "라스트오더",
            "드레스코드", "알레르기", "비건", "채식", "룸차지", "브런치"
        ],
        "객실": [
            "객실", "방", "room", "침대", "bed", "인원", "룸타입", "업그레이드",
            "베딩", "침구", "토퍼", "엑스트라베드", "아기침대", "기준인원", "최대인원",
            "오션뷰", "시티뷰", "커넥팅룸"
        ],
        "부대시설": [
            "피트니스", "수영", "사우나", "스파", "헬스", "gym", "pool", "fitness",
            "라운지", "키즈클럽", "락커", "샤워", "탈의실", "운영시간", "휴무", "휴관"
        ],
        "환불/취소": [
            "환불", "취소", "cancel", "refund", "위약금", "노쇼", "환불규정", "취소규정"
        ],
        "반려동물": [
            "반려동물", "애완", "pet", "강아지", "고양이", "펫", "반려견",
            "반려동물가능", "펫동반", "동물동반"
        ],
        "위치/교통": [
            "위치", "교통", "지하철", "버스", "택시", "공항", "주차요금", "무료주차",
            "발렛요금", "공항버스", "셔틀버스", "픽업서비스", "길찾기", "네비주소"
        ],
        "정책/규정": [
            "미성년자", "반려동물가능", "휠체어", "배리어프리", "짐보관", "요청사항",
            "보호자", "동반가능"
        ],
    }

    # 동의어 사전 (쿼리 확장용)
    SYNONYM_DICT = {
        # 반려동물
        "강아지": ["반려견", "pet", "개", "펫", "반려동물", "애견", "소형견"],
        "반려견": ["강아지", "pet", "개", "펫", "반려동물", "애견"],
        "펫": ["pet", "반려견", "강아지", "반려동물"],
        "pet": ["펫", "반려견", "강아지", "반려동물"],
        "펫동반": ["펫 동반", "반려동물동반", "반려동물 동반", "동물동반", "pet friendly", "pet-friendly"],

        # 주차
        "주차": ["parking", "발렛", "valet", "파킹", "자가용"],
        "발렛": ["valet", "주차", "발렛파킹", "발레", "대리주차"],
        "주차요금": ["주차 요금", "parking fee", "parking cost", "주차비"],

        # 수영장
        "수영장": ["pool", "풀", "swimming", "인피니티풀", "swimming pool", "인피니티 풀"],

        # 조식/다이닝
        "조식": ["breakfast", "아침", "뷔페", "아침식사", "모닝", "morning buffet"],
        "아침": ["breakfast", "조식", "아침식사"],
        "애프터눈티": ["afternoon tea", "티세트", "티 세트", "하이티", "high tea"],
        "라스트오더": ["last order", "LO", "주문마감", "주문 마감"],

        # 스파/웰니스
        "스파": ["spa", "마사지", "웰니스", "massage", "wellness", "SWISS PERFECTION"],
        "마사지": ["massage", "스파", "spa", "웰니스"],
        "사우나": ["sauna", "스파", "스팀", "steam", "찜질"],

        # 피트니스
        "피트니스": ["fitness", "헬스", "gym", "운동", "운동시설", "트레이닝룸"],
        "헬스": ["fitness", "피트니스", "gym", "헬스장"],

        # 체크인/아웃
        "체크인": ["check-in", "입실", "checkin"],
        "체크아웃": ["check-out", "퇴실", "checkout"],
        "얼리체크인": ["early check-in", "early check in", "조기입실", "빠른입실", "이른체크인"],
        "레이트체크아웃": ["late check-out", "late check out", "늦은퇴실", "늦퇴실", "연장체크아웃"],

        # 결제/증빙
        "영수증": ["영수증발급", "증빙", "증빙서류", "인보이스", "invoice", "세금계산서", "세금 계산서"],
        "디파짓": ["보증금", "deposit", "preauth", "pre-authorization", "보증"],

        # 객실/침구
        "엑스트라베드": ["extra bed", "침대추가", "침대 추가", "보조침대", "보조 침대"],
        "아기침대": ["baby cot", "cot", "crib", "유아침대", "베이비침대", "크립"],
        "기준인원": ["기준 인원", "standard occupancy", "base occupancy"],
        "최대인원": ["최대 인원", "max occupancy", "maximum occupancy"],

        # 뷰
        "오션뷰": ["오션 뷰", "씨뷰", "시뷰", "sea view", "ocean view"],
        "시티뷰": ["시티 뷰", "도시전망", "city view"],
    }

    # 금지 키워드 (정책 필터)
    FORBIDDEN_KEYWORDS = [
        "예약번호", "카드번호", "비밀번호", "주민등록", "여권번호",
        "계좌번호", "신용카드", "결제정보"
    ]

    # 모호한 질문 패턴 (명확화 필요)
    # 키: 모호한 키워드, 값: 가능한 대상 옵션들
    AMBIGUOUS_PATTERNS = {
        "시간": {
            "keywords": ["시간", "몇시", "언제", "오픈", "open", "마감", "close"],
            "options": ["체크인/체크아웃", "조식", "수영장", "피트니스", "스파/사우나", "레스토랑"],
            "question": "어떤 시설의 운영 시간을 알고 싶으신가요?",
        },
        "가격": {
            "keywords": ["가격", "요금", "얼마", "비용", "금액"],
            "options": ["객실", "조식", "주차", "스파/마사지", "다이닝"],
            "question": "어떤 서비스의 가격을 알고 싶으신가요?",
        },
        "예약": {
            "keywords": ["예약"],
            "excludes": ["예약확인", "예약조회", "예약내역", "예약번호", "예약취소", "예약변경"],  # 명확한 질문 제외
            "options": ["객실 예약", "레스토랑 예약", "스파 예약", "연회장 예약"],
            "question": "어떤 예약에 대해 문의하시나요?",
        },
        "위치": {
            "keywords": ["위치", "어디", "어딨"],
            "excludes": ["호텔 위치", "호텔 어디", "찾아가", "오시는"],  # 호텔 위치 질문은 명확
            "options": ["호텔 위치/찾아오는 길", "수영장", "피트니스", "레스토랑", "스파"],
            "question": "어떤 시설의 위치를 알고 싶으신가요?",
        },
    }

    # 무의미/비속어/스팸 질문 블랙리스트
    INVALID_QUERY_PATTERNS = [
        # 비속어/무의미
        r'방구', r'뭔\s*맛', r'무슨\s*맛', r'맛이야', r'냄새나',
        r'똥|오줌|변기|소변|대변',
        r'섹스|야동|포르노|음란',
        r'^ㅋ+$|^ㅎ+$|^ㅠ+$|^ㄱㄱ+$',
        r'바보|멍청|병신',
        r'이쁘니|예쁘니|귀엽니',  # 무관한 감탄 질문

        # 링크/스팸
        r'http[s]?://',           # 링크만 던지는 경우
        r'www\.',                 # 링크
        r'^\s*\d+\s*$',           # 숫자만
        r'^\s*[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>/?]+\s*$',  # 특수문자만
        r'^\s*[😂🤣😊😅👍🙏❤️💙💚🖤]+\s*$',               # 이모지 도배
        r'(광고|홍보|대출|코인|리딩방)',                   # 스팸성 키워드
    ]

    # 최소 질문 길이
    MIN_QUERY_LENGTH = 3

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

        # 맥락 참조 패턴 감지 (대명사, 지시어 등)
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
        ]

        needsRewrite = any(re.search(p, query, re.IGNORECASE) for p in contextPatterns)

        # 질문이 너무 짧으면 맥락 필요할 가능성 높음
        if len(query.strip()) < 15:
            needsRewrite = True

        if not needsRewrite:
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

[재작성된 질문]"""

        try:
            response = ollama.chat(
                model="qwen2.5:7b",
                messages=[{"role": "user", "content": rewritePrompt}],
                options={
                    "temperature": 0.0,
                    "num_predict": 100,
                }
            )
            rewrittenQuery = response["message"]["content"].strip()

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
        """명확화 체크 노드: 모호한 질문 감지 및 명확화 질문 생성"""
        query = state.get("normalized_query") or state.get("rewritten_query") or state["query"]
        queryLower = query.lower()
        hotel = state.get("detected_hotel")

        # 호텔 정보 (명확화 질문에 포함)
        hotelInfo = self.HOTEL_INFO.get(hotel, {})
        hotelName = hotelInfo.get("name", "")

        # 기본값 설정
        needsClarification = False
        clarificationQuestion = ""
        clarificationOptions = []

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
            "취소", "환불", "취소정책", "환불정책", "노쇼", "정책",
        ]

        # 질문에 이미 구체적인 대상이 있으면 명확화 불필요
        hasSpecificTarget = any(target in queryLower for target in specificTargets)

        if hasSpecificTarget:
            return {
                **state,
                "needs_clarification": False,
                "clarification_question": "",
                "clarification_options": [],
            }

        # 모호한 패턴 검사
        for patternKey, patternInfo in self.AMBIGUOUS_PATTERNS.items():
            keywords = patternInfo["keywords"]
            excludes = patternInfo.get("excludes", [])

            # 제외 패턴 체크 (명확한 질문)
            if any(exc in queryLower for exc in excludes):
                continue

            # 모호한 키워드 매칭
            if any(kw in queryLower for kw in keywords):
                needsClarification = True
                clarificationQuestion = patternInfo["question"]
                clarificationOptions = patternInfo["options"]

                # 호텔명 추가
                if hotelName:
                    clarificationQuestion = f"[{hotelName}] {clarificationQuestion}"

                print(f"[명확화 필요] '{query}' → {clarificationQuestion}")
                break

        if needsClarification:
            # 명확화 질문을 final_answer로 설정
            return {
                **state,
                "needs_clarification": True,
                "clarification_question": clarificationQuestion,
                "clarification_options": clarificationOptions,
                # 명확화 시 바로 응답하기 위한 필드 설정
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
        if isValidQuery:
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

        return {
            **state,
            "language": language,
            "detected_hotel": detectedHotel,
            "category": detectedCategory,
            "normalized_query": query,
            "is_valid_query": isValidQuery,
        }

    def retrieveNode(self, state: RAGState) -> RAGState:
        """검색 노드: Vector DB에서 관련 청크 검색 (쿼리 확장 + 카테고리 필터)

        카테고리 필터는 후속 질문(히스토리 있음)에서만 적용하여
        컨텍스트 오염을 방지.
        """
        query = state["normalized_query"]
        hotel = state["detected_hotel"]
        detectedCategory = state.get("category")
        history = state.get("history", [])

        # 대화 주제 추출 (히스토리 기반)
        conversationTopic = self._extractConversationTopic(history)

        # 효과적 카테고리 결정:
        # - 히스토리가 있는 경우(후속 질문): 대화 주제로 필터링
        # - 히스토리가 없는 경우(첫 질문): 필터 없이 검색
        effectiveCategory = None
        if history and conversationTopic:
            # 후속 질문: 대화 주제로 필터링 (컨텍스트 오염 방지)
            effectiveCategory = conversationTopic

        # 쿼리 확장 (동의어 추가)
        expandedQuery = self._expandQuery(query)

        # 1차 검색
        results = self.indexer.search(
            query=expandedQuery,
            hotel=hotel,
            category=effectiveCategory,  # 후속 질문시에만 필터 적용
            topK=5
        )

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

        # 최고 점수 계산
        topScore = results[0]["score"] if results else 0.0

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

        systemPrompt = f"""당신은 조선호텔앤리조트의 프리미엄 AI 컨시어지입니다. 하이엔드 고객을 응대합니다.
{currentHotelNotice}

[핵심 원칙]
1. 컨텍스트에 있는 정보만 사용
2. 정보가 없으면: "정확한 정보 확인을 위해 {contactInfo}로 문의 부탁드립니다"
3. 가격, 시간, 전화번호는 정확히 인용
4. 추측 금지 ("약", "대략", "아마" 사용 금지)

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

[정보 조합 금지]
- 질문에서 언급되지 않은 주제의 정보는 절대 답변에 포함하지 마세요
- 컨텍스트에 해당 정보가 없으면: "해당 정보를 찾을 수 없습니다. {contactInfo}로 문의 부탁드립니다."

[절대 금지]
- "궁금하신가요?" 금지
- "더 필요하신 것이 있으신가요?" 금지
- 답변 끝에 질문 형태 문장 금지
- 단어/숫자만 던지는 불친절한 답변 금지"""

        userPrompt = f"""[참고 정보]
{context}

[질문]
{query}

[지시사항]
1. 반드시 완성된 문장으로 정중하게 답변하세요
2. 단어나 숫자만 던지지 마세요 (예: "역삼역" X → "가장 가까운 역은 역삼역입니다" O)
3. 참고 정보만 사용하세요
4. "궁금하신가요?" 같은 추가 질문은 절대 하지 마세요"""

        try:
            response = ollama.chat(
                model=self.LLM_MODEL,
                messages=[
                    {"role": "system", "content": systemPrompt},
                    {"role": "user", "content": userPrompt}
                ],
                options={
                    "temperature": 0.0,  # 온도 0으로 완전 결정론적 답변
                    "num_predict": 512,  # 토큰 수 증가 (긴 답변 대응)
                }
            )
            answer = response["message"]["content"].strip()

            # 후처리: 중국어/일본어 문자 제거 (qwen 모델의 할루시네이션 방지)
            # 중국어 한자 범위: \u4e00-\u9fff
            # 일본어 히라가나/가타카나: \u3040-\u30ff
            chinesePart = re.search(r'[\u4e00-\u9fff]{3,}', answer)
            if chinesePart:
                # 중국어가 시작되는 지점에서 자르기
                cutIndex = chinesePart.start()
                answer = answer[:cutIndex].strip()
                # 문장이 잘렸으면 마무리
                if answer and not answer.endswith(('.', '다', '요', '!')):
                    answer = answer.rstrip(',.;:')
                    if answer:
                        answer += "."

            return answer
        except Exception as e:
            # LLM 실패 시 에러 로깅 후 컨텍스트 요약 반환
            import traceback
            print(f"[LLM 에러] {type(e).__name__}: {e}")
            traceback.print_exc()
            return f"[시스템 오류] LLM 응답 실패. 검색된 정보: {context[:200]}..."

    def _extractConversationTopic(self, history: list[dict]) -> Optional[str]:
        """대화 히스토리에서 현재 주제 추출 (컨텍스트 오염 방지)

        최근 4개 메시지를 분석하여 대화 주제(카테고리)를 반환.
        예: 조식 → "조식", 수영장 → "부대시설"
        """
        if not history:
            return None

        # 최근 4개 메시지만 분석
        recentMessages = history[-4:] if len(history) > 4 else history

        # 메시지 텍스트 결합
        combinedText = ""
        for msg in recentMessages:
            content = msg.get("content", "")
            combinedText += f" {content}"

        combinedTextLower = combinedText.lower()

        # 카테고리별 키워드 매칭 (우선순위 순서)
        # 더 구체적인 카테고리를 먼저 검사
        topicPriority = [
            ("조식", ["조식", "breakfast", "아침식사", "뷔페", "아침밥", "모닝"]),
            ("다이닝", ["레스토랑", "식당", "다이닝", "저녁", "점심", "런치", "디너"]),
            ("수영장", ["수영", "pool", "풀", "swimming", "수영장"]),
            ("피트니스", ["피트니스", "헬스", "gym", "fitness", "운동"]),
            ("스파", ["스파", "spa", "마사지", "massage", "사우나"]),
            ("주차", ["주차", "parking", "발렛", "valet", "파킹"]),
            ("체크인/아웃", ["체크인", "체크아웃", "입실", "퇴실", "check-in", "check-out"]),
            ("객실", ["객실", "방", "room", "침대", "bed", "뷰", "전망"]),
            ("요금/결제", ["요금", "가격", "결제", "비용", "금액"]),
            ("반려동물", ["강아지", "반려견", "pet", "펫", "반려동물", "애견"]),
        ]

        for topic, keywords in topicPriority:
            for keyword in keywords:
                if keyword.lower() in combinedTextLower:
                    return topic

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

    def _extractQueryKeywords(self, query: str) -> list[str]:
        """질문에서 핵심 키워드 추출"""
        # 반려동물/펫 관련 키워드
        petKeywords = ["강아지", "반려견", "pet", "펫", "반려동물", "개", "애견", "고양이"]
        # 주차 관련 키워드
        parkingKeywords = ["주차", "parking", "발렛", "valet", "파킹"]
        # 수영장 관련 키워드
        poolKeywords = ["수영장", "pool", "풀", "swimming"]
        # 조식 관련 키워드
        breakfastKeywords = ["조식", "breakfast", "아침", "뷔페", "아침식사"]

        queryLower = query.lower()
        foundKeywords = []

        # 카테고리별 키워드 검사
        if any(kw in queryLower for kw in petKeywords):
            foundKeywords.append("반려동물")
        if any(kw in queryLower for kw in parkingKeywords):
            foundKeywords.append("주차")
        if any(kw in queryLower for kw in poolKeywords):
            foundKeywords.append("수영장")
        if any(kw in queryLower for kw in breakfastKeywords):
            foundKeywords.append("조식")

        return foundKeywords

    def _checkQueryContextRelevance(self, query: str, chunks: list) -> tuple[bool, str]:
        """질문 핵심 키워드가 검색된 청크에 있는지 검증"""
        queryKeywords = self._extractQueryKeywords(query)

        if not queryKeywords:
            # 핵심 키워드가 없으면 검증 통과 (일반 질문)
            return True, ""

        # 청크 텍스트 결합
        chunkTexts = " ".join([c.get("text", "") for c in chunks[:3]])
        chunkTextsLower = chunkTexts.lower()

        # 카테고리 메타데이터도 확인
        chunkCategories = [c.get("metadata", {}).get("category", "").lower() for c in chunks[:3]]

        # 카테고리별 확장 키워드 (검색 범위 확대)
        categoryKeywordMap = {
            "반려동물": ["반려", "pet", "펫", "강아지", "dog", "애견", "소형견", "반려견", "동물", "salon"],
            "주차": ["주차", "parking", "발렛", "valet", "파킹"],
            "수영장": ["수영", "pool", "풀", "swimming", "인피니티"],
            "조식": ["조식", "breakfast", "아침", "뷔페", "dining"],
        }

        # 동의어 포함하여 매칭 검사
        for keyword in queryKeywords:
            keywordFound = False

            # 카테고리 메타데이터에서 직접 매칭
            for cat in chunkCategories:
                if keyword.replace("동물", "") in cat or keyword in cat:
                    keywordFound = True
                    break

            # 텍스트에서 확장 키워드 매칭
            if not keywordFound:
                expandedKeywords = categoryKeywordMap.get(keyword, [keyword])
                for kw in expandedKeywords:
                    if kw.lower() in chunkTextsLower:
                        keywordFound = True
                        break

            if not keywordFound:
                return False, f"질문의 '{keyword}' 관련 정보가 검색 결과에 없습니다."

        return True, ""

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

    def _checkResponseQuality(self, answer: str, query: str) -> tuple[bool, list[str]]:
        """응답 품질 검사 (Phase 1): 비정상 문자, 언어 혼합 탐지"""
        issues = []

        # 1. 비정상 문자 탐지 (중국어 한자)
        chineseChars = re.findall(r'[\u4e00-\u9fff]', answer)
        if len(chineseChars) > 2:  # 2글자 이상 중국어
            issues.append(f"비정상: 중국어 문자 포함 ({len(chineseChars)}자)")

        # 2. 일본어 문자 탐지 (히라가나/가타카나)
        japaneseChars = re.findall(r'[\u3040-\u30ff]', answer)
        if len(japaneseChars) > 2:
            issues.append(f"비정상: 일본어 문자 포함 ({len(japaneseChars)}자)")

        # 3. 한글 비율 검사 (개선: 시간/숫자/영문 브랜드명 제외 후 계산)
        # 정상적인 호텔 정보에 포함되는 패턴 제거
        normalizedAnswer = answer

        # 시간 패턴 제거 (06:30, 10:00 - 18:00, BREAK TIME 등)
        normalizedAnswer = re.sub(r'\d{1,2}:\d{2}\s*[-~]\s*\d{1,2}:\d{2}', '', normalizedAnswer)
        normalizedAnswer = re.sub(r'\d{1,2}:\d{2}', '', normalizedAnswer)
        normalizedAnswer = re.sub(r'BREAK\s*TIME', '', normalizedAnswer, flags=re.IGNORECASE)

        # 호텔 관련 영문 브랜드/용어 제거
        hotelTerms = [
            'KIDS', 'Superior', 'Deluxe', 'Suite', 'Premier', 'Standard',
            'Twin', 'Double', 'King', 'Queen', 'Pool', 'Spa', 'Fitness',
            'Andish', 'Zerovity', 'Aria', 'Constans', 'Eat2O',
            'VAT', 'URL', 'http', 'https', 'do', 'josunhotel', 'com',
        ]
        for term in hotelTerms:
            normalizedAnswer = re.sub(rf'\b{term}\b', '', normalizedAnswer, flags=re.IGNORECASE)

        # 숫자, URL, 특수문자 제거
        normalizedAnswer = re.sub(r'[\d\-:~/.,@#$%^&*()_+=\[\]{}|\\<>]', '', normalizedAnswer)

        koreanChars = len(re.findall(r'[가-힣]', normalizedAnswer))
        totalChars = len(normalizedAnswer.replace(' ', '').replace('\n', ''))

        # 정규화 후 최소 문자가 남아있을 때만 비율 체크
        if totalChars > 5 and koreanChars / totalChars < 0.25:
            issues.append(f"비정상: 한글 비율 낮음 ({koreanChars}/{totalChars})")

        # 4. 의미 없는 패턴 탐지
        meaninglessPatterns = [
            (r'宫咚咚', "중국어 의미없는 패턴"),
            (r'参考资料', "중국어 안내 문구"),
            (r'无法提供', "중국어 안내 문구"),
            (r'\?\?+', "반복 물음표"),
            (r'！！+', "반복 느낌표"),
            (r'\.\.\.\.+', "과도한 말줄임"),
        ]
        for pattern, desc in meaninglessPatterns:
            if re.search(pattern, answer):
                issues.append(f"비정상: {desc}")
                break

        # 5. 답변이 너무 짧거나 비어있음
        cleanAnswer = answer.strip()
        if len(cleanAnswer) < 5:
            issues.append("비정상: 답변이 너무 짧음")

        # 6. 금지 패턴 강제 필터링 (LLM이 무시해도 잡아냄)
        forbiddenPatterns = [
            (r'궁금하신가요', "금지 문구"),
            (r'더\s*필요하신\s*것', "금지 문구"),
            (r'어떤\s*것이?\s*궁금', "금지 문구"),
            (r'도움이?\s*되셨', "금지 문구"),
            (r'추가.*질문', "금지 문구"),
            (r'알려주시면', "금지 문구"),
            (r'말씀해\s*주시', "금지 문구"),
            (r'문의.*주시면', "금지 문구"),
            (r'^\s*-\s*-\s*$', "빈 내용"),  # "- -" 같은 의미없는 패턴
            (r'정보가\s*없습니다.*문의', "잘못된 안내"),  # 정보 없다면서 문의 유도
        ]
        for pattern, desc in forbiddenPatterns:
            if re.search(pattern, answer, re.IGNORECASE | re.MULTILINE):
                issues.append(f"금지패턴: {desc}")

        return len(issues) == 0, issues

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
        relevancePassed, relevanceReason = self._checkQueryContextRelevance(query, chunks)
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
        qualityPassed, qualityIssues = self._checkResponseQuality(answer, query)
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
        hallucinationPassed, hallucinationIssues = self._checkHallucination(answer, context)
        allIssues.extend(hallucinationIssues)

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
        passed = qualityPassed and hallucinationPassed and groundingResult.passed

        # 금지 패턴 제거
        forbiddenPhrases = [
            r'궁금하신가요\??',
            r'더\s*필요하신\s*것이?\s*있으신가요\??',
            r'어떤\s*것이?\s*궁금하신가요\??',
            r'도움이?\s*되셨[기나]?를?.*바랍니다\.?',
            r'도움이?\s*되셨나요\??',
            r'알려주시면.*답변.*드리겠습니다\.?',
            r'다른\s*궁금한\s*사항이?\s*있으시면.*',
            r'이에\s*대한\s*추가\s*문의사항이?\s*있으시다면.*',
            r'더\s*필요한\s*정보가?\s*있으신가요\??',
            r'더\s*궁금하신\s*사항이?\s*있으신가요\??',
            r'이\s*정보로\s*도움이?.*',  # "이 정보로 도움이..." 전체 제거
            r'이용에\s*불편을\s*드려\s*죄송합니다\.?',
            r'이\s*정보로\s*$',  # 문장 끝에 남은 "이 정보로" 제거
        ]
        cleanedAnswer = answer
        for phrase in forbiddenPhrases:
            cleanedAnswer = re.sub(phrase, '', cleanedAnswer, flags=re.IGNORECASE)

        # 빈 줄 정리
        cleanedAnswer = re.sub(r'\n{3,}', '\n\n', cleanedAnswer).strip()

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

    def chat(self, query: str, hotel: str = None, history: list = None) -> dict:
        """채팅 실행"""
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
            # 명확화 관련 필드
            "needs_clarification": result.get("needs_clarification", False),
            "clarification_options": result.get("clarification_options", []),
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
