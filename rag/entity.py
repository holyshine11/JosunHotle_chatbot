"""레스토랑 엔티티 추출/검증 모듈

쿼리에서 레스토랑명을 감지하고, 현재 호텔 맥락과 비교하여
proceed / redirect / clarify 액션을 결정한다.
"""

from rag.constants import (
    RESTAURANT_ALIAS_INDEX,
    RESTAURANT_HOTEL_MAP,
    HOTEL_INFO,
)


def extractRestaurantEntity(query: str, currentHotel: str | None) -> dict:
    """쿼리에서 레스토랑 엔티티를 추출하고 호텔 맥락과 검증

    Args:
        query: 사용자 쿼리 (정규화된)
        currentHotel: 현재 선택된 호텔 ID (예: "grand_josun_jeju")

    Returns:
        {
            "action": "proceed" | "redirect" | "clarify",
            "matched_alias": str | None,       # 매칭된 alias
            "matched_restaurants": list[dict],  # 매칭된 레스토랑 정보 목록
            "redirect_hotel": str | None,       # redirect 시 대상 호텔
            "message": str | None,              # 사용자 안내 메시지
        }
    """
    queryLower = query.lower()

    # 1. 쿼리에서 레스토랑 alias 매칭 (긴 이름 우선)
    sortedAliases = sorted(RESTAURANT_ALIAS_INDEX.keys(), key=len, reverse=True)

    matchedAlias = None
    matchedEntries = []

    for alias in sortedAliases:
        if alias in queryLower:
            matchedAlias = alias
            matchedEntries = RESTAURANT_ALIAS_INDEX[alias]
            break

    # 매칭 없으면 일반 쿼리로 처리
    if not matchedAlias:
        return {
            "action": "proceed",
            "matched_alias": None,
            "matched_restaurants": [],
            "redirect_hotel": None,
            "message": None,
        }

    # 2. 현재 호텔에 존재하는지 확인
    if currentHotel:
        localMatches = [e for e in matchedEntries if e["hotel_id"] == currentHotel]
        if localMatches:
            # 현재 호텔에 해당 레스토랑 있음 → 정상 진행
            return {
                "action": "proceed",
                "matched_alias": matchedAlias,
                "matched_restaurants": localMatches,
                "redirect_hotel": None,
                "message": None,
            }

    # 3. 다른 호텔에 존재하는 경우
    otherMatches = matchedEntries if not currentHotel else [
        e for e in matchedEntries if e["hotel_id"] != currentHotel
    ]
    uniqueHotels = list(set(e["hotel_id"] for e in otherMatches))

    if len(uniqueHotels) == 1:
        # 다른 호텔 1곳에만 존재 → 리다이렉트
        targetHotel = uniqueHotels[0]
        targetHotelName = HOTEL_INFO.get(targetHotel, {}).get("name", targetHotel)
        restName = otherMatches[0]["restaurant"]
        # 괄호 내 호텔명 제거하여 깔끔한 이름
        displayName = _cleanRestaurantName(restName)

        msg = f"{displayName}은(는) {targetHotelName}에 위치한 레스토랑입니다."

        return {
            "action": "redirect",
            "matched_alias": matchedAlias,
            "matched_restaurants": otherMatches,
            "redirect_hotel": targetHotel,
            "message": msg,
        }

    elif len(uniqueHotels) >= 2:
        # 2곳 이상 → 명확화 질문
        hotelNames = []
        for hid in uniqueHotels:
            hName = HOTEL_INFO.get(hid, {}).get("name", hid)
            hotelNames.append(hName)
        displayName = _cleanRestaurantName(otherMatches[0]["restaurant"])
        hotelList = ", ".join(hotelNames)
        msg = f"{displayName}은(는) {hotelList}에 있습니다. 어느 호텔의 {displayName}을(를) 안내해 드릴까요?"

        return {
            "action": "clarify",
            "matched_alias": matchedAlias,
            "matched_restaurants": otherMatches,
            "redirect_hotel": None,
            "message": msg,
            "clarify_options": hotelNames,
        }

    # 어디에도 없으면 일반 쿼리로 처리
    return {
        "action": "proceed",
        "matched_alias": matchedAlias,
        "matched_restaurants": [],
        "redirect_hotel": None,
        "message": None,
    }


def _cleanRestaurantName(name: str) -> str:
    """'아리아(부산)' → '아리아' 형태로 괄호 제거"""
    idx = name.find("(")
    if idx > 0:
        return name[:idx].strip()
    return name
