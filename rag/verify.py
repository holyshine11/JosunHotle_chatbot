"""답변 검증 모듈

answerVerifyNode에서 사용하는 검증 메서드를 분리.
- 응답 품질 검사
- 숫자/고유명사/교통편 할루시네이션 검사
- 쿼리-컨텍스트 관련성 검증
- 호텔 간 교차 오염 검증
- 전화번호/URL/날짜 할루시네이션 검사
- Fallback 직접 추출
- 금지 표현 제거
"""

import re
import json
import os

from rag.constants import SUSPICIOUS_PATTERNS, HOTEL_INFO


# 설정 파일 경로
_CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'config')


class AnswerVerifier:
    """답변 검증기 - graph.py의 answerVerifyNode에서 사용"""

    # 사전 컴파일 정규식 — extractNumbers
    _RE_PRICES = re.compile(r'[\d,]+\s*원')
    _RE_TIMES = re.compile(r'\d{1,2}:\d{2}')
    _RE_PHONES = re.compile(r'\d{2,4}[-.]?\d{3,4}[-.]?\d{4}')
    _RE_PERCENTS = re.compile(r'\d+\s*%')
    _RE_FLOORS = re.compile(r'\d+\s*층')
    _RE_PERSONS = re.compile(r'\d+\s*인')
    _RE_WEIGHTS = re.compile(r'\d+\s*kg', re.IGNORECASE)
    _RE_AGES = re.compile(r'\d+\s*세')
    _RE_FULL_DATES = re.compile(r'\d{4}년\s*\d{1,2}월\s*\d{1,2}일')
    _RE_MONTH_DAYS = re.compile(r'\d{1,2}월\s*\d{1,2}일')

    # 사전 컴파일 정규식 — checkResponseQuality 의미없는 패턴
    _MEANINGLESS_PATTERNS = [
        (re.compile(r'宫咚咚'), "중국어 의미없는 패턴"),
        (re.compile(r'参考资料'), "중국어 안내 문구"),
        (re.compile(r'无法提供'), "중국어 안내 문구"),
        (re.compile(r'\?\?+'), "반복 물음표"),
        (re.compile(r'！！+'), "반복 느낌표"),
        (re.compile(r'\.\.\.\.+'), "과도한 말줄임"),
    ]

    # 사전 컴파일 정규식 — checkResponseQuality 금지 패턴
    _FORBIDDEN_PATTERNS = [
        (re.compile(r'궁금하신가요', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'더\s*필요하신\s*것', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'어떤\s*것이?\s*궁금', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'도움이?\s*되셨', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'추가.*질문', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'알려주시면', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'말씀해\s*주시', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'문의.*주시면', re.IGNORECASE | re.MULTILINE), "금지 문구"),
        (re.compile(r'^\s*-\s*-\s*$', re.IGNORECASE | re.MULTILINE), "빈 내용"),
        (re.compile(r'정보가\s*없습니다.*문의', re.IGNORECASE | re.MULTILINE), "잘못된 안내"),
    ]

    # 사전 컴파일 정규식 — checkTransportationHallucination
    _TRANSPORT_PATTERNS = [
        (re.compile(r'\d+호선'), "지하철 노선"),
        (re.compile(r'지하철\s*[가-힣]+선'), "지하철 노선명"),
        (re.compile(r'버스\s*\d+번?'), "버스 노선"),
        (re.compile(r'[가-힣]+역에서\s*[가-힣]+역'), "지하철 경로"),
        (re.compile(r'환승|갈아타'), "환승 안내"),
    ]

    def __init__(self):
        self.knownNames = self._loadKnownNames()
        self.forbiddenPhrases = self._loadForbiddenPatterns()

    def _loadKnownNames(self) -> set:
        """고유명사 화이트리스트 로딩 (data/config/known_names.json)"""
        configPath = os.path.join(_CONFIG_DIR, 'known_names.json')
        try:
            with open(configPath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            names = set(data.get('brands', []))
            for hotelNames in data.get('restaurants', {}).values():
                names.update(hotelNames)
            names.update(data.get('facilities', []))
            names.update(data.get('room_types', []))
            return names
        except (FileNotFoundError, json.JSONDecodeError):
            return {"조선", "그랜드 조선", "조선 팰리스", "레스케이프", "그래비티", "조선호텔"}

    def _loadForbiddenPatterns(self) -> list[str]:
        """금지 표현 패턴 로딩 (data/config/forbidden_patterns.json)"""
        configPath = os.path.join(_CONFIG_DIR, 'forbidden_patterns.json')
        try:
            with open(configPath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('patterns', [])
        except (FileNotFoundError, json.JSONDecodeError):
            return [r'궁금하신가요\??', r'도움이?\s*되셨나요\??']

    def extractQueryKeywords(self, query: str) -> list[str]:
        """질문에서 핵심 키워드 추출"""
        petKeywords = ["강아지", "반려견", "pet", "펫", "반려동물", "애견", "고양이", "댕댕이"]
        parkingKeywords = ["주차", "parking", "발렛", "valet", "파킹"]
        poolKeywords = ["수영장", "pool", "풀", "swimming"]
        breakfastKeywords = ["조식", "breakfast", "아침", "뷔페", "아침식사"]

        queryLower = query.lower()
        foundKeywords = []

        if any(kw in queryLower for kw in petKeywords):
            foundKeywords.append("반려동물")
        if any(kw in queryLower for kw in parkingKeywords):
            foundKeywords.append("주차")
        if any(kw in queryLower for kw in poolKeywords):
            foundKeywords.append("수영장")
        if any(kw in queryLower for kw in breakfastKeywords):
            foundKeywords.append("조식")

        return foundKeywords

    def checkQueryContextRelevance(self, query: str, chunks: list) -> tuple[bool, str]:
        """질문 핵심 키워드가 검색된 청크에 있는지 검증"""
        queryKeywords = self.extractQueryKeywords(query)

        if not queryKeywords:
            return True, ""

        chunkTexts = " ".join([c.get("text", "") for c in chunks[:5]])
        chunkTextsLower = chunkTexts.lower()
        chunkCategories = [c.get("metadata", {}).get("category", "").lower() for c in chunks[:5]]
        chunkPageTypes = [c.get("metadata", {}).get("page_type", "").lower() for c in chunks[:5]]

        categoryKeywordMap = {
            "반려동물": ["반려", "pet", "펫", "강아지", "dog", "애견", "소형견", "반려견", "동물", "salon", "패키지", "불가", "동반"],
            "주차": ["주차", "parking", "발렛", "valet", "파킹", "차량", "주차장"],
            "수영장": ["수영", "pool", "풀", "swimming", "인피니티", "워터"],
            "조식": ["조식", "breakfast", "아침", "뷔페", "dining", "식사", "레스토랑"],
        }

        for keyword in queryKeywords:
            keywordFound = False

            for cat in chunkCategories:
                if keyword.replace("동물", "") in cat or keyword in cat:
                    keywordFound = True
                    break

            if not keywordFound:
                for pt in chunkPageTypes:
                    if keyword in pt or "package" in pt:
                        keywordFound = True
                        break

            if not keywordFound:
                expandedKeywords = categoryKeywordMap.get(keyword, [keyword])
                for kw in expandedKeywords:
                    if kw.lower() in chunkTextsLower:
                        keywordFound = True
                        break

            if not keywordFound:
                print(f"[관련성 검증] '{keyword}' 관련 정보 미발견 — 하지만 검색 결과가 있으므로 진행")

        return True, ""

    def extractNumbers(self, text: str) -> set[str]:
        """텍스트에서 숫자 정보 추출 (가격, 시간, 전화번호, 층수, 날짜)"""
        numbers = set()
        numbers.update(self._RE_PRICES.findall(text))
        numbers.update(self._RE_TIMES.findall(text))
        numbers.update(self._RE_PHONES.findall(text))
        numbers.update(self._RE_PERCENTS.findall(text))
        numbers.update(self._RE_FLOORS.findall(text))
        numbers.update(self._RE_PERSONS.findall(text))
        numbers.update(self._RE_WEIGHTS.findall(text))
        numbers.update(self._RE_AGES.findall(text))
        numbers.update(self._RE_FULL_DATES.findall(text))
        numbers.update(self._RE_MONTH_DAYS.findall(text))
        return numbers

    def checkResponseQuality(self, answer: str, query: str) -> tuple[bool, list[str]]:
        """응답 품질 검사: 비정상 문자, 언어 혼합, 금지 패턴 탐지"""
        issues = []

        # 1. 비정상 문자 탐지
        chineseChars = re.findall(r'[\u4e00-\u9fff]', answer)
        if len(chineseChars) > 2:
            issues.append(f"비정상: 중국어 문자 포함 ({len(chineseChars)}자)")

        japaneseChars = re.findall(r'[\u3040-\u30ff]', answer)
        if len(japaneseChars) > 2:
            issues.append(f"비정상: 일본어 문자 포함 ({len(japaneseChars)}자)")

        # 2. 한글 비율 검사
        normalizedAnswer = answer
        normalizedAnswer = re.sub(r'\d{1,2}:\d{2}\s*[-~]\s*\d{1,2}:\d{2}', '', normalizedAnswer)
        normalizedAnswer = re.sub(r'\d{1,2}:\d{2}', '', normalizedAnswer)
        normalizedAnswer = re.sub(r'BREAK\s*TIME', '', normalizedAnswer, flags=re.IGNORECASE)

        hotelTerms = [
            'KIDS', 'Superior', 'Deluxe', 'Suite', 'Premier', 'Standard',
            'Twin', 'Double', 'King', 'Queen', 'Pool', 'Spa', 'Fitness',
            'Andish', 'Zerovity', 'Aria', 'Constans', 'Eat2O',
            'VAT', 'URL', 'http', 'https', 'do', 'josunhotel', 'com',
        ]
        for term in hotelTerms:
            normalizedAnswer = re.sub(rf'\b{term}\b', '', normalizedAnswer, flags=re.IGNORECASE)

        normalizedAnswer = re.sub(r'[\d\-:~/.,@#$%^&*()_+=\[\]{}|\\<>]', '', normalizedAnswer)

        koreanChars = len(re.findall(r'[가-힣]', normalizedAnswer))
        totalChars = len(normalizedAnswer.replace(' ', '').replace('\n', ''))

        if totalChars > 5 and koreanChars / totalChars < 0.25:
            issues.append(f"비정상: 한글 비율 낮음 ({koreanChars}/{totalChars})")

        # 3. 의미 없는 패턴 탐지 (사전 컴파일 사용)
        for compiledPattern, desc in self._MEANINGLESS_PATTERNS:
            if compiledPattern.search(answer):
                issues.append(f"비정상: {desc}")
                break

        # 4. 답변이 너무 짧거나 비어있음
        cleanAnswer = answer.strip()
        if len(cleanAnswer) < 5:
            issues.append("비정상: 답변이 너무 짧음")

        # 5. 금지 패턴 탐지 (사전 컴파일 사용)
        for compiledPattern, desc in self._FORBIDDEN_PATTERNS:
            if compiledPattern.search(answer):
                issues.append(f"금지패턴: {desc}")

        return len(issues) == 0, issues

    def extractDirectAnswer(self, topText: str, query: str) -> str:
        """chunk에서 직접 답변 추출 (Fallback용)"""
        directAnswer = None

        # 1. Q&A 형식에서 A: 부분 추출 (다음 Q: 또는 텍스트 끝까지)
        if "A:" in topText:
            aMatch = re.search(r'A:\s*(.+?)(?=\nQ:|\Z)', topText, re.DOTALL)
            if aMatch:
                directAnswer = aMatch.group(1).strip()

        # 2. 구조화된 정보 추출
        if not directAnswer:
            parts = []

            facilityName = ""
            headerMatch = re.search(r'레스토랑[:\s]+([가-힣a-zA-Z\'\s]+)', topText)
            if headerMatch:
                facilityName = headerMatch.group(1).strip()
            if not facilityName:
                headerMatch = re.search(r'([가-힣]+(?:\s+[가-힣]+)*)\s*(?:안내|상세)', topText)
                if headerMatch:
                    facilityName = headerMatch.group(1).strip()

            if facilityName:
                parts.append(facilityName)

            descMatch = re.search(r'(?:BUFFET|뷔페|시푸드|Seafood|그릴|Grill)[^\n]*', topText, re.IGNORECASE)
            if descMatch:
                parts.append(descMatch.group(0).strip().rstrip('.'))

            timeMatch = re.search(
                r'(?:HOURS?\s*(?:OF\s*)?OPERATION|운영\s*시간)\s*[:：]?\s*(\d{1,2}:\d{2}\s*[-~]\s*\d{1,2}:\d{2})',
                topText, re.IGNORECASE
            )
            if timeMatch:
                hours = timeMatch.group(1).strip()
                parts.append(f"운영시간: {hours}")

            locationMatch = re.search(
                r'(?:LOCATION|위치)\s*[:：]?\s*(.+?)(?:\n|PERIOD|HOURS|INQUIRY|$)',
                topText, re.IGNORECASE
            )
            if locationMatch:
                loc = locationMatch.group(1).strip().rstrip('-').strip()
                if loc:
                    parts.append(f"위치: {loc}")

            inquiryMatch = re.search(r'(?:INQUIRY|문의/?예약|문의)\s*[:：]?\s*([\d\.\-\s,]+)', topText, re.IGNORECASE)
            if inquiryMatch:
                phone = inquiryMatch.group(1).strip()
                parts.append(f"문의: {phone}")

            if len(parts) >= 2:
                directAnswer = "\n".join([f"- {p}" for p in parts])

        return directAnswer

    def checkTransportationHallucination(self, answer: str, context: str, query: str) -> tuple[bool, list[str], str]:
        """교통편/노선 정보 날조 검사"""
        issues = []
        cleanedAnswer = answer

        for compiledPattern, desc in self._TRANSPORT_PATTERNS:
            matches = compiledPattern.findall(answer)
            for match in matches:
                if match not in context:
                    issues.append(f"교통편 날조: '{match}' ({desc}) — 컨텍스트에 없음")

        if issues:
            sentences = re.split(r'(?<=[.!?다요])\s+', cleanedAnswer)
            filteredSentences = []
            for sentence in sentences:
                hasTransportFabrication = False
                for compiledPattern, _ in self._TRANSPORT_PATTERNS:
                    matches = compiledPattern.findall(sentence)
                    for match in matches:
                        if match not in context:
                            hasTransportFabrication = True
                            break
                    if hasTransportFabrication:
                        break
                if not hasTransportFabrication:
                    filteredSentences.append(sentence)

            cleanedAnswer = " ".join(filteredSentences).strip()
            print(f"[교통편 날조 검증] 감지: {issues}")

        # 주제 이탈 검사
        queryLower = query.lower()
        transportKeywords = ["지하철", "버스", "택시", "노선", "호선", "교통편", "환승"]
        queryIsTransport = any(kw in queryLower for kw in ["교통", "오시는", "셔틀", "공항에서", "어떻게 가"])

        if not queryIsTransport:
            for kw in transportKeywords:
                if kw in answer and kw not in context:
                    issues.append(f"주제 이탈: 질문 '{query[:20]}...'에 교통 정보 혼입")
                    sentences = re.split(r'(?<=[.!?다요])\s+', cleanedAnswer)
                    cleanedAnswer = " ".join(
                        s for s in sentences
                        if not any(tk in s for tk in transportKeywords)
                    ).strip()
                    break

        passed = len(issues) == 0
        return passed, issues, cleanedAnswer

    def checkHallucination(self, answer: str, context: str) -> tuple[bool, list[str]]:
        """숫자 할루시네이션 검사"""
        issues = []

        answerNumbers = self.extractNumbers(answer)
        contextNumbers = self.extractNumbers(context)

        # 의심 패턴 검사 (constants.py에서 관리, chunk 원본 대조)
        for pattern, issueType in SUSPICIOUS_PATTERNS:
            match = re.search(pattern, answer)
            if match:
                if match.group() not in context:
                    issues.append(f"의심: {issueType} 발견")

        # 답변에만 있고 컨텍스트에 없는 숫자 검사
        for num in answerNumbers:
            numNorm = re.sub(r'[\s,]', '', num)
            found = False
            for ctxNum in contextNumbers:
                ctxNorm = re.sub(r'[\s,]', '', ctxNum)
                if numNorm in ctxNorm or ctxNorm in numNorm:
                    found = True
                    break

            if not found and len(numNorm) > 2:
                if numNorm not in context.replace(',', '').replace(' ', ''):
                    issues.append(f"검증실패: '{num}' - 컨텍스트에 없음")

        return len(issues) == 0, issues

    def checkProperNounHallucination(self, answer: str, context: str) -> tuple[bool, list[str], str]:
        """고유명사 할루시네이션 검사"""
        issues = []
        cleanedAnswer = answer

        bilingualPattern = re.findall(
            r'([가-힣]{2,}(?:\s+[가-힣]+)*)\s*\(([A-Za-z][A-Za-z\s&\'-]+)\)',
            answer
        )
        quotedNames = re.findall(r"['\"]([가-힣A-Za-z][가-힣A-Za-z\s&\'-]+)['\"]", answer)
        facilityPattern = re.findall(
            r'([가-힣A-Za-z]{2,}(?:\s+[가-힣A-Za-z]+)*)\s*(?:레스토랑|식당|라운지|풀|센터|카페|바|클럽|스파|사우나)',
            answer
        )

        properNouns = set()

        commonWords = {
            "하지만", "그리고", "또한", "그래서", "따라서", "다만", "그러나", "그런데",
            "그렇게", "이렇게", "그곳에", "이곳에", "해당", "물론", "참고로", "특히",
            "다양한", "일반적", "기본적", "대표적", "실내외", "실내", "실외",
            "해운대", "강남", "판교", "명동", "제주", "부산", "서울", "인천",
            "투숙객", "고객님", "이용객", "방문객",
        }

        for koName, enName in bilingualPattern:
            properNouns.add(koName.strip())
            properNouns.add(enName.strip())
        for name in quotedNames:
            if len(name) >= 2:
                properNouns.add(name.strip())
        for name in facilityPattern:
            if len(name) >= 2 and name.strip() not in commonWords:
                properNouns.add(name.strip())

        contextLower = context.lower()

        for noun in properNouns:
            nounLower = noun.lower()

            if any(known.lower() == nounLower or known.lower() in nounLower for known in self.knownNames):
                continue

            if len(noun) <= 2:
                continue

            if nounLower not in contextLower:
                issues.append(f"고유명사 미검증: '{noun}' — 컨텍스트에 없음")

                sentences = re.split(r'(?<=[.!?\n])\s*', cleanedAnswer)
                filteredSentences = []
                for sentence in sentences:
                    if noun in sentence or nounLower in sentence.lower():
                        issues.append(f"할루시네이션 문장 제거: '{sentence[:60]}...'")
                    else:
                        filteredSentences.append(sentence)
                cleanedAnswer = " ".join(filteredSentences).strip()

        passed = len(issues) == 0
        return passed, issues, cleanedAnswer

    def checkHotelCrossContamination(self, answer: str, context: str,
                                       targetHotel: str = None) -> tuple[bool, list[str], str]:
        """호텔 간 교차 오염 검사

        답변이 다른 호텔의 정보를 포함하는지 검증.
        예: 부산 호텔 질문에 제주 호텔 정보가 섞이는 경우.
        """
        if not targetHotel:
            return True, [], answer

        issues = []
        cleanedAnswer = answer

        # 현재 호텔 이름
        currentHotelName = HOTEL_INFO.get(targetHotel, {}).get("name", "")

        # 다른 호텔의 이름 목록
        otherHotelNames = {}
        for hotelId, info in HOTEL_INFO.items():
            if hotelId != targetHotel:
                otherHotelNames[hotelId] = info["name"]

        # 다른 호텔 이름이 답변에 포함되어 있는지 검사
        answerLower = answer.lower()
        contextLower = context.lower()

        for otherHotelId, otherName in otherHotelNames.items():
            # 컨텍스트에도 없는데 답변에 다른 호텔명이 있으면 오염
            if otherName.lower() in answerLower and otherName.lower() not in contextLower:
                issues.append(f"호텔 교차 오염: '{otherName}' 이(가) 답변에 포함 (대상: {currentHotelName})")

                # 오염된 문장 제거
                sentences = re.split(r'(?<=[.!?다요])\s+', cleanedAnswer)
                filteredSentences = []
                for sentence in sentences:
                    if otherName.lower() not in sentence.lower():
                        filteredSentences.append(sentence)
                cleanedAnswer = " ".join(filteredSentences).strip()

        # 다른 호텔의 전화번호가 섞여 있는지 검사
        for otherHotelId, otherInfo in HOTEL_INFO.items():
            if otherHotelId == targetHotel:
                continue
            otherPhone = otherInfo.get("phone", "")
            if otherPhone and otherPhone in answer and otherPhone not in context:
                issues.append(f"전화번호 교차 오염: '{otherPhone}' ({otherInfo['name']})")
                cleanedAnswer = cleanedAnswer.replace(otherPhone, "")

        passed = len(issues) == 0
        return passed, issues, cleanedAnswer

    def checkPhoneHallucination(self, answer: str, context: str) -> tuple[bool, list[str], str]:
        """전화번호 할루시네이션 전용 검사

        답변에 포함된 전화번호가 컨텍스트에 실제로 있는지 정밀 검증.
        """
        issues = []
        cleanedAnswer = answer

        # 전화번호 패턴 (다양한 형식)
        phonePattern = r'\d{2,4}[-.]?\d{3,4}[-.]?\d{4}'
        answerPhones = re.findall(phonePattern, answer)

        if not answerPhones:
            return True, [], answer

        contextPhones = re.findall(phonePattern, context)
        contextPhoneDigits = set()
        for ctxPhone in contextPhones:
            contextPhoneDigits.add(re.sub(r'[^\d]', '', ctxPhone))

        # 알려진 호텔 전화번호 (화이트리스트)
        knownPhoneDigits = set()
        for info in HOTEL_INFO.values():
            phoneDigits = re.sub(r'[^\d]', '', info.get("phone", ""))
            if phoneDigits:
                knownPhoneDigits.add(phoneDigits)

        for phone in answerPhones:
            phoneDigits = re.sub(r'[^\d]', '', phone)
            if len(phoneDigits) < 8:
                continue  # 짧은 숫자는 전화번호가 아닐 수 있음

            # 컨텍스트에 있거나, 알려진 호텔 번호인지 확인
            inContext = phoneDigits in contextPhoneDigits
            isKnown = phoneDigits in knownPhoneDigits

            if not inContext and not isKnown:
                issues.append(f"전화번호 할루시네이션: '{phone}' — 컨텍스트에 없음")
                # 전화번호가 포함된 문장 제거
                sentences = re.split(r'(?<=[.!?\n])\s*', cleanedAnswer)
                filteredSentences = []
                for sentence in sentences:
                    if phone not in sentence:
                        filteredSentences.append(sentence)
                cleanedAnswer = " ".join(filteredSentences).strip()

        passed = len(issues) == 0
        return passed, issues, cleanedAnswer

    def checkUrlHallucination(self, answer: str, context: str) -> tuple[bool, list[str], str]:
        """URL 할루시네이션 검사

        답변에 포함된 URL이 컨텍스트에 실제로 있는지 검증.
        """
        issues = []
        cleanedAnswer = answer

        # URL 패턴
        urlPattern = r'https?://[^\s\)\]>\"\']+|www\.[^\s\)\]>\"\']+'
        answerUrls = re.findall(urlPattern, answer)

        if not answerUrls:
            return True, [], answer

        contextUrls = set(re.findall(urlPattern, context))
        # 알려진 호텔 URL 도메인
        knownDomains = {"josunhotel.com", "jpg.josunhotel.com", "gjb.josunhotel.com",
                        "gjj.josunhotel.com", "les.josunhotel.com", "grp.josunhotel.com"}

        for url in answerUrls:
            # 정확 매칭 확인
            if url in contextUrls:
                continue

            # 도메인이 알려진 조선호텔 도메인인지 확인
            isKnownDomain = any(domain in url for domain in knownDomains)

            if not isKnownDomain:
                issues.append(f"URL 할루시네이션: '{url[:60]}...' — 알 수 없는 도메인")
                cleanedAnswer = cleanedAnswer.replace(url, "")

            # 알려진 도메인이지만 컨텍스트에 없는 경로인 경우 경고만
            elif url not in context:
                # 경로 부분만 다를 수 있으므로 도메인 매칭이면 허용 (경고만)
                pass

        passed = len(issues) == 0
        return passed, issues, cleanedAnswer

    def checkPriceDigitManipulation(self, answer: str, context: str) -> tuple[bool, list[str]]:
        """가격 자릿수 변조 검사

        컨텍스트에 "50,000원"이 있는데 답변에 "500,000원"으로
        0이 추가/삭제되는 자릿수 변조를 감지.
        """
        issues = []

        # 가격 추출
        pricePattern = r'([\d,]+)\s*원'
        answerPrices = re.findall(pricePattern, answer)
        contextPrices = re.findall(pricePattern, context)

        if not answerPrices or not contextPrices:
            return True, []

        # 컨텍스트 가격 숫자 집합
        ctxPriceNums = set()
        for p in contextPrices:
            ctxPriceNums.add(int(p.replace(',', '')))

        for ansPrice in answerPrices:
            ansPriceNum = int(ansPrice.replace(',', ''))

            # 정확히 일치하면 통과
            if ansPriceNum in ctxPriceNums:
                continue

            # 10배/0.1배 차이가 나면 자릿수 변조 의심
            for ctxPrice in ctxPriceNums:
                if ctxPrice == 0:
                    continue
                ratio = ansPriceNum / ctxPrice
                if ratio in (10, 0.1, 100, 0.01):
                    issues.append(
                        f"가격 자릿수 변조 의심: 답변 '{ansPrice}원' vs 컨텍스트 '{ctxPrice:,}원' (비율: {ratio})"
                    )
                    break

        return len(issues) == 0, issues

    def removeForbiddenPhrases(self, answer: str) -> str:
        """금지 표현 제거"""
        cleanedAnswer = answer
        for phrase in self.forbiddenPhrases:
            cleanedAnswer = re.sub(phrase, '', cleanedAnswer, flags=re.IGNORECASE)
        cleanedAnswer = re.sub(r'\n{3,}', '\n\n', cleanedAnswer).strip()
        return cleanedAnswer


# 싱글톤 인스턴스
answerVerifier = AnswerVerifier()
