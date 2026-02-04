"""
CLI 대시보드
- 터미널에서 통계 조회
- 실패 케이스 확인
- 보고서 생성
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# 상위 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.analyzer import LogAnalyzer


class Dashboard:
    """CLI 대시보드"""

    # 호텔 이름 매핑
    HOTEL_NAMES = {
        "josun_palace": "조선 팰리스",
        "grand_josun_busan": "그랜드 조선 부산",
        "grand_josun_jeju": "그랜드 조선 제주",
        "lescape": "레스케이프",
        "gravity_pangyo": "그래비티 판교",
        "unknown": "미분류"
    }

    def __init__(self):
        self.analyzer = LogAnalyzer()

    def printHeader(self, title: str):
        """헤더 출력"""
        print("\n" + "=" * 60)
        print(f" {title}")
        print("=" * 60)

    def printSummary(self, stats: dict):
        """요약 통계 출력"""
        self.printHeader("요약 통계")

        print(f"  총 질문 수: {stats['total']:,}개")
        print(f"  답변 성공률: {stats['success_rate']*100:.1f}%")
        print(f"  평균 유사도: {stats['avg_score']:.3f}")
        print(f"  검증 실패: {stats['verification_issues']}건")

    def printHotelStats(self, byHotel: dict):
        """호텔별 통계 출력"""
        self.printHeader("호텔별 통계")

        # 총 질문 수 기준 정렬
        sortedHotels = sorted(
            byHotel.items(),
            key=lambda x: x[1]["total"],
            reverse=True
        )

        print(f"  {'호텔':<20} {'질문':<8} {'성공':<8} {'성공률':<8}")
        print("  " + "-" * 44)

        for hotel, data in sortedHotels:
            hotelName = self.HOTEL_NAMES.get(hotel, hotel)[:18]
            total = data["total"]
            success = data["success"]
            rate = success / total * 100 if total > 0 else 0
            print(f"  {hotelName:<20} {total:<8} {success:<8} {rate:.1f}%")

    def printCategoryStats(self, byCategory: dict):
        """카테고리별 통계 출력"""
        self.printHeader("카테고리별 통계")

        sortedCategories = sorted(
            byCategory.items(),
            key=lambda x: x[1]["total"],
            reverse=True
        )

        print(f"  {'카테고리':<16} {'질문':<8} {'성공':<8} {'성공률':<8}")
        print("  " + "-" * 40)

        for category, data in sortedCategories:
            catName = (category or "미분류")[:14]
            total = data["total"]
            success = data["success"]
            rate = success / total * 100 if total > 0 else 0
            print(f"  {catName:<16} {total:<8} {success:<8} {rate:.1f}%")

    def printDateStats(self, byDate: dict):
        """일별 통계 출력"""
        self.printHeader("일별 추이")

        sortedDates = sorted(byDate.items(), reverse=True)[:7]  # 최근 7일

        print(f"  {'날짜':<12} {'질문':<8} {'성공':<8} {'성공률':<8}")
        print("  " + "-" * 36)

        for date, data in sortedDates:
            total = data["total"]
            success = data["success"]
            rate = success / total * 100 if total > 0 else 0
            print(f"  {date:<12} {total:<8} {success:<8} {rate:.1f}%")

    def printFailedCases(self, failedCases: list[dict], limit: int = 10):
        """실패 케이스 출력"""
        self.printHeader(f"실패 케이스 (최근 {limit}개)")

        if not failedCases:
            print("  실패 케이스가 없습니다.")
            return

        for i, case in enumerate(failedCases[:limit], 1):
            print(f"\n  [{i}] {case.get('query', '')[:50]}")
            hotel = self.HOTEL_NAMES.get(case.get("hotel"), case.get("hotel", ""))
            print(f"      호텔: {hotel}")
            print(f"      점수: {case.get('score', 0):.3f}")
            print(f"      사유: {case.get('reason', '')}")

    def printTopQueries(self, topQueries: list[dict]):
        """자주 묻는 질문 출력"""
        self.printHeader("자주 묻는 질문 TOP 10")

        if not topQueries:
            print("  데이터가 없습니다.")
            return

        print(f"  {'순위':<4} {'질문':<40} {'횟수':<6} {'성공률':<8}")
        print("  " + "-" * 58)

        for i, item in enumerate(topQueries, 1):
            query = item["query"][:38]
            count = item["count"]
            rate = item["success_rate"] * 100
            print(f"  {i:<4} {query:<40} {count:<6} {rate:.1f}%")

    def show(self, days: int = 7, showFailed: bool = True, showTop: bool = True):
        """대시보드 표시

        Args:
            days: 분석할 기간 (일)
            showFailed: 실패 케이스 표시 여부
            showTop: 자주 묻는 질문 표시 여부
        """
        print("\n" + "=" * 60)
        print(f" RAG 챗봇 모니터링 대시보드")
        print(f" 분석 기간: 최근 {days}일")
        print(f" 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # 로그 로드
        logs = self.analyzer.loadLogs(days=days)

        if not logs:
            print("\n  로그 데이터가 없습니다.")
            print(f"  로그 경로: {self.analyzer.logPath}")
            return

        # 통계 계산
        stats = self.analyzer.calculateStats(logs)

        # 출력
        self.printSummary(stats)
        self.printHotelStats(stats["by_hotel"])
        self.printCategoryStats(stats["by_category"])
        self.printDateStats(stats["by_date"])

        if showFailed:
            failedCases = self.analyzer.getFailedCases(logs)
            self.printFailedCases(failedCases)

        if showTop:
            topQueries = self.analyzer.getTopQueries(logs)
            self.printTopQueries(topQueries)

        print("\n" + "=" * 60)

    def exportReport(self, days: int = 7) -> str:
        """보고서 내보내기"""
        logs = self.analyzer.loadLogs(days=days)
        reportPath = self.analyzer.exportReport(logs)
        print(f"\n[보고서 저장] {reportPath}")
        return reportPath


def main():
    """CLI 진입점"""
    parser = argparse.ArgumentParser(description="RAG 챗봇 모니터링 대시보드")
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=7,
        help="분석할 기간 (일, 기본값: 7)"
    )
    parser.add_argument(
        "--no-failed",
        action="store_true",
        help="실패 케이스 숨기기"
    )
    parser.add_argument(
        "--no-top",
        action="store_true",
        help="자주 묻는 질문 숨기기"
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="JSON 보고서 내보내기"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="요약만 표시"
    )

    args = parser.parse_args()

    dashboard = Dashboard()

    if args.export:
        dashboard.exportReport(days=args.days)
    elif args.summary:
        dashboard.show(
            days=args.days,
            showFailed=False,
            showTop=False
        )
    else:
        dashboard.show(
            days=args.days,
            showFailed=not args.no_failed,
            showTop=not args.no_top
        )


if __name__ == "__main__":
    main()
