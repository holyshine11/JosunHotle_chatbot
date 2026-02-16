#!/usr/bin/env python3
"""
조선호텔 FAQ 챗봇 CLI
터미널에서 대화형으로 테스트

## 터미널 실행 커멘드
 -  ~/.pyenv/versions/3.11.7/bin/python3 chat.py

"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rag.graph import createRAGGraph
from rag.constants import HOTEL_KEYWORDS


# 호텔 목록
HOTELS = [
    {"key": "josun_palace", "name": "조선 팰리스", "short": "팰리스"},
    {"key": "grand_josun_busan", "name": "그랜드 조선 부산", "short": "부산"},
    {"key": "grand_josun_jeju", "name": "그랜드 조선 제주", "short": "제주"},
    {"key": "lescape", "name": "레스케이프", "short": "레스케이프"},
    {"key": "gravity_pangyo", "name": "그래비티 판교", "short": "판교"},
]


def selectHotel() -> str:
    """호텔 선택 메뉴"""
    print("\n어느 호텔에 대해 문의하시나요?")
    for i, hotel in enumerate(HOTELS, 1):
        print(f"  {i}. {hotel['name']}")
    print(f"  0. 전체 호텔 (호텔 미지정)")

    while True:
        try:
            choice = input("\n호텔 선택 (0-5)> ").strip()
            if not choice:
                continue

            num = int(choice)
            if num == 0:
                return None
            elif 1 <= num <= len(HOTELS):
                selected = HOTELS[num - 1]
                print(f"\n[{selected['name']}] 선택됨\n")
                return selected["key"]
            else:
                print("1~5 또는 0을 입력해주세요.")
        except ValueError:
            print("숫자를 입력해주세요.")


def detectHotelFromQuery(query: str) -> str:
    """질문에서 호텔 키워드 감지"""
    queryLower = query.lower()
    for hotelKey, keywords in HOTEL_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in queryLower:
                return hotelKey
    return None


def main():
    print("\n" + "=" * 50)
    print("조선호텔 FAQ 챗봇")
    print("=" * 50)
    print("종료: quit 또는 q 입력")
    print("호텔 변경: /hotel 입력")
    print("=" * 50)

    print("\n[초기화 중...]")
    rag = createRAGGraph()
    print("[준비 완료!]")

    # 세션에서 사용할 호텔 (None이면 미지정)
    sessionHotel = None
    hotelSelected = False  # 호텔 선택 여부

    while True:
        try:
            query = input("\n질문> ").strip()

            if not query:
                continue

            if query.lower() in ("quit", "q", "exit", "종료"):
                print("\n챗봇을 종료합니다. 감사합니다!")
                break

            # 호텔 변경 명령
            if query.lower() == "/hotel":
                sessionHotel = selectHotel()
                hotelSelected = True
                continue

            # 질문에서 호텔 감지 시도
            detectedHotel = detectHotelFromQuery(query)

            # 호텔이 감지되지 않고, 아직 선택 안했으면 선택 요청
            if not detectedHotel and not hotelSelected:
                sessionHotel = selectHotel()
                hotelSelected = True

            # 질문에서 감지된 호텔 우선, 없으면 세션 호텔 사용
            useHotel = detectedHotel or sessionHotel

            result = rag.chat(query, hotel=useHotel)

            # 호텔 이름 찾기
            hotelName = "전체"
            if result["hotel"]:
                for h in HOTELS:
                    if h["key"] == result["hotel"]:
                        hotelName = h["name"]
                        break

            print(f"\n답변: {result['answer']}")
            print(f"(호텔: {hotelName}, 점수: {result['score']:.3f})")

        except KeyboardInterrupt:
            print("\n\n챗봇을 종료합니다.")
            break
        except Exception as e:
            print(f"\n[오류] {e}")


if __name__ == "__main__":
    main()
