# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

조선호텔 계열 5개 호텔의 공개 FAQ/공지 데이터를 수집하여 구축한 근거 기반 RAG 챗봇.

**대상 호텔:** 조선 팰리스, 그랜드 조선 부산, 그랜드 조선 제주, 레스케이프, 그래비티 판교

**핵심 제약:**
- 로컬 실행 (16GB 노트북)
- 무료 LLM (Ollama qwen2.5:7b Q4 양자화)
- "No Retrieval, No Answer" 정책 강제

## 명령어

```bash
# 서버 실행
python rag/server.py                    # RAG API (포트 8000)

# 테스트
python tests/evaluate.py --save         # 전체 평가 (50개 골든 QA)
python tests/evaluate.py --hotel busan  # 호텔별
python tests/evaluate.py --category dining  # 카테고리별
python tests/evaluate.py --quick        # 10개 샘플만
python tests/test_multiturn.py --save   # 멀티턴 테스트 (6시나리오, 22턴)

# 데이터 파이프라인
python pipeline/index_supplementary.py  # 보충 데이터 인덱싱
python crawler/crawl_api.py             # JSON API 크롤링 (패키지/이벤트/액티비티)

# 모니터링
python monitor/dashboard.py --days 7
```

## 아키텍처

```
Crawler → Cleaner → Chunker → Indexer(Chroma + BM25) → RAG API(LangGraph 9노드) → FastAPI → UI
```

### RAG 플로우 (9개 노드) - `rag/graph.py`

```
queryRewriteNode → preprocessNode → clarificationCheckNode → retrieveNode
→ evidenceGateNode → answerComposeNode → answerVerifyNode → policyFilterNode → logNode
```

| 노드 | 역할 |
|------|------|
| `queryRewriteNode` | 대화 맥락 반영 쿼리 재작성 |
| `preprocessNode` | 입력 정규화, 언어/호텔/카테고리 감지, `VALID_QUERY_KEYWORDS` 검증 |
| `clarificationCheckNode` | 모호한 질문 명확화 (맥락 인식, 주체 감지) |
| `retrieveNode` | Vector(70%) + BM25(30%) 하이브리드 검색 + Cross-Encoder 리랭킹 |
| `evidenceGateNode` | 근거 검증 (`EVIDENCE_THRESHOLD: 0.65`), topScore = max(scores) |
| `answerComposeNode` | LLM 답변 생성 (Temperature 0.1), `[REF:N]` 참조 추적 |
| `answerVerifyNode` | 할루시네이션 검증 + `CategoryConsistencyChecker` 오염 검사 |
| `policyFilterNode` | 금지 주제/개인정보 필터링 |
| `logNode` | JSONL 로깅 → `data/logs/` |

### 핵심 클래스/상수

- `RAGState` (TypedDict): 그래프 상태 - query, hotel, history, retrieved_chunks, answer 등
- `RAGGraph`: 메인 그래프 클래스. `chat(query, hotel, history, sessionId)` 메서드
- `VALID_QUERY_KEYWORDS`: 586개 호텔 관련 키워드 (무관한 질문 차단)
- `CATEGORY_KEYWORDS`: 15개 카테고리 분류 키워드
- `EVIDENCE_THRESHOLD = 0.65`: 근거 점수 임계값
- `Reranker` (`rag/reranker.py`): BAAI/bge-reranker-v2-m3, `RELATIVE_THRESHOLD = 0.35`, 키워드 보호 로직
- `GroundingGate` (`rag/grounding.py`): 문장 단위 근거 검증
- `CategoryConsistencyChecker`: 카테고리 교차 오염 감지/정제

### API 엔드포인트 - `rag/server.py`

```
POST /chat  { message, hotelId, sessionId, history? }
GET  /health
GET  /          → ui/index.html (정적 파일 서빙)
```

## 기술 스택

| 구분 | 기술 |
|------|------|
| Vector DB | Chroma |
| 검색 | 하이브리드 (Vector 70% + BM25 30%) + Cross-Encoder 리랭킹 |
| LLM | Ollama (qwen2.5:7b) |
| 프레임워크 | LangGraph |
| Embedding | intfloat/multilingual-e5-small |
| 리랭커 | BAAI/bge-reranker-v2-m3 |
| API 서버 | FastAPI + Uvicorn |
| 언어 | Python 3.11 |

## 데이터

- **Chroma**: 648개 청크 / **BM25**: 450개 청크
- **보충 데이터** (`data/supplementary/`): 91개 (패키지 51, 이벤트 19, 액티비티 2, 반려동물 6, 연락처 5 등)
- **인덱스**: `data/index/chroma/`, `data/index/bm25_index.pkl`
- **청킹**: 300~600 토큰 단위, FAQ는 Q/A 쌍 유지

호텔 ID: `josun_palace`, `grand_josun_busan`, `grand_josun_jeju`, `lescape`, `gravity_pangyo`

## 정책 원칙

- 근거 없는 답변 금지 (No Retrieval, No Answer)
- 추정/일반론 금지 ("약", "대략", "아마" 사용 금지)
- 답변에 출처 URL 필수
- 개인정보(예약번호/카드번호) 요구 금지
- 근거 부족 시: "확인이 어렵습니다" + 공식 채널 안내

## 코드 스타일

- 변수/함수: camelCase
- 클래스: PascalCase
- 상수: UPPER_SNAKE_CASE
- 주석: 한글
- 커밋 메시지: 영문

## 현재 상태 (2026-02-07)

- **정확도**: 100% (50/50 골든 QA) + 멀티턴 100% (22/22)
- **완료 Phase**: 17개 + Security Patch 2개 (Phase 1~17, S1~S2)
- **상세 이력**: `doc/changelog.md`
- **세션 컨텍스트**: `doc/session.md`
