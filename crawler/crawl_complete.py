#!/usr/bin/env python3
"""
조선호텔 완전 크롤링 스크립트
- 모든 공개 페이지 크롤링 (로그인 불필요)
- 각 호텔별 전체 섹션 포함
"""

import json
import time
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup


OUTPUT_DIR = Path(__file__).parent.parent / "data" / "raw" / "deep_crawled"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 호텔별 전체 페이지 설정
HOTELS = {
    "josun_palace": {
        "name": "조선 팰리스",
        "base_url": "https://jpg.josunhotel.com",
        "phone": "02-727-7200",
        "pages": [
            # 객실
            "/rooms/subMain.do",
            "/rooms/State.do",
            "/rooms/Masters.do",
            "/rooms/GrandMasters.do",
            "/rooms/GrandMastersBay.do",
            "/rooms/MastersJr.Suite.do",
            "/rooms/MastersSuite.do",
            "/rooms/GrandMastersSuite.do",
            "/rooms/JosunMastersSuite.do",
            "/rooms/JosunGrandMastersSuite.do",
            # 다이닝
            "/dining/subMain.do",
            "/dining/constans.do",
            "/dining/1914.do",
            "/dining/EatanicGarden.do",
            "/dining/HongYuan.do",
            "/dining/JosunDeli.do",
            # 시설
            "/facilities/subMain.do",
            "/facilities/Fitness.do",
            "/facilities/Pool.do",
            "/facilities/Sauna.do",
            "/facilities/pilates.do",
            "/facilities/businessCenter.do",
            # 미팅/웨딩
            "/meeting/subMain.do",
            "/meeting/meeting.do",
            "/meeting/wedding.do",
            # 아트
            "/artCollection/artCollection.do",
            "/artTour/subMain.do",
            "/artTour/artTour.do",
            # 이벤트/패키지
            "/event/list.do",
            "/package/list.do",
            # 소개
            "/about/aboutUs.do",
            "/about/location.do",
            "/about/contactUs.do",
            "/about/promise.do",
            "/about/faq.do",
            # 정책
            "/policy/hotel.do",
        ]
    },
    "grand_josun_busan": {
        "name": "그랜드 조선 부산",
        "base_url": "https://gjb.josunhotel.com",
        "phone": "051-922-5000",
        "pages": [
            # 객실
            "/rooms/subMain.do",
            "/rooms/superior.do",
            "/rooms/deluxe.do",
            "/rooms/premier.do",
            "/rooms/kidsDeluxe.do",
            "/rooms/kidsSuperior.do",
            "/rooms/kidsSuite.do",
            "/rooms/cornerSuite.do",
            "/rooms/familySuite.do",
            "/rooms/executiveSuite.do",
            "/rooms/royalSuite.do",
            "/rooms/presidentialSuite.do",
            # 다이닝
            "/dining/subMain.do",
            "/dining/aria.do",
            "/dining/palais.do",
            "/dining/lounge.do",
            "/dining/deli.do",
            # 시설
            "/facilities/subMain.do",
            "/facilites/pool.do",
            "/facilites/sauna.do",
            "/facilites/fitness.do",
            "/facilites/library.do",
            "/facilites/entertainment.do",
            # 미팅
            "/meeting/subMain.do",
            "/meeting/ballroom.do",
            "/meeting/boardRoom.do",
            "/meeting/meetingRoom.do",
            "/meeting/wedding.do",
            # 액티비티
            "/activity/list.do",
            # 이벤트/패키지
            "/event/list.do",
            "/package/list.do",
            # 소개
            "/about/aboutUs.do",
            "/about/junior.do",
            "/about/faq.do",
            # 정책
            "/policy/hotel.do",
        ]
    },
    "grand_josun_jeju": {
        "name": "그랜드 조선 제주",
        "base_url": "https://gjj.josunhotel.com",
        "phone": "064-735-8000",
        "pages": [
            # 객실
            "/rooms/subMain.do",
            "/rooms/deluxe.do",
            "/rooms/kidsDeluxe.do",
            "/rooms/kidsPremierSuite.do",
            "/rooms/studioSuite.do",
            "/rooms/premierSuite.do",
            "/rooms/luxurySuite.do",
            "/rooms/royalSuite.do",
            "/rooms/thesuite.do",
            "/rooms/hillStudioSuite.do",
            "/rooms/hillSuite.do",
            "/rooms/prestigeHillSuite.do",
            # 다이닝
            "/dining/subMain.do",
            "/dining/aria.do",
            "/dining/loungebar.do",
            "/dining/peak.do",
            "/dining/deli.do",
            "/dining/eat2o.do",
            "/dining/granj.do",
            "/dining/heavenlyLounge.do",
            # 시설
            "/facilites/subMain.do",
            "/facilites/heavenlypool.do",
            "/facilites/peakpool.do",
            "/facilites/gardenpool.do",
            "/facilites/fitness.do",
            "/facilites/gxroom.do",
            "/facilites/library.do",
            "/facilites/entertainment.do",
            "/facilites/juniorclub.do",
            "/facilites/aquashop.do",
            # 미팅
            "/meeting/subMain.do",
            "/meeting/meeting.do",
            "/meeting/wedding.do",
            # 액티비티
            "/activity/list.do",
            # 이벤트/패키지
            "/event/list.do",
            "/package/list.do",
            # 소개
            "/about/aboutUs.do",
            "/about/junior.do",
            "/about/faq.do",
            # 정책
            "/policy/hotel.do",
        ]
    },
    "lescape": {
        "name": "레스케이프",
        "base_url": "https://les.josunhotel.com",
        "phone": "02-317-4000",
        "pages": [
            # 객실
            "/rooms/subMain.do",
            "/rooms/classic.do",
            "/rooms/amour.do",
            "/rooms/secret.do",
            "/rooms/cornersuite.do",
            "/rooms/juniorsuite.do",
            "/rooms/royalsuite.do",
            "/rooms/presidentialsuite.do",
            "/rooms/lescapesuite.do",
            # 다이닝
            "/dining/subMain.do",
            "/dining/lamantsecret.do",
            "/dining/palaisdechine.do",
            "/dining/marquedamour.do",
            "/dining/teasalon.do",
            # 시설
            "/facilities/subMain.do",
            "/facilities/boutiquelounge.do",
            "/facilities/fitness.do",
            "/facilities/spa.do",
            # 살롱 (레스케이프 특화)
            "/salon/subMain.do",
            "/salon/lescapecollection.do",
            "/salon/petfrientdly.do",
            "/salon/program.do",
            # 미팅
            "/meeting/subMain.do",
            "/meeting/meeting.do",
            "/meeting/wedding.do",
            # 이벤트/패키지
            "/event/list.do",
            "/package/list.do",
            # 소개
            "/about/aboutus.do",
            "/about/location.do",
            "/about/gallery.do",
            "/about/notice.do",
            "/about/partners.do",
            "/about/faq.do",
            # 정책
            "/policy/hotel.do",
        ]
    },
    "gravity_pangyo": {
        "name": "그래비티 판교",
        "base_url": "https://grp.josunhotel.com",
        "phone": "031-539-4800",
        "pages": [
            # 객실
            "/rooms/subMain.do",
            "/rooms/BusinessDeluxe.do",
            "/rooms/PremierDeluxe.do",
            "/rooms/ValleySuite.do",
            "/rooms/GravitySuite.do",
            # 다이닝
            "/dining/subMain.do",
            "/dining/andish.do",
            "/dining/zerovity.do",
            "/dining/josunDeli.do",
            "/dining/voost.do",
            # 시설
            "/facilites/facilites.do",
            # 피트니스 (그래비티 특화)
            "/fitness/subMain.do",
            "/fitness/gravityClub.do",
            "/fitness/gym.do",
            "/fitness/pool.do",
            # 미팅
            "/meeting/subMain.do",
            "/meeting/Spacballroom.do",
            "/meeting/wedding.do",
            # 액티비티
            "/activity/list.do",
            # 이벤트/패키지
            "/event/list.do",
            "/package/list.do",
            # 소개
            "/about/aboutUs.do",
            "/about/gallery.do",
            "/about/faq.do",
            # 정책
            "/policy/hotel.do",
        ]
    },
}


class CompleteCrawler:
    """완전 크롤러"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def extractInfo(self, soup: BeautifulSoup) -> dict:
        """페이지에서 정보 추출"""
        info = {}

        # dl/dt/dd 구조에서 정보 추출
        for dl in soup.find_all("dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            if dt and dd:
                key = dt.get_text(strip=True)
                val = dd.get_text(strip=True)
                if key and val and len(key) < 100:
                    info[key] = val

        return info

    def extractText(self, soup: BeautifulSoup) -> str:
        """페이지에서 텍스트 추출"""
        # 불필요한 요소 제거
        for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 메인 콘텐츠 영역
        main = soup.find("div", id="container") or soup.find("main") or soup.body
        if not main:
            return ""

        text = main.get_text(separator="\n", strip=True)
        # 연속 줄바꿈 정리
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text

    def extractNotices(self, soup: BeautifulSoup) -> list:
        """안내사항 추출"""
        notices = []
        keywords = ["체크인", "체크아웃", "이용", "안내", "주의", "금지", "필수", "불가"]

        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if any(kw in text for kw in keywords) and 10 < len(text) < 200:
                if text not in notices:
                    notices.append(text)

        return notices[:10]

    def detectSection(self, url: str) -> str:
        """URL에서 섹션 감지"""
        if "/rooms/" in url:
            return "rooms"
        elif "/dining/" in url:
            return "dining"
        elif "/facilit" in url or "/fitness/" in url:
            return "facilities"
        elif "/meeting/" in url:
            return "meeting"
        elif "/about/" in url:
            return "about"
        elif "/event/" in url:
            return "event"
        elif "/package/" in url:
            return "package"
        elif "/activity/" in url:
            return "activity"
        elif "/salon/" in url:
            return "salon"
        elif "/art" in url:
            return "art"
        elif "/policy/" in url:
            return "policy"
        else:
            return "general"

    def crawlPage(self, url: str, hotelKey: str, hotelName: str) -> dict:
        """단일 페이지 크롤링"""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # 페이지 제목
            title = ""
            titleTag = soup.find("title")
            if titleTag:
                title = titleTag.get_text(strip=True)

            # 섹션 감지
            section = self.detectSection(url)

            # 이름 추출 (h1, h2, strong 등)
            name = ""
            for tag in ["h1", "h2", "strong"]:
                nameTag = soup.find(tag)
                if nameTag:
                    name = nameTag.get_text(strip=True)[:100]
                    break

            # 정보 추출
            info = self.extractInfo(soup)
            notices = self.extractNotices(soup)
            content = self.extractText(soup)

            # 가격 추출
            price = ""
            priceMatch = re.search(r'정상가\s*[:：]?\s*([\d,]+)\s*원', content)
            if priceMatch:
                price = priceMatch.group(1) + "원"

            # 운영시간 추출
            hours = ""
            hoursMatch = re.search(r'(\d{1,2}:\d{2}\s*[-~]\s*\d{1,2}:\d{2})', content)
            if hoursMatch:
                hours = hoursMatch.group(1)

            return {
                "hotel": hotelKey,
                "hotel_name": hotelName,
                "section": section,
                "url": url,
                "title": title,
                "name": name,
                "info": info,
                "notices": notices,
                "price": price,
                "hours": hours,
                "content": content[:3000],  # 최대 3000자
                "crawled_at": datetime.now().isoformat()
            }

        except Exception as e:
            print(f"    [에러] {url}: {e}")
            return None

    def crawlHotel(self, hotelKey: str):
        """호텔 전체 크롤링"""
        config = HOTELS[hotelKey]
        baseUrl = config["base_url"]
        hotelName = config["name"]
        pages = config["pages"]

        print(f"\n{'='*60}")
        print(f"[{hotelName}] 크롤링 시작 ({len(pages)}개 페이지)")
        print(f"{'='*60}")

        allData = []
        crawledUrls = set()

        for pagePath in pages:
            url = baseUrl + pagePath

            if url in crawledUrls:
                continue

            print(f"  [{self.detectSection(url)}] {pagePath}")

            data = self.crawlPage(url, hotelKey, hotelName)
            if data:
                allData.append(data)
                crawledUrls.add(url)

                # 페이지 내 추가 링크 추출 (상세 페이지)
                try:
                    resp = self.session.get(url, timeout=30)
                    soup = BeautifulSoup(resp.text, "html.parser")

                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if href.endswith(".do") and not href.startswith("http"):
                            fullUrl = baseUrl + href
                            section = self.detectSection(href)

                            # 동일 섹션 상세 페이지만 추가
                            if section == self.detectSection(pagePath) and fullUrl not in crawledUrls:
                                time.sleep(0.3)
                                detailData = self.crawlPage(fullUrl, hotelKey, hotelName)
                                if detailData and detailData["content"]:
                                    allData.append(detailData)
                                    crawledUrls.add(fullUrl)
                                    print(f"    -> {href}")

                except Exception as e:
                    pass

            time.sleep(0.5)

        # 저장
        outputFile = OUTPUT_DIR / f"{hotelKey}_complete.json"
        with open(outputFile, "w", encoding="utf-8") as f:
            json.dump({
                "hotel": hotelKey,
                "hotel_name": hotelName,
                "phone": config["phone"],
                "base_url": baseUrl,
                "crawled_at": datetime.now().isoformat(),
                "total_pages": len(allData),
                "data": allData
            }, f, ensure_ascii=False, indent=2)

        print(f"\n[완료] {len(allData)}개 페이지 → {outputFile}")
        return allData


def main():
    print("=" * 60)
    print("조선호텔 완전 크롤링 시작")
    print("=" * 60)

    crawler = CompleteCrawler()

    for hotelKey in HOTELS:
        crawler.crawlHotel(hotelKey)
        time.sleep(2)

    print("\n" + "=" * 60)
    print("전체 크롤링 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
