#!/bin/bash
# ============================================================
# 배포 스크립트 (GitHub Actions 또는 수동 실행)
# - git pull → 이전 이미지 백업 → 빌드 → 헬스체크 → 실패 시 롤백
# ============================================================
set -e

PROJECT_DIR="/opt/josun_chatbot"
cd "$PROJECT_DIR"

echo "[배포] $(date '+%Y-%m-%d %H:%M:%S') 시작"

# 1. 코드 업데이트
echo "[1/5] git pull..."
git pull origin main

# 2. 이전 이미지 백업 (롤백용)
echo "[2/5] 이전 이미지 백업..."
docker tag josun_chatbot-app:latest josun_chatbot-app:prev 2>/dev/null || true

# 3. 빌드 & 배포
echo "[3/5] Docker 빌드 & 배포..."
docker compose up -d --build --remove-orphans

# 4. 헬스체크 대기 (최대 180초, 모델 로딩 시간 고려)
echo "[4/5] 헬스체크 대기..."
MAX_WAIT=180
WAIT=0
INTERVAL=10

while [ $WAIT -lt $MAX_WAIT ]; do
    sleep $INTERVAL
    WAIT=$((WAIT + INTERVAL))

    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "  -> 헬스체크 통과 (${WAIT}초)"
        break
    fi
    echo "  -> 대기 중... (${WAIT}/${MAX_WAIT}초)"
done

# 5. 결과 판정
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "[5/5] 배포 성공!"
    # 미사용 이미지 정리
    docker image prune -f 2>/dev/null || true
    echo "[배포] 완료 $(date '+%Y-%m-%d %H:%M:%S')"
    exit 0
else
    echo "[5/5] 배포 실패 → 롤백 시작"
    docker compose down

    # 이전 이미지로 롤백
    if docker image inspect josun_chatbot-app:prev > /dev/null 2>&1; then
        docker tag josun_chatbot-app:prev josun_chatbot-app:latest
        docker compose up -d
        echo "[롤백] 이전 버전으로 복구 완료"
    else
        echo "[롤백] 이전 이미지 없음 - 수동 복구 필요"
    fi
    exit 1
fi
