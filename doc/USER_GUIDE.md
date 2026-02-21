# 조선호텔 RAG 챗봇 사용 설명서

> 작성일: 2026-02-04 (최종 수정: 2026-02-21)

---

## 목차

1. [로컬 실행](#1-로컬-실행)
2. [평가 및 테스트](#2-평가-및-테스트)
3. [데이터 관리](#3-데이터-관리)
4. [문제 해결](#4-문제-해결)
5. [Git 사용법](#5-git-사용법)
6. [NCP 서버 배포](#6-ncp-서버-배포)
7. [서버 운영 및 유지보수](#7-서버-운영-및-유지보수)

---

## 1. 로컬 실행

### 터미널 챗봇

```bash
cd /Users/Dev/josun_chatbot
python chat.py
```

- `quit` 또는 `q`: 종료
- `/hotel`: 호텔 변경

### 웹 UI (터미널 2개 필요)

```bash
# 터미널 1 - API 서버
python rag/server.py

# 터미널 2 - UI 서버
cd ui && python -m http.server 3000
```

브라우저에서 `http://localhost:3000` 접속

> 반드시 `http://localhost:3000`으로 접속해야 합니다 (`file://`로 열면 에러).

---

## 2. 평가 및 테스트

```bash
# 전체 평가 (결과 저장)
python tests/evaluate.py --save

# 빠른 평가 (10개만)
python tests/evaluate.py --quick

# 특정 호텔만
python tests/evaluate.py --hotel josun_palace

# 멀티턴 테스트
python tests/test_multiturn.py --save
```

결과 파일: `tests/eval_report.json`

---

## 3. 데이터 관리

### 인덱싱

```bash
# 보충 데이터만 인덱싱
python pipeline/index_supplementary.py

# 전체 재인덱싱
python pipeline/index_all.py
```

### 주요 폴더

| 폴더 | 설명 |
|------|------|
| `data/clean/` | 호텔별 정제 데이터 |
| `data/supplementary/` | 보충 데이터 (메뉴, 콜키지 등) |
| `data/index/` | 검색 인덱스 (Chroma, BM25) |
| `data/logs/` | 채팅 로그 |

### 호텔 ID

| 호텔 | ID |
|------|-----|
| 조선 팰리스 | `josun_palace` |
| 그랜드 조선 부산 | `grand_josun_busan` |
| 그랜드 조선 제주 | `grand_josun_jeju` |
| 레스케이프 | `lescape` |
| 그래비티 판교 | `gravity_pangyo` |

---

## 4. 문제 해결

| 오류 | 해결 방법 |
|------|----------|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| `Connection refused` | `ollama serve` 실행 |
| `No chunks found` | `python pipeline/index_all.py` |
| 정확도 낮음 | `data/supplementary/` 데이터 보강 → `python pipeline/index_all.py` → `python tests/evaluate.py --save` |

---

## 5. Git 사용법

  # 1. 로컬에서 push                                                                                                                 
  git push origin main                                                                                                                 
                                                                                                                                       
  # 2. NCP 서버에 SSH 접속
  ssh root@223.130.159.146

  # 3. 서버에서 수동 반영 (도커 빌드 까지 해야 적용 됨)
  cd /opt/josun_chatbot
  git pull origin main
  docker build -t josun_chatbot-app .
  docker compose up -d

### 기본 흐름

```bash
git add .
git commit -m "feat: 변경 내용 설명"
git push origin main
```

### 커밋 메시지 규칙

| 접두사 | 용도 |
|--------|------|
| `feat:` | 새 기능 |
| `fix:` | 버그 수정 |
| `docs:` | 문서 수정 |
| `refactor:` | 리팩토링 |

### 자주 쓰는 명령어

```bash
git pull origin main          # 최신 코드 가져오기
git restore --staged 파일명    # add 취소
git restore 파일명             # 수정 취소
```

---

## 6. NCP 서버 배포

네이버 클라우드 플랫폼(NCP)에 Docker로 배포하는 방법입니다.

### 6-0. 사전 준비

| 항목 | 설명 |
|------|------|
| NCP 계정 | https://www.ncloud.com 회원가입 + 결제수단 등록 |
| Groq API 키 | https://console.groq.com 에서 무료 발급 (`gsk_`로 시작) |

> **Groq API가 필요한 이유**
: NCP 서버에는 GPU가 없어서 로컬 LLM(Ollama)을 쓸 수 없습니다. 대신 Groq 클라우드 API로 LLM을 호출합니다 (무료 티어: 일 500,000 토큰, 약 300~500회 대화).

### 6-1. NCP 인프라 생성

NCP 콘솔(https://console.ncloud.com)에서 아래 순서대로 생성합니다.

#### 1) VPC 생성
- VPC > VPC Management > VPC 생성
- 이름: `josun-vpc`, IP 대역: `10.0.0.0/16`

#### 2) Subnet 생성
- VPC > Subnet Management > Subnet 생성
- 이름: `josun-subnet`, IP 대역: `10.0.1.0/24`
- VPC: josun-vpc, 용도: 일반, 인터넷 게이트웨이: 연결

#### 3) ACG (방화벽) 생성
- VPC > ACG > ACG 생성
- 이름: `josun-acg`, VPC: josun-vpc

**규칙 설정 (필수!):**

| 방향 | 프로토콜 | 접근 소스 | 포트 |
|------|----------|----------|------|
| Inbound | TCP | 0.0.0.0/0 | 22 |
| Inbound | TCP | 0.0.0.0/0 | 80 |
| Outbound | TCP | 0.0.0.0/0 | 1-65535 |

> ACG 규칙이 없으면 SSH 접속이 안 됩니다 (무한 대기).

#### 4) 서버 생성
- Server > 서버 생성
- 이미지: **Ubuntu 24.04**
- 서버 타입: **Standard (2vCPU/8GB RAM)**
- 요금제: **시간 요금제** (시간당 115원, 월 ~82,800원)
- VPC/Subnet: josun-vpc / josun-subnet
- ACG: josun-acg
- 인증키: 새로 생성 → `.pem` 파일 안전한 곳에 저장

> Compact (2vCPU/4GB) 타입은 NCP에서 더 이상 제공하지 않습니다.
> Micro (1GB)는 메모리 부족으로 실사용 불가합니다.

#### 5) 공인 IP 신청
- Server > Public IP > 공인 IP 신청 → 생성한 서버에 연결

### 6-2. SSH 접속

#### 관리자 비밀번호 확인
1. NCP 콘솔 > Server > 서버 선택
2. "서버 관리 및 설정 변경" > "관리자 비밀번호 확인"
3. `.pem` 파일 업로드 → 비밀번호 표시 (복사해두기)

#### SSH 접속
```bash
ssh root@공인IP주소
```
비밀번호 입력 (위에서 확인한 값)

> 처음 접속 시 `Are you sure you want to continue connecting?` → `yes` 입력

### 6-3. 서버 초기 설정

SSH 접속 후 아래 명령어를 **한 줄씩** 실행합니다.

#### 1) Swap 생성
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

> `GROQ_API_KEY=` 뒤에 본인의 Groq API 키를 입력하세요. `=` 양쪽에 **공백 없이** 작성!

#### 5) Basic Auth 계정 생성
```bash
apt-get install -y apache2-utils
htpasswd -cb /opt/josun_chatbot/deploy/.htpasswd admin 원하는비밀번호
```

#### 6) 비용 감시 설정
```bash
# Standard 서버 기준 (월 10만원 상한, 시간당 115원)
sed -i 's/MAX_MONTHLY_WON=10000/MAX_MONTHLY_WON=100000/' /opt/josun_chatbot/deploy/cost-guard.sh
sed -i 's/SERVER_HOURLY_WON=18/SERVER_HOURLY_WON=115/' /opt/josun_chatbot/deploy/cost-guard.sh
chmod +x /opt/josun_chatbot/deploy/*.sh
(crontab -l 2>/dev/null; echo "0 * * * * /opt/josun_chatbot/deploy/cost-guard.sh >> /var/log/cost-guard.log 2>&1") | crontab -
```

> 80% (80,000원) 도달 시 경고, 100% (100,000원) 초과 시 서비스 자동 정지

### 6-4. Docker 빌드 & 실행

```bash
cd /opt/josun_chatbot
docker build -t josun_chatbot-app .
docker compose up -d
```

> 빌드 시간: 약 5~10분

#### 시작 확인
```bash
docker compose logs -f app
```

아래 로그가 나오면 정상:
```
[Warm-up] 모델 사전 로딩 시작...
[모델 로딩] intfloat/multilingual-e5-small...
[BM25] 인덱스 로드 완료
[서버] RAG 그래프 초기화 완료
INFO:     Uvicorn running on 0.0.0.0:8000
```

`Ctrl+C`로 로그 종료 후 브라우저에서 `http://223.130.159.146/` 접속
→ Basic Auth 로그인 (admin / 설정한 비밀번호)

> 마이크(음성입력)는 HTTPS가 필요합니다. 도메인 + SSL 인증서 설정 전에는 텍스트 입력만 가능합니다.

---

## 7. 서버 운영 및 유지보수

### 7-1. 서버 접속

```bash
ssh root@223.130.159.146
```
비밀번호: NCP 콘솔 > Server > 서버 관리 및 설정 변경 > 관리자 비밀번호 확인

### 7-2. 서버 파일 구조

```
/opt/josun_chatbot/              ← 프로젝트 루트
├── .env                         ← 환경변수 (Groq 키, 설정)
├── docker-compose.yml           ← Docker 서비스 정의
├── Dockerfile                   ← 앱 이미지 빌드
├── rag/                         ← RAG 챗봇 코드
├── data/                        ← 데이터 + 인덱스
├── ui/                          ← 웹 UI (HTML/CSS/JS)
├── deploy/
│   ├── .htpasswd                ← Basic Auth 계정
│   ├── ops.sh                   ← 운영 명령어 모음
│   ├── cost-guard.sh            ← 비용 감시 스크립트
│   └── nginx.conf               ← nginx 설정
└── logs/                        ← 앱 로그 (Docker 볼륨)

/var/log/cost-guard.log          ← 비용 감시 로그
/swapfile                        ← Swap 파일 (4GB)
```

### 7-3. 운영 명령어

```bash
cd /opt/josun_chatbot

./deploy/ops.sh logs       # 실시간 로그
./deploy/ops.sh status     # 상태 확인
./deploy/ops.sh restart    # 재시작
./deploy/ops.sh stop       # 서비스 중지 (비용 절약)
```

### 7-4. 로그 확인

```bash
# 앱 로그 (실시간)
docker compose logs -f app

# nginx 로그 (접속 기록)
docker compose logs -f nginx

# 최근 100줄만
docker compose logs --tail 100 app

# 비용 감시 로그
cat /var/log/cost-guard.log
```

> `Ctrl+C`로 실시간 로그 보기를 종료합니다.

### 7-5. 코드 업데이트 (재배포)

로컬에서 코드 수정 → `git push` 후, 서버에서:
```bash
cd /opt/josun_chatbot
git pull origin main
docker build -t josun_chatbot-app .
docker compose up -d
```

### 7-6. 유지보수

#### 서비스 상태 확인
```bash
docker ps                  # 컨테이너 상태
docker stats --no-stream   # 메모리/CPU 사용량
df -h                      # 디스크 사용량
```

#### 서비스 중지/시작
```bash
# 중지
cd /opt/josun_chatbot && docker compose down

# 시작
cd /opt/josun_chatbot && docker compose up -d
```

#### 환경변수 변경 시
```bash
nano /opt/josun_chatbot/.env

# 반영 (재빌드 + 재시작)
cd /opt/josun_chatbot
docker build -t josun_chatbot-app .
docker compose up -d
```

#### Basic Auth 비밀번호 변경
```bash
htpasswd -cb /opt/josun_chatbot/deploy/.htpasswd admin 새비밀번호
cd /opt/josun_chatbot && docker compose restart nginx
```

#### Docker 디스크 정리 (용량 부족 시)
```bash
docker system prune -f
```

### 7-7. 문제 해결

| 증상 | 해결 |
|------|------|
| SSH 무한 대기 | ACG에 포트 22 규칙 추가 |
| `502 Bad Gateway` | 앱 시작 중, 3~5분 대기 (`docker compose logs -f app`으로 확인) |
| 서버 죽음 (OOM) | `.env`에 `RERANKER_ENABLED=false` → 재빌드 |
| `.env` 미적용 | `=` 양쪽 공백 제거 후 `docker build` → `docker compose up -d` |
| 디스크 부족 | `docker system prune -f`로 정리 |
| 서버 재부팅 후 서비스 안 뜸 | `cd /opt/josun_chatbot && docker compose up -d` |

### 7-8. 비용 관리

- 매시간 `cost-guard.sh`가 비용을 추적합니다
- 월 10만원 초과 시 서비스 자동 정지
- **수동 정지**: `./deploy/ops.sh stop`
- **NCP 콘솔에서 서버 정지**: 서버 요금도 절약 (공인 IP 비용 ~4,000원/월은 유지)
- **비용 로그 확인**: `cat /var/log/cost-guard.log`

---

## 문의

- **GitHub**: https://github.com/holyshine11/JosunHotle_chatbot
- **로그 위치**: `data/logs/chat_YYYYMMDD.jsonl`
