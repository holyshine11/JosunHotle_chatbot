# ✅ Worklog (Auto-updated)

> 마지막 업데이트: 2026-02-04

## 프로젝트/목표
- **프로젝트**: 조선호텔 FAQ 챗봇 (RAG 기반)
- **목표**: 5개 호텔(조선팰리스, 그랜드조선부산, 그랜드조선제주, 레스케이프, 그래비티판교)의 FAQ/정책 데이터를 수집하여 근거 기반 RAG 챗봇 구축
- **핵심 제약**: 로컬 16GB, 무료 LLM, "No Retrieval, No Answer" 정책

## 저장소/경로
- `/Users/Dev/josun_chatbot`
- Git 저장소: 초기화됨 (커밋 전)

## 현재 브랜치/버전
- main (초기 상태)
- MVP v1.0 완료

## 완료한 작업
1. ✅ 프로젝트 초기화 (디렉토리 구조, requirements.txt, .gitignore)
2. ✅ 조선호텔 URL 조사 및 분석 (`data/analysis_josun_hotels.md`)
3. ✅ 크롤러 구현 (`crawler/josun_crawler.py`) - 5개 호텔 23개 문서 수집
4. ✅ 정제/청킹 파이프라인 (`pipeline/cleaner.py`, `chunker.py`) - 189개 청크 생성
5. ✅ Vector DB 인덱싱 (`pipeline/indexer.py`) - Chroma + multilingual-e5-small
6. ✅ LangGraph RAG 서버 (`rag/graph.py`, `server.py`) - 6개 노드 플로우
7. ✅ 정책 파일 (`policies/josun_policies.yaml`, `policy_manager.py`)
8. ✅ 테스트 및 평가 (`tests/test_qa.py`) - 25개 일반 + 8개 레드팀 테스트
9. ✅ **MCP Playwright 크롤링** - FAQ 페이지네이션 처리, 135개 추가 FAQ 수집
   - 그랜드 조선 부산: 42개
   - 그래비티 판교: 27개
   - 레스케이프: 24개
   - 그랜드 조선 제주: 23개
   - 조선 팰리스: 19개
   - 파이프라인 재실행 완료
10. ✅ **Ollama LLM 연동** - qwen2.5:7b 모델로 자연어 답변 생성
    - `rag/graph.py`에 `_generateWithLLM()` 메서드 추가
    - 시스템 프롬프트: 조선호텔 AI 컨시어지 역할
    - temperature 0.3, max_tokens 256 설정

## 변경된 파일
```
josun_chatbot/
├── crawler/
│   ├── josun_crawler.py
│   ├── seed_urls.json
│   └── README.md
├── pipeline/
│   ├── cleaner.py
│   ├── chunker.py
│   ├── indexer.py
│   ├── merge_mcp_data.py (MCP 데이터 통합)
│   └── README.md
├── rag/
│   ├── graph.py
│   ├── server.py
│   └── README.md
├── policies/
│   ├── josun_policies.yaml
│   ├── policy_manager.py
│   └── README.md
├── tests/
│   ├── test_data.json
│   ├── test_qa.py
│   └── README.md
├── data/
│   ├── raw/ (5개 호텔 크롤링 데이터)
│   ├── raw/mcp_crawled/ (MCP 크롤링 FAQ 135개)
│   ├── clean/ (319개 정제 문서)
│   ├── chunks/ (189개 청크)
│   ├── index/ (Chroma DB)
│   ├── analysis_josun_hotels.md
│   └── logs/
├── requirements.txt
├── .gitignore
├── CLAUDE.md
├── dev_guide.md
└── plan_josun_mvp.md
```

## 테스트 결과
- 일반 테스트: 76.0% (19/25 통과)
- 레드팀 테스트: 100.0% (8/8 통과)
- Citation Coverage: 80.0%
- Refusal Correctness: 100.0%

## 보류/이슈/리스크
- 아직 Git 커밋 안됨
- 테스트 정확도 76% (일부 질문에서 검색 관련성 낮음)

## 다음 해야 할 일 (우선순위 1~5)
1. **Git 커밋** - 현재까지 작업 커밋
2. **UI 구현** - 간단한 웹 채팅 인터페이스
3. **검색 품질 개선** - 임베딩 모델 파인튜닝 또는 하이브리드 검색 도입
4. **테스트 케이스 보강** - 실패한 케이스 분석 및 개선
5. **운영 환경 설정** - Docker 또는 systemd 서비스화

## 다음에 사용자 입력이 필요한 최소 정보
- Git 커밋 진행 여부
- UI 스타일 선호도 (간단한 HTML vs React)

## Resume Recipe (다음 세션에서 바로 재개 절차)
1. `/Users/Dev/josun_chatbot` 디렉토리 확인
2. `WORKLOG.md` 읽어서 현재 상태 파악
3. `plan_josun_mvp.md` 확인하여 작업 상태 체크
4. 사용자에게 "다음 작업(Git 커밋/LLM 연동/UI) 중 무엇을 진행할까요?" 질문

## 주요 명령어 (빠른 참조)
```bash
PYTHON=~/.pyenv/versions/3.11.7/bin/python3

# 크롤링
$PYTHON crawler/josun_crawler.py --force

# 파이프라인
$PYTHON pipeline/cleaner.py
$PYTHON pipeline/chunker.py
$PYTHON pipeline/indexer.py

# RAG 서버
$PYTHON rag/server.py

# 테스트
$PYTHON tests/test_qa.py --save
```
