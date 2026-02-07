# 의도 파악 개선 계획 (Intent Understanding Enhancement)

> Phase 12: 모호한 질문의 의도 파악 개선

---

## 문제 정의

### 현상
```
입력: "강아지 대려갈게"
기대: 반려동물 정책 안내
실제: "어떤 시설의 위치를 알고 싶으신가요?" + [위치 옵션]
```

### 근본 원인

1. **키워드 누락**: `specificTargets`에 반려동물 관련 키워드 없음
2. **의미 분석 부재**: "대려갈게" = "데려가도 돼?" 의도 추론 불가
3. **맥락 무시**: 명사(강아지) + 동사(대려갈게) 조합 분석 안함
4. **오분류**: 위치 관련 없는 질문을 위치로 분류

---

## 분석

### 현재 흐름 (graph.py)

```
queryRewrite → preprocess → clarificationCheck → retrieve → ...
                              ↓
                    AMBIGUOUS_PATTERNS 매칭
                              ↓
                    "위치" 키워드 없어도 매칭?
                              ↓
                    잘못된 명확화 질문 출력
```

### 키워드 분석

| 현재 있음 | 필요함 (누락) |
|-----------|---------------|
| 조식, 수영장, 스파 | 강아지, 반려견, 반려동물, 펫 |
| 체크인, 체크아웃 | 데려가, 대려가, 동반, 입장 |
| 레스토랑, 다이닝 | 허용, 가능, 출입 |

### 의도 분류 필요

| 패턴 | 의도 | 올바른 응답 |
|------|------|-------------|
| 강아지 대려갈게 | 반려동물 정책 질문 | 반려동물 정책 안내 |
| 강아지 어디 | 반려동물 정책 질문 | 반려동물 정책 안내 |
| 수영장 어디 | 위치 질문 | 수영장 위치 안내 |
| 어디있어 (단독) | 모호 | 명확화 필요 |

---

## 해결 방안

### 방안 1: specificTargets 확장 (Quick Fix)

**변경**: `clarificationCheckNode`의 `specificTargets`에 반려동물 키워드 추가

```python
specificTargets = [
    # ... 기존 ...
    # 반려동물 (추가)
    "강아지", "반려견", "반려동물", "펫", "pet", "dog", "애견",
    "고양이", "고냥이", "cat",
    "데려", "대려", "동반",  # 동사 패턴
]
```

**장점**: 즉시 적용 가능, 코드 변경 최소
**단점**: 모든 패턴 열거 필요, 확장성 한계

### 방안 2: 의도 기반 사전 매칭 (Intent Pattern)

**변경**: 명사+동사 조합 패턴으로 의도 우선 분류

```python
INTENT_PATTERNS = {
    "반려동물": {
        "nouns": ["강아지", "반려견", "펫", "고양이", "반려동물"],
        "verbs": ["대려", "데려", "동반", "입장", "가능", "허용"],
        "category": "반려동물",
        "direct_answer": True,  # 명확화 불필요
    },
    "예약": {
        "nouns": ["방", "객실", "룸"],
        "verbs": ["예약", "잡", "취소"],
        "category": "예약",
        "direct_answer": True,
    },
}
```

**장점**: 의미 기반 분류, 확장 용이
**단점**: 새 로직 필요, 테스트 필요

### 방안 3: LLM 의도 분류 (Advanced)

**변경**: 모호한 질문에 LLM으로 의도 분류 후 처리

```python
# clarificationCheckNode에서 모호할 때:
if isAmbiguous:
    intent = llm.classify_intent(query)
    if intent.confidence > 0.8:
        # 직접 검색으로 진행
        return proceed_with_intent(intent)
    else:
        # 명확화 질문
        return ask_clarification()
```

**장점**: 자연어 이해력 최고
**단점**: 지연 증가, 비용 증가, 로컬 LLM 품질 한계

---

## 권장 방안

**1단계 (즉시)**: 방안 1 적용 - specificTargets 확장
**2단계 (향후)**: 방안 2 적용 - INTENT_PATTERNS 시스템 구축

---

## 구현 계획

### 1단계: specificTargets 확장

```python
# graph.py:668-685 수정
specificTargets = [
    # 체크인/아웃
    "체크인", "체크아웃", ...

    # 반려동물 (신규)
    "강아지", "반려견", "반려동물", "펫", "pet", "dog", "애견",
    "고양이", "고냥이", "cat",
    "데려", "대려", "동반", "입장가능", "출입",

    # ... 기존 유지 ...
]
```

### 2단계: AMBIGUOUS_PATTERNS 보완

```python
# "위치" 패턴에 excludes 추가
"위치": {
    "keywords": ["위치", "어디", "어딨"],
    "excludes": [
        "호텔 위치", "호텔 어디", "찾아가", "오시는",
        "강아지", "반려", "펫",  # 반려동물 맥락 제외
    ],
    ...
}
```

### 3단계: 테스트 케이스 추가

```json
{
  "id": "pet_ambiguous_001",
  "query": "강아지 대려갈게",
  "expected_keywords": ["반려", "동반", "가능", "불가"],
  "forbidden_keywords": ["위치", "어디"]
}
```

---

## 검증 방법

```bash
# 1. 코드 수정 후 서버 재시작
python rag/server.py

# 2. 테스트 질문
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "강아지 대려갈게", "hotel": "grand_josun_busan"}'

# 3. 기대 결과: 반려동물 정책 안내 (위치 질문 아님)

# 4. 전체 평가
python tests/evaluate.py
```

---

## 예상 효과

| 항목 | Before | After |
|------|--------|-------|
| "강아지 대려갈게" | 위치 명확화 질문 | 반려동물 정책 안내 |
| "펫 데려가도 돼?" | 알 수 없음 | 반려동물 정책 안내 |
| 사용자 만족도 | 낮음 (재질문 필요) | 높음 (바로 답변) |

---

## 일정

| 단계 | 작업 | 소요 |
|------|------|------|
| 1 | specificTargets 확장 | 5분 |
| 2 | AMBIGUOUS_PATTERNS excludes 추가 | 5분 |
| 3 | 테스트 케이스 추가 | 10분 |
| 4 | 통합 테스트 | 10분 |
| **합계** | | **30분** |

---

## 파일 변경 목록

| 파일 | 변경 내용 |
|------|----------|
| `rag/graph.py` | specificTargets 확장, AMBIGUOUS_PATTERNS excludes 추가 |
| `tests/golden_qa.json` | 모호한 반려동물 질문 테스트 추가 |
