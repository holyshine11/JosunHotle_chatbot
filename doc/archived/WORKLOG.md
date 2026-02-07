# 조선호텔 RAG 챗봇 워크로그

> 마지막 업데이트: 2026-02-04
> GitHub: https://github.com/holyshine11/JosunHotle_chatbot

---

## 현재 상태

| 항목 | 값 |
|------|-----|
| 정확도 | **100%** (48/48) |
| 평균 유사도 | 0.937 |
| 할루시네이션율 | 0% |
| 총 청크 | 361개 |
| 호텔 | 5개 |

---

## 최근 작업 (2026-02-04)

### 완료된 작업

1. **LLM 프롬프트 개선** (`316a6a7`)
   - 문제: 답변 끝에 불필요한 후속 질문 ("어떤 레스토랑이 궁금하신가요?")
   - 해결: 프롬프트에 "절대 금지" 규칙 추가, Temperature 0.3→0.1
   - 파일: `rag/graph.py:answerComposeNode`

2. **쿼리 검증 로직 추가** (`40423c0`)
   - 문제: "복실이 이쁘니?" 같은 무관한 질문에도 답변 생성
   - 해결: `VALID_QUERY_KEYWORDS` + `is_valid_query` 필드 추가
   - 파일: `rag/graph.py:preprocessNode`, `evidenceGateNode`

3. **호텔 관련 키워드 확장** (`3e26f3f`)
   - 변경: 80개 → 586개 키워드
   - 카테고리: 객실, 시설, 다이닝, 주차, 반려동물, 예약, 위치 등 25개
   - 파일: `rag/graph.py:VALID_QUERY_KEYWORDS`

4. **사용자 가이드 작성** (`76d05e9`)
   - 파일: `docs/USER_GUIDE.md`
   - 내용: Git 워크플로우, 챗봇 실행, 평가, 모니터링, 문제해결

---

## 핵심 파일

| 파일 | 설명 |
|------|------|
| `rag/graph.py` | RAG 파이프라인 (7개 노드) |
| `tests/evaluate.py` | 자동 평가 스크립트 |
| `tests/golden_qa.json` | 48개 테스트 케이스 |
| `docs/USER_GUIDE.md` | 사용자 가이드 |
| `monitor/dashboard.py` | 모니터링 대시보드 |

---

## 다음 세션에서 할 일 (예정)

- [ ] 웹 UI 개발 (Streamlit/Gradio)
- [ ] 동의어 사전 구축 (쿼리 확장)
- [ ] 답변 템플릿 시스템
- [ ] 실시간 알림 시스템

---

## 자주 사용하는 명령어

```bash
# 챗봇 실행
python chat.py

# 평가 실행 (결과 저장)
python tests/evaluate.py --save

# 대시보드
python monitor/dashboard.py

# Git 푸시
git add . && git commit -m "메시지" && git push origin main
```

---

## 기술 스택

- **LLM**: Ollama + qwen2.5:7b-instruct-q4_K_M
- **Embedding**: multilingual-e5-small (384차원)
- **Vector DB**: ChromaDB
- **검색**: Hybrid (Vector 70% + BM25 30%)
- **프레임워크**: LangGraph

---

## 세션 재개 방법

1. 이 파일(`WORKLOG.md`)을 읽어 현재 상태 파악
2. `CLAUDE.md`에서 아키텍처 및 정책 확인
3. `python tests/evaluate.py`로 현재 정확도 확인
4. 위 "다음 세션에서 할 일" 항목 참조
