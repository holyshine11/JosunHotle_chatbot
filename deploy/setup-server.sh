#!/bin/bash
# ============================================================
# NCP 서버 초기 설정 스크립트 (1회 실행)
# 대상: Ubuntu 22.04 LTS, Micro (1vCPU/1GB) 또는 Compact (2vCPU/4GB)
# 실행: sudo bash setup-server.sh
# ============================================================
set -e

echo "=========================================="
echo " NCP 서버 초기 설정 시작"
echo "=========================================="

# ---- 1. Swap 생성 (Micro 서버 필수, Compact면 선택) ----
SWAP_SIZE="4G"
if [ ! -f /swapfile ]; then
    echo "[1/6] Swap ${SWAP_SIZE} 생성..."
    fallocate -l ${SWAP_SIZE} /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    # Swap 사용 성향: 가능하면 RAM 우선 사용
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
    sysctl -p
    echo "  -> Swap 활성화 완료"
else
    echo "[1/6] Swap 이미 존재 → 스킵"
fi

# ---- 2. Docker 설치 ----
if ! command -v docker &> /dev/null; then
    echo "[2/6] Docker 설치..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources-list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable docker
    echo "  -> Docker 설치 완료"
else
    echo "[2/6] Docker 이미 설치됨 → 스킵"
fi

# ---- 3. 프로젝트 클론 ----
PROJECT_DIR="/opt/josun_chatbot"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "[3/6] 프로젝트 클론..."
    echo "  GitHub 리포지토리 URL을 입력하세요:"
    read -r REPO_URL
    git clone "$REPO_URL" "$PROJECT_DIR"
    echo "  -> 클론 완료"
else
    echo "[3/6] 프로젝트 이미 존재 → git pull"
    cd "$PROJECT_DIR" && git pull origin main
fi

# ---- 4. 환경변수 설정 ----
cd "$PROJECT_DIR"
if [ ! -f .env ]; then
    echo "[4/6] 환경변수 설정..."
    cp deploy/.env.example .env
    echo "  Groq API 키를 입력하세요 (https://console.groq.com 에서 발급):"
    read -r GROQ_KEY
    sed -i "s/gsk_여기에_발급받은_키_입력/${GROQ_KEY}/" .env
    echo "  -> .env 생성 완료"
else
    echo "[4/6] .env 이미 존재 → 스킵"
fi

# ---- 5. Basic Auth (htpasswd) 생성 ----
if [ ! -f deploy/.htpasswd ]; then
    echo "[5/6] Basic Auth 계정 생성..."
    apt-get install -y apache2-utils 2>/dev/null || true
    echo "  사용자명 (기본: admin):"
    read -r AUTH_USER
    AUTH_USER=${AUTH_USER:-admin}
    echo "  비밀번호:"
    read -rs AUTH_PASS
    htpasswd -cb deploy/.htpasswd "$AUTH_USER" "$AUTH_PASS"
    echo ""
    echo "  -> Basic Auth 설정 완료 (${AUTH_USER})"
else
    echo "[5/6] .htpasswd 이미 존재 → 스킵"
fi

# ---- 6. 비용 감시 cron 등록 ----
echo "[6/6] 비용 감시 cron 등록..."
chmod +x deploy/cost-guard.sh deploy/deploy.sh deploy/ops.sh
CRON_ENTRY="0 * * * * /opt/josun_chatbot/deploy/cost-guard.sh >> /var/log/cost-guard.log 2>&1"
(crontab -l 2>/dev/null | grep -v "cost-guard" ; echo "$CRON_ENTRY") | crontab -
echo "  -> 매시간 비용 감시 cron 등록 완료"

echo ""
echo "=========================================="
echo " 초기 설정 완료!"
echo "=========================================="
echo ""
echo " 다음 단계:"
echo "   1) .env 파일 확인:  cat .env"
echo "   2) 첫 배포 실행:    cd $PROJECT_DIR && docker compose up -d --build"
echo "   3) 상태 확인:       ./deploy/ops.sh status"
echo "   4) 로그 확인:       ./deploy/ops.sh logs"
echo ""
echo " 접속: http://<서버_공인IP>  (Basic Auth 인증 필요)"
echo "=========================================="
