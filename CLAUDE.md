# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

호텔 FAQ 기반 RAG 챗봇 프로젝트. 여러 호텔(신라, 글레드, MUWA NISEKO, 라한, 반얀트리, 조선 등)의 공개 FAQ/공지 데이터를 수집하여 근거 기반 RAG 챗봇을 구축한다.

**핵심 제약:**
- 로컬 실행 (16GB 노트북)
- 무료 LLM 사용 (Ollama/llama.cpp, 7B~8B 4bit 양자화)
- "No Retrieval, No Answer" 정책 강제

## 아키텍처

```
Crawler → Cleaner/Normalizer → Chunker → Indexer(Embedding + VectorDB) → RAG API(LangGraph) → UI
```

**저장소 구조:**
- `/crawler` - 호텔별 크롤러 (증분 업데이트 지원)
- `/pipeline` - 정제/청킹/인덱싱 파이프라인
- `/rag` - LangGraph 기반 RAG 서버
- `/policies` - 정책 파일 및 필터 로직
- `/tests` - QA 테스트셋 및 평가 스크립트
- `/ui` - 웹 UI (옵션)

## LangGraph RAG 플로우

필수 노드 순서:
1. `preprocess_node` - 입력 정규화, 언어/호텔/카테고리 감지
2. `retrieve_node` - Vector search + BM25 하이브리드 검색
3. `evidence_gate_node` - 근거 검증 (기준 미달 시 답변 생성 금지)
4. `answer_compose_node` - 근거 기반 답변 생성 + 출처 URL 포함
5. `policy_filter_node` - 금지 주제/개인정보 필터링
6. `log_node` - 질문/검색결과/gate 통과 여부 로깅

## 기술 스택

- **Vector DB:** Chroma (권장) 또는 FAISS
- **LLM:** qwen2.5 7B instruct 또는 Llama 3.1 8B instruct (Q4 양자화)
- **프레임워크:** LangGraph
- **Embedding:** 다국어 지원 모델 (ko/en/ja)

## 데이터 스키마

- `raw_documents`: doc_id, hotel, url, fetched_at, html, content_hash
- `clean_documents`: doc_id, hotel, url, title, category, language, updated_at, text
- `chunks`: chunk_id, doc_id, hotel, url, category, updated_at, chunk_index, chunk_text

청킹: 300~600 토큰 단위, FAQ는 Q/A 쌍 단위 유지

## 정책 원칙

- 근거 없는 답변 금지
- 추정/일반론 금지
- 답변에 출처 링크 필수
- 개인정보(예약번호/전화/카드번호) 입력 요구 금지
- 결제/환불은 공식 페이지 링크 + 상담 유도
- 근거 부족 시: "확인이 어렵습니다" + 공식 채널 안내

---

## 고도화 진행 현황 (2026-02-07)

### 현재 상태: 정확도 100% (50/50) + 멀티턴 100% (22/22)

| Phase | 내용 | 결과 |
|-------|------|------|
| 1 | 자동 평가 시스템 | 91.7% |
| 2 | BM25 하이브리드 검색 | 91.7% |
| 3 | 답변 검증 노드 | 91.7% |
| 4 | 데이터 품질 개선 | **100%** |
| 5 | 모니터링 시스템 | ✅ |
| 6 | 프롬프트 개선 | ✅ |
| 7 | 쿼리 검증 강화 | **100%** |
| 8 | 컨텍스트 오염 방지 | **100%** |
| 9 | UI 디자인 개선 (다크모드, 반응형) | ✅ |
| 10 | 소스 URL 미스매칭 수정 | ✅ |
| 11 | 반려동물 정책 할루시네이션 수정 | ✅ |
| 12 | 모호한 질문 의도 파악 개선 | ✅ |
| 13 | 맥락 인식 명확화 시스템 | **96%** |
| 14 | 주체 감지 + 호텔명 제거 + 다턴 맥락 개선 | **100%** |
| S1 | 보안/안정성 긴급 패치 (CORS, timeout, health) | ✅ |
| S2 | 연락처 데이터 보충 + 멀티턴 테스트 자동화 | **100%** |
| 15 | 리랭커 키워드 보호 + Evidence Gate 고도화 | **100%** |
| 16 | 명확화 루프 버그 수정 + 패키지 데이터 보충 | **100%** |
| 17 | JSON API 크롤러 + topScore 버그 수정 | **100%** |

### 주요 구현 내용

1. **자동 평가 시스템** (`tests/evaluate.py`, `tests/golden_qa.json`)
   - 50개 테스트 케이스 (5개 호텔, 12개 카테고리)
   - 키워드 기반 정확도 측정, 할루시네이션 감지

2. **BM25 하이브리드 검색** (`pipeline/indexer.py`)
   - Vector (70%) + BM25 (30%) 결합
   - 한국어 토크나이저 적용

3. **답변 검증 노드** (`rag/graph.py`)
   - 숫자 정보 할루시네이션 감지
   - 추측 표현 필터링 ("약", "대략", "아마")

4. **데이터 품질 개선** (`pipeline/index_supplementary.py`)
   - 주차/위치 정보 보충 (7개 청크 추가)
   - 총 361개 청크 인덱싱

5. **모니터링 시스템** (`monitor/`)
   - CLI 대시보드 (`dashboard.py`)
   - 로그 분석기 (`analyzer.py`)
   - 실패 케이스 수집기 (`collector.py`)

6. **LLM 프롬프트 개선** (`rag/graph.py:answerComposeNode`)
   - 불필요한 후속 질문 제거 ("궁금하신가요?" 등 금지)
   - Temperature 0.1로 낮춤 (일관된 응답)
   - 절대 금지 규칙 명시

7. **쿼리 검증 강화** (`rag/graph.py:VALID_QUERY_KEYWORDS`)
   - 586개 호텔 관련 키워드 정의
   - 무관한 질문 차단 ("복실이 이쁘니?" 등)
   - EVIDENCE_THRESHOLD: 0.65

8. **컨텍스트 오염 방지** (`rag/graph.py`, `rag/grounding.py`)
   - 대화 주제 추적 (`_extractConversationTopic`)
   - 후속 질문에서 카테고리 필터 적용
   - `CategoryConsistencyChecker`: 교차 오염 감지/정제
   - 조식↔수영장 정보 혼입 방지

9. **UI 디자인 개선** (`ui/index.html`, `ui/css/style.css`)
   - 다크모드 지원 (토글 버튼, localStorage 저장)
   - 딥블루 + 골드 악센트 색상 시스템
   - 메시지 애니메이션 (fadeIn + slideUp)
   - 모바일 반응형 최적화

10. **소스 URL 미스매칭 수정** (`rag/graph.py`)
    - 컨텍스트에 `[참조N]` 형태로 청크 번호/URL 포함
    - LLM에게 `[REF:1,3]` 형식으로 사용한 참조 명시 요청
    - 응답 파싱하여 사용된 URL만 추출 및 표시

11. **반려동물 정책 할루시네이션 수정** (`data/supplementary/pet_policy.json`)
    - 모호한 표현 → 정확한 정책 기술
    - 호텔별 가능/불가 명확히 구분

12. **모호한 질문 의도 파악** (`rag/graph.py`)
    - `specificTargets`에 반려동물 키워드 추가
    - `AMBIGUOUS_PATTERNS` excludes 확장

13. **맥락 인식 명확화 시스템** (`rag/graph.py`)
    - `CONTEXT_CLARIFICATION` 패턴 (반려동물, 어린이)
    - `direct_triggers`로 질문형 감지 시 직접 검색
    - 맥락 맞춤 후속 질문 및 옵션 제시

14. **Phase 14: 주체 감지 + 호텔명 제거 + 다턴 맥락 개선** (`rag/graph.py`)
    - 주체(entity) 감지 시 명확화 건너뜀 → 바로 검색 ("스타벅스 위치 알려줘" → 직접 검색)
    - 원본 쿼리 기반 모호성 판단 (LLM 재작성이 주입한 키워드 무시)
    - `_stripHotelName`: 검색 쿼리에서 호텔명 제거 (벡터 임베딩 왜곡 방지)
    - `_extractConversationTopic`: user 메시지만 역순 분석 (봇 답변 노이즈 제거)
    - `_extractSubjectEntity`: 모호 키워드 제거 후 주체 추출

15. **Phase 15: 리랭커 키워드 보호** (`rag/reranker.py`)
    - 쿼리 키워드가 포함된 청크는 리랭크 점수와 무관하게 유지
    - `RELATIVE_THRESHOLD` 0.4 → 0.35로 완화
    - `_extractQueryKeywords`, `_hasQueryKeyword` 헬퍼 추가

16. **Phase 16: 명확화 루프 버그 수정** (`rag/graph.py`)
    - 명확화 응답 후 재질문 루프 방지
    - 패키지 데이터 보충 (6개 수동 → 51개 API 소싱)

17. **Phase 17: JSON API 크롤러** (`crawler/crawl_api.py`)
    - 호텔 REST API에서 패키지/이벤트/액티비티 자동 수집
    - topScore 계산 버그 수정 (`results[0]["score"]` → `max()`)
    - 보충 데이터: 패키지 51, 이벤트 19, 액티비티 2

### 프로젝트 문서

- `doc/changelog.md` - 개발 진행 내역
- `doc/architecture.md` - 시스템 아키텍처
- `doc/session.md` - 세션 컨텍스트 (이어서 작업용)

### 자주 사용하는 명령어

```bash
# 의존성 설치
pip install -r requirements.txt

# RAG API 서버 실행 (포트 8000)
python rag/server.py

# 웹 UI 서버 실행 (포트 3000)
cd ui && python -m http.server 3000

# 전체 평가 실행
python tests/evaluate.py --save

# 특정 호텔/카테고리만 테스트
python tests/evaluate.py --hotel busan
python tests/evaluate.py --category dining
python tests/evaluate.py --quick  # 10개 샘플만

# 대시보드 확인
python monitor/dashboard.py --days 7

# 실패 케이스 분석
python monitor/collector.py --save

# 보충 데이터 인덱싱
python pipeline/index_supplementary.py

# 멀티턴 시나리오 테스트 (6개 시나리오, 22턴)
python tests/test_multiturn.py --save
python tests/test_multiturn.py --scenario 1 --verbose  # 특정 시나리오
```

### 데이터 현황

- **총 청크**: Chroma 648개, BM25 460개
- **보충 데이터**: 101개 (패키지 51, 이벤트 19, 액티비티 2, 반려동물 6, 연락처 5, 조식 1 등)
- **호텔**: 조선 팰리스, 그랜드 조선 부산/제주, 레스케이프, 그래비티 판교
- **인덱스 경로**: `data/index/chroma/`, `data/index/bm25_index.pkl`

### 추후 개선 가능 항목

1. 쿼리 확장 (동의어 사전)
2. 답변 템플릿 적용
3. 실시간 알림 시스템
4. 다국어 지원 강화 (영어/일본어)
