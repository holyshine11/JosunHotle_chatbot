#!/usr/bin/env python3
"""
모든 호텔 심층 크롤링 스크립트
- Playwright 기반 (JavaScript 렌더링 지원)
- 객실, 다이닝, 시설 정보 수집
"""

import json
import time
import subprocess
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "raw" / "deep_crawled"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 호텔별 크롤링 설정
HOTELS = {
    "grand_josun_busan": {
        "name": "그랜드 조선 부산",
        "base_url": "https://gjb.josunhotel.com",
        "phone": "051-922-5000"
    },
    "grand_josun_jeju": {
        "name": "그랜드 조선 제주",
        "base_url": "https://gjj.josunhotel.com",
        "phone": "064-735-8000"
    },
    "lescape": {
        "name": "레스케이프",
        "base_url": "https://les.josunhotel.com",
        "phone": "02-317-4000"
    },
    "gravity_pangyo": {
        "name": "그래비티 판교",
        "base_url": "https://grp.josunhotel.com",
        "phone": "031-539-4800"
    }
}

def crawlWithPlaywright(hotelKey: str, hotelConfig: dict):
    """Playwright CLI로 크롤링"""
    print(f"\n{'='*60}")
    print(f"[{hotelConfig['name']}] 크롤링 시작")
    print(f"{'='*60}")

    baseUrl = hotelConfig["base_url"]

    # 객실 페이지 URL 목록 가져오기
    roomsUrl = f"{baseUrl}/rooms/subMain.do"
    diningUrl = f"{baseUrl}/dining/subMain.do"
    facilitiesUrl = f"{baseUrl}/facilities/subMain.do"
    faqUrl = f"{baseUrl}/about/faq.do"
    policyUrl = f"{baseUrl}/policy/hotel.do"

    # 기본 정보 수집 (requests 사용)
    import requests
    from bs4 import BeautifulSoup

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })

    allData = []

    # 각 섹션 크롤링
    for section, url in [("rooms", roomsUrl), ("dining", diningUrl),
                          ("facilities", facilitiesUrl), ("faq", faqUrl), ("policy", policyUrl)]:
        print(f"  [{section}] {url}")
        try:
            resp = session.get(url, timeout=30)
            soup = BeautifulSoup(resp.text, "html.parser")

            # 텍스트 추출
            for tag in soup.find_all(["script", "style", "nav", "footer"]):
                tag.decompose()

            mainContent = soup.find("div", id="container") or soup.body
            text = mainContent.get_text(separator="\n", strip=True) if mainContent else ""

            # 상세 링크 추출
            detailLinks = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if f"/{section}/" in href and href.endswith(".do"):
                    if not href.startswith("http"):
                        href = baseUrl + href
                    if href not in [d["url"] for d in detailLinks]:
                        detailLinks.append({"url": href, "name": a.get_text(strip=True)[:50]})

            # 메인 페이지 데이터
            allData.append({
                "hotel": hotelKey,
                "hotel_name": hotelConfig["name"],
                "section": section,
                "url": url,
                "content": text[:5000],
                "detail_links": detailLinks[:10],
                "crawled_at": datetime.now().isoformat()
            })

            # 상세 페이지 크롤링
            for link in detailLinks[:10]:
                time.sleep(0.5)
                try:
                    detailResp = session.get(link["url"], timeout=30)
                    detailSoup = BeautifulSoup(detailResp.text, "html.parser")

                    for tag in detailSoup.find_all(["script", "style", "nav", "footer"]):
                        tag.decompose()

                    # 정보 추출
                    info = {}
                    for dl in detailSoup.find_all("dl"):
                        dt = dl.find("dt")
                        dd = dl.find("dd")
                        if dt and dd:
                            key = dt.get_text(strip=True)
                            val = dd.get_text(strip=True)
                            if key and val and len(key) < 50:
                                info[key] = val

                    detailContent = detailSoup.find("div", id="container")
                    detailText = detailContent.get_text(separator="\n", strip=True)[:3000] if detailContent else ""

                    allData.append({
                        "hotel": hotelKey,
                        "hotel_name": hotelConfig["name"],
                        "section": section,
                        "url": link["url"],
                        "name": link["name"],
                        "info": info,
                        "content": detailText,
                        "crawled_at": datetime.now().isoformat()
                    })
                    print(f"    -> {link['name'][:30]}")
                except Exception as e:
                    print(f"    [에러] {link['url']}: {e}")

        except Exception as e:
            print(f"  [에러] {section}: {e}")

    # 저장
    outputFile = OUTPUT_DIR / f"{hotelKey}_deep.json"
    with open(outputFile, "w", encoding="utf-8") as f:
        json.dump({
            "hotel": hotelKey,
            "hotel_name": hotelConfig["name"],
            "phone": hotelConfig["phone"],
            "crawled_at": datetime.now().isoformat(),
            "total_items": len(allData),
            "data": allData
        }, f, ensure_ascii=False, indent=2)

    print(f"[완료] {len(allData)}개 페이지 → {outputFile}")
    return allData


def main():
    print("=" * 60)
    print("조선호텔 전체 심층 크롤링 시작")
    print("=" * 60)

    for hotelKey, config in HOTELS.items():
        crawlWithPlaywright(hotelKey, config)
        time.sleep(2)

    print("\n" + "=" * 60)
    print("전체 크롤링 완료!")
    print("=" * 60)


if __name__ == "__main__":
    main()
