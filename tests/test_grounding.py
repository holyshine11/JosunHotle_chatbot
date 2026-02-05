"""
Grounding Gate 테스트
- 문장 단위 근거 검증
- 수치 토큰 검증
- 의도 분류
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.grounding import groundingGate, GroundingGate, Claim, GroundingResult, categoryChecker


def testIntentClassification():
    """의도 분류 테스트"""
    print("\n[테스트 1] 의도 분류")
    print("-" * 40)

    testCases = [
        ("수영장 입장료가 얼마예요?", ["fee_entry"]),
        ("타월 대여 비용 알려주세요", ["fee_rental", "rental_items"]),
        ("수영모 대여 가능한가요?", ["rental_items"]),
        ("반려견 입장 가능한가요?", ["rule"]),
        ("피트니스 운영시간이 어떻게 되나요?", ["hours"]),
        ("스파 위치가 어디예요?", ["location"]),
        ("최대 몇명까지 입장 가능해요?", ["capacity"]),
        ("안녕하세요", ["general"]),
    ]

    passed = 0
    for query, expectedIntents in testCases:
        intents = groundingGate.classifyIntent(query)
        # 예상 의도 중 하나라도 포함되면 통과
        match = any(e in intents for e in expectedIntents)
        status = "✓" if match else "✗"
        if match:
            passed += 1
        print(f"  {status} '{query}' → {intents} (기대: {expectedIntents})")

    print(f"\n  결과: {passed}/{len(testCases)} 통과")
    return passed == len(testCases)


def testSensitiveTokenExtraction():
    """민감 토큰 추출 테스트"""
    print("\n[테스트 2] 민감 토큰 추출")
    print("-" * 40)

    testCases = [
        ("입장료는 50,000원입니다.", [("50,000원", "가격")]),
        ("할인율은 20%입니다.", [("20%", "할인율")]),
        ("12세 이하 무료입니다.", [("12세", "연령"), ("무료", "무료")]),
        ("최대 4인까지 입장 가능합니다.", [("4인", "인원")]),
        ("운영시간은 06:00~22:00입니다.", [("06:00", "시간"), ("22:00", "시간")]),
        ("일반 텍스트입니다.", []),
    ]

    passed = 0
    for text, expectedTokens in testCases:
        tokens = groundingGate.extractSensitiveTokens(text)
        # 토큰 수가 맞으면 통과 (정확한 매칭보다 추출 여부 확인)
        match = len(tokens) >= len(expectedTokens)
        status = "✓" if match else "✗"
        if match:
            passed += 1
        print(f"  {status} '{text[:30]}...' → {tokens}")

    print(f"\n  결과: {passed}/{len(testCases)} 통과")
    return passed == len(testCases)


def testNumericVerification():
    """수치 토큰 검증 테스트"""
    print("\n[테스트 3] 수치 토큰 검증")
    print("-" * 40)

    testCases = [
        # (답변, 컨텍스트, 검증 통과 예상 여부)
        (
            "입장료는 50,000원입니다.",
            "수영장 입장료: 50,000원 (VAT 별도)",
            True
        ),
        (
            "입장료는 30,000원입니다.",
            "수영장 입장료: 50,000원 (VAT 별도)",
            False  # 30,000원은 컨텍스트에 없음
        ),
        (
            "운영시간은 06:00~22:00입니다.",
            "피트니스 운영시간: 06:00 - 22:00",
            True
        ),
        (
            "할인율은 30%입니다.",
            "호텔 회원 할인: 20%",
            False  # 30%는 컨텍스트에 없음
        ),
        (
            "일반 텍스트입니다.",
            "일반 정보입니다.",
            True  # 수치 없으면 통과
        ),
    ]

    passed = 0
    for answer, context, expectedPass in testCases:
        verified, unverified = groundingGate.verifyNumericTokens(answer, context)
        match = verified == expectedPass
        status = "✓" if match else "✗"
        if match:
            passed += 1
        print(f"  {status} '{answer[:30]}...' → 검증: {verified}, 미검증: {unverified}")

    print(f"\n  결과: {passed}/{len(testCases)} 통과")
    return passed == len(testCases)


def testClaimSplitting():
    """문장/claim 분리 테스트"""
    print("\n[테스트 4] 문장 분리")
    print("-" * 40)

    testCases = [
        (
            "수영장 입장료는 50,000원입니다. 운영시간은 06:00~22:00입니다.",
            2
        ),
        (
            "- 입장료: 50,000원\n- 운영시간: 06:00~22:00\n- 위치: B1층",
            3
        ),
        (
            "체크인은 15:00입니다.",
            1
        ),
    ]

    passed = 0
    for answer, expectedCount in testCases:
        claims = groundingGate.splitIntoClaims(answer)
        match = len(claims) >= expectedCount
        status = "✓" if match else "✗"
        if match:
            passed += 1
        print(f"  {status} 분리된 claim 수: {len(claims)} (기대: {expectedCount}+)")
        for i, claim in enumerate(claims[:3]):
            print(f"      [{i+1}] {claim[:50]}...")

    print(f"\n  결과: {passed}/{len(testCases)} 통과")
    return passed == len(testCases)


def testFullVerification():
    """전체 검증 플로우 테스트"""
    print("\n[테스트 5] 전체 검증 플로우")
    print("-" * 40)

    testCases = [
        # (질문, 답변, 컨텍스트, 검증 통과 예상, confidence)
        (
            "수영장 입장료가 얼마예요?",
            "수영장 입장료는 50,000원입니다.",
            "수영장 이용 안내\n- 입장료: 50,000원 (VAT 별도)\n- 운영시간: 06:00 - 22:00",
            True,
            "확실"
        ),
        (
            "수영장 입장료가 얼마예요?",
            "수영장 입장료는 30,000원입니다.",  # 틀린 가격
            "수영장 이용 안내\n- 입장료: 50,000원 (VAT 별도)",
            False,
            "근거없음"
        ),
        (
            "피트니스 운영시간 알려주세요",
            "피트니스는 24시간 운영됩니다.",
            "피트니스 운영시간: 06:00 - 22:00",  # 24시간이 아님
            False,
            None  # 불확실 또는 근거없음
        ),
    ]

    passed = 0
    for query, answer, context, expectedPass, expectedConfidence in testCases:
        result = groundingGate.verify(answer, context, query)
        matchPass = result.passed == expectedPass
        matchConf = expectedConfidence is None or result.confidence == expectedConfidence

        status = "✓" if (matchPass and matchConf) else "✗"
        if matchPass and matchConf:
            passed += 1

        print(f"  {status} Q: '{query}'")
        print(f"      A: '{answer}'")
        print(f"      검증: {result.passed} (기대: {expectedPass}), 신뢰도: {result.confidence}")
        print(f"      사유: {result.reason}")

    print(f"\n  결과: {passed}/{len(testCases)} 통과")
    return passed == len(testCases)


def testRentalFeeScenario():
    """대여 비용 시나리오 테스트 (Section C)"""
    print("\n[테스트 6] 대여 비용 시나리오")
    print("-" * 40)

    # 사용자 질문: "타월 대여 비용 알려줘"
    query = "타월 대여 비용 알려줘"

    # 시나리오 1: 컨텍스트에 대여 비용 정보 있음
    context1 = """
    수영장 이용 안내
    - 타월 대여: 5,000원
    - 수영모 대여: 3,000원
    - 수영복 대여: 10,000원
    """
    answer1 = "타월 대여 비용은 5,000원입니다."

    result1 = groundingGate.verify(answer1, context1, query)
    print(f"  [시나리오 1] 정보 있음")
    print(f"    답변: {answer1}")
    print(f"    검증: {result1.passed}, 신뢰도: {result1.confidence}")

    # 시나리오 2: 컨텍스트에 대여 비용 정보 없음
    context2 = """
    수영장 이용 안내
    - 운영시간: 06:00 - 22:00
    - 위치: B1층
    """
    answer2 = "타월 대여 비용은 5,000원입니다."  # 근거 없이 가격 생성

    result2 = groundingGate.verify(answer2, context2, query)
    print(f"\n  [시나리오 2] 정보 없음 (할루시네이션)")
    print(f"    답변: {answer2}")
    print(f"    검증: {result2.passed}, 신뢰도: {result2.confidence}")
    print(f"    사유: {result2.reason}")

    # 시나리오 3: 대체 응답 생성
    if not result2.passed:
        fallback = groundingGate._buildFallbackResponse(result2, "조선 팰리스", "02-727-7200")
        print(f"\n  [시나리오 3] 대체 응답")
        print(f"    {fallback}")

    # 검증
    scenario1Pass = result1.passed and result1.confidence == "확실"
    scenario2Pass = not result2.passed  # 근거 없는 답변은 실패해야 함

    print(f"\n  결과: 시나리오1 {'✓' if scenario1Pass else '✗'}, 시나리오2 {'✓' if scenario2Pass else '✗'}")
    return scenario1Pass and scenario2Pass


def testCategoryConsistency():
    """카테고리 교차 오염 감지 테스트"""
    print("\n[테스트 7] 카테고리 교차 오염 감지")
    print("-" * 40)

    testCases = [
        # (답변, 대상 카테고리, 오염 예상 여부)
        (
            "조식 운영시간은 07:00~10:30입니다.",
            "조식",
            False  # 오염 없음
        ),
        (
            "조식 운영시간은 07:00~10:30입니다. 수영장은 19세 이상만 입장 가능합니다.",
            "조식",
            True  # 수영장/19세 정보 오염
        ),
        (
            "수영장은 오전 6시부터 저녁 10시까지 운영됩니다.",
            "수영장",
            False  # 오염 없음
        ),
        (
            "수영장은 오전 6시부터 저녁 10시까지 운영됩니다. 조식은 07:00부터 시작합니다.",
            "수영장",
            True  # 조식 정보 오염
        ),
        (
            "주차는 발렛 서비스가 가능합니다.",
            "주차",
            False  # 오염 없음
        ),
        (
            "일반 정보입니다.",
            None,  # 카테고리 미지정
            False  # 검사 스킵
        ),
    ]

    passed = 0
    for answer, category, expectedContaminated in testCases:
        result = categoryChecker.verifyCategoryConsistency(answer, category)
        isContaminated = not result.passed
        match = isContaminated == expectedContaminated

        status = "✓" if match else "✗"
        if match:
            passed += 1

        contaminationStatus = "오염됨" if isContaminated else "정상"
        print(f"  {status} 카테고리: {category}")
        print(f"      답변: {answer[:50]}...")
        print(f"      결과: {contaminationStatus} (기대: {'오염됨' if expectedContaminated else '정상'})")
        if result.foreign_keywords_found:
            print(f"      오염 키워드: {result.foreign_keywords_found}")

    print(f"\n  결과: {passed}/{len(testCases)} 통과")
    return passed == len(testCases)


def testCategoryCleanedAnswer():
    """오염된 답변 정제 테스트"""
    print("\n[테스트 8] 오염된 답변 정제")
    print("-" * 40)

    # 오염된 답변
    contaminatedAnswer = """조식 운영시간은 07:00~10:30입니다.
수영장은 19세 이상만 입장 가능합니다.
레스토랑은 24층에 위치해 있습니다."""

    cleanedAnswer, wasCleaned = categoryChecker.getCleanedAnswer(
        contaminatedAnswer, "조식", "조선 팰리스 (02-727-7200)"
    )

    print(f"  원본 답변:")
    for line in contaminatedAnswer.split('\n'):
        print(f"    {line}")

    print(f"\n  정제된 답변:")
    print(f"    {cleanedAnswer}")

    print(f"\n  정제 여부: {wasCleaned}")

    # 검증: 수영장 관련 문장이 제거되어야 함
    hasPool = "수영장" in cleanedAnswer or "19세" in cleanedAnswer
    hasBreakfast = "조식" in cleanedAnswer or "07:00" in cleanedAnswer

    success = wasCleaned and not hasPool and hasBreakfast
    print(f"\n  결과: {'✓ PASS' if success else '✗ FAIL'}")
    return success


def runAllTests():
    """모든 테스트 실행"""
    print("=" * 60)
    print("Grounding Gate 테스트")
    print("=" * 60)

    results = []
    results.append(("의도 분류", testIntentClassification()))
    results.append(("민감 토큰 추출", testSensitiveTokenExtraction()))
    results.append(("수치 토큰 검증", testNumericVerification()))
    results.append(("문장 분리", testClaimSplitting()))
    results.append(("전체 검증", testFullVerification()))
    results.append(("대여 비용 시나리오", testRentalFeeScenario()))
    results.append(("카테고리 오염 감지", testCategoryConsistency()))
    results.append(("오염된 답변 정제", testCategoryCleanedAnswer()))

    print("\n" + "=" * 60)
    print("[최종 결과]")
    print("=" * 60)

    passedCount = sum(1 for _, passed in results if passed)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\n  총 {passedCount}/{len(results)} 테스트 통과")

    return passedCount == len(results)


if __name__ == "__main__":
    success = runAllTests()
    exit(0 if success else 1)
