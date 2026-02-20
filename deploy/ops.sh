#!/bin/bash
# ============================================================
# 운영 명령 모음 (5개 명령으로 모든 운영 커버)
# 사용법: ./deploy/ops.sh {logs|restart|status|version|stop}
# ============================================================

PROJECT_DIR="/opt/josun_chatbot"
cd "$PROJECT_DIR"

case "$1" in
    logs)
        # 실시간 로그 확인 (Ctrl+C로 종료)
        docker compose logs -f --tail 100
        ;;

    restart)
        # 컨테이너 재시작 (코드 변경 없이)
        echo "[재시작] 컨테이너 재시작 중..."
        docker compose restart
        sleep 5
        echo "[상태]"
        docker compose ps
        ;;

    status)
        # 서비스 상태 + 헬스체크 + 리소스 사용량
        echo "=== 컨테이너 상태 ==="
        docker compose ps
        echo ""
        echo "=== 헬스체크 ==="
        curl -s http://localhost:8000/health 2>/dev/null | python3 -m json.tool || echo "  응답 없음"
        echo ""
        echo "=== 리소스 사용량 ==="
        docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null
        echo ""
        echo "=== 디스크 ==="
        df -h / | tail -1
        echo ""
        echo "=== 비용 추적 ==="
        if [ -f deploy/.monthly_hours ]; then
            cat deploy/.monthly_hours
        else
            echo "  추적 데이터 없음"
        fi
        ;;

    version)
        # 현재 배포 버전 (최근 커밋)
        echo "=== 배포 버전 ==="
        git log --oneline -3
        echo ""
        echo "=== 이미지 정보 ==="
        docker images josun_chatbot-app --format "table {{.Tag}}\t{{.Size}}\t{{.CreatedAt}}" 2>/dev/null
        ;;

    stop)
        # 서비스 중지 (비용 절약)
        echo "[중지] 서비스 중지 중..."
        docker compose down
        echo "  -> 중지 완료 (서버 자체는 NCP 콘솔에서 정지)"
        ;;

    *)
        echo "============================================"
        echo " 조선호텔 챗봇 운영 명령"
        echo "============================================"
        echo ""
        echo " ./deploy/ops.sh logs      로그 실시간 확인"
        echo " ./deploy/ops.sh restart   컨테이너 재시작"
        echo " ./deploy/ops.sh status    상태/헬스체크/리소스"
        echo " ./deploy/ops.sh version   배포 버전 확인"
        echo " ./deploy/ops.sh stop      서비스 중지"
        echo ""
        ;;
esac
