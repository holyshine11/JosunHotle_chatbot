#!/bin/bash
# ============================================================
# 비용 상한 감시 스크립트 (cron: 매시간 실행)
# - 월간 가동 시간 추적 → 예산 초과 시 서비스 자동 정지
# - 80% 경고 로그 + 100% 하드 정지
# ============================================================

# ==== 설정 (필요 시 수정) ====
MAX_MONTHLY_WON=10000          # 월 예산 상한 (원)
PUBLIC_IP_MONTHLY_WON=4032     # 공인 IP 월 고정비 (원, NCP 기준)
SERVER_HOURLY_WON=18           # Micro 서버 시간당 단가 (원)
WARN_PERCENT=80                # 경고 임계치 (%)
PROJECT_DIR="/opt/josun_chatbot"
TRACKER_FILE="${PROJECT_DIR}/deploy/.monthly_hours"
LOG_TAG="[비용감시]"

# ==== 서버 예산 계산 ====
BUDGET_FOR_SERVER=$((MAX_MONTHLY_WON - PUBLIC_IP_MONTHLY_WON))
MAX_HOURS=$((BUDGET_FOR_SERVER / SERVER_HOURLY_WON))

# ==== 월 변경 감지 & 초기화 ====
CURRENT_MONTH=$(date +%Y-%m)

if [ -f "$TRACKER_FILE" ]; then
    STORED_MONTH=$(sed -n '1p' "$TRACKER_FILE")
    CURRENT_HOURS=$(sed -n '2p' "$TRACKER_FILE")

    # 새 달이면 카운터 리셋
    if [ "$STORED_MONTH" != "$CURRENT_MONTH" ]; then
        echo "${LOG_TAG} 새 달 시작 (${CURRENT_MONTH}) → 카운터 리셋"
        CURRENT_HOURS=0
    fi
else
    CURRENT_HOURS=0
fi

# ==== 1시간 추가 ====
NEW_HOURS=$((CURRENT_HOURS + 1))

# 파일 업데이트 (원자적 쓰기)
TMP_FILE="${TRACKER_FILE}.tmp"
echo "$CURRENT_MONTH" > "$TMP_FILE"
echo "$NEW_HOURS" >> "$TMP_FILE"
mv "$TMP_FILE" "$TRACKER_FILE"

# ==== 비용 추정 ====
ESTIMATED_COST=$((NEW_HOURS * SERVER_HOURLY_WON + PUBLIC_IP_MONTHLY_WON))
WARN_THRESHOLD=$((MAX_MONTHLY_WON * WARN_PERCENT / 100))

echo "${LOG_TAG} $(date '+%m/%d %H:%M') | 가동 ${NEW_HOURS}h/${MAX_HOURS}h | 추정 ${ESTIMATED_COST}원/${MAX_MONTHLY_WON}원"

# ==== 80% 경고 (소프트) ====
if [ "$ESTIMATED_COST" -ge "$WARN_THRESHOLD" ] && [ "$ESTIMATED_COST" -lt "$MAX_MONTHLY_WON" ]; then
    echo "${LOG_TAG} ⚠️  예산 ${WARN_PERCENT}% 도달 (${ESTIMATED_COST}원/${MAX_MONTHLY_WON}원)"
    # 슬랙 웹훅 알림 (선택, URL 설정 시 활성화)
    # SLACK_WEBHOOK="https://hooks.slack.com/services/xxx"
    # curl -sf -X POST "$SLACK_WEBHOOK" -H 'Content-type: application/json' \
    #     -d "{\"text\":\"⚠️ 챗봇 서버 예산 ${WARN_PERCENT}% 도달: ${ESTIMATED_COST}원/${MAX_MONTHLY_WON}원\"}" || true
fi

# ==== 100% 자동 정지 (하드) ====
if [ "$ESTIMATED_COST" -ge "$MAX_MONTHLY_WON" ]; then
    echo "${LOG_TAG} 🛑 예산 초과! (${ESTIMATED_COST}원 ≥ ${MAX_MONTHLY_WON}원) → 서비스 정지"

    # Docker 서비스 정지
    cd "$PROJECT_DIR"
    docker compose down 2>/dev/null || true

    # 정지 기록
    echo "STOPPED_AT=$(date '+%Y-%m-%d %H:%M:%S')" >> "$TRACKER_FILE"

    echo "${LOG_TAG} 서비스 정지 완료. 복구: cd ${PROJECT_DIR} && docker compose up -d"
fi
