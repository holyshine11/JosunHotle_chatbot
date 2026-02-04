"""
로그 분석 모듈
- JSONL 로그 파일 파싱
- 통계 계산
- 실패 케이스 수집
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional


class LogAnalyzer:
    """로그 분석기"""

    def __init__(self, logPath: str = None):
        if logPath:
            self.logPath = Path(logPath)
        else:
            self.logPath = Path(__file__).parent.parent / "logs"

    def loadLogs(self, days: int = 7, date: str = None) -> list[dict]:
        """로그 로드

        Args:
            days: 최근 N일간 로그 (기본 7일)
            date: 특정 날짜 (YYYYMMDD 형식)

        Returns:
            로그 엔트리 리스트
        """
        logs = []

        if date:
            # 특정 날짜
            logFile = self.logPath / f"chat_{date}.jsonl"
            if logFile.exists():
                logs.extend(self._parseLogFile(logFile))
        else:
            # 최근 N일
            today = datetime.now()
            for i in range(days):
                targetDate = today - timedelta(days=i)
                logFile = self.logPath / f"chat_{targetDate.strftime('%Y%m%d')}.jsonl"
                if logFile.exists():
                    logs.extend(self._parseLogFile(logFile))

        return logs

    def _parseLogFile(self, logFile: Path) -> list[dict]:
        """JSONL 파일 파싱"""
        entries = []
        with open(logFile, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries

    def calculateStats(self, logs: list[dict]) -> dict:
        """통계 계산

        Returns:
            {
                "total": int,
                "success_rate": float,
                "avg_score": float,
                "by_hotel": dict,
                "by_category": dict,
                "by_date": dict,
                "verification_issues": int
            }
        """
        if not logs:
            return {
                "total": 0,
                "success_rate": 0.0,
                "avg_score": 0.0,
                "by_hotel": {},
                "by_category": {},
                "by_date": {},
                "verification_issues": 0
            }

        total = len(logs)
        successCount = sum(1 for log in logs if log.get("evidence_passed", False))
        scores = [log.get("top_score", 0) for log in logs if log.get("top_score")]
        verificationIssues = sum(1 for log in logs if not log.get("verification_passed", True))

        # 호텔별 통계
        byHotel = defaultdict(lambda: {"total": 0, "success": 0})
        for log in logs:
            hotel = log.get("hotel") or "unknown"
            byHotel[hotel]["total"] += 1
            if log.get("evidence_passed", False):
                byHotel[hotel]["success"] += 1

        # 카테고리별 통계
        byCategory = defaultdict(lambda: {"total": 0, "success": 0})
        for log in logs:
            category = log.get("category") or "unknown"
            byCategory[category]["total"] += 1
            if log.get("evidence_passed", False):
                byCategory[category]["success"] += 1

        # 날짜별 통계
        byDate = defaultdict(lambda: {"total": 0, "success": 0})
        for log in logs:
            timestamp = log.get("timestamp", "")
            if timestamp:
                date = timestamp[:10]  # YYYY-MM-DD
                byDate[date]["total"] += 1
                if log.get("evidence_passed", False):
                    byDate[date]["success"] += 1

        return {
            "total": total,
            "success_rate": successCount / total if total > 0 else 0.0,
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
            "by_hotel": dict(byHotel),
            "by_category": dict(byCategory),
            "by_date": dict(byDate),
            "verification_issues": verificationIssues
        }

    def getFailedCases(self, logs: list[dict], limit: int = 20) -> list[dict]:
        """실패 케이스 수집

        Args:
            logs: 로그 리스트
            limit: 최대 개수

        Returns:
            실패 케이스 리스트 (최근 순)
        """
        failed = []
        for log in logs:
            if not log.get("evidence_passed", False):
                failed.append({
                    "timestamp": log.get("timestamp"),
                    "query": log.get("query"),
                    "hotel": log.get("hotel"),
                    "category": log.get("category"),
                    "score": log.get("top_score", 0),
                    "reason": "threshold 미달" if log.get("top_score", 0) < 0.65 else "근거 부족",
                    "answer": log.get("final_answer", "")[:100]  # 답변 미리보기
                })

        # 검증 실패 케이스
        for log in logs:
            if not log.get("verification_passed", True):
                failed.append({
                    "timestamp": log.get("timestamp"),
                    "query": log.get("query"),
                    "hotel": log.get("hotel"),
                    "category": log.get("category"),
                    "score": log.get("top_score", 0),
                    "reason": "검증 실패: " + ", ".join(log.get("verification_issues", [])),
                    "answer": log.get("final_answer", "")[:100]
                })

        # 최근 순 정렬
        failed.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return failed[:limit]

    def getTopQueries(self, logs: list[dict], limit: int = 10) -> list[dict]:
        """자주 묻는 질문 분석

        Returns:
            [{"query": str, "count": int, "success_rate": float}]
        """
        queryStats = defaultdict(lambda: {"count": 0, "success": 0})

        for log in logs:
            query = log.get("query", "").strip()
            if query:
                # 쿼리 정규화 (간단한 버전)
                normalizedQuery = query.lower()
                queryStats[normalizedQuery]["count"] += 1
                if log.get("evidence_passed", False):
                    queryStats[normalizedQuery]["success"] += 1

        # 정렬
        sortedQueries = sorted(
            queryStats.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )[:limit]

        return [
            {
                "query": q,
                "count": stats["count"],
                "success_rate": stats["success"] / stats["count"] if stats["count"] > 0 else 0
            }
            for q, stats in sortedQueries
        ]

    def exportReport(self, logs: list[dict], outputPath: str = None) -> str:
        """분석 보고서 내보내기

        Args:
            logs: 로그 리스트
            outputPath: 출력 파일 경로 (없으면 자동 생성)

        Returns:
            저장된 파일 경로
        """
        stats = self.calculateStats(logs)
        failed = self.getFailedCases(logs, limit=50)
        topQueries = self.getTopQueries(logs)

        report = {
            "generated_at": datetime.now().isoformat(),
            "period": {
                "start": min(log.get("timestamp", "") for log in logs) if logs else "",
                "end": max(log.get("timestamp", "") for log in logs) if logs else ""
            },
            "summary": stats,
            "failed_cases": failed,
            "top_queries": topQueries
        }

        if not outputPath:
            reportDir = self.logPath.parent / "reports"
            reportDir.mkdir(parents=True, exist_ok=True)
            outputPath = reportDir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(outputPath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return str(outputPath)
