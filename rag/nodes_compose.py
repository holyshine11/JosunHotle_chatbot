"""답변 생성 노드: LLM 기반 자연어 답변 생성 + 청크 병합/교차참조"""

import re
import time
from typing import Optional

from rag.state import RAGState
from rag.llm_provider import callLLM
from rag.constants import HOTEL_INFO, LLM_ENABLED


def answerComposeNode(state: RAGState) -> dict:
    """답변 생성 노드: LLM을 사용해 자연어 답변 생성

    - 복수 청크 교차 참조 조합 (중복 제거 + 정보 병합)
    - URL 메타데이터에서 핵심 상세 정보 추출하여 컨텍스트에 포함
    - 청크 간 보완 관계 분석으로 완성도 높은 답변 생성
    """
    _start = time.time()
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
    # 단순 싱글턴 질문만 상위 3개 (멀티턴은 맥락 유지를 위해 5개)
    history = state.get("history", [])
    maxChunks = 3 if len(query) < 20 and not history else 5
    mergedChunks = _mergeChunkInfo(chunks[:maxChunks])

    # 컨텍스트 구성 + 출처 수집
    contextParts = []
    sources = []
    seenUrls = set()

    for i, chunk in enumerate(mergedChunks, 1):
        hotelName = chunk["metadata"].get("hotel_name", "")
        url = chunk["metadata"].get("url", "")
        text = chunk["text"]

        # === Phase 2: URL 메타데이터에서 핵심 정보 추출 ===
        urlDetails = _extractUrlDetails(url, chunk)
        urlDetailText = f"\n[URL 상세: {urlDetails}]" if urlDetails else ""

        contextParts.append(
            f"[참조{i}] [{hotelName}] (출처: {url}){urlDetailText}\n{text}"
        )

        if url and url not in seenUrls:
            sources.append({"index": i, "url": url, "hotel": hotelName})
            seenUrls.add(url)

    # === Phase 3: 교차 참조 힌트 생성 ===
    crossRefHint = _buildCrossRefHint(mergedChunks, query)

    context = "\n\n".join(contextParts)
    if crossRefHint:
        context += f"\n\n[교차 참조 가이드]\n{crossRefHint}"

    # === 맥락 충분성 사전 검증 ===
    insufficiencyResult = _checkContextSufficiency(query, chunks, hotel)
    if insufficiencyResult:
        return {
            **state,
            "answer": insufficiencyResult,
            "sources": [src["url"] for src in sources],
        }

    # === 고점수 FAQ 직접 추출 (LLM 스킵으로 10~20초 절약) ===
    topScore = state.get("top_score", 0)
    directExtractResult = _tryDirectExtraction(query, chunks, topScore, hotel)
    if directExtractResult:
        directAnswer, directSources = directExtractResult
        _elapsed = time.time() - _start
        print(f"[타이밍] answerCompose: {_elapsed:.3f}s (직접 추출, LLM 생략)")
        return {
            **state,
            "answer": directAnswer,
            "sources": directSources,
        }

    # LLM 사용 여부에 따라 분기
    usedRefs = []
    llmFailed = state.get("llm_failed", False)
    if llmFailed:
        print(f"[answerCompose] queryRewrite LLM 실패 감지 → LLM 건너뛰고 chunk 직접 추출")

    if LLM_ENABLED and not llmFailed:
        # 동적 maxTokens: 짧은 단순 질문 → 256, 복합 질문 → 512
        dynamicMaxTokens = 200 if len(query) < 15 else 256 if len(mergedChunks) <= 2 else 350
        answer = _generateWithLLM(query, context, hotel, maxTokens=dynamicMaxTokens)

        # LLM 실패 감지 → top chunk 직접 추출 fallback
        llmFailed = "일시적인 오류로 답변을 생성하지 못했습니다" in answer
        if llmFailed and chunks:
            from rag.verify import answerVerifier
            for chunk in chunks[:3]:
                chunkText = chunk.get("text", "")
                extracted = answerVerifier.extractDirectAnswer(chunkText, query)
                if extracted and len(extracted) >= 10:
                    # raw dump 검증: 원시 청크 데이터가 아닌지 확인
                    if answerVerifier.isRawDump(extracted):
                        print(f"[LLM 실패 Fallback] raw dump 감지 → 스킵: {extracted[:60]}...")
                        continue
                    chunkUrl = chunk.get("metadata", {}).get("url", chunk.get("url", ""))
                    answer = extracted
                    if chunkUrl:
                        answer += f"\n\n참고 정보: {chunkUrl}"
                    usedRefs = [1]
                    print(f"[LLM 실패 Fallback] chunk에서 직접 추출: {extracted[:80]}...")
                    break

        # [REF:1,3] 형태의 참조 번호 파싱
        refMatch = re.search(r'\[REF:([0-9,\s]+)\]', answer)
        if refMatch:
            refStr = refMatch.group(1)
            usedRefs = [int(r.strip()) for r in refStr.split(',') if r.strip().isdigit()]
            answer = re.sub(r'\s*\[REF:[0-9,\s]+\]', '', answer).strip()
    else:
        # LLM 미사용 또는 LLM 실패 시 — chunk 직접 추출
        from rag.verify import answerVerifier
        answer = None
        for chunk in chunks[:3]:
            chunkText = chunk.get("text", "")
            extracted = answerVerifier.extractDirectAnswer(chunkText, query)
            if extracted and len(extracted) >= 10:
                answer = extracted
                break
        if not answer:
            # raw chunk를 그대로 출력하지 않고 안전한 거부 응답 반환
            print(f"[answerCompose] 직접 추출 실패 → raw dump 대신 거부 응답")
            answer = "죄송합니다, 해당 내용에 대한 정확한 정보를 현재 자료에서 확인하기 어렵습니다."
        usedRefs = [1]

    # 사용된 참조의 URL만 필터링
    usedSources = []
    if usedRefs:
        for src in sources:
            if src["index"] in usedRefs:
                usedSources.append(src["url"])
    else:
        usedSources = [src["url"] for src in sources]

    # 레스토랑 리다이렉트 메시지가 있으면 답변 앞에 추가
    redirectMsg = state.get("restaurant_redirect_msg")
    if redirectMsg and answer:
        answer = f"{redirectMsg}\n\n{answer}"

    _elapsed = time.time() - _start
    print(f"[타이밍] answerCompose: {_elapsed:.3f}s")
    return {
        **state,
        "answer": answer,
        "sources": usedSources,
    }


# === 헬퍼 함수 ===

def _tryDirectExtraction(query: str, chunks: list, topScore: float,
                          hotel: str = None) -> Optional[tuple[str, list]]:
    """고점수 FAQ 직접 추출: LLM 호출 없이 chunk에서 바로 답변 추출

    FAQ 형식(Q:/A:)은 정답이 명확하므로 score >= 0.72 이상이면 직접 추출.
    질문 키워드가 Q: 부분과 매칭되는지 추가 검증.

    Returns:
        (answer, sources) 또는 None (직접 추출 불가)
    """
    FAQ_THRESHOLD = 0.72  # FAQ 형식은 구조화되어 있으므로 낮은 임계값 허용
    # 리랭커가 고신뢰(rerank_score>=0.8) 확인 시 임계값 완화 (벡터 점수만으로는 부족한 경우)
    rerankScore = chunks[0].get("rerank_score", 0) if chunks else 0
    effectiveThreshold = 0.60 if rerankScore >= 0.8 else FAQ_THRESHOLD
    if topScore < effectiveThreshold or not chunks:
        return None

    topChunk = chunks[0]
    text = topChunk.get("text", "")
    url = topChunk.get("metadata", {}).get("url", "")

    # FAQ 형식만 허용: "Q: ... A: ..." 패턴
    if "Q:" not in text or "A:" not in text:
        return None

    qPart = text.split("A:")[0].strip()  # Q: 부분
    aPart = text.split("A:")[-1].strip()  # A: 부분

    # A: 부분이 충분히 길어야 함
    if len(aPart) < 15:
        return None

    # 질문 키워드가 Q: 부분에 포함되는지 검증 (오매칭 방지)
    queryKeywords = set(re.findall(r'[가-힣]{2,}', query.lower()))
    # 기능어/일반어 제거
    queryKeywords -= {"알려줘", "알려주세요", "알려", "어떻게", "언제", "얼마",
                      "무엇", "호텔", "안내", "정보", "문의"}
    qPartLower = qPart.lower()

    # 시설 범주 키워드 (의도 매칭에서 제외 — 너무 범용적)
    FACILITY_GENERICS = {"레스토랑", "식당", "다이닝", "카페", "라운지", "수영장",
                         "피트니스", "스파", "객실", "시설"}

    # 동의어 확장 매칭 (다이닝↔dinner, 조식↔breakfast 등)
    SYNONYM_PAIRS = {
        "다이닝": ["dinner", "dining", "레스토랑", "식당"],
        "조식": ["breakfast", "아침", "뷔페", "모닝"],
        "수영장": ["pool", "swimming"],
        "피트니스": ["fitness", "gym", "헬스"],
        "스파": ["spa", "마사지"],
        "체크인": ["check-in", "입실"],
        "체크아웃": ["check-out", "퇴실"],
    }
    expandedKeywords = set(queryKeywords)
    for kw in queryKeywords:
        if kw in SYNONYM_PAIRS:
            expandedKeywords.update(SYNONYM_PAIRS[kw])

    matchCount = sum(1 for kw in expandedKeywords if kw in qPartLower)
    if matchCount < 1:
        return None  # 질문과 FAQ가 매칭되지 않음

    # 핵심 의도 키워드 검증: 시설 범주를 제외한 주제 키워드가 Q:에 있어야 함
    # 예: "레스토랑 운영시간" → 주제="운영", "시간" / "레스토랑 콜키지" → 주제="콜키지"
    topicKeywords = queryKeywords - FACILITY_GENERICS
    if topicKeywords:
        topicMatchCount = sum(1 for kw in topicKeywords if kw in qPartLower)
        if topicMatchCount == 0:
            print(f"[직접 추출 거부] 주제 불일치: 쿼리 의도={topicKeywords}, FAQ Q='{qPart[:50]}...'")
            return None  # 핵심 의도 키워드가 FAQ에 없음 → 주제 불일치

    # 첫 문장이 너무 짧으면 (단어만) LLM에 맡김
    firstSentence = re.split(r'[.\n]', aPart)[0].strip()
    if len(firstSentence) < 8:
        return None

    sources = [url] if url else []
    print(f"[직접 추출] FAQ 형식, score={topScore:.3f}, Q매칭={matchCount}/{len(queryKeywords)}, 답변 길이={len(aPart)}")
    return aPart, sources

def _mergeChunkInfo(chunks: list) -> list:
    """복수 청크의 중복 제거 및 정보 병합"""
    if len(chunks) <= 1:
        return chunks

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
            deduped = _deduplicateSentences(group[0]["text"], seenSentences)
            if deduped.strip():
                mergedChunk = {**group[0], "text": deduped}
                merged.append(mergedChunk)
        else:
            combinedTexts = []
            bestScore = 0
            bestMetadata = group[0].get("metadata", {})

            for c in group:
                deduped = _deduplicateSentences(c["text"], seenSentences)
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

    for chunk in standalone:
        deduped = _deduplicateSentences(chunk["text"], seenSentences)
        if deduped.strip():
            merged.append({**chunk, "text": deduped})

    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    return merged[:5]


def _deduplicateSentences(text: str, seenSentences: set) -> str:
    """텍스트 내 중복 문장 제거 (교차 청크 중복 포함)"""
    lines = text.split('\n')
    uniqueLines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            uniqueLines.append(line)
            continue

        if stripped.startswith("Q:") or stripped.startswith("A:"):
            uniqueLines.append(line)
            seenSentences.add(stripped)
            continue

        normalized = re.sub(r'\s+', ' ', stripped).lower()
        if len(normalized) < 10:
            uniqueLines.append(line)
            continue

        if normalized not in seenSentences:
            seenSentences.add(normalized)
            uniqueLines.append(line)

    return '\n'.join(uniqueLines)


def _extractUrlDetails(url: str, chunk: dict) -> str:
    """URL 메타데이터에서 핵심 상세 정보 추출"""
    if not url:
        return ""

    details = []
    urlLower = url.lower()
    metadata = chunk.get("metadata", {})

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


def _buildCrossRefHint(chunks: list, query: str) -> str:
    """교차 참조 힌트 생성: 복수 청크의 보완 관계를 LLM에 안내"""
    if len(chunks) <= 1:
        return ""

    chunkInfoTypes = []
    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "")
        infoTypes = []

        if re.search(r'\d{1,2}:\d{2}', text):
            infoTypes.append("운영시간")
        if re.search(r'[\d,]+\s*원', text):
            infoTypes.append("가격")
        if re.search(r'[-•]\s*[가-힣]', text) or text.count('\n') > 5:
            infoTypes.append("항목목록")
        if re.search(r'(역|정류장|출구|도보|차량|층)', text):
            infoTypes.append("위치/접근")
        if re.search(r'(가능|불가|금지|허용|필수|제한)', text):
            infoTypes.append("정책/규정")

        metadata = chunk.get("metadata", {})
        pageType = metadata.get("page_type", "")
        if pageType in ["package", "event", "activity"]:
            infoTypes.append(f"{pageType}상세")

        if "Q:" in text and "A:" in text:
            infoTypes.append("FAQ")

        if infoTypes:
            chunkInfoTypes.append(f"참조{i}: {', '.join(infoTypes)}")

    if not chunkInfoTypes:
        return ""

    hint = "아래 참조들은 서로 보완적인 정보를 포함합니다. 관련 정보를 조합하여 완성도 높은 답변을 작성하세요:\n"
    hint += "\n".join(f"- {info}" for info in chunkInfoTypes)

    return hint


def _checkContextSufficiency(query: str, chunks: list, hotel: str = None) -> Optional[str]:
    """맥락 충분성 검증: 질문이 구체적 정보를 요구하는데 청크가 일반론만 제공하는지 확인"""
    if not chunks:
        return None

    queryLower = query.lower()

    specificInfoPatterns = [
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

    allChunkText = " ".join([c.get("text", "") for c in chunks[:5]])

    hasSpecificTime = bool(re.search(r'\d{1,2}:\d{2}', allChunkText))
    hasSpecificName = bool(re.search(
        r'[가-힣]{2,}(?:\s+[가-힣]+)*\s*(?:레스토랑|식당|카페|바|라운지|다이닝)',
        allChunkText
    ))
    hasSpecificPrice = bool(re.search(r'[\d,]+\s*원', allChunkText))
    hasFaqFormat = bool(re.search(r'[QA]:|\?.*\n', allChunkText))

    if hasSpecificTime or hasSpecificName or hasSpecificPrice or hasFaqFormat:
        return None

    hotelInfo = HOTEL_INFO.get(hotel, {})
    hotelName = hotelInfo.get("name", "")
    hotelPhone = hotelInfo.get("phone", "")
    contactInfo = f"{hotelName} ({hotelPhone})" if hotelPhone else "호텔 고객센터"

    print(f"[맥락 충분성] 구체적 정보 부족 — 일반론만 존재, LLM 호출 생략")
    return f"죄송합니다, 해당 내용에 대한 구체적인 정보를 현재 자료에서 확인하기 어렵습니다.\n자세한 사항은 {contactInfo}로 문의 부탁드립니다."


def _generateWithLLM(query: str, context: str, hotel: str = None, maxTokens: int = 512) -> str:
    """Ollama LLM으로 답변 생성"""
    hotelInfo = HOTEL_INFO.get(hotel, {})
    hotelName = hotelInfo.get("name", "")
    hotelPhone = hotelInfo.get("phone", "")

    contactInfo = f"{hotelName} ({hotelPhone})" if hotelPhone else "호텔 고객센터"

    currentHotelNotice = ""
    if hotelName:
        currentHotelNotice = f"""
[현재 호텔] {hotelName}
- 다른 호텔 정보를 섞지 마세요
- 문의 안내 시: {contactInfo}"""

    systemPrompt = f"""조선호텔 AI 컨시어지. 존댓말 응대.{currentHotelNotice}

[원칙] 아래 참고 정보에 명시된 내용만 사용. 참고 정보에 없는 시설명, 레스토랑명, 교통편, 버스노선, 지하철역 절대 창작 금지. 가격/시간/번호는 참고 정보에서 정확히 인용. 추측("약","대략","아마") 금지. 참고 정보에 없으면 "{contactInfo}로 문의 부탁드립니다".
[형식] 완성 문장, 첫 문장에 직접 답변, 추가정보는 불릿(-), 답변 끝 질문 금지."""

    userPrompt = f"""[참고 정보]
{context}

[질문]
{query}

중요: 위 참고 정보에 명시된 이름, 숫자, 사실만 사용하세요. 참고 정보에 없는 시설명이나 교통편을 만들어내지 마세요.
답변 마지막에 사용한 참조 번호 표시: [REF:1,3]"""

    try:
        try:
            answer = callLLM(
                prompt=userPrompt,
                system=systemPrompt,
                temperature=0.0,
                maxTokens=maxTokens,
                numCtx=2048  # 기본 4096의 절반, KV캐시 절감
            ).strip()
        except TypeError:
            answer = callLLM(
                prompt=userPrompt,
                system=systemPrompt,
                temperature=0.0
            ).strip()

        # 후처리: 중국어/일본어 문자 제거 (qwen 모델의 할루시네이션 방지)
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
        answer = answer.replace('。', '.').replace('，', ', ').replace('！', '!').replace('？', '?')
        answer = re.sub(r'\s{2,}', ' ', answer).strip()
        answer = re.sub(r'\.{2,}', '.', answer)

        return answer
    except Exception as e:
        import traceback
        print(f"[LLM 에러] {type(e).__name__}: {e}")
        traceback.print_exc()

        if hotelName and hotelPhone:
            return f"죄송합니다, 일시적인 오류로 답변을 생성하지 못했습니다.\n자세한 사항은 {contactInfo}로 문의 부탁드립니다."
        return "죄송합니다, 일시적인 오류로 답변을 생성하지 못했습니다.\n잠시 후 다시 시도해 주세요."
