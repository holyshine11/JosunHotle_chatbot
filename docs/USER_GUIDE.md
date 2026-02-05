# 조선호텔 RAG 챗봇 사용 설명서

> 작성일: 2026-02-04
> 버전: 1.0

---

## 목차

1. [Git 커밋 방법](#1-git-커밋-방법)
2. [챗봇 실행 방법 (터미널)](#2-챗봇-실행-방법-터미널)
3. [웹 UI 실행 방법](#3-웹-ui-실행-방법)
4. [평가 및 테스트](#4-평가-및-테스트)
5. [모니터링 대시보드](#5-모니터링-대시보드)
6. [데이터 관리](#6-데이터-관리)
7. [문제 해결](#7-문제-해결)

---

## 1. Git 커밋 방법

### 1-1. 기본 커밋 절차

```bash
# Step 1: 변경 사항 확인
git status

# Step 2: 변경된 파일 스테이징 (추가)
git add 파일명              # 특정 파일만
git add .                 # 모든 변경 파일

# Step 3: 커밋 메시지 작성
git commit -m "커밋 메시지"

# Step 4: GitHub에 푸시
git push origin main
```

### 1-2. 커밋 메시지 규칙

```
feat: 새로운 기능 추가
fix: 버그 수정
docs: 문서 수정
refactor: 코드 리팩토링
test: 테스트 추가/수정
chore: 기타 작업
```

**예시:**
```bash
git commit -m "feat: Add new hotel data for Palace"
git commit -m "fix: Correct checkout time in FAQ"
git commit -m "docs: Update user guide"
```

### 1-3. 변경 취소하기

```bash
# 스테이징 취소 (add 취소)
git restore --staged 파일명

# 파일 변경 취소 (수정 전으로 복원)
git restore 파일명

# 최근 커밋 메시지 수정
git commit --amend -m "새 메시지"
```

### 1-4. GitHub에서 최신 코드 가져오기

```bash
git pull origin main
```

---

## 2. 챗봇 실행 방법 (터미널)

### 2-1. 터미널에서 챗봇 실행

```bash
# 프로젝트 폴더로 이동
cd /Users/Dev/josun_chatbot

# 챗봇 실행
python chat.py
```

### 2-2. 챗봇 사용법

```
==================================================
조선호텔 FAQ 챗봇
==================================================
종료: quit 또는 q 입력
호텔 변경: /hotel 입력
==================================================

질문> 체크인 시간이 언제야?

어느 호텔에 대해 문의하시나요?
  1. 조선 팰리스
  2. 그랜드 조선 부산
  3. 그랜드 조선 제주
  4. 레스케이프
  5. 그래비티 판교
  0. 전체 호텔 (호텔 미지정)

호텔 선택 (0-5)> 1

답변: 조선 팰리스의 체크인 시간은 오후 3시(15:00)입니다.
```

### 2-3. 챗봇 명령어

| 명령어 | 설명 |
|--------|------|
| `/hotel` | 호텔 변경 |
| `quit` 또는 `q` | 종료 |
| `Ctrl + C` | 강제 종료 |

### 2-4. Python 코드에서 직접 호출

```python
from rag.graph import RAGGraph

# RAG 그래프 초기화
rag = RAGGraph()

# 질문하기
result = rag.chat("체크인 시간 알려줘", hotel="josun_palace")

print(result["answer"])  # 답변
print(result["score"])   # 유사도 점수
print(result["sources"]) # 출처 URL
```

---

## 3. 웹 UI 실행 방법

웹 브라우저에서 챗봇을 사용하려면 **2개의 서버**를 실행해야 합니다.

### 3-1. 서버 실행 (터미널 2개 필요)

**터미널 1 - RAG API 서버 (포트 8000)**
```bash
cd /Users/Dev/josun_chatbot
python rag/server.py
```

**터미널 2 - UI 서버 (포트 3000)**
```bash
cd /Users/Dev/josun_chatbot/ui
python -m http.server 3000
```

### 3-2. 브라우저 접속

```
http://localhost:3000
```

### 3-3. 웹 UI 사용법

1. **호텔 선택**: 화면 중앙의 호텔 버튼 클릭 또는 우측 상단 드롭다운
2. **질문 입력**: 하단 입력창에 질문 작성
3. **전송**: Enter 키 또는 전송 버튼 클릭
4. **줄바꿈**: Shift + Enter

### 3-4. 주의사항

- `file://` 프로토콜로 직접 열면 CORS 에러 발생
- 반드시 `http://localhost:3000`으로 접속
- RAG 서버(8000)가 먼저 실행되어 있어야 함

### 3-5. 한 줄 실행 (백그라운드)

```bash
# 두 서버 동시 실행
cd /Users/Dev/josun_chatbot && python rag/server.py &
cd /Users/Dev/josun_chatbot/ui && python -m http.server 3000 &

# 종료 시
pkill -f "server.py"
pkill -f "http.server"
```

---

## 4. 평가 및 테스트

### 4-1. 전체 평가 실행

```bash
# 기본 평가 (48개 테스트)
python tests/evaluate.py

# 결과 저장
python tests/evaluate.py --save

# 빠른 평가 (10개만)
python tests/evaluate.py --quick
```

### 4-2. 특정 호텔/카테고리만 평가

```bash
# 특정 호텔
python tests/evaluate.py --hotel josun_palace

# 특정 카테고리
python tests/evaluate.py --category 체크인/아웃
```

### 4-3. 평가 결과 확인

```bash
# 결과 파일 위치
cat tests/eval_report.json
```

**주요 지표:**
- `accuracy`: 정확도 (목표: 80% 이상)
- `coverage`: 답변 생성률
- `hallucination_rate`: 할루시네이션 비율 (목표: 0%)
- `avg_score`: 평균 유사도 점수

---

## 5. 모니터링 대시보드

### 5-1. 대시보드 실행

```bash
# 최근 7일 통계
python monitor/dashboard.py

# 기간 지정
python monitor/dashboard.py --days 30

# 요약만 표시
python monitor/dashboard.py --summary

# JSON 보고서 내보내기
python monitor/dashboard.py --export
```

### 5-2. 실패 케이스 분석

```bash
# 실패 케이스 확인
python monitor/collector.py

# 보고서 저장
python monitor/collector.py --save
```

### 5-3. 로그 파일 위치

```
logs/
└── chat_20260204.jsonl   # 일별 로그 (JSONL 형식)
```

---

## 6. 데이터 관리

### 6-1. 데이터 인덱싱

```bash
# 보충 데이터 인덱싱 (주차, 위치 정보 등)
python pipeline/index_supplementary.py

# 전체 재인덱싱 (시간 소요)
python pipeline/indexer.py
```

### 6-2. 데이터 파일 구조

```
data/
├── clean/                    # 정제된 데이터
│   ├── josun_palace/         # 호텔별 폴더
│   ├── grand_josun_busan/
│   └── supplementary_info.json  # 보충 데이터
├── chunks/                   # 청크 데이터
│   └── _all_hotels_chunks.json
└── index/                    # 인덱스 (Vector DB)
    ├── chroma/               # ChromaDB
    └── bm25_index.pkl        # BM25 인덱스
```

### 6-3. 테스트 데이터 수정

테스트 케이스 추가/수정: `tests/golden_qa.json`

```json
{
  "id": "test_id_001",
  "query": "질문 내용",
  "hotel": "josun_palace",
  "category": "체크인/아웃",
  "expected_keywords": ["15:00", "오후 3시"],
  "forbidden_keywords": ["부산", "제주"],
  "min_score": 0.7
}
```

---

## 7. 문제 해결

### 7-1. 자주 발생하는 오류

| 오류 | 원인 | 해결 방법 |
|------|------|----------|
| `ModuleNotFoundError` | 패키지 미설치 | `pip install -r requirements.txt` |
| `Connection refused` | Ollama 미실행 | `ollama serve` 실행 |
| `No chunks found` | 인덱스 없음 | `python pipeline/indexer.py` |

### 7-2. Ollama 관련

```bash
# Ollama 실행 확인
ollama list

# 모델 다운로드
ollama pull qwen2.5:7b-instruct-q4_K_M

# Ollama 서버 시작
ollama serve
```

### 7-3. 환경 설정

```bash
# 가상환경 활성화 (pyenv 사용 시)
pyenv activate josun_chatbot

# 패키지 설치
pip install -r requirements.txt
```

### 7-4. 정확도가 낮을 때

1. **평가 실행**: `python tests/evaluate.py --save`
2. **실패 케이스 확인**: `python monitor/collector.py`
3. **데이터 보강**: `data/clean/supplementary_info.json` 수정
4. **재인덱싱**: `python pipeline/index_supplementary.py`
5. **재평가**: `python tests/evaluate.py --save`

---

## 빠른 참조

### 주요 명령어 모음

```bash
# 챗봇 실행
python chat.py

# 평가 실행
python tests/evaluate.py --save

# 대시보드
python monitor/dashboard.py

# Git 푸시
git add . && git commit -m "메시지" && git push origin main
```

### 호텔 키 목록

| 호텔명 | 키 |
|--------|-----|
| 조선 팰리스 | `josun_palace` |
| 그랜드 조선 부산 | `grand_josun_busan` |
| 그랜드 조선 제주 | `grand_josun_jeju` |
| 레스케이프 | `lescape` |
| 그래비티 판교 | `gravity_pangyo` |

---

## 문의

문제가 발생하면 GitHub Issues에 등록하거나 로그 파일을 확인하세요.

- **GitHub**: https://github.com/holyshine11/JosunHotle_chatbot
- **로그 위치**: `logs/chat_YYYYMMDD.jsonl`
