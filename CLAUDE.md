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

## 고도화 진행 현황 (2026-02-04)

### 현재 상태: 정확도 100% (48/48 테스트 통과)

| Phase | 내용 | 커밋 | 결과 |
|-------|------|------|------|
| 1 | 자동 평가 시스템 | - | 91.7% |
| 2 | BM25 하이브리드 검색 | - | 91.7% |
| 3 | 답변 검증 노드 | `40fdb2f` | 91.7% |
| 4 | 데이터 품질 개선 | `f2e3054` | **100%** |
| 5 | 모니터링 시스템 | `e90a1ce` | ✅ |

### 주요 구현 내용

1. **자동 평가 시스템** (`tests/evaluate.py`, `tests/golden_qa.json`)
   - 48개 테스트 케이스 (5개 호텔, 12개 카테고리)
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

### 자주 사용하는 명령어

```bash
# 평가 실행
python tests/evaluate.py --save

# 대시보드 확인
python monitor/dashboard.py --days 7

# 실패 케이스 분석
python monitor/collector.py --save

# 보충 데이터 인덱싱
python pipeline/index_supplementary.py
```

### 데이터 현황

- **총 청크**: 361개 (기존 354 + 보충 7)
- **호텔**: 조선 팰리스, 그랜드 조선 부산/제주, 레스케이프, 그래비티 판교
- **인덱스 경로**: `data/index/chroma/`, `data/index/bm25_index.pkl`

### 추후 개선 가능 항목

1. 쿼리 확장 (동의어 사전)
2. 답변 템플릿 적용
3. 웹 UI (Streamlit/Gradio)
4. 실시간 알림 시스템
