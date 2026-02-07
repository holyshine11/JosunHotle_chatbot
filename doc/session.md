# 세션 컨텍스트 (Session Context)

> 다음 세션/에이전트가 이어서 작업할 수 있도록 현재 상태 기록

---

## 현재 상태 (2026-02-07)

### 완료된 작업

- ✅ Phase 9: UI 디자인 개선 (다크모드, 애니메이션, 반응형)
- ✅ Phase 10: 소스 URL 미스매칭 버그 수정
- ✅ Phase 11: 반려동물 정책 할루시네이션 수정
- ✅ Phase 12: 모호한 질문 의도 파악 개선
- ✅ Phase 13: 맥락 인식 명확화 시스템
- ✅ Phase 14: 주체 감지 + 호텔명 제거 + 다턴 맥락 개선
- ✅ Phase 15: 리랭커 키워드 보호 + Evidence Gate 고도화
- ✅ Phase 16: 명확화 루프 버그 수정 + 패키지 데이터 보충
- ✅ Phase 17: JSON API 크롤러 + topScore 버그 수정
- ✅ 정확도 100% (50/50) + 멀티턴 100% (22/22)

---

## 시스템 현황

| 항목 | 값 |
|------|-----|
| 정확도 | 100% (50/50) |
| 멀티턴 | 100% (22/22) |
| 테스트 케이스 | 50개 (골든) + 22턴 (멀티턴) |
| Chroma 청크 | 648개 |
| BM25 청크 | 460개 |
| 보충 데이터 | 101개 (패키지 51, 이벤트 19, 액티비티 2 등) |
| 호텔 수 | 5개 |
| 실패 케이스 | 없음 |

---

## 핵심 파일 위치

| 역할 | 파일 |
|------|------|
| RAG 메인 | `rag/graph.py` |
| 리랭커 | `rag/reranker.py` |
| Grounding | `rag/grounding.py` |
| 서버 | `rag/server.py` |
| 평가 스크립트 | `tests/evaluate.py` |
| 테스트 데이터 | `tests/golden_qa.json` |
| 멀티턴 테스트 | `tests/test_multiturn.py` |
| 인덱서 | `pipeline/indexer.py` |
| 보충 인덱서 | `pipeline/index_supplementary.py` |
| JSON API 크롤러 | `crawler/crawl_api.py` |
| UI 메인 | `ui/index.html` |
| UI 스타일 | `ui/css/style.css` |
| 보충 데이터 | `data/supplementary/` |

---

## 다음 작업 후보

1. **리랭커 고도화 (Phase 15 플랜)**: 사우나 쿼리 등 키워드 매칭 보완
2. **쿼리 확장**: 동의어 사전 확장
3. **답변 템플릿**: 카테고리별 답변 형식 통일
4. **다국어 지원**: 영어/일본어 답변
5. **실시간 알림**: 실패 케이스 자동 알림

---

## 이어서 작업하기

```bash
# 1. 상태 확인
python tests/evaluate.py

# 2. 서버 실행
python rag/server.py

# 3. UI 서버 실행 (다른 터미널)
cd ui && python -m http.server 3000

# 4. 멀티턴 테스트
python tests/test_multiturn.py --save
```

---

## 주요 변경점 (Phase 14-17)

### Phase 14: 주체 감지 + 호텔명 제거

| 기능 | 설명 |
|------|------|
| 주체 감지 | 주체(entity) 있으면 명확화 건너뜀 |
| 호텔명 제거 | 검색 쿼리에서 호텔명 strip |
| 토픽 추출 | user 메시지만 역순 분석 |

### Phase 15: 리랭커 키워드 보호

| 기능 | 설명 |
|------|------|
| 키워드 매칭 | 쿼리 키워드 포함 청크 보호 |
| 임계값 완화 | RELATIVE_THRESHOLD 0.4 → 0.35 |
| 로그 개선 | [K] 상태로 키워드 보호 표시 |

### Phase 16: 명확화 루프 수정

| 기능 | 설명 |
|------|------|
| 루프 방지 | 명확화 응답 후 재질문 방지 |
| 데이터 보충 | 패키지 6개 → 51개 (API 소싱) |

### Phase 17: JSON API 크롤러

| 기능 | 설명 |
|------|------|
| crawl_api.py | 호텔 REST API 자동 수집 |
| topScore 수정 | max() 사용으로 정확한 최고 점수 계산 |
| 데이터 | 패키지 51, 이벤트 19, 액티비티 2 |

---

## 문의

- 개발 진행 내역: `doc/changelog.md`
- 시스템 구조: `doc/architecture.md`
- 프로젝트 개요: `CLAUDE.md`
