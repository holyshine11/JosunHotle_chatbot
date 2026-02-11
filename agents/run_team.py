"""
조선호텔 RAG 챗봇 - Agent Team 실행 스크립트

사용법:
    python agents/run_team.py                     # Phase 1부터 순차 실행
    python agents/run_team.py --agent speed       # 특정 에이전트만 실행
    python agents/run_team.py --agent speed,data  # 복수 에이전트 병렬 실행
    python agents/run_team.py --phase 2           # 특정 Phase만 실행
    python agents/run_team.py --dry-run           # 프롬프트 확인만 (실행 안 함)
    python agents/run_team.py --list              # 에이전트 목록 출력
"""

import asyncio
import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

# 프로젝트 루트 기준
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from claude_code_sdk import query, ClaudeCodeOptions
from agents.team_config import TEAM_AGENTS, EXECUTION_PHASES, AgentConfig


# ──────────────────────────────────────────────
# 결과 저장 디렉토리
# ──────────────────────────────────────────────
RESULTS_DIR = PROJECT_ROOT / "agents" / "results"


def buildAllowedTools(agent: AgentConfig) -> list[str]:
    """에이전트 담당 파일 기반으로 허용 도구 결정"""
    # 모든 에이전트: 읽기 + 검색
    tools = ["Read", "Glob", "Grep"]
    # 수정 가능 파일이 있으면 편집 도구 추가
    if agent.ownerFiles:
        tools.extend(["Edit", "Write"])
    return tools


def buildPrompt(agent: AgentConfig) -> str:
    """시스템 프롬프트 + 작업 프롬프트 + 파일 제약 조합"""
    fileConstraint = ""
    if agent.ownerFiles:
        ownerList = "\n".join(f"  - {f}" for f in agent.ownerFiles)
        fileConstraint += f"\n## 수정 가능한 파일\n{ownerList}\n"
    if agent.readOnlyFiles:
        readList = "\n".join(f"  - {f}" for f in agent.readOnlyFiles)
        fileConstraint += f"\n## 참조 파일 (읽기만)\n{readList}\n"

    return f"""{agent.systemPrompt}
{fileConstraint}
---
## 작업 지시
{agent.taskPrompt}

## 출력 형식
작업 완료 후 반드시 아래 형식으로 요약하세요:

### 변경 요약
- 변경한 파일과 수정 내용

### 개선 효과
- 구체적인 개선 사항

### 주의 사항
- 후속 테스트 필요 여부
- 다른 에이전트 작업과의 호환성
"""


async def runAgent(agent: AgentConfig, acceptEdits: bool = False) -> dict:
    """단일 에이전트 실행"""
    agentName = agent.name
    permMode = "acceptEdits" if acceptEdits else "plan"
    startTime = datetime.now()
    print(f"\n{'='*60}")
    print(f"  [{agentName.upper()}] {agent.role} 시작")
    print(f"  모델: {agent.model} | 모드: {permMode} | 최대 턴: {agent.maxTurns}")
    print(f"  담당 파일: {', '.join(agent.ownerFiles)}")
    print(f"{'='*60}\n")

    prompt = buildPrompt(agent)
    options = ClaudeCodeOptions(
        model=agent.model,
        cwd=str(PROJECT_ROOT),
        max_turns=agent.maxTurns,
        system_prompt=agent.systemPrompt,
        permission_mode=permMode,
    )

    result = {
        "agent": agentName,
        "role": agent.role,
        "model": agent.model,
        "startTime": startTime.isoformat(),
        "messages": [],
        "finalResult": "",
        "status": "running",
    }

    try:
        async for message in query(prompt=prompt, options=options):
            # 결과 메시지 수집
            msgType = type(message).__name__
            if hasattr(message, "content"):
                content = message.content
                if isinstance(content, str):
                    result["messages"].append({"type": msgType, "content": content})
                elif isinstance(content, list):
                    for block in content:
                        if hasattr(block, "text"):
                            result["messages"].append({"type": msgType, "content": block.text})

            # ResultMessage = 최종 결과
            if msgType == "ResultMessage":
                if hasattr(message, "result"):
                    result["finalResult"] = message.result
                elif hasattr(message, "content"):
                    result["finalResult"] = str(message.content)

        result["status"] = "completed"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"  [{agentName.upper()}] 오류 발생: {e}")

    endTime = datetime.now()
    result["endTime"] = endTime.isoformat()
    result["duration"] = str(endTime - startTime)

    print(f"\n  [{agentName.upper()}] 완료 ({result['duration']})")
    print(f"  상태: {result['status']}")

    return result


async def runParallel(agentNames: list[str], acceptEdits: bool = False) -> list[dict]:
    """복수 에이전트 병렬 실행"""
    agents = [TEAM_AGENTS[name] for name in agentNames if name in TEAM_AGENTS]
    if not agents:
        print("유효한 에이전트가 없습니다.")
        return []

    print(f"\n{'#'*60}")
    print(f"  병렬 실행: {', '.join(a.name for a in agents)}")
    print(f"{'#'*60}")

    tasks = [runAgent(agent, acceptEdits=acceptEdits) for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 예외 처리
    processedResults = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            processedResults.append({
                "agent": agents[i].name,
                "status": "error",
                "error": str(r),
            })
        else:
            processedResults.append(r)

    return processedResults


def saveResults(results: list[dict], label: str):
    """결과를 JSON으로 저장"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = RESULTS_DIR / f"team_result_{label}_{timestamp}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {filepath}")
    return filepath


def printSummary(results: list[dict]):
    """실행 결과 요약 출력"""
    print(f"\n{'='*60}")
    print("  실행 결과 요약")
    print(f"{'='*60}")
    for r in results:
        status = "✅" if r.get("status") == "completed" else "❌"
        agent = r.get("agent", "unknown")
        duration = r.get("duration", "N/A")
        print(f"  {status} [{agent}] - {duration}")
        if r.get("error"):
            print(f"     오류: {r['error']}")
    print(f"{'='*60}\n")


def printDryRun():
    """에이전트 프롬프트 미리보기"""
    for name, agent in TEAM_AGENTS.items():
        print(f"\n{'='*60}")
        print(f"  [{name.upper()}] {agent.role}")
        print(f"  모델: {agent.model}")
        print(f"  수정 파일: {agent.ownerFiles}")
        print(f"  참조 파일: {agent.readOnlyFiles}")
        print(f"{'='*60}")
        print(f"\n--- 프롬프트 미리보기 (첫 500자) ---")
        prompt = buildPrompt(agent)
        print(prompt[:500])
        print("...\n")


def printList():
    """에이전트 목록 출력"""
    print(f"\n{'='*60}")
    print("  등록된 에이전트 목록")
    print(f"{'='*60}")
    for name, agent in TEAM_AGENTS.items():
        print(f"  [{name}] {agent.role}")
        print(f"    모델: {agent.model} | 턴: {agent.maxTurns}")
        print(f"    수정: {', '.join(agent.ownerFiles)}")
        print()

    print("  실행 Phase:")
    for phase in EXECUTION_PHASES:
        mode = "병렬" if phase["parallel"] else "순차"
        print(f"    Phase {phase['phase']}: {phase['name']} ({mode})")
        print(f"      에이전트: {', '.join(phase['agents'])}")
    print(f"{'='*60}\n")


async def main():
    parser = argparse.ArgumentParser(description="조선호텔 RAG Agent Team")
    parser.add_argument("--agent", type=str, help="실행할 에이전트 (콤마 구분: speed,data)")
    parser.add_argument("--phase", type=int, help="실행할 Phase 번호")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 확인")
    parser.add_argument("--list", action="store_true", help="에이전트 목록 출력")
    parser.add_argument("--accept-edits", action="store_true",
                        help="편집 자동 승인 (주의: 파일이 자동 수정됨)")

    args = parser.parse_args()

    # 목록 출력
    if args.list:
        printList()
        return

    # 드라이런
    if args.dry_run:
        printDryRun()
        return

    print(f"\n{'#'*60}")
    print("  조선호텔 RAG Agent Team 시작")
    print(f"  시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  프로젝트: {PROJECT_ROOT}")
    print(f"{'#'*60}")

    useAcceptEdits = args.accept_edits
    if useAcceptEdits:
        print("  모드: acceptEdits (편집 자동 승인)")
    else:
        print("  모드: plan (계획만 수립, 편집은 승인 필요)")

    allResults = []

    # 특정 에이전트 실행
    if args.agent:
        agentNames = [a.strip() for a in args.agent.split(",")]
        invalid = [n for n in agentNames if n not in TEAM_AGENTS]
        if invalid:
            print(f"알 수 없는 에이전트: {invalid}")
            print(f"사용 가능: {list(TEAM_AGENTS.keys())}")
            return

        if len(agentNames) == 1:
            result = await runAgent(TEAM_AGENTS[agentNames[0]], acceptEdits=useAcceptEdits)
            allResults.append(result)
        else:
            results = await runParallel(agentNames, acceptEdits=useAcceptEdits)
            allResults.extend(results)

        saveResults(allResults, "_".join(agentNames))
        printSummary(allResults)
        return

    # 특정 Phase 실행
    if args.phase:
        phase = next((p for p in EXECUTION_PHASES if p["phase"] == args.phase), None)
        if not phase:
            print(f"Phase {args.phase}를 찾을 수 없습니다.")
            return

        print(f"\n  Phase {phase['phase']}: {phase['name']}")
        if phase["parallel"]:
            results = await runParallel(phase["agents"], acceptEdits=useAcceptEdits)
        else:
            results = []
            for agentName in phase["agents"]:
                r = await runAgent(TEAM_AGENTS[agentName], acceptEdits=useAcceptEdits)
                results.append(r)

        allResults.extend(results)
        saveResults(allResults, f"phase{args.phase}")
        printSummary(allResults)
        return

    # 전체 실행 (Phase 순서대로)
    for phase in EXECUTION_PHASES:
        print(f"\n{'#'*60}")
        print(f"  Phase {phase['phase']}: {phase['name']}")
        print(f"  {phase['description']}")
        print(f"{'#'*60}")

        if phase["parallel"]:
            results = await runParallel(phase["agents"], acceptEdits=useAcceptEdits)
        else:
            results = []
            for agentName in phase["agents"]:
                r = await runAgent(TEAM_AGENTS[agentName], acceptEdits=useAcceptEdits)
                results.append(r)

        allResults.extend(results)

    # 전체 결과 저장
    saveResults(allResults, "full")
    printSummary(allResults)


if __name__ == "__main__":
    asyncio.run(main())
