#!/usr/bin/env python3
"""
조선호텔 심층 크롤러
- MCP Playwright 대신 requests + BeautifulSoup 사용
- 모든 섹션의 상세 페이지 크롤링
- 탭, 숨겨진 콘텐츠 포함
"""

import json
import time
import re
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup


# 호텔 설정
HOTELS = {
    "josun_palace": {
        "name": "조선 팰리스",
        "base_url": "https://jpg.josunhotel.com",
        "phone": "02-727-7200",
        "sections": {
            "rooms": "/rooms/subMain.do",
            "dining": "/dining/subMain.do",
            "facilities": "/facilities/subMain.do",
            "meeting": "/meeting/subMain.do",
            "offers": "/package/list.do",
            "about": "/about/aboutUs.do",
            "faq": "/about/faq.do",
            "policy": "/policy/hotel.do",
        }
    },
    "grand_josun_busan": {
        "name": "그랜드 조선 부산",
        "base_url": "https://gjb.josunhotel.com",
        "phone": "051-922-5000",
        "sections": {
            "rooms": "/rooms/subMain.do",
            "dining": "/dining/subMain.do",
            "facilities": "/facilities/subMain.do",
            "meeting": "/meeting/subMain.do",
            "offers": "/package/list.do",
            "about": "/about/aboutUs.do",
            "faq": "/about/faq.do",
            "policy": "/policy/hotel.do",
        }
    },
    "grand_josun_jeju": {
        "name": "그랜드 조선 제주",
        "base_url": "https://gjj.josunhotel.com",
        "phone": "064-735-8000",
        "sections": {
            "rooms": "/rooms/subMain.do",
            "dining": "/dining/subMain.do",
            "facilities": "/facilities/subMain.do",
            "meeting": "/meeting/subMain.do",
            "offers": "/package/list.do",
            "about": "/about/aboutUs.do",
            "faq": "/about/faq.do",
            "policy": "/policy/hotel.do",
        }
    },
    "lescape": {
        "name": "레스케이프",
        "base_url": "https://les.josunhotel.com",
        "phone": "02-317-4000",
        "sections": {
            "rooms": "/rooms/subMain.do",
            "dining": "/dining/subMain.do",
            "facilities": "/facilities/subMain.do",
            "offers": "/package/list.do",
            "about": "/about/aboutUs.do",
            "faq": "/about/faq.do",
            "policy": "/policy/hotel.do",
        }
    },
    "gravity_pangyo": {
        "name": "그래비티 판교",
        "base_url": "https://grp.josunhotel.com",
        "phone": "031-539-4800",
        "sections": {
            "rooms": "/rooms/subMain.do",
            "dining": "/dining/subMain.do",
            "facilities": "/facilities/subMain.do",
            "offers": "/package/list.do",
            "about": "/about/aboutUs.do",
            "faq": "/about/faq.do",
            "policy": "/policy/hotel.do",
        }
    },
}


class DeepCrawler:
    """심층 크롤러"""

    def __init__(self, outputDir: Path = None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })

        self.outputDir = outputDir or Path(__file__).parent.parent / "data" / "raw" / "deep_crawled"
        self.outputDir.mkdir(parents=True, exist_ok=True)

        self.crawledUrls = set()
        self.allData = []

    def fetch(self, url: str) -> BeautifulSoup:
        """페이지 가져오기"""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  [에러] {url}: {e}")
            return None

    def extractText(self, soup: BeautifulSoup) -> str:
        """페이지에서 텍스트 추출"""
        # 불필요한 요소 제거
        for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 메인 콘텐츠 영역 찾기
        main = soup.find("div", id="container") or soup.find("main") or soup.body
        if not main:
            return ""

        return main.get_text(separator="\n", strip=True)

    def extractLinks(self, soup: BeautifulSoup, baseUrl: str, section: str) -> list:
        """상세 페이지 링크 추출"""
        links = []

        # 자세히보기 링크
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)

            # 상세 페이지 패턴
            if any(pattern in href for pattern in [
                f"/{section}/", ".do", "detail", "view"
            ]):
                if not href.startswith("http"):
                    href = urljoin(baseUrl, href)

                if href.startswith(baseUrl) and href not in self.crawledUrls:
                    links.append({"url": href, "text": text})

        return links

    def extractRoomDetails(self, soup: BeautifulSoup, url: str) -> dict:
        """객실 상세 정보 추출"""
        data = {
            "type": "room",
            "url": url,
            "overview": {},
            "amenities": [],
            "notices": [],
            "services": [],
        }

        # 객실명
        title = soup.find("strong")
        if title:
            data["name"] = title.get_text(strip=True)

        # 개요 (dl/dt/dd)
        for dl in soup.find_all("dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            if dt and dd:
                key = dt.get_text(strip=True)
                val = dd.get_text(strip=True)
                if key and val:
                    data["overview"][key] = val

        # 어메니티
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if any(kw in text for kw in ["목욕", "샴푸", "타월", "칫솔", "비데", "드라이어", "가운", "슬리퍼"]):
                if len(text) < 50:
                    data["amenities"].append(text)

        # 안내사항
        for li in soup.find_all("li"):
            text = li.get_text(strip=True)
            if any(kw in text for kw in ["체크인", "체크아웃", "취소", "금연", "미성년자", "정상가"]):
                if text not in data["notices"]:
                    data["notices"].append(text)

        # 가격
        pageText = soup.get_text()
        priceMatch = re.search(r"정상가\s*[:：]?\s*([\d,]+)원", pageText)
        if priceMatch:
            data["price"] = priceMatch.group(1) + "원"

        return data

    def extractDiningDetails(self, soup: BeautifulSoup, url: str) -> dict:
        """다이닝 상세 정보 추출"""
        data = {
            "type": "dining",
            "url": url,
            "info": {},
        }

        # 레스토랑명
        title = soup.find("strong") or soup.find("h2")
        if title:
            data["name"] = title.get_text(strip=True)

        # 개요 (dl/dt/dd)
        for dl in soup.find_all("dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            if dt and dd:
                key = dt.get_text(strip=True)
                val = dd.get_text(strip=True)
                if key and val:
                    data["info"][key] = val

        # 운영시간 추출
        pageText = soup.get_text()
        timePatterns = [
            r"운영\s*시간[:\s]*([\d:]+\s*[-~]\s*[\d:]+)",
            r"영업\s*시간[:\s]*([\d:]+\s*[-~]\s*[\d:]+)",
            r"(\d{2}:\d{2}\s*[-~]\s*\d{2}:\d{2})",
        ]
        for pattern in timePatterns:
            match = re.search(pattern, pageText)
            if match:
                data["hours"] = match.group(1)
                break

        # 전체 텍스트 (설명)
        mainContent = soup.find("div", class_=re.compile("content|detail|info"))
        if mainContent:
            data["description"] = mainContent.get_text(separator=" ", strip=True)[:500]

        return data

    def extractFacilityDetails(self, soup: BeautifulSoup, url: str) -> dict:
        """시설 상세 정보 추출"""
        data = {
            "type": "facility",
            "url": url,
            "info": {},
        }

        # 시설명
        title = soup.find("strong") or soup.find("h2")
        if title:
            data["name"] = title.get_text(strip=True)

        # 개요
        for dl in soup.find_all("dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            if dt and dd:
                key = dt.get_text(strip=True)
                val = dd.get_text(strip=True)
                if key and val:
                    data["info"][key] = val

        # 운영시간
        pageText = soup.get_text()
        timeMatch = re.search(r"(\d{2}:\d{2}\s*[-~]\s*\d{2}:\d{2})", pageText)
        if timeMatch:
            data["hours"] = timeMatch.group(1)

        return data

    def crawlSection(self, hotel: str, hotelConfig: dict, section: str, sectionPath: str):
        """섹션 크롤링"""
        baseUrl = hotelConfig["base_url"]
        url = baseUrl + sectionPath

        print(f"  [{section}] {url}")

        soup = self.fetch(url)
        if not soup:
            return []

        self.crawledUrls.add(url)
        results = []

        # 메인 페이지 데이터
        mainData = {
            "hotel": hotel,
            "hotel_name": hotelConfig["name"],
            "section": section,
            "url": url,
            "title": soup.title.string if soup.title else section,
            "content": self.extractText(soup),
            "crawled_at": datetime.now().isoformat(),
        }
        results.append(mainData)

        # 상세 페이지 링크 추출
        detailLinks = self.extractLinks(soup, baseUrl, section)

        for link in detailLinks[:20]:  # 최대 20개
            detailUrl = link["url"]

            if detailUrl in self.crawledUrls:
                continue

            time.sleep(0.5)  # 서버 부하 방지

            detailSoup = self.fetch(detailUrl)
            if not detailSoup:
                continue

            self.crawledUrls.add(detailUrl)

            # 섹션별 상세 추출
            if section == "rooms":
                detailData = self.extractRoomDetails(detailSoup, detailUrl)
            elif section == "dining":
                detailData = self.extractDiningDetails(detailSoup, detailUrl)
            elif section == "facilities":
                detailData = self.extractFacilityDetails(detailSoup, detailUrl)
            else:
                detailData = {
                    "type": section,
                    "url": detailUrl,
                    "content": self.extractText(detailSoup),
                }

            detailData["hotel"] = hotel
            detailData["hotel_name"] = hotelConfig["name"]
            detailData["section"] = section
            detailData["crawled_at"] = datetime.now().isoformat()

            results.append(detailData)
            print(f"    -> {detailData.get('name', detailUrl.split('/')[-1])}")

        return results

    def crawlHotel(self, hotelKey: str):
        """호텔 전체 크롤링"""
        if hotelKey not in HOTELS:
            print(f"[에러] 알 수 없는 호텔: {hotelKey}")
            return

        config = HOTELS[hotelKey]
        print(f"\n{'='*60}")
        print(f"[{config['name']}] 심층 크롤링 시작")
        print(f"{'='*60}")

        allResults = []

        for section, path in config["sections"].items():
            results = self.crawlSection(hotelKey, config, section, path)
            allResults.extend(results)
            time.sleep(1)

        # 저장
        outputFile = self.outputDir / f"{hotelKey}_deep.json"
        with open(outputFile, "w", encoding="utf-8") as f:
            json.dump({
                "hotel": hotelKey,
                "hotel_name": config["name"],
                "phone": config["phone"],
                "crawled_at": datetime.now().isoformat(),
                "total_pages": len(allResults),
                "data": allResults,
            }, f, ensure_ascii=False, indent=2)

        print(f"\n[완료] {len(allResults)}개 페이지 크롤링 → {outputFile}")

        return allResults

    def crawlAll(self):
        """모든 호텔 크롤링"""
        for hotelKey in HOTELS:
            self.crawlHotel(hotelKey)
            time.sleep(2)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="조선호텔 심층 크롤러")
    parser.add_argument("--hotel", type=str, help="특정 호텔만 크롤링")
    parser.add_argument("--all", action="store_true", help="모든 호텔 크롤링")

    args = parser.parse_args()

    crawler = DeepCrawler()

    if args.hotel:
        crawler.crawlHotel(args.hotel)
    elif args.all:
        crawler.crawlAll()
    else:
        # 기본: 조선 팰리스만
        crawler.crawlHotel("josun_palace")


if __name__ == "__main__":
    main()
