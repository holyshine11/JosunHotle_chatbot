# 조선호텔 RAG 챗봇 — 종합 PM 감사 보고서

> 작성일: 2026-02-07
> 작성자: PM (20년차 챗봇 전문 개발 PM 시뮬레이션)
> 대상: josun_chatbot v1.0 (Phase 1~14 구현 완료)

---

## 1. 목표 / 성공 기준

| 구분 | 기준 |
|------|------|
| **정확도** | Golden QA 테스트 50/50 (100%) |
| **안정성** | 연속 6턴 대화에서 맥락 유실 0건, 서버 장애율 < 0.1% |
| **운영성** | 장애 발생 시 5분 이내 감지, 로그 기반 원인 추적 가능 |
| **UX** | 모호한 질문에 주체 인식 명확화, 1턴 이내 올바른 답변 도달률 > 90% |
| **보안** | OWASP Top 10 취약점 0건, API 키 노출 0건 |

---

## 2. As-Is 요약

### 2.1 시스템 현황

| 항목 | 현재 상태 |
|------|-----------|
| **코드 규모** | `graph.py` 2,064줄 (God Object), 총 6개 Python 모듈 |
| **정확도** | 96% (48/50) — 2건 실패 |
| **데이터** | 5개 호텔, ~557 청크, 보충 14 청크 |
| **LLM** | qwen2.5:7b (로컬 Ollama), 응답 3~8초 |
| **검색** | Vector(70%) + BM25(30%) 하이브리드, Cross-Encoder 리랭커 |
| **세션** | 인메모리 (재시작 시 소멸), 최대 1,000개, TTL 30분 |
| **모니터링** | CLI 전용 대시보드, JSONL 로그 (4일치 2.4MB) |
| **배포** | 단일 프로세스 (uvicorn), CORS 완전 개방 |
| **테스트** | 50개 Golden QA, 멀티턴 시나리오 테스트 없음 (수동 스크립트) |
| **UI** | 단일 HTML + inline JS, Tailwind CDN, 다크모드 지원 |

### 2.2 아키텍처 개요

```
User → FastAPI(server.py) → RAGGraph(graph.py)
         ↓                      ↓
    SessionStore(session.py)   LangGraph Pipeline
         ↓                      ↓
    ConversationContext    preprocessNode → queryRewriteNode
                               ↓
                         clarificationCheckNode
                               ↓
                         retrieveNode (Chroma + BM25)
                               ↓
                         evidenceGateNode
                               ↓
                         answerComposeNode (Ollama qwen2.5:7b)
                               ↓
                         answerVerifyNode → policyFilterNode → logNode
```

---

## 3. 주요 문제 Top 12

### 3.1 Critical (운영 불가 수준)

| # | 문제 | 영향도 | 현재 상태 |
|---|------|--------|-----------|
| **C1** | **CORS 완전 개방** (`allow_origins=["*"]`) | 보안: 아무 도메인에서 API 호출 가능 | server.py:33 |
| **C2** | **예외 처리에서 내부 에러 노출** (`detail=str(e)`) | 보안: 스택 트레이스/내부 경로 유출 | server.py:105 |
| **C3** | **LLM 호출 timeout 없음** | 안정성: Ollama 무응답 시 무한 대기 → 서버 hang | llm_provider.py:42 |
| **C4** | **인메모리 세션** (서버 재시작 시 전체 유실) | 안정성: 배포/재시작마다 모든 대화 컨텍스트 소멸 | session.py |

### 3.2 High (품질/운영 저하)

| # | 문제 | 영향도 | 현재 상태 |
|---|------|--------|-----------|
| **H1** | **graph.py God Object** (2,064줄) | 유지보수: 단일 파일에 전체 비즈니스 로직 | rag/graph.py |
| **H2** | **멀티턴 테스트 자동화 부재** | 품질: 6턴 대화 회귀 수동 검증만 가능 | 스크래치패드 수동 스크립트 |
| **H3** | **로그 로테이션/아카이빙 없음** | 운영: 로그 파일 무한 증가 (현재 4일 2.4MB) | data/logs/ |
| **H4** | **서버 상태 확인 불가** (`/health`만 존재) | 운영: LLM/Chroma/세션 상태 모름 | server.py:70 |
| **H5** | **LLM fallback/retry 없음** | 안정성: Ollama 장애 시 즉시 500 에러 | llm_provider.py |

### 3.3 Medium (개선 필요)

| # | 문제 | 영향도 | 현재 상태 |
|---|------|--------|-----------|
| **M1** | **2건 실패 테스트 미해결** | 품질: 96% → 100% 미달성 | golden_qa.json 중 2건 |
| **M2** | **UI JS 모듈화 없음** | 유지보수: index.html에 인라인 JS (500줄+) | ui/index.html |
| **M3** | **크롤러 자동화/스케줄링 없음** | 데이터: 수동 크롤링, 데이터 신선도 보장 불가 | crawler/ |

---

## 4. 개선안 (Quick Win / Mid / Long)

### 4.1 Quick Win (1~2일, 즉시 적용 가능)

| # | 개선 | 대상 | 예상 효과 |
|---|------|------|-----------|
| **QW1** | CORS 도메인 제한 | server.py | 보안 취약점 즉시 제거 |
| **QW2** | 에러 응답 일반화 | server.py | 내부 정보 유출 차단 |
| **QW3** | LLM timeout 추가 (30초) | llm_provider.py | 서버 hang 방지 |
| **QW4** | `/health` 확장 (LLM/Chroma 상태) | server.py | 장애 즉시 감지 가능 |
| **QW5** | 서버 재시작 알림 | server.py → 로그 | Phase 14 반영 확인 |

**QW1 구현 예시:**
```python
# server.py — CORS 도메인 제한
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

**QW3 구현 예시:**
```python
# llm_provider.py — timeout + retry
response = ollama.chat(
    model="qwen2.5:7b",
    messages=messages,
    options={"temperature": temperature, "num_predict": 1024},
)
# ollama 자체 timeout이 없으므로 signal 또는 concurrent.futures 사용
```

### 4.2 Mid-term (1~2주)

| # | 개선 | 대상 | 예상 효과 |
|---|------|------|-----------|
| **MT1** | graph.py 모듈 분리 | rag/ | 유지보수성 3배 향상 |
| **MT2** | 멀티턴 테스트 자동화 | tests/ | 회귀 테스트 커버리지 2배 |
| **MT3** | 로그 로테이션 + 일별 아카이빙 | monitor/ | 디스크 관리 자동화 |
| **MT4** | 세션 영속화 (SQLite or Redis) | session.py | 재시작 시 대화 유지 |
| **MT5** | 나머지 2건 실패 수정 | rag/graph.py | 100% 달성 |
| **MT6** | Rate limiting 추가 | server.py | DDoS/남용 방지 |

**MT1 모듈 분리안:**
```
rag/
├── graph.py          → 파이프라인 조합만 (~200줄)
├── nodes/
│   ├── preprocess.py     (~150줄)
│   ├── query_rewrite.py  (~100줄)
│   ├── clarification.py  (~300줄)
│   ├── retrieve.py       (~250줄)
│   ├── evidence_gate.py  (~100줄)
│   ├── answer.py         (~200줄)
│   ├── verify.py         (~100줄)
│   └── policy_filter.py  (~100줄)
├── constants.py      → HOTEL_INFO, VALID_QUERY_KEYWORDS 등
├── utils.py          → _stripHotelName, _extractSubjectEntity 등
├── grounding.py      (기존 유지)
├── session.py        (기존 유지)
├── llm_provider.py   (기존 유지)
└── server.py         (기존 유지)
```

**MT2 멀티턴 테스트 구조:**
```python
# tests/test_multiturn.py
SCENARIOS = [
    {
        "name": "부산_4턴_다이닝",
        "hotel": "grand_josun_busan",
        "turns": [
            {"query": "강아지 데려와도 돼?", "expect_keywords": ["불가"], "expect_clarification": False},
            {"query": "레스토랑 위치 알려줘", "expect_keywords": ["아리아", "층"], "expect_clarification": False},
            {"query": "아리아 디너 금액이 얼마야?", "expect_keywords": ["원"], "expect_clarification": False},
            {"query": "운영 시간이 어떻게돼?", "expect_keywords": ["시"], "expect_context": "dining"},
        ]
    },
    # ... 시나리오 추가
]
```

### 4.3 Long-term (1~2개월)

| # | 개선 | 대상 | 예상 효과 |
|---|------|------|-----------|
| **LT1** | 관리자 웹 대시보드 | 신규 | 실시간 모니터링/알림 |
| **LT2** | 크롤러 스케줄링 자동화 | crawler/ | 데이터 신선도 보장 |
| **LT3** | 다국어 지원 (영어/일본어) | rag/ | 외국인 고객 대응 |
| **LT4** | A/B 테스트 프레임워크 | 신규 | 프롬프트/임계값 최적화 |
| **LT5** | 대화 분석 리포트 자동 생성 | monitor/ | 주간/월간 운영 보고 |

---

## 5. 스프린트 로드맵

### Sprint 1 — 보안/안정성 긴급 패치 (2일)

| 작업 | 우선순위 | 예상 시간 |
|------|----------|-----------|
| QW1: CORS 도메인 제한 | P0 | 30분 |
| QW2: 에러 응답 일반화 | P0 | 30분 |
| QW3: LLM timeout 추가 | P0 | 1시간 |
| QW4: /health 확장 | P1 | 1시간 |
| QW5: 서버 재시작 (Phase 14 반영) | P0 | 5분 |
| 전체 회귀 테스트 | - | 30분 |

**완료 기준:** 보안 취약점 0건, 서버 hang 불가, 장애 감지 가능

### Sprint 2 — 품질/테스트 강화 (1주)

| 작업 | 우선순위 | 예상 시간 |
|------|----------|-----------|
| MT5: 실패 2건 수정 (100% 달성) | P0 | 4시간 |
| MT2: 멀티턴 시나리오 테스트 자동화 | P1 | 8시간 |
| MT6: Rate limiting | P1 | 2시간 |
| 엣지 케이스 테스트 추가 (20건+) | P2 | 4시간 |

**완료 기준:** 50/50 통과, 멀티턴 시나리오 5개+ 자동화

### Sprint 3 — 아키텍처/운영 개선 (1주)

| 작업 | 우선순위 | 예상 시간 |
|------|----------|-----------|
| MT1: graph.py 모듈 분리 | P1 | 16시간 |
| MT3: 로그 로테이션 | P2 | 2시간 |
| MT4: 세션 영속화 (SQLite) | P2 | 4시간 |
| UI JS 모듈화 | P3 | 4시간 |

**완료 기준:** graph.py < 300줄, 세션 재시작 유지, 로그 자동 관리

### Sprint 4+ — 고도화 (장기)

| 작업 | 시점 |
|------|------|
| 관리자 웹 대시보드 | Sprint 4 |
| 크롤러 자동화 | Sprint 4 |
| 다국어 지원 | Sprint 5 |
| A/B 테스트 | Sprint 6 |

---

## 6. 검증 / 모니터링 / 운영 가이드

### 6.1 검증 체크리스트

```bash
# 1. 기본 정확도 (필수: 매 배포 전)
python tests/evaluate.py --save
# 기준: 50/50 통과

# 2. 멀티턴 시나리오 (권장: 주 1회)
python tests/test_multiturn.py  # (Sprint 2에서 구현)

# 3. Phase 14 명확화 검증
python tests/test_clarification.py
# 기준: 주체 있는 질문 → 명확화 없이 검색, 주체 없는 질문 → 일반 명확화

# 4. 서버 상태 확인
curl http://localhost:8000/health
# 기준: {"status": "ok", "llm": "ok", "chroma": "ok"}
```

### 6.2 모니터링 항목

| 항목 | 주기 | 임계값 | 알림 방법 |
|------|------|--------|-----------|
| 서버 프로세스 생존 | 1분 | down | 로그 |
| LLM 응답 시간 | 매 요청 | > 15초 | 로그 경고 |
| Evidence Gate 통과율 | 일 1회 | < 80% | 대시보드 |
| 명확화 트리거 비율 | 일 1회 | > 30% | 대시보드 |
| 로그 파일 크기 | 일 1회 | > 100MB | 로그 로테이션 |

### 6.3 장애 대응 절차

```
1. 증상 확인
   - /health 엔드포인트 체크
   - data/logs/chat_YYYYMMDD.jsonl 최근 로그 확인

2. 원인 분류
   A. LLM 무응답 → Ollama 프로세스 확인 (ollama list)
   B. Chroma 에러 → 인덱스 파일 무결성 확인
   C. 세션 문제 → 서버 재시작 (세션 초기화)
   D. 검색 품질 저하 → 로그 분석 (monitor/analyzer.py)

3. 복구
   - 서버 재시작: kill PID && python rag/server.py
   - 인덱스 재구축: python pipeline/indexer.py && python pipeline/index_supplementary.py
   - 모델 재로드: ollama pull qwen2.5:7b
```

### 6.4 배포 프로세스

```bash
# 1. 코드 변경 후
git add -A && git commit -m "description"

# 2. 평가 실행
python tests/evaluate.py --save

# 3. 결과 확인 (50/50 필수)
# 실패 시 → 수정 후 재평가

# 4. 서버 재시작
lsof -ti:8000 | xargs kill 2>/dev/null
nohup python rag/server.py > /dev/null 2>&1 &

# 5. 스모크 테스트
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"hotelId":"grand_josun_jeju","message":"체크인 시간 알려줘"}'
```

---

## 7. 가정 / 리스크

### 7.1 현재 가정

| 가정 | 리스크 |
|------|--------|
| 로컬 Ollama가 항상 실행 중 | 로컬 장비 재시작 시 LLM 불가 |
| 16GB 메모리로 충분 | 청크 수 증가 시 Chroma + 리랭커 메모리 부족 가능 |
| 5개 호텔만 대상 | 호텔 추가 시 graph.py 상수 수동 추가 필요 |
| FAQ 데이터가 자주 변경되지 않음 | 실제 운영 시 가격/시간 변경 미반영 위험 |
| 동시 사용자 10명 이하 | 단일 프로세스로 동시 처리 한계 |

### 7.2 리스크 매트릭스

| 리스크 | 발생 확률 | 영향도 | 대응 |
|--------|-----------|--------|------|
| LLM 장시간 무응답 | 중 | **높음** | Sprint 1: timeout 추가 |
| 동시 요청 병목 | 낮 | 중 | Long-term: 워커 프로세스 확장 |
| 데이터 신선도 저하 | **높음** | 중 | Sprint 4: 크롤러 자동화 |
| 세션 유실 (재시작) | **높음** | 중 | Sprint 3: SQLite 영속화 |
| 보안 공격 (CORS) | 중 | **높음** | Sprint 1: CORS 제한 |

### 7.3 기술 부채 현황

| 항목 | 부채 수준 | 원인 |
|------|-----------|------|
| graph.py 2,064줄 | **심각** | 빠른 이터레이션 우선, 리팩토링 미실시 |
| 인라인 JS (UI) | 중간 | 프로토타입 단계에서 모듈화 생략 |
| 하드코딩된 호텔 상수 | 중간 | 설정 파일 분리 필요 |
| requirements.txt 버전 | 낮음 | 상한선 미지정 (호환성 깨질 수 있음) |

---

## 부록: Phase 14 반영 확인

현재 Phase 14 (주체 중심 명확화) 코드가 `rag/graph.py`에 반영되었으나, **서버(PID on port 8000)가 재시작되지 않아 실제 서비스에는 미적용 상태입니다.**

즉시 서버를 재시작해야 Phase 14 수정사항이 적용됩니다.

---

## 요약

| 영역 | 현재 | 목표 | 갭 |
|------|------|------|----|
| **정확도** | 96% (48/50) | 100% (50/50) | 2건 수정 필요 |
| **보안** | 취약 (CORS/에러노출) | OWASP 준수 | Sprint 1 |
| **안정성** | 불안정 (timeout 없음) | 99.9% | Sprint 1~2 |
| **유지보수** | 어려움 (2,064줄 단일 파일) | 모듈화 | Sprint 3 |
| **운영** | CLI 수동 | 자동화/알림 | Sprint 3~4 |
| **테스트** | 단일턴 50개 | 단일턴 70+ / 멀티턴 10+ | Sprint 2 |

**최우선 조치:** Sprint 1 (보안/안정성) → 2일 내 완료 권장
