"""검색 노드: 하이브리드 검색, 리랭킹, 근거 검증 게이트"""

import re
import time
from typing import Optional

from rag.state import RAGState
from rag.constants import (
    EVIDENCE_THRESHOLD, RERANKER_ENABLED, MIN_CHUNKS_REQUIRED,
    HOTEL_KEYWORDS, HOTEL_INFO, SYNONYM_DICT,
)


def retrieveNode(state: RAGState, *, indexer=None) -> dict:
    """검색 노드: Vector DB에서 관련 청크 검색 (쿼리 확장 + 카테고리 필터)

    - 세션 컨텍스트 기반 주제 폴백
    - 같은 주제 후속 질문 시 캐시 우선 검색
    - 카테고리 필터는 후속 질문에서만 적용 (컨텍스트 오염 방지)
    """
    _start = time.time()
    query = state["normalized_query"]
    hotel = state["detected_hotel"]
    detectedCategory = state.get("category")
    history = state.get("history", [])
    sessionCtx = state.get("session_context")

    # === 호텔명 제거: 벡터 임베딩 왜곡 방지 ===
    searchQuery = _stripHotelName(query, hotel)

    # === 주제 추출: 키워드 기반 + 세션 폴백 ===
    conversationTopic = _extractConversationTopic(history)

    # 키워드 추출 실패 시 세션의 현재 주제 사용
    if not conversationTopic and sessionCtx and sessionCtx.current_topic and history:
        conversationTopic = sessionCtx.current_topic
        print(f"[세션 주제] 키워드 추출 실패 → 세션 주제 사용: {conversationTopic}")

    # 효과적 카테고리 결정 (리랭커가 있으므로 후속 질문에서는 필터 제거)
    effectiveCategory = None
    if history and conversationTopic:
        if detectedCategory and detectedCategory != conversationTopic:
            print(f"[주제 전환] 히스토리 '{conversationTopic}' → 현재 쿼리 '{detectedCategory}'")

    # === 세션 주제 기반 쿼리 보강 ===
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
        if not any(kw in searchQuery for kw in topicKw.split()):
            searchQuery = f"{searchQuery} {topicKw}"
            print(f"[세션 보강] 쿼리에 주제 키워드 추가: '{topicKw}' → '{searchQuery}'")

    # === 캐시 우선 검색 (같은 주제 후속 질문) ===
    cachedResults = None
    if (sessionCtx and sessionCtx.last_chunks and
            history and conversationTopic and
            conversationTopic == sessionCtx.current_topic):
        cachedResults = _searchCachedChunks(searchQuery, sessionCtx.last_chunks,
                                             conversationTopic)

    # 쿼리 확장 (동의어 추가)
    expandedQuery = _expandQuery(searchQuery)

    # 캐시 결과가 충분하면 DB 검색 생략
    if cachedResults and len(cachedResults) >= 2 and cachedResults[0].get("score", 0) >= 0.7:
        print(f"[캐시 히트] 이전 청크에서 {len(cachedResults)}개 관련 결과 발견")
        results = cachedResults
    else:
        # 1차 검색
        results = indexer.search(
            query=expandedQuery,
            hotel=hotel,
            category=effectiveCategory,
            topK=5
        )

        # 캐시 결과와 병합 (캐시에만 있는 관련 청크 추가)
        if cachedResults:
            results = _mergeResults(results, cachedResults, topK=5)

    # 폴백: 결과가 2개 미만이면 필터 완화하여 재검색
    if len(results) < 2 and effectiveCategory:
        fallbackResults = indexer.search(
            query=expandedQuery,
            hotel=hotel,
            category=None,  # 필터 제거
            topK=5
        )
        if len(fallbackResults) > len(results):
            results = fallbackResults
            effectiveCategory = None

    # === 리랭킹 (Cross-Encoder) ===
    # 조건부 스킵: top score가 높으면 리랭킹 불필요 (200~2000ms 절약)
    preRerankTopScore = max((r["score"] for r in results), default=0.0) if results else 0.0

    rerankQuality = "ok"  # 리랭커 품질 신호 (ok/poor/skipped)
    if RERANKER_ENABLED and results and len(results) >= 2:
        from rag.reranker import getReranker, Reranker
        if preRerankTopScore >= Reranker.SKIP_THRESHOLD:
            print(f"[리랭커] 스킵 (top score {preRerankTopScore:.3f} >= {Reranker.SKIP_THRESHOLD})")
            rerankQuality = "skipped"
        else:
            try:
                reranker = getReranker()
                if reranker.isAvailable:
                    results = reranker.rerank(
                        query=searchQuery,
                        chunks=results,
                        topK=5
                    )
                    # 리랭커 품질 신호 추출 (모든 결과 저품질이면 "poor")
                    if results and results[0].get("_rerank_quality") == "poor":
                        rerankQuality = "poor"
                    # 리랭킹은 순서/필터만 변경, 점수 기준은 original_score 유지
                    for chunk in results:
                        if "original_score" in chunk:
                            chunk["score"] = chunk["original_score"]
            except Exception as e:
                print(f"[리랭커 오류] {e}")

    # 최고 점수 계산
    topScore = max((r["score"] for r in results), default=0.0) if results else 0.0

    _elapsed = time.time() - _start
    print(f"[타이밍] retrieve: {_elapsed:.3f}s")
    return {
        **state,
        "retrieved_chunks": results,
        "top_score": topScore,
        "conversation_topic": conversationTopic,
        "effective_category": effectiveCategory,
        "rerank_quality": rerankQuality,
    }


def evidenceGateNode(state: RAGState) -> dict:
    """근거 검증 노드: 검색 결과 품질 확인"""
    _start = time.time()
    chunks = state["retrieved_chunks"]
    topScore = state["top_score"]
    isValidQuery = state.get("is_valid_query", True)
    rerankQuality = state.get("rerank_quality", "ok")

    # 질문 유효성 검사
    if not isValidQuery:
        return {
            **state,
            "evidence_passed": False,
            "evidence_reason": "호텔 관련 질문이 아닙니다.",
        }

    # 리랭커 절대 품질 미달: 모든 검색 결과가 쿼리와 무관
    if rerankQuality == "poor":
        print(f"[evidenceGate] 리랭커 품질 미달 → 근거 부족 판정")
        _elapsed = time.time() - _start
        print(f"[타이밍] evidenceGate: {_elapsed:.3f}s")
        return {
            **state,
            "evidence_passed": False,
            "evidence_reason": "검색 결과의 의미적 관련성이 낮습니다. (리랭커 품질: poor)",
        }

    # 검증 조건
    hasEnoughChunks = len(chunks) >= MIN_CHUNKS_REQUIRED
    hasGoodScore = topScore >= EVIDENCE_THRESHOLD

    passed = hasEnoughChunks and hasGoodScore

    if not passed:
        if not hasEnoughChunks:
            reason = "관련 정보를 찾을 수 없습니다."
        else:
            reason = f"검색 결과의 관련성이 낮습니다. (점수: {topScore:.2f})"
    else:
        reason = "근거 검증 통과"

    _elapsed = time.time() - _start
    print(f"[타이밍] evidenceGate: {_elapsed:.3f}s")
    return {
        **state,
        "evidence_passed": passed,
        "evidence_reason": reason,
    }


# === 헬퍼 함수 ===

def _stripHotelName(query: str, hotel: str) -> str:
    """검색 쿼리에서 호텔명/지역명을 제거하여 벡터 임베딩 왜곡 방지."""
    if not hotel or hotel not in HOTEL_KEYWORDS:
        return query

    hotelKws = HOTEL_KEYWORDS[hotel]
    hotelInfo = HOTEL_INFO.get(hotel, {})
    if hotelInfo.get("name"):
        hotelKws = list(hotelKws) + [hotelInfo["name"]]

    # 긴 키워드부터 제거 (부분 매칭 방지)
    sortedKws = sorted(hotelKws, key=len, reverse=True)

    stripped = query
    for kw in sortedKws:
        pattern = re.escape(kw) + r'(에서|에서의|에|의|은|는|이|가|을|를|으로|로|과|와|도)?'
        stripped = re.sub(pattern, '', stripped)

    stripped = re.sub(r'^\s*(에서|에|의|은|는|이|가|을|를|으로|로|과|와|도)\s+', '', stripped)
    stripped = re.sub(r'\s+(에서|에|의|은|는|이|가|을|를|으로|로|과|와|도)\s+', ' ', stripped)
    stripped = re.sub(r'\s+', ' ', stripped).strip()

    if stripped != query.strip():
        print(f"[호텔명 제거] '{query}' → '{stripped}'")

    if len(stripped) < 3:
        return query

    return stripped


def _extractConversationTopic(history: list[dict]) -> Optional[str]:
    """대화 히스토리에서 현재 주제 추출 (컨텍스트 오염 방지)"""
    if not history:
        return None

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

    userMessages = [
        msg.get("content", "") for msg in history
        if msg.get("role") == "user"
    ]

    if not userMessages:
        return None

    for msg in reversed(userMessages[-3:]):
        msgLower = msg.lower()
        for topic, keywords in topicPriority:
            if any(kw.lower() in msgLower for kw in keywords):
                return topic

    return None


def _expandQuery(query: str) -> str:
    """쿼리 확장 (동의어 추가) - 가장 구체적인 매칭 1개만 확장"""
    queryLower = query.lower()

    # 매칭되는 키워드 중 가장 긴(구체적인) 것 1개만 선택
    bestMatch = None
    bestLen = 0
    for term in SYNONYM_DICT:
        termLower = term.lower()
        if termLower in queryLower and len(termLower) > bestLen:
            bestMatch = term
            bestLen = len(termLower)

    if not bestMatch:
        return query

    # 쿼리에 이미 포함된 단어 제외, 순서 고정 (리스트 유지)
    queryWords = set(queryLower.split())
    expandedTerms = []
    for s in SYNONYM_DICT[bestMatch]:
        if s.lower() not in queryLower and s.lower() not in queryWords:
            expandedTerms.append(s)
        if len(expandedTerms) >= 3:
            break

    if expandedTerms:
        return f"{query} {' '.join(expandedTerms)}"

    return query


def _searchCachedChunks(query: str, cachedChunks: list,
                        sessionTopic: str = None) -> list:
    """캐시된 청크에서 쿼리 관련성 검색 (키워드 오버랩 + 주제 부스팅)"""
    queryLower = query.lower()
    queryTokens = set(re.findall(r'[가-힣]{2,}', queryLower))
    queryTokens.update(re.findall(r'[a-z]{2,}', queryLower))

    if not queryTokens:
        return []

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

        overlap = queryTokens & chunkTokens
        overlapScore = len(overlap) / len(queryTokens) if queryTokens else 0

        topicBoost = 0.0
        if topicBoostKeywords:
            topicOverlap = topicBoostKeywords & chunkTokens
            if topicOverlap:
                topicBoost = 0.4

        originalScore = chunk.get("original_score", chunk.get("score", 0.5))
        combinedScore = overlapScore * 0.3 + originalScore * 0.3 + topicBoost

        scored.append({**chunk, "score": combinedScore, "source": "cache"})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:5]


def _mergeResults(primary: list, secondary: list, topK: int = 5) -> list:
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
