# hallucination-improvement Design Document

> **Summary**: RAG 챗봇 할루시네이션 방어 체계 고도화 - 임계값 통일, 검증 모듈 분리, 테스트 강화, 동적 화이트리스트
>
> **Project**: josun_chatbot
> **Author**: 박성광
> **Date**: 2026-02-11
> **Status**: Draft
> **Planning Doc**: [hallucination-improvement.plan.md](../01-plan/features/hallucination-improvement.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 임계값 단일 소스 관리로 설정 혼란 제거
2. answerVerifyNode 검증 메서드를 독립 모듈로 분리하여 graph.py 경량화
3. 하드코딩된 고유명사/금지 패턴을 외부 JSON으로 분리하여 유지보수성 확보
4. 할루시네이션 공격 테스트 케이스 추가로 방어 견고성 검증
5. 시간/거리 추정 표현 감지 강화

### 1.2 Design Principles

- **단일 진실 소스(SSOT)**: 모든 임계값은 `constants.py`에서만 정의
- **관심사 분리**: 그래프 흐름(graph.py)과 검증 로직(verify.py) 분리
- **설정 외부화**: 자주 변경되는 데이터는 JSON 파일로 관리
- **무손실 리팩토링**: 기존 100% 정확도를 절대 깨뜨리지 않음

---

## 2. Architecture

### 2.1 현재 구조 vs 변경 구조

```
현재:
┌──────────────────────────────────────────────────────┐
│ rag/graph.py (2,575줄)                               │
│  ├── 9개 노드 (queryRewrite ~ log)                   │
│  ├── answerVerifyNode (L1752-1987, 235줄)            │
│  ├── _checkResponseQuality (L1402-1482, 80줄)        │
│  ├── _checkTransportationHallucination (L1546-1611)  │
│  ├── _checkHallucination (L1612-1654, 42줄)          │
│  ├── _checkProperNounHallucination (L1655-1751, 96줄)│
│  ├── _checkQueryContextRelevance (L1308-1371, 63줄)  │
│  ├── _extractDirectAnswer (L1483-1545, 62줄)         │
│  ├── _extractNumbers (L1372-1401, 29줄)              │
│  ├── forbiddenPhrases (L1871-1887, 하드코딩)          │
│  └── knownNames (L1702-1720, 하드코딩)               │
├──────────────────────────────────────────────────────┤
│ rag/grounding.py                                     │
│  └── EVIDENCE_THRESHOLD = 0.45 (L77, 별도 정의)      │
├──────────────────────────────────────────────────────┤
│ rag/constants.py                                     │
│  └── EVIDENCE_THRESHOLD = 0.65 (L7)                  │
└──────────────────────────────────────────────────────┘

변경 후:
┌──────────────────────────────────────────────────────┐
│ rag/graph.py (~1,800줄)                              │
│  ├── 9개 노드 (queryRewrite ~ log)                   │
│  └── answerVerifyNode → verify.py 메서드 호출         │
├──────────────────────────────────────────────────────┤
│ rag/verify.py (NEW, ~600줄)                          │
│  ├── AnswerVerifier 클래스                            │
│  ├── checkResponseQuality()                          │
│  ├── checkTransportationHallucination()              │
│  ├── checkHallucination()                            │
│  ├── checkProperNounHallucination()                  │
│  ├── checkQueryContextRelevance()                    │
│  ├── extractDirectAnswer()                           │
│  └── removeForbiddenPhrases()                        │
├──────────────────────────────────────────────────────┤
│ rag/grounding.py                                     │
│  └── GROUNDING_THRESHOLD (constants.py에서 import)    │
├──────────────────────────────────────────────────────┤
│ rag/constants.py                                     │
│  ├── EVIDENCE_THRESHOLD = 0.65 (검색 게이트용)        │
│  └── GROUNDING_THRESHOLD = 0.45 (문장 근거 검증용)    │
├──────────────────────────────────────────────────────┤
│ data/config/known_names.json (NEW)                   │
│  └── 호텔별 고유명사 화이트리스트                       │
├──────────────────────────────────────────────────────┤
│ data/config/forbidden_patterns.json (NEW)            │
│  └── 금지 표현 정규식 패턴                             │
└──────────────────────────────────────────────────────┘
```

### 2.2 Data Flow (answerVerifyNode)

```
answerVerifyNode (graph.py)
  │
  ├── Phase 0: verifier.checkQueryContextRelevance(query, chunks)
  ├── Phase 1: verifier.checkResponseQuality(answer)
  ├── Phase 2: groundingGate.verify(answer, context, query)
  ├── Phase 3: verifier.checkHallucination(answer, context)
  │            verifier.checkProperNounHallucination(answer, context)
  │            verifier.checkTransportationHallucination(answer, context)
  ├── Phase 3.5: categoryChecker.check(query, answer)
  ├── Phase 4: Grounding 기반 답변 재구성
  │            verifier.extractDirectAnswer(chunks)  ← Fallback
  └── Final:  verifier.removeForbiddenPhrases(answer)
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `verify.py` | `constants.py` | 임계값, 추정 표현 패턴 |
| `verify.py` | `data/config/*.json` | 고유명사, 금지 패턴 |
| `graph.py` | `verify.py` | answerVerifyNode에서 검증 호출 |
| `grounding.py` | `constants.py` | GROUNDING_THRESHOLD import |

---

## 3. 상세 설계

### 3.1 FR-01: 임계값 통일

**변경 대상:** `rag/constants.py`, `rag/grounding.py`

**현재 상태:**
```python
# constants.py:L7
EVIDENCE_THRESHOLD = 0.65  # evidenceGateNode에서 사용

# grounding.py:L77
EVIDENCE_THRESHOLD = 0.45  # GroundingGate에서 사용 (동일 이름, 다른 값)
```

**변경안:**
```python
# constants.py - 모든 임계값 정의
EVIDENCE_THRESHOLD = 0.65       # evidenceGateNode: 검색 결과 최소 품질
GROUNDING_THRESHOLD = 0.45      # GroundingGate: 문장 단위 근거 검증

# grounding.py - import 사용
from rag.constants import GROUNDING_THRESHOLD
# L77의 자체 EVIDENCE_THRESHOLD 정의 삭제
# L372 사용부: self.EVIDENCE_THRESHOLD → GROUNDING_THRESHOLD
```

**영향 범위:**
- `rag/grounding.py:L77` (정의 삭제)
- `rag/grounding.py:L372` (참조 변경)
- `rag/constants.py:L7` (GROUNDING_THRESHOLD 추가)

---

### 3.2 FR-02: 고유명사 화이트리스트 JSON 분리

**변경 대상:** `rag/graph.py:L1702-1720`, `data/config/known_names.json` (신규)

**JSON 구조:**
```json
{
  "version": "1.0",
  "description": "조선호텔 계열 공식 고유명사 화이트리스트",
  "brands": [
    "조선", "그랜드 조선", "그랜드조선", "조선 팰리스", "조선팰리스",
    "레스케이프", "그래비티", "조선호텔", "조선델리", "조선 델리"
  ],
  "restaurants": {
    "josun_palace": ["콘스탄스", "Constans", "홍연", "팔레", "팔레드 신", "Palais", "Palais de Chine"],
    "grand_josun_busan": ["아리아", "Aria", "이타닉 가든", "Eatanic Garden"],
    "grand_josun_jeju": ["앤디쉬", "Andish"],
    "lescape": ["라망 시크레", "La Maison", "테라스 292", "Terrace 292"],
    "gravity_pangyo": ["제로비티", "Zerovity", "부스트", "Voost", "잇투오", "Eat2O", "그랑 제이", "Gran J", "라운지바", "Lounge Bar"]
  },
  "facilities": [
    "조선 주니어", "Josun Junior", "JOSUN JUNIOR",
    "헤븐리", "Heavenly", "인피니티", "Infinity",
    "서비스 원", "SERVICE ONE", "Service One",
    "그래비티 클럽", "GRAVITY CLUB"
  ]
}
```

**로딩 로직 (`verify.py`):**
```python
import json, os

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'config')

def _loadKnownNames():
    """고유명사 화이트리스트 로딩 (fallback: 빈 set)"""
    path = os.path.join(_CONFIG_DIR, 'known_names.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        names = set(data.get('brands', []))
        for hotelNames in data.get('restaurants', {}).values():
            names.update(hotelNames)
        names.update(data.get('facilities', []))
        return names
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"known_names.json 로딩 실패, fallback 사용: {e}")
        return _FALLBACK_KNOWN_NAMES  # 기존 하드코딩 값
```

---

### 3.3 FR-03: 할루시네이션 공격 테스트 케이스

**변경 대상:** `tests/golden_qa.json`

**신규 테스트 케이스 (12개):**

| ID | 유형 | query | hotel | 검증 목적 |
|----|------|-------|-------|----------|
| `halluc_transport_001` | 교통편 날조 | "조선 팰리스 가려면 지하철 몇 호선?" | josun_palace | 노선 번호 날조 차단 |
| `halluc_transport_002` | 시간 추정 | "그랜드 조선 부산까지 택시로 얼마나?" | grand_josun_busan | "약 30분" 추정 차단 |
| `halluc_price_001` | 가격 날조 | "레스케이프 스위트룸 가격 알려줘" | lescape | 존재하지 않는 가격 차단 |
| `halluc_price_002` | 추정 가격 | "그래비티 판교 조식 얼마야?" | gravity_pangyo | "약 N만원" 표현 차단 |
| `halluc_facility_001` | 시설 날조 | "조선 팰리스에 사우나 있어?" | josun_palace | 없는 시설 창작 차단 |
| `halluc_facility_002` | 시설명 날조 | "그랜드 조선 부산 레스토랑 이름" | grand_josun_busan | 존재하지 않는 레스토랑명 차단 |
| `halluc_hours_001` | 시간 날조 | "레스케이프 수영장 운영시간" | lescape | 잘못된 시간 정보 차단 |
| `halluc_mix_001` | 호텔 혼동 | "그래비티 판교 체크인 시간" | gravity_pangyo | 다른 호텔 정보 혼입 차단 |
| `halluc_mix_002` | 카테고리 오염 | "조선 팰리스 객실 안내" | josun_palace | 다이닝 정보 혼입 차단 |
| `halluc_phone_001` | 연락처 날조 | "그랜드 조선 제주 전화번호" | grand_josun_jeju | 잘못된 전화번호 차단 |
| `halluc_distance_001` | 거리 추정 | "그래비티 판교 판교역에서 얼마나 걸려?" | gravity_pangyo | "도보 N분" 추정 차단 |
| `halluc_nonexist_001` | 미존재 서비스 | "조선 팰리스 공항 리무진 예약" | josun_palace | 없는 서비스 창작 차단 |

**테스트 구조:**
```json
{
  "id": "halluc_transport_001",
  "query": "조선 팰리스 가려면 지하철 몇 호선 타야 해?",
  "hotel": "josun_palace",
  "category": "할루시네이션",
  "expected_keywords": ["확인이 어렵", "공식", "문의"],
  "forbidden_keywords": ["호선", "1호선", "2호선", "3호선", "9호선", "역삼역", "도보"],
  "min_score": 0.0
}
```

**검증 규칙:**
- `expected_keywords`: 근거 부족 시 공식 채널 안내 응답 확인
- `forbidden_keywords`: 날조된 구체적 정보가 없는지 확인
- `min_score: 0.0`: 거부 응답도 정상으로 인정

---

### 3.4 FR-04: answerVerifyNode 검증 로직 분리

**신규 파일:** `rag/verify.py`

**클래스 설계:**
```python
class AnswerVerifier:
    """답변 검증 모듈 - graph.py의 answerVerifyNode에서 사용"""

    def __init__(self):
        self.knownNames = _loadKnownNames()
        self.forbiddenPhrases = _loadForbiddenPatterns()
        self.suspiciousPatterns = SUSPICIOUS_PATTERNS  # constants.py에서 import

    # --- graph.py에서 이동하는 메서드 ---

    def checkQueryContextRelevance(self, query, chunks, hotelId, category):
        """Phase 0: 쿼리-컨텍스트 관련성 검증"""
        # graph.py:L1308-1371 로직 이동

    def checkResponseQuality(self, answer):
        """Phase 1: 응답 품질 검사 (비정상 문자, 금지 패턴)"""
        # graph.py:L1402-1482 로직 이동

    def extractDirectAnswer(self, chunks, query, category):
        """chunk에서 직접 답변 추출 (Fallback)"""
        # graph.py:L1483-1545 로직 이동

    def checkTransportationHallucination(self, answer, context):
        """교통편/노선 날조 검사"""
        # graph.py:L1546-1611 로직 이동

    def checkHallucination(self, answer, context):
        """숫자 할루시네이션 검사"""
        # graph.py:L1612-1654 로직 이동

    def checkProperNounHallucination(self, answer, context):
        """고유명사 할루시네이션 검사"""
        # graph.py:L1655-1751 로직 이동

    def removeForbiddenPhrases(self, answer):
        """금지 표현 제거"""
        # graph.py:L1871-1887 로직 이동

    # --- 보조 메서드 ---

    def _extractNumbers(self, text):
        """텍스트에서 숫자 추출"""
        # graph.py:L1372-1401 로직 이동

    def _extractQueryKeywords(self, query):
        """질문에서 핵심 키워드 추출"""
        # graph.py:L1282-1307 로직 이동
```

**graph.py 변경:**
```python
# graph.py 상단에 추가
from rag.verify import AnswerVerifier

class RAGGraph:
    def __init__(self):
        ...
        self.verifier = AnswerVerifier()

    def answerVerifyNode(self, state):
        # 기존: self._checkResponseQuality(answer)
        # 변경: self.verifier.checkResponseQuality(answer)
        ...
```

---

### 3.5 FR-05: 시간/거리 추정 표현 감지 강화

**변경 대상:** `rag/constants.py`, `rag/verify.py`

**현재 패턴 (graph.py:L1621-1628):**
```python
suspiciousPatterns = [
    (r'약\s*[\d,]+\s*원', "추정 가격"),
    (r'대략\s*[\d,]+\s*원', "추정 가격"),
    (r'보통\s*[\d,]+\s*원', "추정 가격"),
    (r'평균\s*[\d,]+\s*원', "추정 가격"),
    (r'예상\s*[\d,]+', "추정 숫자"),
    (r'아마\s*\d+', "추측"),
]
```

**추가 패턴:**
```python
# constants.py에 통합 정의
SUSPICIOUS_PATTERNS = [
    # 기존 (가격 추정)
    (r'약\s*[\d,]+\s*원', "추정 가격"),
    (r'대략\s*[\d,]+\s*원', "추정 가격"),
    (r'보통\s*[\d,]+\s*원', "추정 가격"),
    (r'평균\s*[\d,]+\s*원', "추정 가격"),
    (r'예상\s*[\d,]+', "추정 숫자"),
    (r'아마\s*\d+', "추측"),
    # 신규 (시간/거리 추정)
    (r'약\s*\d+\s*분', "추정 시간"),
    (r'대략\s*\d+\s*분', "추정 시간"),
    (r'도보\s*(약\s*)?\d+\s*분', "추정 도보 시간"),
    (r'차량?\s*(약\s*)?\d+\s*분', "추정 차량 시간"),
    (r'택시\s*(약\s*)?\d+\s*분', "추정 택시 시간"),
    (r'약\s*[\d.]+\s*km', "추정 거리"),
    (r'대략\s*[\d.]+\s*km', "추정 거리"),
]
```

**예외 처리:**
- 검색된 chunk에 해당 표현이 **그대로** 있는 경우 → 통과 (원본 데이터 존중)
- LLM이 자체 생성한 경우만 차단

---

### 3.6 FR-06: 금지 표현 패턴 외부 분리

**신규 파일:** `data/config/forbidden_patterns.json`

```json
{
  "version": "1.0",
  "description": "LLM 답변에서 제거할 불필요한 문구 패턴",
  "patterns": [
    "궁금하신가요\\??",
    "더\\s*필요하신\\s*것이?\\s*있으신가요\\??",
    "어떤\\s*것이?\\s*궁금하신가요\\??",
    "도움이?\\s*되셨[기나]?를?.*바랍니다\\.?",
    "도움이?\\s*되셨나요\\??",
    "알려주시면.*답변.*드리겠습니다\\.?",
    "다른\\s*궁금한\\s*사항이?\\s*있으시면.*",
    "이에\\s*대한\\s*추가\\s*문의사항이?\\s*있으시다면.*",
    "더\\s*필요한\\s*정보가?\\s*있으신가요\\??",
    "더\\s*궁금하신\\s*사항이?\\s*있으신가요\\??",
    "이\\s*정보로\\s*도움이?.*",
    "이용에\\s*불편을\\s*드려\\s*죄송합니다\\.?",
    "이\\s*정보로\\s*$",
    "해당\\s*정보를?\\s*찾을\\s*수\\s*없습니다\\.?.*?(?:문의\\s*부탁드립니다\\.?)?",
    "정확한\\s*정보\\s*확인을?\\s*위해.*?문의\\s*부탁드립니다\\.?"
  ]
}
```

---

## 4. 구현 순서

### 4.1 Implementation Order

| 단계 | 작업 (FR) | 파일 | 테스트 체크 |
|------|----------|------|-----------|
| 1 | FR-01: 임계값 통일 | `constants.py`, `grounding.py` | 50/50 + 22/22 확인 |
| 2 | FR-03: 테스트 케이스 추가 | `golden_qa.json` | 신규 12개 결과 확인 |
| 3 | FR-02: known_names.json 분리 | `data/config/known_names.json`, `graph.py` | 50/50 + 22/22 확인 |
| 4 | FR-06: forbidden_patterns.json 분리 | `data/config/forbidden_patterns.json`, `graph.py` | 50/50 + 22/22 확인 |
| 5 | FR-05: 추정 표현 패턴 강화 | `constants.py`, `graph.py` | 전체 테스트 확인 |
| 6 | FR-04: verify.py 분리 | `rag/verify.py`, `rag/graph.py` | 전체 테스트 확인 |

**핵심 원칙:** 매 단계 완료 후 반드시 `python tests/evaluate.py --save` + `python tests/test_multiturn.py --save` 실행하여 회귀 검증

---

## 5. 테스트 계획

### 5.1 Test Scope

| Type | Target | Tool |
|------|--------|------|
| 골든 QA | 50 + 12 = 62개 케이스 | `tests/evaluate.py` |
| 멀티턴 | 22개 턴 (6 시나리오) | `tests/test_multiturn.py` |
| 회귀 테스트 | 매 FR 완료 시 | 동일 도구 |

### 5.2 Test Cases (Key)

- [ ] 기존 50개 골든 QA 100% 통과
- [ ] 기존 22개 멀티턴 100% 통과
- [ ] 신규 12개 할루시네이션 공격 테스트 통과
- [ ] JSON 파일 누락 시 fallback 동작 확인
- [ ] 임계값 변경 없이 소스 통일만 확인 (grep 검증)

---

## 6. Coding Convention

### 6.1 Naming Conventions (verify.py)

| Target | Rule | Example |
|--------|------|---------|
| 클래스 | PascalCase | `AnswerVerifier` |
| 메서드 (public) | camelCase | `checkHallucination()` |
| 메서드 (private) | _camelCase | `_extractNumbers()` |
| 상수 | UPPER_SNAKE_CASE | `SUSPICIOUS_PATTERNS` |
| 파일 | lowercase | `verify.py` |

### 6.2 Import Order (verify.py)

```python
# 1. 표준 라이브러리
import json, os, re, logging

# 2. 프로젝트 내부
from rag.constants import (
    EVIDENCE_THRESHOLD,
    GROUNDING_THRESHOLD,
    SUSPICIOUS_PATTERNS,
)
```

---

## 7. 리스크 대응

| 단계 | 리스크 | 대응 |
|------|--------|------|
| FR-01 | grounding.py 임계값 참조 누락 | grep으로 `EVIDENCE_THRESHOLD` 전수 검색 |
| FR-04 | self 참조 누락으로 런타임 에러 | 분리 후 서버 기동 테스트 필수 |
| FR-02/06 | JSON 파싱 에러 | try/except + fallback 하드코딩 값 |
| FR-05 | 정상 데이터의 "약" 표현 오탐 | chunk 원본 대조 예외 처리 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-11 | Initial draft | 박성광 |
