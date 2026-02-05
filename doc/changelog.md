# 개발 진행 내역 (Changelog)

> 마지막 업데이트: 2026-02-05

---

## Phase 8: 컨텍스트 오염 방지 시스템 (2026-02-05)

### 문제 상황

```
[대화 맥락]
User: "조식 시간 알려줘"
Bot: "조식은 07:00~10:30에 운영됩니다."

User: "조금 늦어도 이용 할 수 있어? 한 10분 정도"
Bot: "10:30 이후에는 19세 성인만 입장이 가능합니다..." ← 수영장 정책이 섞임!
```

**근본 원인:**
- `retrieveNode`에서 모든 카테고리 검색 (필터 없음)
- 대화 주제 추적 안 함 → 수영장 정책이 조식 답변에 혼입
- Grounding Gate가 카테고리 교차 오염 미감지

### 해결 방안

#### 1. 대화 주제 추적
- `RAGState`에 `conversation_topic`, `effective_category` 필드 추가
- `_extractConversationTopic()` 함수: 최근 4개 메시지에서 주제 추출

#### 2. 카테고리 기반 검색 필터링
- 후속 질문(히스토리 있음)에서만 카테고리 필터 적용
- 결과 < 2개 시 폴백 (필터 제거 재검색)

#### 3. 카테고리 교차 오염 감지
- `CategoryConsistencyChecker` 클래스 추가
- `EXCLUSIVE_KEYWORDS`: 카테고리별 own/foreign 키워드 정의
- 오염된 문장 자동 제거

#### 4. 답변 검증 강화
- `answerVerifyNode`에 Phase 3.5 추가 (카테고리 오염 검사)

### 수정 파일

| 파일 | 변경 내용 |
|------|----------|
| `rag/graph.py` | RAGState 확장, 주제 추출 함수, retrieveNode 수정, 오염 검사 적용 |
| `rag/grounding.py` | `CategoryConsistencyChecker` 클래스, `verifyCategoryConsistency()` 함수 |
| `tests/test_grounding.py` | 카테고리 오염 감지/정제 테스트 추가 |

### 테스트 결과

- 기존 평가 테스트: **48/48 (100%)** 유지
- Grounding 테스트: **8/8 (100%)** 통과
- 대화 맥락 오염 방지: 정상 동작 확인

---

## Phase 7: 쿼리 검증 강화 (2026-02-04)

### 변경 사항
- `VALID_QUERY_KEYWORDS` 586개로 확장
- 무관한 질문 차단 ("복실이 이쁘니?" 등)
- `EVIDENCE_THRESHOLD`: 0.65

### 결과
- 정확도: **100%** (48/48)

---

## Phase 6: 프롬프트 개선 (2026-02-04)

### 변경 사항
- 불필요한 후속 질문 제거 ("궁금하신가요?" 등 금지)
- Temperature 0.1로 낮춤 (일관된 응답)
- 절대 금지 규칙 명시

---

## Phase 5: 모니터링 시스템 (2026-02-04)

### 추가 파일
- `monitor/dashboard.py`: CLI 대시보드
- `monitor/analyzer.py`: 로그 분석기
- `monitor/collector.py`: 실패 케이스 수집기

---

## Phase 4: 데이터 품질 개선 (2026-02-04)

### 변경 사항
- 주차/위치 정보 보충 (7개 청크 추가)
- 총 361개 청크 인덱싱
- `pipeline/index_supplementary.py` 추가

### 결과
- 정확도: **100%** (48/48)

---

## Phase 3: 답변 검증 노드 (2026-02-04)

### 변경 사항
- 숫자 정보 할루시네이션 감지
- 추측 표현 필터링 ("약", "대략", "아마")
- Grounding Gate 기반 문장 단위 검증

---

## Phase 2: BM25 하이브리드 검색 (2026-02-04)

### 변경 사항
- Vector (70%) + BM25 (30%) 결합
- 한국어 토크나이저 적용
- `pipeline/indexer.py` 수정

---

## Phase 1: 자동 평가 시스템 (2026-02-04)

### 추가 파일
- `tests/evaluate.py`: 자동 평가 스크립트
- `tests/golden_qa.json`: 48개 테스트 케이스

### 초기 정확도
- 91.7% (44/48)

---

## 초기 구축 (2026-02-03 이전)

### 핵심 구성
- 호텔 FAQ 크롤러 (`crawler/`)
- 데이터 정제/청킹 파이프라인 (`pipeline/`)
- LangGraph 기반 RAG 서버 (`rag/`)
- Chroma Vector DB + BM25 하이브리드 검색

### 정책 원칙
- **No Retrieval, No Answer**: 근거 없는 답변 금지
- 출처 URL 필수 포함
- 개인정보 요구 금지
