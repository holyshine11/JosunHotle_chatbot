"""
실패 케이스 자동 수집기
- 정기적으로 로그 분석
- 실패 케이스 식별 및 분류
- 개선 포인트 제안
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.analyzer import LogAnalyzer


class FailedCaseCollector:
    """실패 케이스 수집기"""

    # 실패 원인 분류
    FAILURE_TYPES = {
        "low_score": "검색 점수 낮음 (threshold 미달)",
        "no_evidence": "근거 문서 없음",
        "verification_failed": "답변 검증 실패",
        "hallucination": "할루시네이션 의심"
    }

    def __init__(self):
        self.analyzer = LogAnalyzer()
        self.outputPath = Path(__file__).parent.parent / "reports" / "failed_cases"
        self.outputPath.mkdir(parents=True, exist_ok=True)

    def collect(self, days: int = 1) -> dict:
        """실패 케이스 수집 및 분류

        Args:
            days: 분석할 기간

        Returns:
            분류된 실패 케이스
        """
        logs = self.analyzer.loadLogs(days=days)

        classified = {
            "low_score": [],
            "no_evidence": [],
            "verification_failed": [],
            "hallucination": []
        }

        for log in logs:
            if not log.get("evidence_passed", False):
                score = log.get("top_score", 0)

                if score < 0.3:
                    classified["no_evidence"].append(log)
                elif score < 0.65:
                    classified["low_score"].append(log)
                else:
                    classified["no_evidence"].append(log)

            if not log.get("verification_passed", True):
                issues = log.get("verification_issues", [])
                if any("할루시네이션" in issue or "추측" in issue for issue in issues):
                    classified["hallucination"].append(log)
                else:
                    classified["verification_failed"].append(log)

        return classified

    def analyze(self, classified: dict) -> dict:
        """실패 패턴 분석

        Returns:
            {
                "total_failures": int,
                "by_type": dict,
                "by_hotel": dict,
                "by_category": dict,
                "recommendations": list
            }
        """
        allFailures = []
        for failures in classified.values():
            allFailures.extend(failures)

        # 중복 제거 (동일 timestamp)
        seenTimestamps = set()
        uniqueFailures = []
        for f in allFailures:
            ts = f.get("timestamp", "")
            if ts not in seenTimestamps:
                seenTimestamps.add(ts)
                uniqueFailures.append(f)

        # 유형별 통계
        byType = {
            ftype: len(failures)
            for ftype, failures in classified.items()
        }

        # 호텔별 통계
        byHotel = defaultdict(int)
        for f in uniqueFailures:
            hotel = f.get("hotel") or "unknown"
            byHotel[hotel] += 1

        # 카테고리별 통계
        byCategory = defaultdict(int)
        for f in uniqueFailures:
            category = f.get("category") or "unknown"
            byCategory[category] += 1

        # 개선 권장사항 생성
        recommendations = self._generateRecommendations(classified, byHotel, byCategory)

        return {
            "total_failures": len(uniqueFailures),
            "by_type": byType,
            "by_hotel": dict(byHotel),
            "by_category": dict(byCategory),
            "recommendations": recommendations
        }

    def _generateRecommendations(
        self,
        classified: dict,
        byHotel: dict,
        byCategory: dict
    ) -> list[str]:
        """개선 권장사항 생성"""
        recommendations = []

        # 낮은 점수 케이스가 많으면
        if len(classified["low_score"]) > 5:
            recommendations.append(
                "검색 점수가 낮은 케이스가 많습니다. "
                "청크 품질 개선 또는 쿼리 확장을 고려하세요."
            )

        # 근거 없음 케이스가 많으면
        if len(classified["no_evidence"]) > 3:
            recommendations.append(
                "근거 문서를 찾지 못하는 케이스가 있습니다. "
                "데이터셋 보강이 필요합니다."
            )

        # 할루시네이션 케이스가 있으면
        if len(classified["hallucination"]) > 0:
            recommendations.append(
                "할루시네이션이 감지되었습니다. "
                "답변 검증 로직 강화가 필요합니다."
            )

        # 특정 호텔에서 실패가 집중되면
        if byHotel:
            maxHotel = max(byHotel.items(), key=lambda x: x[1])
            if maxHotel[1] > 3:
                recommendations.append(
                    f"'{maxHotel[0]}' 호텔에서 실패가 집중됩니다. "
                    "해당 호텔 데이터를 점검하세요."
                )

        # 특정 카테고리에서 실패가 집중되면
        if byCategory:
            maxCategory = max(byCategory.items(), key=lambda x: x[1])
            if maxCategory[1] > 3:
                recommendations.append(
                    f"'{maxCategory[0]}' 카테고리에서 실패가 집중됩니다. "
                    "해당 유형의 데이터를 보강하세요."
                )

        if not recommendations:
            recommendations.append("특별한 문제 패턴이 감지되지 않았습니다.")

        return recommendations

    def saveReport(self, classified: dict, analysis: dict) -> str:
        """보고서 저장

        Returns:
            저장된 파일 경로
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "analysis": analysis,
            "failed_cases": {
                ftype: [
                    {
                        "timestamp": f.get("timestamp"),
                        "query": f.get("query"),
                        "hotel": f.get("hotel"),
                        "category": f.get("category"),
                        "score": f.get("top_score"),
                        "answer_preview": f.get("final_answer", "")[:200]
                    }
                    for f in failures[:20]  # 유형별 최대 20개
                ]
                for ftype, failures in classified.items()
            }
        }

        filename = f"failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.outputPath / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return str(filepath)

    def printSummary(self, analysis: dict):
        """요약 출력"""
        print("\n" + "=" * 60)
        print(" 실패 케이스 분석 결과")
        print("=" * 60)

        print(f"\n  총 실패: {analysis['total_failures']}건")

        print("\n  [유형별]")
        for ftype, count in analysis["by_type"].items():
            if count > 0:
                desc = self.FAILURE_TYPES.get(ftype, ftype)
                print(f"    - {desc}: {count}건")

        if analysis["by_hotel"]:
            print("\n  [호텔별]")
            for hotel, count in sorted(analysis["by_hotel"].items(), key=lambda x: -x[1]):
                print(f"    - {hotel}: {count}건")

        if analysis["by_category"]:
            print("\n  [카테고리별]")
            for category, count in sorted(analysis["by_category"].items(), key=lambda x: -x[1]):
                print(f"    - {category}: {count}건")

        print("\n  [권장사항]")
        for rec in analysis["recommendations"]:
            print(f"    - {rec}")

        print("\n" + "=" * 60)


def main():
    """CLI 진입점"""
    import argparse

    parser = argparse.ArgumentParser(description="실패 케이스 수집 및 분석")
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=1,
        help="분석할 기간 (일, 기본값: 1)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="보고서 저장"
    )

    args = parser.parse_args()

    collector = FailedCaseCollector()

    # 수집 및 분석
    classified = collector.collect(days=args.days)
    analysis = collector.analyze(classified)

    # 출력
    collector.printSummary(analysis)

    # 저장
    if args.save:
        filepath = collector.saveReport(classified, analysis)
        print(f"\n[보고서 저장] {filepath}")


if __name__ == "__main__":
    main()
