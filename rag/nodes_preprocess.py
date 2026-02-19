"""전처리 노드: 쿼리 재작성, 입력 정규화, 명확화 체크"""

import re
import time
from typing import Optional

from rag.state import RAGState
from rag.llm_provider import callLLM
from rag.entity import extractRestaurantEntity
from rag.constants import (
    HOTEL_KEYWORDS, CATEGORY_KEYWORDS, VALID_QUERY_KEYWORDS,
    INVALID_QUERY_PATTERNS, MIN_QUERY_LENGTH, HOTEL_INFO,
    AMBIGUOUS_PATTERNS, CONTEXT_CLARIFICATION,
)


def _tryRuleBasedRewrite(query: str, history: list) -> Optional[str]:
    """규칙 기반 쿼리 재작성: 단순 후속 질문은 LLM 호출 없이 재작성.

    대상 패턴:
    - "거기 X은?" → 이전 대화 시설/호텔 + X
    - "몇 시에 열어?", "얼마야?" → 이전 대화 주체 + 질문
    - "그럼 X는?" → 이전 대화 호텔 + X 명시

    Returns:
        재작성된 쿼리 또는 None (규칙 적용 불가)
    """
    if not history:
        return None

    queryStrip = query.strip()

    # 이전 assistant 답변에서 호텔명/시설명 추출
    prevSubject = None
    prevHotel = None
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            # 호텔명 추출 ([] 안의 호텔명)
            hotelMatch = re.search(r'\[([^\]]*(?:팰리스|부산|제주|레스케이프|그래비티)[^\]]*)\]', content)
            if hotelMatch:
                prevHotel = hotelMatch.group(1)
            # 시설명 추출 (레스토랑, 수영장, 피트니스 등 핵심 시설)
            facilityPatterns = [
                r'([\w가-힣]+\s*(?:레스토랑|식당|카페|바|라운지|뷔페|다이닝))',
                r'((?:수영장|풀|피트니스|헬스|사우나|스파|키즈클럽|비즈니스\s*센터))',
                r'((?:조식|석식|런치|디너|브런치))',
            ]
            for fp in facilityPatterns:
                m = re.search(fp, content)
                if m:
                    prevSubject = m.group(1).strip()
                    break
            if prevSubject:
                break
        elif msg.get("role") == "user":
            # 이전 사용자 질문에서도 주체 추출
            userContent = msg.get("content", "")
            for fp in [
                r'([\w가-힣]+\s*(?:레스토랑|식당|카페|바|라운지|뷔페|다이닝))',
                r'((?:수영장|풀|피트니스|헬스|사우나|스파|키즈클럽))',
                r'((?:조식|석식|런치|디너|브런치))',
            ]:
                m = re.search(fp, userContent)
                if m:
                    prevSubject = m.group(1).strip()
                    break
            if prevSubject:
                break

    if not prevSubject and not prevHotel:
        return None

    subject = prevSubject or prevHotel or ""

    # 패턴 1: "거기 X은/는?" → 호텔(장소) + X ("거기"는 장소 지시어이므로 호텔 우선)
    m = re.match(r'^거기\s+(.+)', queryStrip)
    if m:
        placeSubject = prevHotel or prevSubject or ""
        return f"{placeSubject} {m.group(1)}"

    # 패턴 2: "그럼 X는/은?" → 호텔 + X
    m = re.match(r'^그럼\s+(.+)', queryStrip)
    if m:
        rest = m.group(1)
        if prevHotel:
            return f"{prevHotel} {rest}"
        return f"{subject} {rest}"

    # 패턴 3: "그러면 X" → 호텔 + X
    m = re.match(r'^그러면\s+(.+)', queryStrip)
    if m:
        if prevHotel:
            return f"{prevHotel} {m.group(1)}"
        return f"{subject} {m.group(1)}"

    # 패턴 4: 짧은 후속 질문 (시간/가격/위치 등)
    shortPatterns = [
        (r'^몇\s*시.*', f"{subject} 운영시간"),
        (r'^얼마.*', f"{subject} 가격"),
        (r'^어디.*', f"{subject} 위치"),
        (r'^언제.*', f"{subject} 운영시간"),
        (r'^예약.*', f"{subject} 예약 방법"),
    ]
    for pattern, rewritten in shortPatterns:
        if re.match(pattern, queryStrip):
            return rewritten

    return None


def queryRewriteNode(state: RAGState) -> dict:
    """쿼리 재작성 노드: 대화 맥락을 반영하여 질문을 완전한 형태로 재작성"""
    _start = time.time()
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

    # === 규칙 기반 재작성 시도 (LLM 호출 없이 5-8s 절약) ===
    ruleResult = _tryRuleBasedRewrite(query, history)
    if ruleResult:
        _elapsed = time.time() - _start
        print(f"[쿼리 재작성] 규칙 기반: '{query}' → '{ruleResult}' ({_elapsed:.3f}s, LLM 스킵)")
        return {
            **state,
            "rewritten_query": ruleResult,
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
        # 히스토리에서 주제 키워드를 추출할 수 없어도 (빈 set) 현재 쿼리에
        # 명확한 주제가 있으면 자체 완결형이므로 재작성 건너뜀
        if not historyTopics or currentTopic not in historyTopics:
            print(f"[주제 전환 감지] 히스토리 '{historyTopics}' → 현재 '{currentTopic}', 재작성 건너뜀")
            return {
                **state,
                "rewritten_query": query,
            }

        # 같은 주제 follow-up이지만 쿼리에 이미 구체적 시설/서비스명이 있으면 자체 완결형
        # 예: "피트니스는 몇시에 문을 열어?" → "피트니스" 포함 → 재작성 불필요
        # LLM 재작성이 오히려 무관한 맥락을 주입하여 검색 품질을 저하시키는 것을 방지
        topicKeywordsInQuery = [kw for kw in topicGroups[currentTopic] if kw in queryLower]
        if topicKeywordsInQuery:
            print(f"[자체 완결] '{query}' → 주제 키워드 '{topicKeywordsInQuery[0]}' 포함, 재작성 건너뜀")
            return {
                **state,
                "rewritten_query": query,
            }

    # 최근 대화 맥락 구성 (최대 2턴 = 4메시지, 입력 토큰 절약)
    recentHistory = history[-4:] if len(history) > 4 else history

    historyText = ""
    for msg in recentHistory:
        role = "Q" if msg.get("role") == "user" else "A"
        content = msg.get("content", "")[:150]  # 짧게 자르기
        historyText += f"{role}: {content}\n"

    # LLM으로 쿼리 재작성 (경량화 프롬프트 + 시스템 한국어 강제)
    rewriteSystem = "한국어 질문 재작성 전문가. 반드시 한국어로만 응답. 질문 1문장만 출력."
    rewritePrompt = f"""[대화]
{historyText}
[현재 질문] {query}

이전 대화의 주제(장소/서비스명)를 포함하여 완전한 질문으로 재작성하세요. 다른 주제면 원본 유지.
재작성:"""

    try:
        rewrittenQuery = callLLM(
            prompt=rewritePrompt,
            system=rewriteSystem,
            temperature=0.0,
            maxTokens=60,
            numCtx=1024  # 입력 짧음, KV캐시 75% 절감
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
        # LLM 실패 플래그: answerCompose에서 LLM 재호출 방지 (연쇄 타임아웃 차단)
        _elapsed = time.time() - _start
        print(f"[타이밍] queryRewrite: {_elapsed:.3f}s (LLM 실패)")
        return {
            **state,
            "rewritten_query": rewrittenQuery,
            "llm_failed": True,
        }

    _elapsed = time.time() - _start
    print(f"[타이밍] queryRewrite: {_elapsed:.3f}s")
    return {
        **state,
        "rewritten_query": rewrittenQuery,
    }


def preprocessNode(state: RAGState) -> dict:
    """전처리 노드: 입력 정규화, 언어/호텔/카테고리 감지"""
    _start = time.time()
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
        for hotelKey, keywords in HOTEL_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in queryLower:
                    detectedHotel = hotelKey
                    break
            if detectedHotel:
                break

    # 카테고리 감지
    detectedCategory = None
    queryLower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in queryLower:
                detectedCategory = category
                break
        if detectedCategory:
            break

    # Phase 2: 블랙리스트 패턴 검사 (최우선)
    isValidQuery = True
    for pattern in INVALID_QUERY_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            isValidQuery = False
            break

    # 최소 길이 검사
    if isValidQuery and len(query.strip()) < MIN_QUERY_LENGTH:
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
        for keyword in VALID_QUERY_KEYWORDS:
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
    # 원본 쿼리 사용: LLM 재작성 시 히스토리 레스토랑명 주입으로 인한 오탐 방지
    originalQueryForEntity = state.get("query", "").strip()
    entityResult = extractRestaurantEntity(originalQueryForEntity, detectedHotel)
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

    _elapsed = time.time() - _start
    print(f"[타이밍] preprocess: {_elapsed:.3f}s")
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


def clarificationCheckNode(state: RAGState) -> dict:
    """명확화 체크 노드: 모호한 질문 감지 및 명확화 질문 생성

    Phase 13: 맥락 인식 명확화 시스템
    - 반려동물, 어린이 등 특정 맥락 감지 시 맥락 맞춤 후속 질문
    - direct_triggers가 있으면 바로 검색 (질문형인 경우)
    - 없으면 맥락 맞춤 옵션 제시

    Phase 16: 명확화 루프 방지 + 구체적 대상 우선 체크
    - 히스토리에서 이미 명확화가 발생한 맥락은 재명확화 차단
    - 구체적 대상(시설, 정책 등)이 있으면 명확화보다 검색 우선
    """
    _start = time.time()
    # 모호성 판단은 원본 쿼리 기준 (LLM 재작성이 추가한 키워드 무시)
    originalQuery = state.get("query", "").strip()
    originalQueryLower = originalQuery.lower()
    # 맥락 감지/구체적 대상 체크는 재작성 쿼리 (맥락 보강 상태)
    query = state.get("normalized_query") or state.get("rewritten_query") or state["query"]
    queryLower = query.lower()
    hotel = state.get("detected_hotel")

    # 호텔 정보 (명확화 질문에 포함)
    hotelInfo = HOTEL_INFO.get(hotel, {})
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
            for contextKey in CONTEXT_CLARIFICATION:
                contextInfo = CONTEXT_CLARIFICATION[contextKey]
                if contextInfo["question"] in content:
                    previousClarificationContexts.add(contextKey)

    if previousClarificationContexts:
        print(f"[루프 방지] 이전 명확화 감지: {previousClarificationContexts}")
        # 이미 명확화가 발생한 맥락이면 바로 검색 진행
        for contextKey in previousClarificationContexts:
            keywords = CONTEXT_CLARIFICATION[contextKey]["keywords"]
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

    for contextKey, contextInfo in CONTEXT_CLARIFICATION.items():
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
    for contextKey, contextInfo in CONTEXT_CLARIFICATION.items():
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
    transportKeywords = AMBIGUOUS_PATTERNS.get("교통", {}).get("keywords", [])
    transportExcludes = AMBIGUOUS_PATTERNS.get("교통", {}).get("excludes", [])
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
    patternKey = None

    for patternKey, patternInfo in AMBIGUOUS_PATTERNS.items():
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
            subjectEntity = _extractSubjectEntity(originalQuery, matchedKeywords)

            # 교통 패턴: "호텔"은 주체가 아님 (출발지가 핵심)
            if patternKey == "교통" and subjectEntity:
                transportNonSubjects = ["호텔", "숙소", "리조트", "호텔로", "호텔까지", "호텔에"]
                if any(ns in subjectEntity for ns in transportNonSubjects):
                    subjectEntity = None

            if subjectEntity:
                # 주체가 있음 → 모호하지 않음 → 명확화 불필요, 바로 검색
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
        _elapsed = time.time() - _start
        print(f"[타이밍] clarificationCheck: {_elapsed:.3f}s")
        return {
            **state,
            "needs_clarification": True,
            "clarification_question": clarificationQuestion,
            "clarification_options": clarificationOptions,
            "clarification_type": patternKey,
            "evidence_passed": True,
            "final_answer": clarificationQuestion,
        }

    _elapsed = time.time() - _start
    print(f"[타이밍] clarificationCheck: {_elapsed:.3f}s")
    return {
        **state,
        "needs_clarification": False,
        "clarification_question": "",
        "clarification_options": [],
    }


def _extractSubjectEntity(query: str, ambiguousKeywords: list[str]) -> Optional[str]:
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
