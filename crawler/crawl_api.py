#!/usr/bin/env python3
"""
조선호텔 JSON API 크롤러
- /package/list.json: 패키지 상품 목록
- /event/list.json: 이벤트/프로모션 목록
- /activity/listJson.json: 액티비티 목록
- 정적 크롤러(crawl_complete.py)가 놓치는 동적 콘텐츠 수집
"""

import json
import time
import re
from pathlib import Path
from datetime import datetime
import requests

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "supplementary"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 호텔 설정
HOTELS = {
    "josun_palace": {
        "name": "조선 팰리스",
        "base_url": "https://jpg.josunhotel.com",
        "phone": "02-727-7200",
    },
    "grand_josun_busan": {
        "name": "그랜드 조선 부산",
        "base_url": "https://gjb.josunhotel.com",
        "phone": "051-922-5000",
    },
    "grand_josun_jeju": {
        "name": "그랜드 조선 제주",
        "base_url": "https://gjj.josunhotel.com",
        "phone": "064-735-8000",
    },
    "lescape": {
        "name": "레스케이프",
        "base_url": "https://les.josunhotel.com",
        "phone": "02-317-4000",
    },
    "gravity_pangyo": {
        "name": "그래비티 판교",
        "base_url": "https://grp.josunhotel.com",
        "phone": "031-539-4800",
    },
}

# HTML 태그 제거
def stripHtml(text: str) -> str:
    """HTML 태그 및 엔티티 제거"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def formatDate(dateStr: str) -> str:
    """날짜 문자열 포맷팅 (20260131 → 2026.01.31)"""
    if not dateStr or len(dateStr) < 8:
        return dateStr or ""
    # YYYY-MM-DDTHH:MM:SS 형식
    if "T" in str(dateStr):
        return str(dateStr).split("T")[0]
    # YYYYMMDD 형식
    dateStr = str(dateStr).replace("-", "")[:8]
    if len(dateStr) == 8:
        return f"{dateStr[:4]}.{dateStr[4:6]}.{dateStr[6:8]}"
    return str(dateStr)


def formatPrice(price) -> str:
    """가격 포맷팅"""
    if not price:
        return ""
    try:
        return f"{int(price):,}원"
    except (ValueError, TypeError):
        return str(price)


class ApiCrawler:
    """JSON API 크롤러"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        })

    def fetchPackages(self, hotelKey: str) -> list[dict]:
        """패키지 목록 수집"""
        config = HOTELS[hotelKey]
        url = f"{config['base_url']}/package/list.json"
        allPackages = []
        page = 1

        while True:
            try:
                resp = self.session.get(url, params={"pageNo": page, "rowPerPage": 20}, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                pkgList = data.get("list", [])
                if not pkgList:
                    break

                for pkg in pkgList:
                    title = stripHtml(pkg.get("productTitle", ""))
                    desc = stripHtml(pkg.get("packageDc", ""))
                    keywords = [k.get("kwrdNm", "") for k in pkg.get("packageKeywordList", []) if k.get("kwrdNm")]
                    notice = stripHtml(pkg.get("noticeCn", ""))
                    benefits = stripHtml(pkg.get("bnefDetailDc", ""))
                    lowPrice = formatPrice(pkg.get("lowPrice"))
                    saleBegin = formatDate(pkg.get("sleBeginDe"))
                    saleEnd = formatDate(pkg.get("sleEndDe"))
                    stayBegin = formatDate(pkg.get("stayBeginDe"))
                    stayEnd = formatDate(pkg.get("stayEndDe"))
                    tel = pkg.get("inquiryTelno", "") or config["phone"]

                    # 판매 기간이 이미 지난 패키지는 제외
                    if saleEnd:
                        try:
                            endDate = datetime.strptime(saleEnd.replace(".", "-"), "%Y-%m-%d")
                            if endDate < datetime.now():
                                continue
                        except ValueError:
                            pass

                    # Q&A 텍스트 생성
                    text = f"Q: {config['name']} {title} 패키지에 대해 알려주세요\n"
                    text += f"A: {config['name']}의 \"{title}\" 패키지를 소개합니다.\n\n"
                    if desc:
                        text += f"{desc}\n\n"
                    if keywords:
                        text += f"카테고리: {', '.join(keywords)}\n"
                    if lowPrice:
                        text += f"가격: {lowPrice}~\n"
                    if stayBegin and stayEnd:
                        text += f"투숙 가능 기간: {stayBegin} ~ {stayEnd}\n"
                    if saleBegin and saleEnd:
                        text += f"판매 기간: {saleBegin} ~ {saleEnd}\n"
                    if benefits:
                        text += f"\n포함 혜택:\n{benefits}\n"
                    if notice:
                        text += f"\n유의사항: {notice}\n"
                    text += f"\n예약 문의: {config['name']} ({tel})"
                    text += f"\n패키지 상세: {config['base_url']}/package/list.do"

                    allPackages.append({
                        "hotel": hotelKey,
                        "hotel_name": config["name"],
                        "category": "패키지",
                        "page_type": "package",
                        "url": f"{config['base_url']}/package/list.do",
                        "text": text,
                        "package_id": pkg.get("packageId"),
                        "title": title,
                        "keywords": keywords,
                    })

                # 다음 페이지 확인
                totalCount = data.get("totalCount", 0)
                if page * 20 >= int(totalCount or len(pkgList)):
                    break
                page += 1
                time.sleep(0.3)

            except Exception as e:
                print(f"  [에러] {hotelKey} 패키지 page {page}: {e}")
                break

        return allPackages

    def fetchEvents(self, hotelKey: str) -> list[dict]:
        """이벤트 목록 수집"""
        config = HOTELS[hotelKey]
        url = f"{config['base_url']}/event/list.json"
        allEvents = []

        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for evt in data.get("list", []):
                title = stripHtml(evt.get("eventTitle", ""))
                desc = stripHtml(evt.get("eventDc", ""))
                notice = stripHtml(evt.get("noticeCn", ""))
                tel = evt.get("inquiryTelno", "") or config["phone"]
                prgBegin = formatDate(evt.get("prgBeginDe"))
                prgEnd = formatDate(evt.get("prgEndDe"))

                # 종료된 이벤트 제외
                if evt.get("endYn") == "Y":
                    continue
                if prgEnd:
                    try:
                        endDate = datetime.strptime(prgEnd.replace(".", "-"), "%Y-%m-%d")
                        if endDate < datetime.now():
                            continue
                    except ValueError:
                        pass

                # Q&A 텍스트 생성
                text = f"Q: {config['name']} \"{title}\" 이벤트에 대해 알려주세요\n"
                text += f"A: {config['name']}에서 진행 중인 \"{title}\" 이벤트를 소개합니다.\n\n"
                if desc:
                    text += f"{desc}\n\n"
                if prgBegin and prgEnd:
                    text += f"진행 기간: {prgBegin} ~ {prgEnd}\n"
                if notice:
                    text += f"유의사항: {notice}\n"
                text += f"\n문의: {config['name']} ({tel})"
                text += f"\n이벤트 상세: {config['base_url']}/event/list.do"

                allEvents.append({
                    "hotel": hotelKey,
                    "hotel_name": config["name"],
                    "category": "이벤트",
                    "page_type": "event",
                    "url": f"{config['base_url']}/event/list.do",
                    "text": text,
                    "title": title,
                })

        except Exception as e:
            print(f"  [에러] {hotelKey} 이벤트: {e}")

        return allEvents

    def fetchActivities(self, hotelKey: str) -> list[dict]:
        """액티비티 목록 수집"""
        config = HOTELS[hotelKey]
        url = f"{config['base_url']}/activity/listJson.json"
        allActivities = []

        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for act in data.get("list", []):
                title = stripHtml(act.get("activitySe", ""))
                desc = stripHtml(act.get("activityDc", ""))
                notice = stripHtml(act.get("noticeCn", ""))
                tel = act.get("inquiryTelno", "") or config["phone"]

                if not title:
                    continue

                text = f"Q: {config['name']} \"{title}\" 액티비티에 대해 알려주세요\n"
                text += f"A: {config['name']}에서 제공하는 \"{title}\" 액티비티를 소개합니다.\n\n"
                if desc:
                    text += f"{desc}\n\n"
                if notice:
                    text += f"유의사항: {notice}\n"
                text += f"\n문의: {config['name']} ({tel})"
                text += f"\n액티비티 상세: {config['base_url']}/activity/list.do"

                allActivities.append({
                    "hotel": hotelKey,
                    "hotel_name": config["name"],
                    "category": "액티비티",
                    "page_type": "activity",
                    "url": f"{config['base_url']}/activity/list.do",
                    "text": text,
                    "title": title,
                })

        except Exception as e:
            print(f"  [에러] {hotelKey} 액티비티: {e}")

        return allActivities


def main():
    print("=" * 60)
    print("조선호텔 JSON API 크롤링")
    print("=" * 60)

    crawler = ApiCrawler()
    allPackages = []
    allEvents = []
    allActivities = []

    for hotelKey in HOTELS:
        hotelName = HOTELS[hotelKey]["name"]
        print(f"\n[{hotelName}]")

        # 패키지
        packages = crawler.fetchPackages(hotelKey)
        print(f"  패키지: {len(packages)}개")
        allPackages.extend(packages)

        # 이벤트
        events = crawler.fetchEvents(hotelKey)
        print(f"  이벤트: {len(events)}개")
        allEvents.extend(events)

        # 액티비티
        activities = crawler.fetchActivities(hotelKey)
        print(f"  액티비티: {len(activities)}개")
        allActivities.extend(activities)

        time.sleep(0.5)

    # 저장 (기존 package_info.json 대체)
    if allPackages:
        pkgPath = OUTPUT_DIR / "package_info.json"
        with open(pkgPath, "w", encoding="utf-8") as f:
            json.dump(allPackages, f, ensure_ascii=False, indent=2)
        print(f"\n[저장] 패키지: {len(allPackages)}개 → {pkgPath}")

    if allEvents:
        evtPath = OUTPUT_DIR / "event_info.json"
        with open(evtPath, "w", encoding="utf-8") as f:
            json.dump(allEvents, f, ensure_ascii=False, indent=2)
        print(f"[저장] 이벤트: {len(allEvents)}개 → {evtPath}")

    if allActivities:
        actPath = OUTPUT_DIR / "activity_info.json"
        with open(actPath, "w", encoding="utf-8") as f:
            json.dump(allActivities, f, ensure_ascii=False, indent=2)
        print(f"[저장] 액티비티: {len(allActivities)}개 → {actPath}")

    print(f"\n{'=' * 60}")
    print(f"총 수집: 패키지 {len(allPackages)}개, 이벤트 {len(allEvents)}개, 액티비티 {len(allActivities)}개")
    print("=" * 60)


if __name__ == "__main__":
    main()
