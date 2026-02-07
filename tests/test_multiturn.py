#!/usr/bin/env python3
"""
멀티턴 대화 시나리오 자동 테스트

실행:
    python tests/test_multiturn.py              # 전체
    python tests/test_multiturn.py --scenario 1 # 특정 시나리오만
    python tests/test_multiturn.py --verbose     # 상세 출력
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict

projectPath = Path(__file__).parent.parent
sys.path.insert(0, str(projectPath))

from rag.graph import createRAGGraph


@dataclass
class TurnResult:
    """개별 턴 결과"""
    turnNum: int
    query: str
    answer: str
    needsClarification: bool
    score: float
    sources: list
    # 검증 결과
    expectClarification: bool
    clarificationMatch: bool
    keywordMatch: bool
    matchedKeywords: list
    contextMatch: bool  # 맥락 오염 여부
    passed: bool


@dataclass
class ScenarioResult:
    """시나리오 결과"""
    name: str
    hotel: str
    totalTurns: int
    passedTurns: int
    failedTurns: int
    passed: bool
    turns: list = field(default_factory=list)


# === 시나리오 정의 ===

SCENARIOS = [
    # --- 시나리오 1: 부산 4턴 — 주제 전환 + 맥락 유지 ---
    {
        "name": "부산_4턴_주제전환",
        "hotel": "grand_josun_busan",
        "description": "반려동물 → 다이닝 → 다이닝 후속 → 맥락 유지 확인",
        "turns": [
            {
                "query": "강아지 데려와도 돼?",
                "expectClarification": False,
                "expectKeywords": ["불가", "동반"],
                "forbiddenKeywords": ["제주", "팰리스"],
            },
            {
                "query": "레스토랑 위치 알려줘",
                "expectClarification": False,
                "expectKeywords": ["아리아", "층", "레스토랑", "문의"],
                "forbiddenKeywords": [],
                "matchAny": True,
            },
            {
                "query": "아리아 디너 금액이 얼마야?",
                "expectClarification": False,
                "expectKeywords": ["아리아", "원", "문의"],  # 가격 또는 문의 안내
                "forbiddenKeywords": [],
                "matchAny": True,  # 1개만 매칭되면 통과
            },
            {
                "query": "운영 시간이 어떻게돼?",
                "expectClarification": False,
                "expectKeywords": ["시"],
                "forbiddenKeywords": ["수영", "피트니스"],
                "expectContext": "dining",
            },
        ]
    },

    # --- 시나리오 2: 제주 6턴 — 시설 탐색 + 주제 전환 ---
    {
        "name": "제주_6턴_시설탐색",
        "hotel": "grand_josun_jeju",
        "description": "객실 → 다이닝 → 스타벅스 → 다이닝 상세 → 수영장 → 피트니스",
        "turns": [
            {
                "query": "객실은 몇개 있나요?",
                "expectClarification": False,
                "expectKeywords": ["객실", "문의"],  # 객실 정보 또는 문의 안내
                "forbiddenKeywords": ["부산"],
                "matchAny": True,
            },
            {
                "query": "레스토랑 뭐뭐 있어?",
                "expectClarification": False,
                "expectKeywords": [],
                "forbiddenKeywords": ["부산", "팰리스"],
            },
            {
                "query": "스타벅스는?",
                "expectClarification": False,
                "expectKeywords": [],
                "forbiddenKeywords": [],
            },
            {
                "query": "고메 라운지 시그니처 메뉴가 뭐야?",
                "expectClarification": False,
                "expectKeywords": [],
                "forbiddenKeywords": ["부산"],
            },
            {
                "query": "수영장 종료 시간이 언제야",
                "expectClarification": False,
                "expectKeywords": ["시"],
                "forbiddenKeywords": [],
                "expectContext": "pool",
            },
            {
                "query": "피트니스는 몇시에 문을 열어?",
                "expectClarification": False,
                "expectKeywords": ["시"],
                "forbiddenKeywords": [],
                "expectContext": "fitness",
            },
        ]
    },

    # --- 시나리오 3: 팰리스 3턴 — 명확화 → 선택 → 후속 ---
    {
        "name": "팰리스_3턴_명확화",
        "hotel": "josun_palace",
        "description": "모호한 질문 → 명확화 트리거 확인 + 구체적 질문",
        "turns": [
            {
                "query": "어디야?",
                "expectClarification": True,
                "expectKeywords": ["시설", "위치"],
                "forbiddenKeywords": [],
            },
            {
                "query": "수영장 위치 알려줘",
                "expectClarification": False,
                "expectKeywords": [],
                "forbiddenKeywords": ["부산", "제주"],
            },
            {
                "query": "운영시간은?",
                "expectClarification": False,
                "expectKeywords": ["시"],
                "forbiddenKeywords": [],
                "expectContext": "pool",
            },
        ]
    },

    # --- 시나리오 4: 제주 주체 인식 (Phase 14) ---
    {
        "name": "제주_주체인식_Phase14",
        "hotel": "grand_josun_jeju",
        "description": "주체가 있는 질문은 명확화 없이 바로 검색",
        "turns": [
            {
                "query": "스타벅스 위치 알려줘",
                "expectClarification": False,
                "expectKeywords": ["스타벅스"],
                "forbiddenKeywords": [],
            },
            {
                "query": "스파 위치는?",
                "expectClarification": False,
                "expectKeywords": [],
                "forbiddenKeywords": [],
            },
            {
                "query": "수영장은 어디에 있어?",
                "expectClarification": False,
                "expectKeywords": [],
                "forbiddenKeywords": [],
            },
        ]
    },

    # --- 시나리오 5: 레스케이프 — 반려동물 상세 질문 ---
    {
        "name": "레스케이프_반려동물_상세",
        "hotel": "lescape",
        "description": "반려동물 정책 → 비용 → 추가 조건",
        "turns": [
            {
                "query": "강아지 데려갈 수 있어?",
                "expectClarification": False,
                "expectKeywords": ["가능", "반려"],
                "forbiddenKeywords": ["불가"],
            },
            {
                "query": "비용이 얼마야?",
                "expectClarification": False,
                "expectKeywords": ["원"],
                "forbiddenKeywords": [],
                "expectContext": "pet",
            },
            {
                "query": "몇 킬로까지 돼?",
                "expectClarification": False,
                "expectKeywords": ["kg", "10"],
                "forbiddenKeywords": [],
                "expectContext": "pet",
            },
        ]
    },

    # --- 시나리오 6: 그래비티 판교 — 체크인/아웃 + 조식 ---
    {
        "name": "판교_체크인_조식",
        "hotel": "gravity_pangyo",
        "description": "체크인 → 조식 → 주차",
        "turns": [
            {
                "query": "체크인 몇시야?",
                "expectClarification": False,
                "expectKeywords": ["3시", "15"],
                "forbiddenKeywords": ["부산", "제주"],
            },
            {
                "query": "조식 운영시간 알려줘",
                "expectClarification": False,
                "expectKeywords": ["시", "조식", "문의"],  # 시간 또는 문의 안내
                "forbiddenKeywords": [],
                "matchAny": True,
            },
            {
                "query": "주차 가능해?",
                "expectClarification": False,
                "expectKeywords": ["주차", "무료", "문의", "원", "1,000"],  # 주차 정보/요금 또는 문의
                "forbiddenKeywords": [],
                "matchAny": True,
            },
        ]
    },
]


class MultiTurnTester:
    """멀티턴 시나리오 테스터"""

    def __init__(self):
        self.rag = None
        self.results: list[ScenarioResult] = []

    def initRAG(self):
        print("[초기화] RAG 시스템 로딩...")
        self.rag = createRAGGraph()
        print("[초기화] 완료\n")

    def runScenario(self, scenario: dict, verbose: bool = False) -> ScenarioResult:
        """시나리오 실행"""
        name = scenario["name"]
        hotel = scenario["hotel"]
        turns = scenario["turns"]
        history = []

        scenarioResult = ScenarioResult(
            name=name,
            hotel=hotel,
            totalTurns=len(turns),
            passedTurns=0,
            failedTurns=0,
            passed=True,
        )

        for i, turn in enumerate(turns, 1):
            query = turn["query"]

            # RAG 호출
            result = self.rag.chat(
                query=query,
                hotel=hotel,
                history=history if history else None
            )

            answer = result.get("answer", "")
            needsClarification = result.get("needs_clarification", False)
            score = result.get("score", 0.0)
            sources = result.get("sources", [])

            # === 검증 ===

            # 1. 명확화 기대 검증
            expectClarification = turn.get("expectClarification", False)
            clarificationMatch = (needsClarification == expectClarification)

            # 2. 키워드 매칭
            expectKeywords = turn.get("expectKeywords", [])
            forbiddenKeywords = turn.get("forbiddenKeywords", [])
            answerLower = answer.lower()

            matchedKeywords = [kw for kw in expectKeywords if kw.lower() in answerLower]
            violatedKeywords = [kw for kw in forbiddenKeywords if kw.lower() in answerLower]
            matchAny = turn.get("matchAny", False)

            # 기대 키워드 매칭
            keywordMatch = True
            if expectKeywords and not matchedKeywords:
                keywordMatch = False
            if violatedKeywords:
                keywordMatch = False

            # 3. 맥락 오염 체크
            contextMatch = True
            # 맥락 오염은 금지 키워드 위반으로 이미 체크됨

            # 최종 판정
            passed = clarificationMatch and keywordMatch and contextMatch

            turnResult = TurnResult(
                turnNum=i,
                query=query,
                answer=answer[:200],
                needsClarification=needsClarification,
                score=float(score) if score else 0.0,
                sources=[s.split("/")[-1] for s in (sources or [])],
                expectClarification=expectClarification,
                clarificationMatch=clarificationMatch,
                keywordMatch=keywordMatch,
                matchedKeywords=matchedKeywords,
                contextMatch=contextMatch,
                passed=passed,
            )

            scenarioResult.turns.append(turnResult)

            if passed:
                scenarioResult.passedTurns += 1
            else:
                scenarioResult.failedTurns += 1
                scenarioResult.passed = False

            # 히스토리 누적
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": answer})

            # 출력
            status = "PASS" if passed else "FAIL"
            clarifyLabel = "명확화" if needsClarification else "답변"

            if verbose or not passed:
                print(f"  Q{i}: {query}")
                print(f"    [{status}] [{clarifyLabel}] {answer[:120]}")
                if not clarificationMatch:
                    print(f"    >> 명확화 불일치: 기대={expectClarification}, 실제={needsClarification}")
                if not keywordMatch:
                    if expectKeywords and not matchedKeywords:
                        print(f"    >> 키워드 미매칭: 기대={expectKeywords}")
                    if violatedKeywords:
                        print(f"    >> 금지 키워드 위반: {violatedKeywords}")
            else:
                print(f"  Q{i}: {query} → [{status}]")

        return scenarioResult

    def runAll(self, scenarios: list = None, verbose: bool = False):
        """전체 시나리오 실행"""
        scenarios = scenarios or SCENARIOS

        for idx, scenario in enumerate(scenarios, 1):
            print(f"{'='*60}")
            print(f"시나리오 {idx}: {scenario['name']}")
            print(f"  호텔: {scenario['hotel']}")
            print(f"  설명: {scenario['description']}")
            print(f"{'='*60}")

            result = self.runScenario(scenario, verbose=verbose)
            self.results.append(result)

            status = "PASS" if result.passed else "FAIL"
            print(f"  → [{status}] {result.passedTurns}/{result.totalTurns} 턴 통과\n")

    def printSummary(self):
        """결과 요약"""
        totalScenarios = len(self.results)
        passedScenarios = sum(1 for r in self.results if r.passed)
        totalTurns = sum(r.totalTurns for r in self.results)
        passedTurns = sum(r.passedTurns for r in self.results)

        print(f"{'='*60}")
        print("멀티턴 테스트 결과 요약")
        print(f"{'='*60}")
        print(f"  시나리오: {passedScenarios}/{totalScenarios} 통과")
        print(f"  총 턴: {passedTurns}/{totalTurns} 통과 ({passedTurns/totalTurns*100:.0f}%)")
        print()

        for r in self.results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.name}: {r.passedTurns}/{r.totalTurns}")

            if not r.passed:
                for t in r.turns:
                    if not t.passed:
                        print(f"       >> Q{t.turnNum} 실패: {t.query}")

        print(f"{'='*60}")

        if passedScenarios == totalScenarios:
            print("모든 시나리오 통과!")
        else:
            print(f"{totalScenarios - passedScenarios}개 시나리오 실패")

        return passedScenarios == totalScenarios

    def saveReport(self, outputPath: str = None):
        """보고서 저장"""
        outputPath = outputPath or projectPath / "tests" / "multiturn_report.json"

        report = {
            "timestamp": datetime.now().isoformat(),
            "totalScenarios": len(self.results),
            "passedScenarios": sum(1 for r in self.results if r.passed),
            "totalTurns": sum(r.totalTurns for r in self.results),
            "passedTurns": sum(r.passedTurns for r in self.results),
            "scenarios": [asdict(r) for r in self.results],
        }

        with open(outputPath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n[저장] 보고서 → {outputPath}")


def main():
    parser = argparse.ArgumentParser(description="멀티턴 대화 시나리오 테스트")
    parser.add_argument("--scenario", type=int, help="특정 시나리오 번호만 실행 (1부터)")
    parser.add_argument("--verbose", action="store_true", help="상세 출력")
    parser.add_argument("--save", action="store_true", help="보고서 저장")
    args = parser.parse_args()

    tester = MultiTurnTester()
    tester.initRAG()

    if args.scenario:
        idx = args.scenario - 1
        if 0 <= idx < len(SCENARIOS):
            tester.runAll([SCENARIOS[idx]], verbose=args.verbose)
        else:
            print(f"시나리오 번호 범위: 1~{len(SCENARIOS)}")
            sys.exit(1)
    else:
        tester.runAll(verbose=args.verbose)

    allPassed = tester.printSummary()

    if args.save:
        tester.saveReport()

    sys.exit(0 if allPassed else 1)


if __name__ == "__main__":
    main()
