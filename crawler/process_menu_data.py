#!/usr/bin/env python3
"""
크롤링된 레스토랑 메뉴 데이터를 RAG 보충 데이터(dining_menu.json)로 변환
- data/raw/dining_menus_raw.json → data/supplementary/dining_menu.json
- 영문 메뉴명은 제거하고 한글 위주로 정리
- 코스명 + 구성 + 가격을 간결하게 정리
"""

import json
import os
import re

INPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "dining_menus_raw.json")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "supplementary", "dining_menu.json")

SKIP_ENTRIES = {"인쇄하기\n\t\t\t\t다운로드"}
MAX_CHUNK_SIZE = 1500


def cleanAndSimplify(text):
    """메뉴 텍스트를 한글 위주로 정리"""
    text = text.replace("\t", " ")
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 원산지 표시 안내 이하 제거
    originIdx = text.find("원산지 표시 안내")
    if originIdx > 0:
        text = text[:originIdx].rstrip()

    # 영문 전용 줄 제거 (한글이 전혀 없는 줄)
    lines = text.split("\n")
    filteredLines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            filteredLines.append("")
            continue
        # 가격 줄은 유지
        if re.match(r'^[\d,.]+ ?\(?', stripped):
            filteredLines.append(stripped)
            continue
        if re.match(r'^\d{1,3}(,\d{3})*(\s*\/|\s*\()', stripped):
            filteredLines.append(stripped)
            continue
        # 한글이 하나라도 있으면 유지
        if re.search(r'[가-힣]', stripped):
            # 영문 부분 제거 (한글 뒤 영문만)
            # 예: "부용 게살 수프Crab Meat Soup" → "부용 게살 수프"
            # 하지만 "LUNCH", "DINNER" 같은 헤더는 유지
            cleaned = re.sub(r'([가-힣)\]）])\s*[A-Z][a-z].*$', r'\1', stripped)
            # 가격 표시 유지 (숫자,000 패턴)
            filteredLines.append(cleaned)
            continue
        # "or" 같은 짧은 영문은 유지
        if stripped.lower() == "or":
            filteredLines.append(stripped)
            continue
        # 영문 대문자 헤더는 유지 (LUNCH, DINNER, A LA CARTE, FOOD, BEVERAGE 등)
        if stripped.isupper() and len(stripped) < 30:
            filteredLines.append(stripped)
            continue
        # 가격 패턴 포함 줄 유지
        if re.search(r'\d{2,3},\d{3}', stripped):
            filteredLines.append(stripped)
            continue
        # No. + 숫자 패턴 (칵테일 번호 등) 유지
        if re.match(r'^No\.\s*\d+', stripped):
            filteredLines.append(stripped)
            continue
        # 그 외 영문 전용 줄 제거

    result = "\n".join(filteredLines)
    # 연속 빈줄 정리
    result = re.sub(r"\n{3,}", "\n\n", result)
    # 전각 공백 제거
    result = result.replace("　", "")

    return result.strip()


def splitIntoChunks(text, maxSize=MAX_CHUNK_SIZE):
    """텍스트를 적절한 크기로 분할"""
    if len(text) <= maxSize:
        return [text]

    lines = text.split("\n")
    chunks = []
    currentChunk = ""

    for line in lines:
        if len(currentChunk) + len(line) + 1 > maxSize and currentChunk:
            chunks.append(currentChunk.strip())
            currentChunk = line + "\n"
        else:
            currentChunk += line + "\n"

    if currentChunk.strip():
        chunks.append(currentChunk.strip())

    return chunks


def buildMenuEntry(hotelId, hotelName, restaurantName, restaurantNameEn, url, tabName, content, chunkIdx=None, totalChunks=None):
    """보충 데이터 엔트리 생성"""
    chunkLabel = ""
    if totalChunks and totalChunks > 1:
        chunkLabel = f" ({chunkIdx}/{totalChunks})"

    questionParts = [f"{hotelName} {restaurantName}"]
    if tabName not in ("MENU", "기본메뉴"):
        questionParts.append(tabName)
    questionParts.append("메뉴")
    question = " ".join(questionParts)

    text = (
        f"{hotelName} {restaurantName}({restaurantNameEn}) {tabName} 메뉴 안내{chunkLabel}\n\n"
        f"Q: {question}를 알려주세요\n"
        f"A: {hotelName} {restaurantName}의 {tabName} 메뉴 안내입니다.\n\n"
        f"{content}"
    )

    return {
        "hotel": hotelId,
        "hotel_name": hotelName,
        "category": "다이닝",
        "page_type": "dining_menu",
        "url": url,
        "text": text
    }


def main():
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        rawData = json.load(f)

    supplementary = []
    skipped = 0

    for item in rawData:
        hotelId = item["hotel"]
        hotelName = item["hotel_name"]
        restaurantName = item["restaurant_name"]
        restaurantNameEn = item["restaurant_name_en"]
        url = item["url"]

        for tabName, content in item["menu_tabs"].items():
            cleaned = content.strip()
            if cleaned in SKIP_ENTRIES or len(cleaned) < 50:
                skipped += 1
                continue

            simplified = cleanAndSimplify(content)
            if len(simplified) < 30:
                skipped += 1
                continue

            chunks = splitIntoChunks(simplified)

            if len(chunks) == 1:
                entry = buildMenuEntry(
                    hotelId, hotelName, restaurantName, restaurantNameEn,
                    url, tabName, chunks[0]
                )
                supplementary.append(entry)
            else:
                for i, chunk in enumerate(chunks, 1):
                    entry = buildMenuEntry(
                        hotelId, hotelName, restaurantName, restaurantNameEn,
                        url, tabName, chunk, i, len(chunks)
                    )
                    supplementary.append(entry)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(supplementary, f, ensure_ascii=False, indent=2)

    print(f"✅ 변환 완료!")
    print(f"   입력: {len(rawData)}개 레스토랑")
    print(f"   출력: {len(supplementary)}개 보충 데이터 엔트리")
    print(f"   스킵: {skipped}개")
    print(f"   저장: {OUTPUT_PATH}")

    maxLen = 0
    for entry in supplementary:
        tl = len(entry["text"])
        if tl > maxLen:
            maxLen = tl
        if tl > 2000:
            label = entry["text"].split("\n")[0][:80]
            print(f"   [WARN] 긴 엔트리: {tl}자 | {label}")
    print(f"   최대 길이: {maxLen}자")


if __name__ == "__main__":
    main()
