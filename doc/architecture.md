# 시스템 아키텍처

> 호텔 FAQ RAG 챗봇 시스템 구조

---

## 전체 아키텍처

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Crawler   │ -> │  Pipeline   │ -> │   Indexer   │ -> │   RAG API   │
│  (수집)     │    │  (정제)     │    │  (인덱싱)   │    │  (서빙)     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                                                               │
                                                               v
                                                         ┌─────────────┐
                                                         │     UI      │
                                                         │  (웹 채팅)  │
                                                         └─────────────┘
```

---

## 폴더 구조

```
josun_chatbot/
├── crawler/          # 호텔별 FAQ 크롤러
├── pipeline/         # 데이터 정제/청킹/인덱싱
├── rag/              # LangGraph RAG 서버
├── policies/         # 정책 파일 및 필터 로직
├── tests/            # 테스트 및 평가
├── monitor/          # 모니터링 대시보드
├── ui/               # 웹 UI (HTML/CSS/JS)
├── data/             # 데이터 저장소
├── doc/              # 프로젝트 문서
├── docs/             # PDCA 문서 (plan/design)
└── reports/          # 평가 결과 리포트
```

---

## 폴더별 상세 설명

### `/crawler` - 데이터 수집

호텔별 FAQ/공지 크롤러

| 파일 | 설명 |
|------|------|
| `josun_crawler.py` | 조선호텔 통합 크롤러 |
| `deep_crawler.py` | 심층 크롤링 (상세 페이지) |

**수집 대상**: 조선 팰리스, 그랜드 조선 부산/제주, 레스케이프, 그래비티 판교

---

### `/pipeline` - 데이터 처리

데이터 정제 → 청킹 → 인덱싱 파이프라인

| 파일 | 설명 |
|------|------|
| `cleaner.py` | HTML 정제, 노이즈 제거 |
| `chunker.py` | 300~600 토큰 단위 청킹, Q/A 쌍 유지 |
| `indexer.py` | Chroma + BM25 하이브리드 인덱싱 |
| `index_supplementary.py` | 보충 데이터 인덱싱 |
| `index_all.py` | 전체 재인덱싱 스크립트 |

---

### `/rag` - RAG 서버 (핵심)

LangGraph 기반 RAG 플로우

| 파일 | 설명 |
|------|------|
| `graph.py` | **메인 RAG 그래프** (7개 노드) |
| `grounding.py` | Grounding Gate (문장 단위 검증) |
| `server.py` | FastAPI 서버 |

#### RAG 플로우 (7개 노드)

```
1. queryRewriteNode    # 대화 맥락 반영 쿼리 재작성
2. preprocessNode      # 입력 정규화, 언어/호텔/카테고리 감지
3. retrieveNode        # Vector + BM25 하이브리드 검색
4. evidenceGateNode    # 근거 검증 (품질 확인)
5. answerComposeNode   # LLM 답변 생성 (Ollama)
6. answerVerifyNode    # 할루시네이션 검증 + 카테고리 오염 검사
7. policyFilterNode    # 금지 주제/개인정보 필터링
8. logNode             # 로깅
```

#### 핵심 클래스

| 클래스 | 역할 |
|--------|------|
| `RAGState` | 그래프 상태 정의 (TypedDict) |
| `RAGGraph` | 메인 RAG 그래프 |
| `GroundingGate` | 문장 단위 근거 검증 |
| `CategoryConsistencyChecker` | 카테고리 교차 오염 감지 |

---

### `/tests` - 테스트

| 파일 | 설명 |
|------|------|
| `evaluate.py` | **자동 평가 스크립트** (정확도 측정) |
| `golden_qa.json` | 48개 골든 테스트 케이스 |
| `test_grounding.py` | Grounding Gate 단위 테스트 |

**실행 방법:**
```bash
python tests/evaluate.py        # 전체 평가
python tests/test_grounding.py  # Grounding 테스트
```

---

### `/monitor` - 모니터링

| 파일 | 설명 |
|------|------|
| `dashboard.py` | CLI 대시보드 |
| `analyzer.py` | 로그 분석기 |
| `collector.py` | 실패 케이스 수집기 |

---

### `/ui` - 웹 UI

정적 웹 채팅 인터페이스

| 폴더/파일 | 설명 |
|-----------|------|
| `index.html` | 메인 페이지 |
| `css/` | 스타일시트 |
| `js/` | 클라이언트 JavaScript |
| `assets/` | 이미지/아이콘 |

---

### `/data` - 데이터 저장소

| 폴더 | 설명 |
|------|------|
| `raw/` | 크롤링 원본 HTML |
| `clean/` | 정제된 텍스트 |
| `chunks/` | 청킹된 데이터 |
| `index/chroma/` | Chroma Vector DB |
| `index/bm25_index.pkl` | BM25 인덱스 |
| `logs/` | 채팅 로그 (JSONL) |
| `supplementary/` | 보충 데이터 |

**데이터 현황:**
- 총 청크: 361개
- 호텔: 5개 (조선 팰리스, 부산, 제주, 레스케이프, 그래비티)

---

### `/policies` - 정책

| 파일 | 설명 |
|------|------|
| `forbidden.json` | 금지 키워드/주제 |
| `contact_info.json` | 호텔별 연락처 |

---

### `/doc` - 프로젝트 문서

| 파일 | 설명 |
|------|------|
| `changelog.md` | 개발 진행 내역 |
| `architecture.md` | 시스템 아키텍처 (본 문서) |

---

### `/docs` - PDCA 문서

bkit PDCA 사이클 문서

| 파일 | 설명 |
|------|------|
| `plan-rag.md` | RAG 기능 계획 |
| `design-rag.md` | RAG 설계 문서 |
| `USER_GUIDE.md` | 사용자 가이드 |

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| **Vector DB** | Chroma |
| **검색** | 하이브리드 (Vector 70% + BM25 30%) |
| **LLM** | Ollama (qwen2.5:7b) |
| **프레임워크** | LangGraph |
| **Embedding** | intfloat/multilingual-e5-small |
| **API 서버** | FastAPI |
| **언어** | Python 3.11 |

---

## 핵심 정책 원칙

1. **No Retrieval, No Answer**: 근거 없는 답변 금지
2. **추정/일반론 금지**: "약", "대략", "아마" 사용 금지
3. **출처 URL 필수**: 모든 답변에 참고 URL 포함
4. **개인정보 요구 금지**: 예약번호, 카드번호 등 요청 안 함
5. **근거 부족 시**: "확인이 어렵습니다" + 공식 채널 안내

---

## 자주 사용하는 명령어

```bash
# 평가 실행
python tests/evaluate.py --save

# Grounding 테스트
python tests/test_grounding.py

# 서버 실행
python rag/server.py

# 대시보드
python monitor/dashboard.py --days 7

# 보충 데이터 인덱싱
python pipeline/index_supplementary.py
```
