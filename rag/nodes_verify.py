"""검증 노드: 답변 검증, 정책 필터, 로깅"""

import re
import json
import time
from datetime import datetime
from pathlib import Path

from rag.state import RAGState
from rag.grounding import groundingGate, categoryChecker
from rag.verify import answerVerifier
from rag.constants import HOTEL_INFO, FORBIDDEN_KEYWORDS


def answerVerifyNode(state: RAGState) -> dict:
    """답변 검증 노드: Grounding Gate 기반 문장 단위 근거 검증 + 할루시네이션 탐지"""
    _start = time.time()
    answer = state.get("answer", "")
    query = state.get("query", "")
    chunks = state.get("retrieved_chunks", [])
    hotel = state.get("detected_hotel")

    # 호텔 연락처 정보
    hotelInfo = HOTEL_INFO.get(hotel, {})
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

    # Phase 1: 응답 품질 검사
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

    # Phase 2: Grounding Gate 검증 (문장 단위 근거 검증)
    queryIntents = groundingGate.classifyIntent(query)
    groundingResult = groundingGate.verify(answer, context, query)

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

    if not groundingResult.passed:
        allIssues.append(f"Grounding 실패: {groundingResult.reason}")

    for claim in groundingResult.rejected_claims:
        if claim.has_numeric and not claim.numeric_verified:
            allIssues.append(f"수치 검증 실패: '{claim.text[:30]}...'")

    # Phase 3: 기존 할루시네이션 검사
    hallucinationPassed, hallucinationIssues = answerVerifier.checkHallucination(answer, context)
    allIssues.extend(hallucinationIssues)

    # Phase 3.3: 고유명사 할루시네이션 검사
    properNounPassed, properNounIssues, properNounCleaned = answerVerifier.checkProperNounHallucination(answer, context)
    allIssues.extend(properNounIssues)
    if not properNounPassed:
        answer = properNounCleaned
        print(f"[고유명사 검증] 할루시네이션 감지: {properNounIssues}")

    # Phase 3.35: 쿼리 내 인물명 검증
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

    # Phase 3.4: 교통편/노선 날조 검사
    transportPassed, transportIssues, transportCleaned = answerVerifier.checkTransportationHallucination(answer, context, query)
    allIssues.extend(transportIssues)
    if not transportPassed:
        answer = transportCleaned if len(transportCleaned) >= 10 else answer

    # Phase 3.5: 카테고리 교차 오염 검사
    targetCategory = state.get("conversation_topic") or state.get("effective_category") or state.get("category")
    categoryConsistencyResult = categoryChecker.verifyCategoryConsistency(answer, targetCategory, chunks)

    if not categoryConsistencyResult.passed:
        allIssues.append(f"카테고리 오염: {categoryConsistencyResult.reason}")
        if categoryConsistencyResult.cleaned_answer and len(categoryConsistencyResult.cleaned_answer) >= 10:
            answer = categoryConsistencyResult.cleaned_answer

    # 검증 결과 종합
    passed = qualityPassed and hallucinationPassed and groundingResult.passed and properNounPassed and transportPassed

    # 금지 패턴 제거
    cleanedAnswer = answerVerifier.removeForbiddenPhrases(answer)
    verifiedAnswer = cleanedAnswer

    # Phase 4: Grounding 기반 답변 재구성
    if groundingResult.confidence == "근거없음":
        verifiedAnswer = groundingGate._buildFallbackResponse(
            groundingResult, hotelName, contactGuide
        )
    elif groundingResult.confidence == "불확실" and groundingResult.rejected_claims:
        if groundingResult.verified_claims:
            verifiedAnswer = cleanedAnswer
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
        verifiedAnswer = cleanedAnswer

    # 심각한 이슈 최종 체크
    hasSeriousIssue = any(
        "추정" in i or "추측" in i or "비정상" in i or "수치 검증 실패" in i
        for i in allIssues
    )

    if hasSeriousIssue:
        verifiedAnswer = f"정확한 정보 확인을 위해 {contactGuide}로 문의 부탁드립니다."
    elif not passed and len(verifiedAnswer) < 10:
        verifiedAnswer = f"정확한 정보 확인을 위해 {contactGuide}로 문의 부탁드립니다."
    elif not passed and (not properNounPassed or not transportPassed) and len(verifiedAnswer) < 80:
        verifiedAnswer = f"해당 정보를 확인하기 어렵습니다. {contactGuide}로 문의 부탁드립니다."

    # Phase 4.1: Fallback 답변 개선 — top chunk 직접 추출
    refusalPatterns = ["찾지 못했습니다", "찾을 수 없습니다", "확인하기 어렵습니다",
                      "정확한 정보 확인을 위해", "문의 부탁드립니다"]
    isFallback = (
        len(verifiedAnswer) < 100
        and any(p in verifiedAnswer for p in refusalPatterns)
    )
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
        isFallback = False

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

        # Phase 4.1c: 일반 chunk 직접 추출 (주제 일치 검증 포함)
        if not phonePatternMatch:
            directAnswer = None
            bestUrl = ""
            queryKeywords = answerVerifier.extractQueryKeywords(query)
            for chunk in chunks[:3]:
                chunkText = chunk.get("text", "")
                chunkUrl = chunk.get("metadata", {}).get("url", chunk.get("url", ""))
                # Fallback 주제 일치 검증: 쿼리 핵심 키워드가 chunk에 존재하는지 확인
                topicMismatch = False
                if queryKeywords:
                    chunkLower = chunkText.lower()
                    for kw in queryKeywords:
                        expanded = answerVerifier.CATEGORY_KEYWORD_MAP.get(kw, [kw])
                        if not any(e.lower() in chunkLower for e in expanded):
                            topicMismatch = True
                            print(f"[Fallback 주제 검증] '{kw}' chunk에 없음 → 스킵")
                            break
                if topicMismatch:
                    continue
                extracted = answerVerifier.extractDirectAnswer(chunkText, query)
                if extracted and len(extracted) >= 10:
                    # raw dump 검증: 네비게이션/UI 요소가 포함된 원시 데이터 스킵
                    if answerVerifier.isRawDump(extracted):
                        print(f"[Fallback 직접 추출] raw dump 감지 → 스킵: {extracted[:60]}...")
                        continue
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

    _elapsed = time.time() - _start
    print(f"[타이밍] answerVerify: {_elapsed:.3f}s")
    return {
        **state,
        "verification_passed": passed,
        "verification_issues": allIssues,
        "verified_answer": verifiedAnswer,
        "grounding_result": groundingDict,
        "query_intents": queryIntents,
    }


def policyFilterNode(state: RAGState) -> dict:
    """정책 필터 노드: 금지 주제 및 개인정보 필터링"""
    # 검증된 답변 사용 (없으면 원본 답변)
    answer = state.get("verified_answer") or state.get("answer", "")
    query = state["query"]
    hotel = state.get("detected_hotel")

    _start = time.time()
    hotelInfo = HOTEL_INFO.get(hotel, {})
    hotelName = hotelInfo.get("name", "")
    hotelPhone = hotelInfo.get("phone", "")

    if hotelName and hotelPhone:
        contactGuide = f"{hotelName} ({hotelPhone})"
    else:
        allContacts = ", ".join([
            f"{info['name']} ({info['phone']})"
            for info in HOTEL_INFO.values()
        ])
        contactGuide = f"각 호텔 대표번호({allContacts})"

    # 금지 키워드 체크
    for keyword in FORBIDDEN_KEYWORDS:
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

    # 최종 안전망 (LLM의 [참조N] 형식은 허용, 시스템 오류 패턴만 차단)
    errorPatterns = ["[시스템 오류]", "검색된 정보:", "일시적인 오류로 답변을 생성하지 못했습니다"]
    if any(p in answer for p in errorPatterns):
        print(f"[안전망] 답변에 오류 패턴 감지, fallback 교체")
        answer = f"죄송합니다, 일시적인 오류로 답변을 생성하지 못했습니다.\n자세한 사항은 {contactGuide}로 문의 부탁드립니다."

    # 출처 추가 (중복 방지)
    sources = state.get("sources", [])
    finalAnswer = answer

    if "\n\n참고 정보:" in finalAnswer:
        refIdx = finalAnswer.index("\n\n참고 정보:")
        existingRefSection = finalAnswer[refIdx:]
        finalAnswer = finalAnswer[:refIdx]
        existingUrls = re.findall(r'https?://[^\s\n]+', existingRefSection)
        sources = list(sources) + existingUrls

    if sources:
        uniqueSources = list(dict.fromkeys(sources))
        if len(uniqueSources) == 1:
            finalAnswer += f"\n\n참고 정보: {uniqueSources[0]}"
        else:
            sourceList = "\n".join(uniqueSources)
            finalAnswer += f"\n\n참고 정보:\n{sourceList}"

    _elapsed = time.time() - _start
    print(f"[타이밍] policyFilter: {_elapsed:.3f}s")
    return {
        **state,
        "policy_passed": True,
        "policy_reason": "정상 처리",
        "final_answer": finalAnswer,
    }


def logNode(state: RAGState, *, logPath=None) -> dict:
    """로그 노드: 대화 기록 저장"""
    logEntry = {
        "timestamp": datetime.now().isoformat(),
        "duration_s": round(time.time() - state.get("_pipeline_start", time.time()), 2),
        "query": state["query"],
        "hotel": state.get("detected_hotel"),
        "category": state.get("category"),
        "evidence_passed": bool(state["evidence_passed"]),
        "verification_passed": bool(state.get("verification_passed", True)),
        "verification_issues": state.get("verification_issues", []),
        "top_score": float(state["top_score"]),
        "chunks_count": len(state["retrieved_chunks"]),
        "final_answer": state["final_answer"],
        "grounding_result": state.get("grounding_result"),
        "query_intents": state.get("query_intents", []),
    }

    # 파일에 로그 저장
    if logPath is None:
        logPath = Path(__file__).parent.parent / "data" / "logs"
        logPath.mkdir(parents=True, exist_ok=True)

    logFile = logPath / f"chat_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with open(logFile, "a", encoding="utf-8") as f:
        f.write(json.dumps(logEntry, ensure_ascii=False) + "\n")

    return {
        **state,
        "log": logEntry,
    }
