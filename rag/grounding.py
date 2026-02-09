"""
Grounding Gate 모듈
- 문장 단위 근거 검증
- 수치/키워드 토큰 매칭
- 할루시네이션 방지
"""

import re
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class Claim:
    """답변의 개별 주장(claim)"""
    text: str
    evidence_span: Optional[str] = None
    evidence_score: float = 0.0
    is_grounded: bool = False
    has_numeric: bool = False
    numeric_verified: bool = False


@dataclass
class GroundingResult:
    """근거 검증 결과"""
    passed: bool
    verified_claims: List[Claim] = field(default_factory=list)
    rejected_claims: List[Claim] = field(default_factory=list)
    reason: str = ""
    confidence: str = ""  # "확실", "불확실", "근거없음"


class GroundingGate:
    """근거 검증 게이트"""

    # 수치/민감 토큰 패턴 (근거 없이 생성 금지)
    SENSITIVE_PATTERNS = [
        (r'\d[\d,]*\s*원', "가격"),  # 50,000원, 5000원 등
        (r'\d+\s*%', "할인율"),
        (r'\d+\s*세', "연령"),
        (r'\d+\s*인', "인원"),
        (r'\d+\s*명', "인원"),
        (r'\d+\s*kg', "무게"),
        (r'\d{1,2}:\d{2}', "시간"),
        (r'무료', "무료"),
        (r'유료', "유료"),
        (r'할인', "할인"),
    ]

    # 고유명사 패턴 (한글+영문 병기: 할루시네이션 위험 높음)
    PROPER_NOUN_PATTERNS = [
        # "그랜드 셰프 (Grand Chef)" 같은 한영 병기 패턴
        (r'([가-힣]{2,}(?:\s+[가-힣]+)*)\s*\(([A-Za-z][A-Za-z\s&\'-]+)\)', "한영병기 시설명"),
        # "~ 레스토랑", "~ 카페" 등 시설 명칭
        (r'([가-힣A-Za-z]{2,}(?:\s+[가-힣A-Za-z]+)*)\s+(레스토랑|카페|바(?![가-힣])|라운지|센터|클럽)', "시설명"),
    ]

    # 질문 의도 분류 키워드
    INTENT_KEYWORDS = {
        "fee_entry": ["입장료", "이용료", "이용 요금", "얼마", "가격", "비용", "요금"],
        "fee_rental": ["대여", "렌탈", "빌려", "빌릴", "대여료", "대여비", "렌트", "대여 비용"],
        "rental_items": ["타월", "가운", "수영복", "수모", "수영모", "락커", "튜브", "수건", "물안경", "오리발"],
        "rule": ["규정", "규칙", "제한", "금지", "허용", "안되", "안돼", "불가", "가능"],
        "hours": ["시간", "운영", "오픈", "마감", "몇시", "언제"],
        "location": ["위치", "어디", "층", "찾아가"],
        "capacity": ["인원", "몇명", "몇 명", "최대"],
    }

    # "가능" 키워드를 rule로 분류해야 하는 특수 패턴
    RULE_TRIGGER_PATTERNS = [
        "입장 가능", "반려", "펫", "pet", "애완", "어린이", "미성년자",
        "휠체어", "장애인", "흡연", "음식물",
    ]

    # 근거 검증 임계값
    EVIDENCE_THRESHOLD = 0.45  # 나열형 답변 허용
    NUMERIC_MATCH_REQUIRED = True  # 수치가 있으면 근거에도 반드시 있어야 함

    # 무시할 일반 표현 패턴 (LLM이 추가하는 설명)
    GENERIC_PHRASES = [
        r'고급스러운 시설',
        r'다양한 서비스',
        r'고객님의 취향',
        r'편안한 휴식',
        r'최상의 서비스',
        r'이러한 객실들은',
        r'각각.*제공하며',
    ]

    def __init__(self):
        pass

    def classifyIntent(self, query: str) -> list[str]:
        """질문 의도 분류"""
        intents = []
        queryLower = query.lower()

        # 우선순위 기반 분류 (rental_items > fee_rental > rule 등)
        # 1. 먼저 rental_items 체크 (대여 물품 관련)
        if any(kw in queryLower for kw in self.INTENT_KEYWORDS["rental_items"]):
            intents.append("rental_items")

        # 2. 나머지 의도 분류
        for intent, keywords in self.INTENT_KEYWORDS.items():
            if intent == "rental_items":
                continue  # 이미 처리함

            # rule 의도에서 "가능" 키워드 특수 처리
            if intent == "rule":
                # rental_items + "대여 가능"은 fee_rental로 분류
                if "rental_items" in intents and "대여" in queryLower and "가능" in queryLower:
                    if "fee_rental" not in intents:
                        intents.append("fee_rental")
                    continue

                # "가능" 키워드는 RULE_TRIGGER_PATTERNS와 함께 있을 때만 rule로 분류
                if "가능" in queryLower:
                    if any(p in queryLower for p in self.RULE_TRIGGER_PATTERNS):
                        intents.append("rule")
                    continue

            if any(kw in queryLower for kw in keywords):
                intents.append(intent)

        return intents if intents else ["general"]

    def extractSensitiveTokens(self, text: str) -> list[tuple[str, str]]:
        """민감 토큰(수치/가격/인원 등) 추출"""
        tokens = []
        for pattern, tokenType in self.SENSITIVE_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                tokens.append((match, tokenType))
        return tokens

    def findEvidenceSpan(self, claim: str, context: str) -> tuple[Optional[str], float]:
        """claim에 대한 근거 스팬 찾기"""
        if not claim or not context:
            return None, 0.0

        claimLower = claim.lower()
        contextLower = context.lower()

        # 1. 정확 매칭
        if claimLower in contextLower:
            return claim, 1.0

        # 2. 핵심 정보(숫자/가격/시간) 매칭 - 높은 가중치
        claimNumbers = set(re.findall(r'\d[\d,]*', claim))
        contextNumbers = set(re.findall(r'\d[\d,]*', context))

        numberMatchScore = 0.0
        if claimNumbers:
            matched = 0
            for num in claimNumbers:
                numClean = num.replace(',', '')
                for ctxNum in contextNumbers:
                    ctxClean = ctxNum.replace(',', '')
                    if numClean == ctxClean or numClean in ctxClean or ctxClean in numClean:
                        matched += 1
                        break
            numberMatchScore = matched / len(claimNumbers) if claimNumbers else 0

        # 3. 키워드 오버랩 기반 매칭 (한글 단어 분리 개선)
        # 한글은 2글자 이상만, 영어는 단어 단위
        claimWordsKo = set(re.findall(r'[가-힣]{2,}', claimLower))
        claimWordsEn = set(re.findall(r'[a-z]+', claimLower))
        claimWords = claimWordsKo | claimWordsEn

        contextWordsKo = set(re.findall(r'[가-힣]{2,}', contextLower))
        contextWordsEn = set(re.findall(r'[a-z]+', contextLower))
        contextWords = contextWordsKo | contextWordsEn

        if not claimWords:
            # 숫자만 있는 경우 숫자 매칭으로 판단
            return (claim if numberMatchScore > 0 else None), numberMatchScore

        overlap = claimWords & contextWords
        wordOverlapScore = len(overlap) / len(claimWords)

        # 4. 문장 단위 근거 스팬 추출
        sentences = re.split(r'[.\n]', context)
        bestSpan = None
        bestScore = 0.0

        for sentence in sentences:
            if len(sentence.strip()) < 5:
                continue
            sentWordsKo = set(re.findall(r'[가-힣]{2,}', sentence.lower()))
            sentWordsEn = set(re.findall(r'[a-z]+', sentence.lower()))
            sentWords = sentWordsKo | sentWordsEn

            sentOverlap = claimWords & sentWords
            sentScore = len(sentOverlap) / len(claimWords) if claimWords else 0

            # 숫자 매칭 보너스
            sentNumbers = set(re.findall(r'\d[\d,]*', sentence))
            if claimNumbers and sentNumbers:
                for num in claimNumbers:
                    numClean = num.replace(',', '')
                    for sNum in sentNumbers:
                        sClean = sNum.replace(',', '')
                        if numClean == sClean:
                            sentScore += 0.3  # 숫자 정확 매칭 보너스
                            break

            if sentScore > bestScore:
                bestScore = sentScore
                bestSpan = sentence.strip()

        # 최종 점수: 숫자 매칭과 키워드 매칭 중 높은 값 + 보너스
        finalScore = max(wordOverlapScore, bestScore)
        if numberMatchScore > 0:
            finalScore = max(finalScore, numberMatchScore * 0.8 + wordOverlapScore * 0.2)

        return bestSpan, min(finalScore, 1.0)

    def verifyNumericTokens(self, answer: str, context: str) -> tuple[bool, list[str]]:
        """답변의 수치 토큰이 근거에 있는지 검증"""
        answerTokens = self.extractSensitiveTokens(answer)

        if not answerTokens:
            return True, []  # 수치 없으면 통과

        unverified = []
        for token, tokenType in answerTokens:
            # 1. 토큰 정규화 (쉼표 제거)
            tokenClean = token.replace(',', '').replace(' ', '')

            # 2. 가격/숫자 토큰은 정확히 매칭해야 함
            if tokenType == "가격":
                # 가격 패턴: 숫자+원
                priceNum = re.sub(r'[^\d]', '', token)  # 숫자만 추출
                if len(priceNum) >= 3:  # 최소 3자리 숫자 (100원 이상)
                    # 컨텍스트에서 동일 숫자 찾기
                    contextNumbers = re.findall(r'\d[\d,]*', context)
                    found = False
                    for ctxNum in contextNumbers:
                        ctxClean = ctxNum.replace(',', '')
                        if priceNum == ctxClean:
                            found = True
                            break
                    if not found:
                        unverified.append(f"{token} ({tokenType})")
            elif tokenType in ["할인율", "연령", "인원", "시간"]:
                # 정확한 토큰 매칭 필요
                tokenPattern = re.escape(token)
                if not re.search(tokenPattern, context, re.IGNORECASE):
                    # 숫자 부분만 추출해서 재검색
                    numPart = re.search(r'\d+', token)
                    if numPart:
                        numStr = numPart.group()
                        # 컨텍스트에서 동일 숫자+단위 조합 찾기
                        if tokenType == "할인율":
                            if not re.search(rf'{numStr}\s*%', context):
                                unverified.append(f"{token} ({tokenType})")
                        elif tokenType == "연령":
                            if not re.search(rf'{numStr}\s*세', context):
                                unverified.append(f"{token} ({tokenType})")
                        elif tokenType == "인원":
                            if not re.search(rf'{numStr}\s*[인명]', context):
                                unverified.append(f"{token} ({tokenType})")
                        elif tokenType == "시간":
                            if token not in context:
                                unverified.append(f"{token} ({tokenType})")
            elif tokenType in ["무료", "유료", "할인"]:
                # 키워드 존재 여부만 확인
                if token not in context:
                    unverified.append(f"{token} ({tokenType})")

        return len(unverified) == 0, unverified

    def splitIntoClaims(self, answer: str) -> list[str]:
        """답변을 개별 주장으로 분리"""
        claims = []

        # 1. 줄바꿈 기준 분리 먼저 시도 (불릿 포인트 포함)
        lines = answer.strip().split('\n')
        for line in lines:
            line = line.strip()
            # 불릿 포인트 제거
            line = re.sub(r'^[-•*]\s*', '', line)
            if len(line) >= 5:  # 최소 5자 이상
                claims.append(line)

        # 2. 줄바꿈으로 분리된 게 없으면 문장 단위 분리
        if len(claims) <= 1:
            claims = []
            sentences = re.split(r'[.。]\s*', answer)
            for s in sentences:
                s = s.strip()
                if len(s) >= 5:
                    claims.append(s)

        # 빈 결과면 원본 반환
        if not claims:
            claims = [answer.strip()]

        return claims

    def isGenericPhrase(self, text: str) -> bool:
        """일반적인 설명 문구인지 확인"""
        for pattern in self.GENERIC_PHRASES:
            if re.search(pattern, text):
                return True
        return False

    def verifyProperNouns(self, text: str, context: str) -> tuple[bool, list[str]]:
        """고유명사가 컨텍스트에 존재하는지 검증"""
        unverified = []
        contextLower = context.lower()

        for pattern, nounType in self.PROPER_NOUN_PATTERNS:
            matches = re.finditer(pattern, text)
            for match in matches:
                fullMatch = match.group(0)
                # 한영 병기인 경우 두 이름 모두 확인
                if nounType == "한영병기 시설명":
                    koName = match.group(1).strip()
                    enName = match.group(2).strip()
                    # 한글명과 영문명 중 하나라도 컨텍스트에 있으면 통과
                    if koName.lower() not in contextLower and enName.lower() not in contextLower:
                        unverified.append(f"{fullMatch} ({nounType})")
                elif nounType == "시설명":
                    facilityName = match.group(1).strip()
                    if len(facilityName) >= 2 and facilityName.lower() not in contextLower:
                        unverified.append(f"{fullMatch} ({nounType})")

        return len(unverified) == 0, unverified

    def verifyClaim(self, claim: str, context: str) -> Claim:
        """개별 주장 검증"""
        # 일반적인 설명 문구는 검증 건너뛰기 (통과 처리)
        if self.isGenericPhrase(claim):
            return Claim(
                text=claim,
                evidence_span=None,
                evidence_score=1.0,  # 일반 문구는 통과
                is_grounded=True,
                has_numeric=False,
                numeric_verified=True
            )

        evidenceSpan, evidenceScore = self.findEvidenceSpan(claim, context)

        # 수치 토큰 검증
        answerTokens = self.extractSensitiveTokens(claim)
        hasNumeric = len(answerTokens) > 0
        numericVerified = True

        if hasNumeric:
            numericVerified, unverified = self.verifyNumericTokens(claim, context)

        # 고유명사 검증 (컨텍스트에 없는 시설명 차단)
        properNounVerified, properNounUnverified = self.verifyProperNouns(claim, context)
        if not properNounVerified:
            # 고유명사 검증 실패 → 무조건 reject
            return Claim(
                text=claim,
                evidence_span=evidenceSpan,
                evidence_score=evidenceScore,
                is_grounded=False,
                has_numeric=hasNumeric,
                numeric_verified=False  # 고유명사 미검증 = 수치 미검증과 동급
            )

        # 최종 grounded 판정
        isGrounded = (
            evidenceScore >= self.EVIDENCE_THRESHOLD and
            (not hasNumeric or numericVerified)
        )

        return Claim(
            text=claim,
            evidence_span=evidenceSpan,
            evidence_score=evidenceScore,
            is_grounded=isGrounded,
            has_numeric=hasNumeric,
            numeric_verified=numericVerified
        )

    def verify(self, answer: str, context: str, query: str = "") -> GroundingResult:
        """전체 답변 근거 검증"""
        if not answer or not context:
            return GroundingResult(
                passed=False,
                verified_claims=[],
                rejected_claims=[],
                reason="답변 또는 근거 없음",
                confidence="근거없음"
            )

        # 1. 질문 의도 분류
        intents = self.classifyIntent(query)

        # 2. 답변을 claim으로 분리
        claims = self.splitIntoClaims(answer)

        if not claims:
            # 단일 문장인 경우
            claims = [answer]

        # 3. 각 claim 검증
        verifiedClaims = []
        rejectedClaims = []

        for claimText in claims:
            claim = self.verifyClaim(claimText, context)
            if claim.is_grounded:
                verifiedClaims.append(claim)
            else:
                rejectedClaims.append(claim)

        # 4. 최종 판정
        if not verifiedClaims and rejectedClaims:
            return GroundingResult(
                passed=False,
                verified_claims=[],
                rejected_claims=rejectedClaims,
                reason=f"모든 주장이 근거 부족: {len(rejectedClaims)}개",
                confidence="근거없음"
            )

        # 일부만 통과
        if rejectedClaims:
            return GroundingResult(
                passed=True,
                verified_claims=verifiedClaims,
                rejected_claims=rejectedClaims,
                reason=f"일부 주장 근거 부족: {len(rejectedClaims)}개 제거",
                confidence="불확실"
            )

        return GroundingResult(
            passed=True,
            verified_claims=verifiedClaims,
            rejected_claims=[],
            reason="모든 주장 검증 통과",
            confidence="확실"
        )

    def buildVerifiedAnswer(self, result: GroundingResult, context: str,
                            hotelName: str = "", contactInfo: str = "") -> str:
        """검증된 claim만으로 답변 재구성"""
        if not result.passed or not result.verified_claims:
            return self._buildFallbackResponse(result, hotelName, contactInfo)

        # 검증된 claim 조합
        verifiedTexts = [c.text for c in result.verified_claims]
        answer = "\n".join([f"- {t}" for t in verifiedTexts]) if len(verifiedTexts) > 1 else verifiedTexts[0]

        # 근거 첨부
        evidenceSpans = [c.evidence_span for c in result.verified_claims if c.evidence_span]
        if evidenceSpans:
            uniqueSpans = list(set(evidenceSpans))[:2]  # 최대 2개
            answer += "\n\n[근거]\n" + "\n".join([f'"{s[:100]}..."' for s in uniqueSpans])

        # 확실/불확실 표시
        answer += f"\n\n[신뢰도: {result.confidence}]"

        return answer

    def _buildFallbackResponse(self, result: GroundingResult, hotelName: str,
                                contactInfo: str) -> str:
        """근거 부족 시 대체 응답"""
        response = "죄송합니다, 해당 내용에 대한 정확한 정보를 현재 자료에서 찾지 못했습니다."

        if contactInfo:
            response += f"\n\n자세한 사항은 {contactInfo}로 문의 부탁드립니다."

        return response


@dataclass
class CategoryConsistencyResult:
    """카테고리 일관성 검증 결과"""
    passed: bool
    contaminated_sentences: List[str] = field(default_factory=list)
    foreign_keywords_found: List[str] = field(default_factory=list)
    cleaned_answer: str = ""
    reason: str = ""


class CategoryConsistencyChecker:
    """카테고리 교차 오염 감지기

    대화 주제와 답변 내용의 일관성을 검증하여
    다른 카테고리 정보가 섞이는 것을 방지.
    """

    # 카테고리별 배타적 키워드 (own: 해당 카테고리, foreign: 다른 카테고리)
    EXCLUSIVE_KEYWORDS = {
        "조식": {
            "own": ["조식", "breakfast", "뷔페", "아침", "아침식사", "모닝"],
            "foreign": ["수영장", "풀", "pool", "피트니스", "헬스", "gym", "스파", "사우나",
                       "주차", "parking", "발렛", "19세", "성인", "입장료", "탈의실", "락커"]
        },
        "다이닝": {
            "own": ["레스토랑", "식당", "다이닝", "저녁", "점심", "런치", "디너", "메뉴"],
            "foreign": ["수영장", "풀", "pool", "피트니스", "헬스", "gym", "스파", "사우나",
                       "주차", "parking", "발렛", "19세", "성인", "입장료", "탈의실", "락커"]
        },
        "수영장": {
            "own": ["수영", "수영장", "풀", "pool", "swimming", "물", "인피니티", "탈의실", "락커", "수모", "수영복"],
            "foreign": ["조식", "breakfast", "뷔페", "아침식사", "주차", "parking", "발렛"]
        },
        "부대시설": {
            "own": ["수영", "수영장", "피트니스", "헬스", "사우나", "스파", "gym", "pool", "운동"],
            "foreign": ["조식", "breakfast", "뷔페", "아침식사", "주차", "parking", "발렛"]
        },
        "피트니스": {
            "own": ["피트니스", "헬스", "gym", "fitness", "운동", "트레이닝", "기구"],
            "foreign": ["조식", "breakfast", "뷔페", "수영장", "pool", "주차", "parking"]
        },
        "스파": {
            "own": ["스파", "spa", "마사지", "massage", "사우나", "트리트먼트", "테라피"],
            "foreign": ["조식", "breakfast", "주차", "parking", "수영장", "pool"]
        },
        "주차": {
            "own": ["주차", "parking", "발렛", "valet", "파킹", "차량", "대"],
            "foreign": ["조식", "breakfast", "뷔페", "수영장", "pool", "피트니스", "gym", "19세", "성인"]
        },
        "체크인/아웃": {
            "own": ["체크인", "체크아웃", "입실", "퇴실", "check-in", "check-out", "시", "분"],
            "foreign": ["수영장", "pool", "피트니스", "조식", "breakfast", "19세", "성인"]
        },
        "객실": {
            "own": ["객실", "방", "room", "침대", "bed", "뷰", "전망", "스위트", "디럭스"],
            "foreign": ["수영장", "pool", "피트니스", "gym", "19세", "성인", "입장료"]
        },
        "반려동물": {
            "own": ["반려", "pet", "펫", "강아지", "반려견", "애견", "동물", "dog"],
            "foreign": ["수영장", "pool", "조식", "breakfast", "19세", "성인"]
        },
    }

    def __init__(self):
        pass

    def verifyCategoryConsistency(self, answer: str, targetCategory: str,
                                    chunks: list = None) -> CategoryConsistencyResult:
        """답변이 대상 카테고리와 일관성이 있는지 검증

        Args:
            answer: 생성된 답변
            targetCategory: 대화 주제 또는 감지된 카테고리
            chunks: 검색된 청크 목록 (선택적)

        Returns:
            CategoryConsistencyResult: 검증 결과
        """
        if not targetCategory or not answer:
            return CategoryConsistencyResult(
                passed=True,
                reason="카테고리 미지정 또는 답변 없음"
            )

        # 카테고리 키워드 조회
        categoryKeywords = self.EXCLUSIVE_KEYWORDS.get(targetCategory)
        if not categoryKeywords:
            return CategoryConsistencyResult(
                passed=True,
                reason=f"'{targetCategory}' 카테고리 키워드 미정의"
            )

        foreignKeywords = categoryKeywords["foreign"]
        answerLower = answer.lower()

        # 문장 단위로 분리
        sentences = re.split(r'[.\n]', answer)
        contaminatedSentences = []
        foreignFound = []
        cleanSentences = []

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 3:
                continue

            sentenceLower = sentence.lower()
            isContaminated = False

            # foreign 키워드 검사
            for foreignKw in foreignKeywords:
                if foreignKw.lower() in sentenceLower:
                    isContaminated = True
                    foreignFound.append(foreignKw)
                    contaminatedSentences.append(sentence)
                    break

            if not isContaminated:
                cleanSentences.append(sentence)

        # 결과 반환
        if contaminatedSentences:
            cleanedAnswer = ". ".join(cleanSentences) + "." if cleanSentences else ""
            return CategoryConsistencyResult(
                passed=False,
                contaminated_sentences=contaminatedSentences,
                foreign_keywords_found=list(set(foreignFound)),
                cleaned_answer=cleanedAnswer,
                reason=f"다른 카테고리 정보 혼입 감지: {', '.join(set(foreignFound))}"
            )

        return CategoryConsistencyResult(
            passed=True,
            cleaned_answer=answer,
            reason="카테고리 일관성 유지"
        )

    def getCleanedAnswer(self, answer: str, targetCategory: str,
                          contactGuide: str = "") -> tuple[str, bool]:
        """오염된 문장을 제거한 정제된 답변 반환

        Args:
            answer: 원본 답변
            targetCategory: 대상 카테고리
            contactGuide: 연락처 안내 문구

        Returns:
            (정제된 답변, 정제 여부)
        """
        result = self.verifyCategoryConsistency(answer, targetCategory)

        if result.passed:
            return answer, False

        # 정제된 답변이 너무 짧으면 폴백 응답
        if not result.cleaned_answer or len(result.cleaned_answer) < 10:
            fallback = "죄송합니다, 해당 내용에 대한 정확한 정보를 찾을 수 없습니다."
            if contactGuide:
                fallback += f"\n자세한 사항은 {contactGuide}로 문의 부탁드립니다."
            return fallback, True

        return result.cleaned_answer, True


# 싱글톤 인스턴스
groundingGate = GroundingGate()
categoryChecker = CategoryConsistencyChecker()
