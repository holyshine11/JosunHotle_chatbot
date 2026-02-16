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
    mergedChunks = _mergeChunkInfo(chunks[:5])

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

    # LLM 사용 여부에 따라 분기
    usedRefs = []
    llmFailed = state.get("llm_failed", False)
    if llmFailed:
        print(f"[answerCompose] queryRewrite LLM 실패 감지 → LLM 건너뛰고 chunk 직접 추출")

    if LLM_ENABLED and not llmFailed:
        answer = _generateWithLLM(query, context, hotel)

        # LLM 실패 감지 → top chunk 직접 추출 fallback
        llmFailed = "일시적인 오류로 답변을 생성하지 못했습니다" in answer
        if llmFailed and chunks:
            from rag.verify import answerVerifier
            for chunk in chunks[:3]:
                chunkText = chunk.get("text", "")
                extracted = answerVerifier.extractDirectAnswer(chunkText, query)
                if extracted and len(extracted) >= 10:
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
            topChunk = chunks[0]
            answer = topChunk["text"]
            if "A:" in answer:
                answer = answer.split("A:")[-1].strip()
            hotelName = topChunk["metadata"].get("hotel_name", "")
            if hotelName:
                answer = f"[{hotelName}] {answer}"
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


def _generateWithLLM(query: str, context: str, hotel: str = None) -> str:
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
        try:
            answer = callLLM(
                prompt=userPrompt,
                system=systemPrompt,
                temperature=0.0,
                maxTokens=512
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
