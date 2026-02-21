# 조선호텔 RAG 챗봇 사용 설명서

> 작성일: 2026-02-04 (최종 수정: 2026-02-11)
> 버전: 1.1

---

## 목차

1. [Git 커밋 방법](#1-git-커밋-방법)
2. [챗봇 실행 방법 (터미널)](#2-챗봇-실행-방법-터미널)
3. [웹 UI 실행 방법](#3-웹-ui-실행-방법)
4. [평가 및 테스트](#4-평가-및-테스트)
5. [모니터링 대시보드](#5-모니터링-대시보드)
6. [데이터 관리](#6-데이터-관리)
7. [레스토랑 엔티티 시스템](#7-레스토랑-엔티티-시스템)
8. [문제 해결](#8-문제-해결)
9. [NCP 서버 배포 가이드](#9-ncp-서버-배포-가이드)

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

### 3-2. 브라우저 접속 (크롬에서)

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
# 기본 평가 (65개 테스트)
python tests/evaluate.py

# 결과 저장
python tests/evaluate.py --save

# 빠른 평가 (10개만)
python tests/evaluate.py --quick
```

### 4-2. 멀티턴 테스트

```bash
# 멀티턴 대화 테스트 (6개 시나리오, 22턴)
python tests/test_multiturn.py --save
```

### 4-3. 특정 호텔/카테고리만 평가

```bash
# 특정 호텔
python tests/evaluate.py --hotel josun_palace

# 특정 카테고리
python tests/evaluate.py --category 체크인/아웃
```

### 4-4. 평가 결과 확인

```bash
# 결과 파일 위치
cat tests/eval_report.json
```

**주요 지표:**
- `accuracy`: 정확도 (현재: 100%)
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
data/logs/
└── chat_20260204.jsonl   # 일별 로그 (JSONL 형식)
```

---

## 6. 데이터 관리

### 6-1. 데이터 인덱싱

```bash
# 보충 데이터만 인덱싱
python pipeline/index_supplementary.py

# 전체 재인덱싱 (clean + deep_processed + supplementary 통합)
python pipeline/index_all.py
```

### 6-2. 데이터 파일 구조

```
data/
├── clean/                    # 정제된 데이터
│   ├── josun_palace/         # 호텔별 폴더
│   ├── grand_josun_busan/
│   └── ...
├── deep_processed/           # 심층 가공 데이터
├── supplementary/            # 보충 데이터
│   ├── dining_menu.json      # 레스토랑 메뉴 (44개 항목)
│   ├── corkage_info.json     # 콜키지 정보
│   ├── breakfast_info.json   # 조식 정보
│   └── ...
├── config/
│   └── known_names.json      # 고유명사 화이트리스트
├── chunks/                   # 청크 데이터
│   └── _all_hotels_chunks.json
├── logs/                     # 채팅 로그 (JSONL)
└── index/                    # 인덱스 (Vector DB)
    ├── chroma/               # ChromaDB (736 청크)
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

## 7. 레스토랑 엔티티 시스템

24개 레스토랑의 호텔 매핑을 관리하여, 다른 호텔 소속 레스토랑 질문 시 올바르게 안내합니다.

### 7-1. 동작 방식

| 상황 | 동작 | 예시 |
|------|------|------|
| 현재 호텔에 있는 레스토랑 | 정상 답변 | 팰리스에서 "이타닉 가든 메뉴" → 메뉴 안내 |
| 다른 호텔 1곳에만 있는 레스토랑 | 리다이렉트 + 안내 | 제주에서 "홍연 메뉴" → "홍연은 조선 팰리스에 있습니다" |
| 2곳 이상에 있는 레스토랑 | 명확화 질문 | "팔레드신 메뉴" → "부산, 레스케이프 중 어느 호텔?" |

### 7-2. 공유 레스토랑 목록

| 레스토랑 | 소속 호텔 |
|----------|----------|
| 아리아 | 그랜드 조선 부산, 그랜드 조선 제주 |
| 팔레드 신 | 그랜드 조선 부산, 레스케이프 |
| 조선 델리 | 조선 팰리스, 그랜드 조선 부산, 레스케이프, 그래비티 판교 |

### 7-3. 관련 파일

| 파일 | 역할 |
|------|------|
| `rag/constants.py` | RESTAURANT_HOTEL_MAP (24개 매핑), ALIAS_INDEX |
| `rag/entity.py` | 엔티티 추출/검증 (proceed/redirect/clarify) |
| `data/config/known_names.json` | 고유명사 화이트리스트 |

---

## 8. 문제 해결

### 8-1. 자주 발생하는 오류

| 오류 | 원인 | 해결 방법 |
|------|------|----------|
| `ModuleNotFoundError` | 패키지 미설치 | `pip install -r requirements.txt` |
| `Connection refused` | Ollama 미실행 | `ollama serve` 실행 |
| `No chunks found` | 인덱스 없음 | `python pipeline/indexer.py` |

### 8-2. Ollama 관련

```bash
# Ollama 실행 확인
ollama list

# 모델 다운로드
ollama pull qwen2.5:7b-instruct-q4_K_M

# Ollama 서버 시작
ollama serve
```

### 8-3. 환경 설정

```bash
# 가상환경 활성화 (pyenv 사용 시)
pyenv activate josun_chatbot

# 패키지 설치
pip install -r requirements.txt
```

### 8-4. 정확도가 낮을 때

1. **평가 실행**: `python tests/evaluate.py --save`
2. **실패 케이스 확인**: `python monitor/collector.py`
3. **데이터 보강**: `data/supplementary/` 내 JSON 파일 수정
4. **재인덱싱**: `python pipeline/index_all.py`
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

## 9. NCP 서버 배포 가이드

> 네이버 클라우드 플랫폼(NCP)에 Docker 기반으로 배포하는 방법

### 9-0. 사전 준비

| 항목 | 설명 |
|------|------|
| NCP 계정 | https://www.ncloud.com 회원가입 + 결제수단(카드) 등록 |
| Groq API 키 | https://console.groq.com 에서 무료 발급 (gsk_로 시작) |
| GitHub 리포 | https://github.com/holyshine11/JosunHotle_chatbot |

### 9-1. NCP 인프라 생성 (콘솔에서)

아래 순서대로 NCP 콘솔(https://console.ncloud.com)에서 생성합니다.

#### 1) VPC 생성
- **경로**: VPC > VPC Management > VPC 생성
- **이름**: `josun-vpc`
- **IP 대역**: `10.0.0.0/16`

#### 2) Subnet 생성
- **경로**: VPC > Subnet Management > Subnet 생성
- **이름**: `josun-subnet`
- **IP 대역**: `10.0.1.0/24`
- **VPC**: josun-vpc 선택
- **용도**: 일반
- **인터넷 게이트웨이**: 연결

#### 3) ACG (방화벽) 생성
- **경로**: VPC > ACG > ACG 생성
- **이름**: `josun-acg`
- **VPC**: josun-vpc 선택

**ACG 규칙 설정 (필수!):**

| 방향 | 프로토콜 | 접근 소스 | 포트 |
|------|----------|----------|------|
| Inbound | TCP | 0.0.0.0/0 | 22 (SSH) |
| Inbound | TCP | 0.0.0.0/0 | 80 (HTTP) |
| Outbound | TCP | 0.0.0.0/0 | 1-65535 (전체) |

> **주의**: ACG 규칙이 없으면 SSH 접속 불가 (연결 무한 대기)

#### 4) 서버 생성
- **경로**: Server > 서버 생성
- **이미지**: Ubuntu 24.04
- **서버 타입**: 권장 Compact (2vCPU/4GB RAM) — 아래 참고
- **요금제**: 시간 요금제 (비용 절약)
- **VPC/Subnet**: josun-vpc / josun-subnet
- **ACG**: josun-acg
- **인증키**: 새로 생성 → `.pem` 파일 안전한 곳에 저장

#### 5) 공인 IP 신청
- **경로**: Server > Public IP > 공인 IP 신청
- 생성한 서버에 연결

#### 서버 스펙 권장사항

| 스펙 | RAM | 리랭커 | 검색 속도 | 월 비용(추정) |
|------|-----|--------|----------|-------------|
| Micro (1vCPU/1GB) | 1GB | 불가 (OOM) | 60초+ (Swap) | ~13,000원 |
| **Compact (2vCPU/4GB)** | **4GB** | **가능** | **2~5초** | **~26,000원** |
| Standard (2vCPU/8GB) | 8GB | 가능 | 1~3초 | ~52,000원 |

> **Micro (1GB)는 비권장**: embedding 모델 + ChromaDB + BM25 만으로 메모리 부족.
> Swap 사용 시 검색 69초 이상 소요. 실사용 불가.

### 9-2. SSH 접속

#### 관리자 비밀번호 확인
1. NCP 콘솔 > Server > 서버 선택
2. **"서버 관리 및 설정 변경"** > **"관리자 비밀번호 확인"**
3. `.pem` 파일 업로드 → 비밀번호 표시

#### SSH 접속
```bash
ssh root@<공인IP>
# 비밀번호: NCP 콘솔에서 확인한 값
```

### 9-3. 서버 초기 설정

SSH 접속 후 아래 명령어를 **한 줄씩** 실행합니다.

#### 1) Swap 생성 (Compact 이상이면 선택사항)
```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
echo 'vm.swappiness=10' >> /etc/sysctl.conf
sysctl -p
free -h
```
→ Swap 4G가 보이면 성공

#### 2) Docker 설치
```bash
curl -fsSL https://get.docker.com | sh
docker --version
```
→ `Docker version XX.X.X` 출력되면 성공

#### 3) 프로젝트 클론
```bash
git clone https://github.com/holyshine11/JosunHotle_chatbot.git /opt/josun_chatbot
```

#### 4) 환경변수 설정
```bash
cat > /opt/josun_chatbot/.env << 'EOF'
USE_GROQ=true
GROQ_API_KEY=gsk_여기에_본인_키_입력
GROQ_MODEL=llama-3.1-8b-instant
PORT=8000
RERANKER_ENABLED=true
EOF
```

> **중요**: `GROQ_API_KEY=` 뒤에 본인의 Groq API 키를 입력하세요.
> **중요**: `=` 양쪽에 **공백 없이** 작성해야 Docker가 인식합니다.
> **Micro 서버**: `RERANKER_ENABLED=false`로 변경 (메모리 부족)

#### 5) Basic Auth 계정 생성
```bash
apt-get install -y apache2-utils
htpasswd -cb /opt/josun_chatbot/deploy/.htpasswd admin 원하는비밀번호
```

#### 6) 비용 감시 cron 등록
```bash
chmod +x /opt/josun_chatbot/deploy/*.sh
```
```bash
(crontab -l 2>/dev/null; echo "0 * * * * /opt/josun_chatbot/deploy/cost-guard.sh >> /var/log/cost-guard.log 2>&1") | crontab -
```

### 9-4. Docker 빌드 & 배포

#### 첫 배포
```bash
cd /opt/josun_chatbot
docker build -t josun_chatbot-app .
docker compose up -d
```

> **빌드 시간**: Compact 5~10분, Micro 15~20분

#### 서버 시작 확인
```bash
docker compose logs -f app
```

정상 시작 시 아래 순서로 로그 출력:
```
[Warm-up] 모델 사전 로딩 시작...
[모델 로딩] intfloat/multilingual-e5-small...
  -> 로딩 완료 (차원: 384)
[BM25] 인덱스 로드 완료 (754개 문서)
[서버] RAG 그래프 초기화 완료
[Warm-up] 리랭커 로딩 완료           ← RERANKER_ENABLED=true인 경우
INFO:     Uvicorn running on 0.0.0.0:8000   ← 이 메시지가 나오면 완료!
```

`Ctrl+C`로 로그 종료 후 브라우저 접속:
```
http://<공인IP>
```
→ Basic Auth 로그인 (admin / 설정한 비밀번호)

### 9-5. 운영 명령어

```bash
cd /opt/josun_chatbot

# 실시간 로그
./deploy/ops.sh logs

# 서비스 상태 + 헬스체크 + 리소스 사용량
./deploy/ops.sh status

# 컨테이너 재시작 (코드 변경 없이)
./deploy/ops.sh restart

# 배포 버전 확인
./deploy/ops.sh version

# 서비스 중지 (비용 절약)
./deploy/ops.sh stop
```

### 9-6. 코드 업데이트 (재배포)

로컬에서 코드 수정 → push 후, 서버에서:
```bash
cd /opt/josun_chatbot
git pull origin main
docker build -t josun_chatbot-app .
docker compose up -d
```

또는 GitHub Actions 자동 배포 설정 시 push만 하면 자동 배포됩니다.

### 9-7. GitHub Actions CI/CD 설정

GitHub 리포지토리 > Settings > Secrets > Actions에 아래 값 등록:

| Secret 이름 | 값 |
|------------|-----|
| `NCP_HOST` | 서버 공인 IP |
| `NCP_USER` | `root` |
| `NCP_SSH_KEY` | `.pem` 파일 내용 전체 (-----BEGIN 부터 END----- 까지) |
| `NCP_SSH_PORT` | `22` |

등록 후 `main` 브랜치에 push하면 자동 배포됩니다.

### 9-8. 자주 발생하는 문제

| 증상 | 원인 | 해결 |
|------|------|------|
| SSH 접속 시 무한 대기 | ACG에 포트 22 규칙 없음 | NCP 콘솔에서 ACG Inbound 22번 포트 추가 |
| `502 Bad Gateway` | 앱 컨테이너가 아직 시작 중 | `docker compose logs -f app`으로 시작 상태 확인, 3~5분 대기 |
| 응답 생성 실패 (67초 초과) | 1GB RAM으로 검색 매우 느림 | 4GB 이상 서버로 업그레이드 |
| `리랭커 모델 로딩` 후 서버 죽음 | 리랭커 (~1.1GB)가 OOM 유발 | `.env`에 `RERANKER_ENABLED=false` 추가 후 재시작 |
| Docker build `DeadlineExceeded` | Docker 데몬 타임아웃 | `systemctl restart docker` 후 `docker build -t josun_chatbot-app .` |
| `.env` 환경변수 미적용 | `=` 양쪽에 공백 있음 | `KEY=value` 형태로 공백 없이 작성 |
| `RERANKER_ENABLED=false` 안 먹힘 | Docker 이미지 재빌드 안 함 | `docker build -t josun_chatbot-app .` → `docker compose up -d` |

### 9-9. 비용 관리

- `deploy/cost-guard.sh`: 매시간 가동 시간 추적, 예산 초과 시 자동 정지
- 설정: `MAX_MONTHLY_WON=10000` (기본 1만원, 필요 시 수정)
- 수동 정지: `./deploy/ops.sh stop`
- NCP 콘솔에서 서버 자체를 "정지"하면 서버 요금도 절약 (공인 IP 비용은 유지)

---

## 문의

문제가 발생하면 GitHub Issues에 등록하거나 로그 파일을 확인하세요.

- **GitHub**: https://github.com/holyshine11/JosunHotle_chatbot
- **로그 위치**: `data/logs/chat_YYYYMMDD.jsonl`
