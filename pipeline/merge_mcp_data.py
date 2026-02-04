"""
MCP 크롤링 데이터를 기존 파이프라인에 통합하는 스크립트
"""

import json
from pathlib import Path
from datetime import datetime
import hashlib


def loadMcpData(mcpDir: Path) -> list:
    """MCP 크롤링 데이터 로드"""
    allFaqs = []

    for jsonFile in mcpDir.glob("*.json"):
        with open(jsonFile, "r", encoding="utf-8") as f:
            data = json.load(f)

        hotel = data["hotel"]
        hotelName = data["hotel_name"]
        sourceUrl = data["source_url"]

        for faq in data["faqs"]:
            allFaqs.append({
                "hotel": hotel,
                "hotel_name": hotelName,
                "source_url": sourceUrl,
                "category": faq["category"],
                "question": faq["question"],
                "answer": faq["answer"]
            })

    return allFaqs


def convertToCleanFormat(faqs: list, outputDir: Path) -> int:
    """FAQ 데이터를 clean 형식으로 변환"""
    outputDir.mkdir(parents=True, exist_ok=True)

    count = 0
    for faq in faqs:
        # 고유 ID 생성
        contentHash = hashlib.sha256(
            f"{faq['hotel']}:{faq['question']}".encode()
        ).hexdigest()[:12]

        cleanDoc = {
            "id": f"mcp_{faq['hotel']}_{contentHash}",
            "hotel": faq["hotel"],
            "hotel_name": faq["hotel_name"],
            "source_url": faq["source_url"],
            "category": faq["category"],
            "doc_type": "faq",
            "title": faq["question"],
            "content": f"Q: {faq['question']}\nA: {faq['answer']}",
            "question": faq["question"],
            "answer": faq["answer"],
            "language": "ko",
            "crawled_at": datetime.now().isoformat(),
            "source": "mcp_playwright"
        }

        outFile = outputDir / f"mcp_{faq['hotel']}_{contentHash}.json"
        with open(outFile, "w", encoding="utf-8") as f:
            json.dump(cleanDoc, f, ensure_ascii=False, indent=2)

        count += 1

    return count


def main():
    baseDir = Path(__file__).parent.parent
    mcpDir = baseDir / "data" / "raw" / "mcp_crawled"
    cleanDir = baseDir / "data" / "clean"

    print("[MCP 데이터 통합] 시작")
    print(f"  입력: {mcpDir}")
    print(f"  출력: {cleanDir}")

    # MCP 데이터 로드
    faqs = loadMcpData(mcpDir)
    print(f"  로드된 FAQ: {len(faqs)}개")

    # Clean 형식으로 변환
    count = convertToCleanFormat(faqs, cleanDir)
    print(f"  생성된 문서: {count}개")

    print("[MCP 데이터 통합] 완료")
    print("\n다음 단계:")
    print("  1. python pipeline/chunker.py  # 청크 재생성")
    print("  2. python pipeline/indexer.py  # 인덱스 재구축")


if __name__ == "__main__":
    main()
