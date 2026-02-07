#!/usr/bin/env python3
"""
RAG 챗봇 자동 평가 스크립트

실행 방법:
    python tests/evaluate.py              # 전체 평가
    python tests/evaluate.py --quick      # 빠른 평가 (10개 샘플)
    python tests/evaluate.py --hotel busan  # 특정 호텔만
    python tests/evaluate.py --category dining  # 특정 카테고리만
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

# 프로젝트 경로 설정
projectPath = Path(__file__).parent.parent
sys.path.insert(0, str(projectPath))

from rag.graph import createRAGGraph


@dataclass
class TestResult:
    """테스트 결과"""
    test_id: str
    query: str
    hotel: Optional[str]
    category: str

    # RAG 결과
    answer: str
    score: float
    evidence_passed: bool

    # 평가 결과
    has_expected: bool       # 기대 키워드 포함 여부
    has_forbidden: bool      # 금지 키워드 포함 여부
    matched_keywords: list   # 매칭된 기대 키워드
    violated_keywords: list  # 매칭된 금지 키워드
    passed: bool             # 최종 통과 여부

    # 추가 정보
    min_score: float
    score_passed: bool


class RAGEvaluator:
    """RAG 평가기"""

    def __init__(self, testPath: str = None):
        self.testPath = testPath or projectPath / "tests" / "golden_qa.json"
        self.rag = None
        self.results: list[TestResult] = []

    def loadTestCases(self) -> list[dict]:
        """테스트 케이스 로드"""
        with open(self.testPath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["test_cases"]

    def initRAG(self):
        """RAG 시스템 초기화"""
        print("[초기화] RAG 시스템 로딩...")
        self.rag = createRAGGraph()
        print("[초기화] 완료")

    def evaluateCase(self, testCase: dict) -> TestResult:
        """단일 테스트 케이스 평가"""
        testId = testCase["id"]
        query = testCase["query"]
        hotel = testCase.get("hotel")
        category = testCase.get("category", "")
        expectedKeywords = testCase.get("expected_keywords", [])
        forbiddenKeywords = testCase.get("forbidden_keywords", [])
        minScore = testCase.get("min_score", 0.65)

        # RAG 실행
        result = self.rag.chat(query, hotel=hotel)
        answer = result["answer"]
        score = result["score"]
        evidencePassed = result["evidence_passed"]

        # 키워드 검사 (대소문자 무시)
        answerLower = answer.lower()

        matchedKeywords = []
        for kw in expectedKeywords:
            if kw.lower() in answerLower:
                matchedKeywords.append(kw)

        violatedKeywords = []
        for kw in forbiddenKeywords:
            if kw.lower() in answerLower:
                violatedKeywords.append(kw)

        # 평가
        hasExpected = len(matchedKeywords) > 0 if expectedKeywords else True
        hasForbidden = len(violatedKeywords) > 0
        scorePassed = score >= minScore

        # 최종 통과: 기대 키워드 있고 + 금지 키워드 없고 + 점수 통과
        passed = hasExpected and not hasForbidden and scorePassed

        return TestResult(
            test_id=testId,
            query=query,
            hotel=hotel,
            category=category,
            answer=answer[:300] + "..." if len(answer) > 300 else answer,
            score=score,
            evidence_passed=evidencePassed,
            has_expected=hasExpected,
            has_forbidden=hasForbidden,
            matched_keywords=matchedKeywords,
            violated_keywords=violatedKeywords,
            passed=passed,
            min_score=minScore,
            score_passed=scorePassed
        )

    def run(self,
            hotelFilter: str = None,
            categoryFilter: str = None,
            limit: int = None,
            verbose: bool = True) -> dict:
        """전체 평가 실행"""

        if not self.rag:
            self.initRAG()

        testCases = self.loadTestCases()

        # 필터링
        if hotelFilter:
            testCases = [t for t in testCases if hotelFilter in (t.get("hotel") or "")]
        if categoryFilter:
            testCases = [t for t in testCases if categoryFilter in t.get("category", "")]
        if limit:
            testCases = testCases[:limit]

        print(f"\n[평가 시작] {len(testCases)}개 테스트 케이스")
        print("=" * 60)

        self.results = []
        passedCount = 0
        failedCases = []

        for i, testCase in enumerate(testCases, 1):
            testId = testCase["id"]

            if verbose:
                print(f"\n[{i}/{len(testCases)}] {testId}")
                print(f"  Q: {testCase['query']}")

            result = self.evaluateCase(testCase)
            self.results.append(result)

            if result.passed:
                passedCount += 1
                if verbose:
                    print(f"  ✓ 통과 (score: {result.score:.3f})")
            else:
                failedCases.append(result)
                if verbose:
                    print(f"  ✗ 실패")
                    if not result.has_expected:
                        print(f"    - 기대 키워드 없음: {testCase.get('expected_keywords', [])}")
                    if result.has_forbidden:
                        print(f"    - 금지 키워드 포함: {result.violated_keywords}")
                    if not result.score_passed:
                        print(f"    - 점수 미달: {result.score:.3f} < {result.min_score}")

        # 결과 요약
        summary = self.calculateMetrics()

        print("\n" + "=" * 60)
        print("[평가 결과 요약]")
        print("=" * 60)
        print(f"  총 테스트: {summary['total']}개")
        print(f"  통과: {summary['passed']}개 ({summary['accuracy']:.1%})")
        print(f"  실패: {summary['failed']}개")
        print()
        print(f"  정확도 (Accuracy): {summary['accuracy']:.1%}")
        print(f"  커버리지 (답변 생성률): {summary['coverage']:.1%}")
        print(f"  할루시네이션율: {summary['hallucination_rate']:.1%}")
        print(f"  평균 유사도 점수: {summary['avg_score']:.3f}")
        print()

        # 카테고리별 결과
        print("[카테고리별 정확도]")
        for cat, acc in summary['category_accuracy'].items():
            print(f"  {cat}: {acc:.1%}")

        # 실패 케이스 요약
        if failedCases:
            print(f"\n[실패 케이스 상위 5개]")
            for result in failedCases[:5]:
                print(f"  - {result.test_id}: {result.query[:40]}...")
                if not result.has_expected:
                    print(f"    → 기대 키워드 미포함")
                if result.has_forbidden:
                    print(f"    → 금지 키워드: {result.violated_keywords}")

        return summary

    def calculateMetrics(self) -> dict:
        """평가 지표 계산"""
        if not self.results:
            return {}

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        # 커버리지: evidence_passed (답변 생성률)
        coverage = sum(1 for r in self.results if r.evidence_passed) / total

        # 할루시네이션율: 금지 키워드 포함률
        hallucination = sum(1 for r in self.results if r.has_forbidden) / total

        # 평균 점수
        avgScore = sum(r.score for r in self.results) / total

        # 카테고리별 정확도
        categoryResults = {}
        for r in self.results:
            cat = r.category or "기타"
            if cat not in categoryResults:
                categoryResults[cat] = {"passed": 0, "total": 0}
            categoryResults[cat]["total"] += 1
            if r.passed:
                categoryResults[cat]["passed"] += 1

        categoryAccuracy = {
            cat: v["passed"] / v["total"]
            for cat, v in categoryResults.items()
        }

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "accuracy": passed / total,
            "coverage": coverage,
            "hallucination_rate": hallucination,
            "avg_score": avgScore,
            "category_accuracy": categoryAccuracy,
            "timestamp": datetime.now().isoformat()
        }

    def saveReport(self, outputPath: str = None):
        """평가 보고서 저장"""
        outputPath = outputPath or projectPath / "tests" / "eval_report.json"

        report = {
            "summary": self.calculateMetrics(),
            "results": [asdict(r) for r in self.results]
        }

        # numpy bool/int 등 JSON 직렬화 호환 처리
        class SafeEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, bool):
                    return bool(obj)
                if hasattr(obj, 'item'):
                    return obj.item()
                return super().default(obj)

        with open(outputPath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, cls=SafeEncoder)

        print(f"\n[저장] 보고서 → {outputPath}")
        return outputPath


def main():
    parser = argparse.ArgumentParser(description="RAG 챗봇 평가")
    parser.add_argument("--quick", action="store_true", help="빠른 평가 (10개 샘플)")
    parser.add_argument("--hotel", type=str, help="특정 호텔만 평가 (예: busan)")
    parser.add_argument("--category", type=str, help="특정 카테고리만 평가 (예: dining)")
    parser.add_argument("--limit", type=int, help="평가할 테스트 케이스 수")
    parser.add_argument("--quiet", action="store_true", help="간략한 출력")
    parser.add_argument("--save", action="store_true", help="보고서 저장")

    args = parser.parse_args()

    evaluator = RAGEvaluator()

    limit = args.limit
    if args.quick:
        limit = 10

    summary = evaluator.run(
        hotelFilter=args.hotel,
        categoryFilter=args.category,
        limit=limit,
        verbose=not args.quiet
    )

    if args.save:
        evaluator.saveReport()

    # 종료 코드: 정확도 80% 미만이면 실패
    if summary["accuracy"] < 0.8:
        print(f"\n⚠️  정확도가 80% 미만입니다. ({summary['accuracy']:.1%})")
        sys.exit(1)
    else:
        print(f"\n✓ 평가 통과! (정확도: {summary['accuracy']:.1%})")
        sys.exit(0)


if __name__ == "__main__":
    main()
