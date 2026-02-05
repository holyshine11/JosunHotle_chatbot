# 조선호텔 FAQ 챗봇 MVP 구현 계획

> 작성일: 2026-02-04
> 기반 문서: dev_guide.md

--- 

## Phase 1: 환경 설정 및 프로젝트 초기화

### 1-1. 프로젝트 구조
```
josun_chatbot/
├── crawler/          # 조선호텔 크롤러
├── pipeline/         # 정제/청킹/인덱싱
├── rag/              # LangGraph RAG 서버
├── policies/         # 정책 YAML
├── tests/            # 테스트셋
├── data/             # 원본/정제 데이터 저장
│   ├── raw/
│   ├── clean/
│   └── index/
└── ui/               # (옵션) 웹 인터페이스
```

### 1-2. 의존성
- Python 3.11+
- LangGraph, LangChain
- Chroma (Vector DB)
- Ollama + qwen2.5:7b-instruct-q4
- BeautifulSoup4, requests (크롤링)
- sentence-transformers (Embedding)

---

## Phase 2: 조선호텔 데이터 수집

### 2-1. 크롤링 대상 URL (조사 필요)
- 조선호텔앤리조트 공식 사이트 (josunhotel.com)
  - FAQ 페이지
  - 이용안내/정책 페이지
  - 공지사항
- 대상 호텔: 조선팰리스, 그랜드 조선, 조선호텔앤리조트

### 2-2. 크롤러 구현
- `crawler/josun_crawler.py`
- seed URL 리스트 관리 (`crawler/seed_urls.json`)
- content_hash 기반 증분 업데이트
- robots.txt 준수

---

## Phase 3: 데이터 파이프라인

### 3-1. 정제 (Cleaner)
- HTML → 본문 추출
- header/footer/nav 제거
- Q/A 구조 보존

### 3-2. 청킹 (Chunker)
- FAQ: Q/A 쌍 단위
- 일반 텍스트: 300~600 토큰
- 메타데이터: hotel, category, url, updated_at, language

### 3-3. 인덱싱
- Embedding: multilingual-e5-small 또는 paraphrase-multilingual-MiniLM
- Vector DB: Chroma (persistent)

---

## Phase 4: LangGraph RAG 구현

### 4-1. 노드 구현 순서
1. `preprocess_node` - 입력 정규화, 카테고리 분류
2. `retrieve_node` - Vector search (Top-5)
3. `evidence_gate_node` - 근거 검증 (threshold 기반)
4. `answer_compose_node` - 답변 생성 + 출처
5. `policy_filter_node` - 금지 주제 필터
6. `log_node` - 로깅

### 4-2. 핵심 로직
- evidence_gate 실패 시 → "확인이 어렵습니다" + 고객센터 안내
- 모든 답변에 출처 URL 포함

---

## Phase 5: 정책 및 테스트

### 5-1. policies/josun_policies.yaml
- 금지 카테고리 정의
- 답변 템플릿 (정상/거절)
- 개인정보 처리 규칙

### 5-2. 테스트셋 (100개 질문)
- 체크인/아웃, 주차, 조식, 위치, 환불/취소, 부대시설 등

---

## 작업 순서 (우선순위)

| 순서 | 작업 | 산출물 | 상태 |
|-----|------|--------|------|
| 1 | 프로젝트 초기화 | 디렉토리, requirements.txt, Git | 완료 |
| 2 | 조선호텔 URL 조사 | seed_urls.json | 완료 |
| 3 | 크롤러 구현 | crawler/josun_crawler.py | 완료 |
| 4 | 정제/청킹 파이프라인 | pipeline/*.py | 완료 |
| 5 | Embedding + Chroma 인덱싱 | data/index/ | 대기 |
| 6 | LangGraph RAG 서버 | rag/graph.py, rag/server.py | 대기 |
| 7 | 정책 파일 | policies/josun_policies.yaml | 대기 |
| 8 | 테스트 및 평가 | tests/test_qa.py | 대기 |

---

## 확인 필요 사항

- [ ] 조선호텔 웹사이트 구조 조사 - FAQ/공지 페이지 URL 확인
- [ ] Ollama 설치 여부 - 로컬 LLM 환경 준비 상태
- [ ] MVP 범위 결정 - 조선팰리스만? 전체 조선호텔앤리조트?
