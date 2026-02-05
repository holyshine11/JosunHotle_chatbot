# 조선호텔 RAG 챗봇 고도화 계획

## 현황 분석

### 현재 구조
```
질문 → 전처리 → 검색(ChromaDB) → 근거검증(0.65) → LLM 답변 → 정책필터 → 응답
```

### 확인된 문제점
| 문제 | 예시 | 원인 |
|------|------|------|
| 동일 질문 다른 답변 | "스위트룸 가격" → 110만원 / 187만원 | LLM 일관성 부족 |
| 정보 누락 | "수영장 운영시간" → 못찾음 | 청크에 정보 분산 |
| 할루시네이션 | "약 30,000원" | LLM 추측 |
| 매뉴얼 테스트 | 문제 발견까지 시간 소요 | 자동 평가 부재 |

---

## 고도화 계획

### Phase 1: 자동 평가 시스템 (필수)
> 수동 테스트 → 자동화된 정확도 측정

#### 1-1. 테스트 데이터셋 구축
```python
# tests/golden_qa.json
[
  {
    "id": "체크인_부산_001",
    "query": "그랜드 조선 부산 체크인 시간",
    "hotel": "grand_josun_busan",
    "expected_keywords": ["15:00", "오후 3시"],  # 하나 이상 포함
    "forbidden_keywords": ["제주", "팰리스"],     # 포함되면 안됨
    "min_score": 0.7
  },
  {
    "id": "조식_레스케이프_001",
    "query": "레스케이프 조식 시간",
    "hotel": "lescape",
    "expected_keywords": ["07:00", "10:30"],
    "forbidden_keywords": []
  },
  // ... 호텔별 20~30개씩, 총 100~150개
]
```

#### 1-2. 평가 스크립트
```python
# tests/evaluate.py
def evaluate():
    results = {
        "accuracy": 0,      # 정답 키워드 포함률
        "hallucination": 0, # 금지 키워드 포함률
        "coverage": 0,      # 답변 생성률 (no_answer 제외)
        "avg_score": 0      # 평균 유사도 점수
    }
```

#### 1-3. 회귀 테스트
- 코드 변경 시 자동 실행
- 성능 저하 감지 → 알림

**예상 효과**: 문제 조기 발견, 개선 효과 수치화

---

### Phase 2: 검색 품질 향상

#### 2-1. 하이브리드 검색 (키워드 + 의미)
현재: 벡터 검색만 사용 → 정확한 키워드 매칭 약함

```python
# 개선안: BM25 + Vector 결합
def search(query):
    bm25_results = bm25_search(query)      # 키워드 매칭
    vector_results = vector_search(query)  # 의미 매칭
    return rerank(bm25_results + vector_results)  # 결합 후 재순위
```

**예상 효과**: "아리아 전화번호" 같은 정확 매칭 질문 성능 ↑

#### 2-2. 쿼리 확장 (Query Expansion)
```python
# 동의어/유사어 확장
query_variants = {
    "조식": ["아침식사", "breakfast", "뷔페"],
    "수영장": ["풀", "pool", "워터"],
    "전화번호": ["연락처", "문의", "예약"]
}
```

**예상 효과**: 다양한 표현으로 질문해도 동일 결과

#### 2-3. 청크 재구성
현재: 페이지 단위로 청크 분할
개선: 정보 유형별 청크 (가격, 운영시간, 위치 등)

```python
# 구조화된 청크 예시
{
    "type": "operating_hours",
    "facility": "수영장",
    "hotel": "grand_josun_busan",
    "hours": "08:00 - 21:00",
    "notes": "하절기 연장 운영"
}
```

**예상 효과**: 운영시간, 가격 등 정확한 정보 검색 ↑

---

### Phase 3: 답변 품질 향상

#### 3-1. 답변 검증 (Self-Verification)
```python
def verify_answer(answer, context):
    """답변이 컨텍스트에 근거하는지 검증"""
    # 가격, 시간 등 숫자 정보가 컨텍스트에 있는지 확인
    numbers_in_answer = extract_numbers(answer)
    numbers_in_context = extract_numbers(context)

    if not numbers_in_answer.issubset(numbers_in_context):
        return False, "할루시네이션 의심"
    return True, "검증 통과"
```

**예상 효과**: 할루시네이션 사전 차단

#### 3-2. 답변 템플릿
```python
# 질문 유형별 고정 템플릿
TEMPLATES = {
    "operating_hours": "{hotel} {facility} 운영시간은 {hours}입니다.",
    "price": "{hotel} {item} 가격은 {price}입니다.",
    "contact": "{hotel} 문의: {phone}"
}
```

**예상 효과**: 일관된 답변 형식, LLM 변동성 감소

#### 3-3. 컨텍스트 압축
```python
def compress_context(chunks, query):
    """질문과 관련된 문장만 추출"""
    relevant_sentences = []
    for chunk in chunks:
        for sentence in chunk.split('.'):
            if is_relevant(sentence, query):
                relevant_sentences.append(sentence)
    return relevant_sentences
```

**예상 효과**: LLM 입력 노이즈 감소, 정확도 ↑

---

### Phase 4: 데이터 품질 개선

#### 4-1. 메타데이터 강화
```python
# 현재
{"hotel": "grand_josun_busan", "section": "facilities"}

# 개선
{
    "hotel": "grand_josun_busan",
    "section": "facilities",
    "facility_type": "pool",        # 시설 유형
    "info_type": "operating_hours", # 정보 유형
    "keywords": ["수영장", "풀", "pool", "운영시간"]
}
```

#### 4-2. 정형 데이터 추출
크롤링 시 HTML 테이블/리스트에서 구조화된 데이터 추출

```python
# 운영시간 테이블 파싱 예시
operating_hours = {
    "facility": "아리아",
    "breakfast": "07:00-10:00",
    "lunch": "12:00-14:30",
    "dinner": "18:00-21:30"
}
```

---

### Phase 5: 모니터링 및 피드백

#### 5-1. 답변 품질 대시보드
```
일별 통계:
- 총 질문 수: 147
- 답변 성공률: 89%
- 평균 유사도: 0.76
- 호텔별 분포: 부산(35%), 제주(25%), ...
```

#### 5-2. 실패 케이스 자동 수집
```python
# evidence_passed=False 케이스 자동 수집
failed_queries = [
    {"query": "조식 시간", "score": 0.63, "reason": "threshold 미달"}
]
```

#### 5-3. 사용자 피드백 (선택)
```
답변이 도움이 되셨나요? [예] [아니오]
```

---

## 구현 우선순위

| 순위 | 항목 | 난이도 | 영향도 | 비고 |
|:---:|------|:---:|:---:|------|
| 1 | 테스트 데이터셋 구축 | 중 | 상 | 모든 개선의 기준점 |
| 2 | 평가 스크립트 | 중 | 상 | 자동화된 품질 측정 |
| 3 | 답변 검증 로직 | 중 | 상 | 할루시네이션 방지 |
| 4 | 하이브리드 검색 | 상 | 상 | 검색 정확도 향상 |
| 5 | 청크 재구성 | 상 | 중 | 재크롤링 필요 |
| 6 | 쿼리 확장 | 하 | 중 | 동의어 사전 구축 |
| 7 | 답변 템플릿 | 하 | 중 | 일관성 향상 |
| 8 | 모니터링 대시보드 | 중 | 하 | 운영 편의성 |

---

## 승인 요청 항목

아래 항목 중 진행할 것을 선택해주세요:

- [ ] **Phase 1**: 자동 평가 시스템 (테스트셋 + 평가 스크립트)
- [ ] **Phase 2**: 검색 품질 향상 (하이브리드 검색, 쿼리 확장)
- [ ] **Phase 3**: 답변 품질 향상 (검증 로직, 템플릿)
- [ ] **Phase 4**: 데이터 품질 개선 (메타데이터, 정형 데이터)
- [ ] **Phase 5**: 모니터링 시스템

**권장**: Phase 1 → Phase 3 → Phase 2 순서로 진행
(평가 기준 확립 → 즉각적 품질 향상 → 근본적 검색 개선)

---

## 예상 일정

- Phase 1: 테스트셋 100개 + 평가 스크립트
- Phase 2: 하이브리드 검색 구현
- Phase 3: 답변 검증 및 템플릿

*구체적 시간 추정은 실제 구현 시 확인*

---

## 성공 지표

| 지표 | 현재 (추정) | 목표 |
|------|------------|------|
| 정답률 | 70% | 90%+ |
| 할루시네이션 | 발생 | 0% |
| 답변 일관성 | 낮음 | 동일 질문 = 동일 답변 |
| 커버리지 | 85% | 95%+ |
