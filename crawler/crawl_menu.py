#!/usr/bin/env python3
"""
전체 조선호텔 레스토랑 메뉴 크롤링 스크립트 (Playwright)
[메뉴 자세히 보기] 모달(#menuPopup)의 LUNCH/DINNER/A LA CARTE 등 코스 메뉴를 크롤링

모달 DOM 구조:
  #menuPopup (class: layerPop)
    .layerCont
      .menuPanArea
        h2.compTit — 레스토랑명
        ul.tabType03.tabToggle — 탭 목록 (li > a[href="#ID_01"])
        .tabCont.menuCont (id="ID_01") — 각 탭 콘텐츠 (display:block/none)
      .btnClose — 닫기 버튼
"""

import json
import asyncio
import os
import sys
from datetime import datetime

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("playwright 설치 필요: pip install playwright && playwright install chromium")
    sys.exit(1)

# 전체 호텔 레스토랑 목록
RESTAURANTS = {
    "josun_palace": {
        "hotel_name": "조선 팰리스",
        "base_url": "https://jpg.josunhotel.com/dining",
        "pages": [
            {"slug": "constans.do", "name": "콘스탄스", "name_en": "Constans"},
            {"slug": "1914.do", "name": "1914 라운지앤바", "name_en": "1914 Lounge & Bar"},
            {"slug": "EatanicGarden.do", "name": "이타닉 가든", "name_en": "Eatanic Garden"},
            {"slug": "HongYuan.do", "name": "더 그레이트 홍연", "name_en": "The Great Hong Yuan"},
            {"slug": "JosunDeli.do", "name": "조선델리 더 부티크", "name_en": "Josun Deli The Boutique"},
        ]
    },
    "grand_josun_busan": {
        "hotel_name": "그랜드 조선 부산",
        "base_url": "https://gjb.josunhotel.com/dining",
        "pages": [
            {"slug": "aria.do", "name": "아리아", "name_en": "Aria"},
            {"slug": "palais.do", "name": "팔레드 신", "name_en": "Palais de Chine"},
            {"slug": "lounge.do", "name": "라운지&바", "name_en": "Lounge & Bar"},
            {"slug": "deli.do", "name": "조선 델리", "name_en": "Josun Deli"},
        ]
    },
    "grand_josun_jeju": {
        "hotel_name": "그랜드 조선 제주",
        "base_url": "https://gjj.josunhotel.com/dining",
        "pages": [
            {"slug": "aria.do", "name": "아리아", "name_en": "Aria"},
            {"slug": "peak.do", "name": "피크포인트", "name_en": "Peak Point"},
            {"slug": "loungebar.do", "name": "라운지바", "name_en": "Lounge Bar"},
            {"slug": "deli.do", "name": "조선 델리", "name_en": "Josun Deli"},
            {"slug": "eat2o.do", "name": "잇투오", "name_en": "Eat2o"},
            {"slug": "granj.do", "name": "그랑 제이", "name_en": "Gran J"},
            {"slug": "heavenlyLounge.do", "name": "헤븐리 라운지", "name_en": "Heavenly Lounge"},
        ]
    },
    "lescape": {
        "hotel_name": "레스케이프",
        "base_url": "https://les.josunhotel.com/dining",
        "pages": [
            {"slug": "lamantsecret.do", "name": "라망 시크레", "name_en": "L'Amant Secret"},
            {"slug": "palaisdechine.do", "name": "팔레드 신", "name_en": "Palais de Chine"},
            {"slug": "marquedamour.do", "name": "마크 다모르", "name_en": "Marque D'Amour"},
            {"slug": "teasalon.do", "name": "티 살롱", "name_en": "Tea Salon"},
        ]
    },
    "gravity_pangyo": {
        "hotel_name": "그래비티 판교",
        "base_url": "https://grp.josunhotel.com/dining",
        "pages": [
            {"slug": "andish.do", "name": "앤디쉬", "name_en": "Andish"},
            {"slug": "zerovity.do", "name": "제로비티", "name_en": "Zerovity"},
            {"slug": "voost.do", "name": "부스트", "name_en": "Voost"},
            {"slug": "josunDeli.do", "name": "조선 델리", "name_en": "Josun Deli"},
        ]
    }
}


async def crawlRestaurantMenu(page, url, hotelId, hotelName, restaurant):
    """단일 레스토랑 페이지에서 메뉴 크롤링"""
    print(f"\n  📍 {restaurant['name']} ({restaurant['name_en']}) - {url}")

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"    [ERROR] 페이지 로드 실패: {e}")
        return None

    # [메뉴 자세히 보기] 버튼 찾기 — 실제 DOM에서 text 기반 검색
    menuBtn = await page.evaluate("""
    () => {
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            if (btn.textContent.includes('메뉴') && btn.textContent.includes('보기')) {
                return true;
            }
        }
        return false;
    }
    """)

    if not menuBtn:
        print(f"    [SKIP] 메뉴 버튼 없음")
        return None

    # 버튼 클릭
    try:
        await page.evaluate("""
        () => {
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                if (btn.textContent.includes('메뉴') && btn.textContent.includes('보기')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }
        """)
        await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"    [ERROR] 버튼 클릭 실패: {e}")
        return None

    # #menuPopup 모달에서 탭 목록 추출
    tabList = await page.evaluate("""
    () => {
        const popup = document.getElementById('menuPopup');
        if (!popup || popup.style.display === 'none') return null;

        const title = popup.querySelector('h2.compTit');
        const titleText = title ? title.textContent.trim() : '';

        const tabs = popup.querySelectorAll('.tabType03 li a');
        if (tabs.length > 0) {
            const tabInfo = [];
            tabs.forEach(tab => {
                const href = tab.getAttribute('href');
                tabInfo.push({
                    name: tab.textContent.trim(),
                    contId: href ? href.replace('#', '') : ''
                });
            });
            return {title: titleText, tabs: tabInfo};
        } else {
            return {title: titleText, tabs: []};
        }
    }
    """)

    if not tabList:
        print(f"    [SKIP] 메뉴 데이터 없음 (모달 미표시)")
        return None

    menuResult = {}
    title = tabList.get("title", "")

    if tabList["tabs"]:
        # 각 탭을 클릭해서 활성 상태(display:block)에서 innerText 추출
        for tabInfo in tabList["tabs"]:
            tabName = tabInfo["name"]
            contId = tabInfo["contId"]
            if not contId:
                continue

            # 탭 클릭 (fncSelectMenuTab JS 함수 호출)
            await page.evaluate(f"() => {{ if (typeof fncSelectMenuTab === 'function') fncSelectMenuTab('{contId}'); }}")
            await page.wait_for_timeout(300)

            # 활성 상태에서 innerText 추출
            content = await page.evaluate("""
            (contId) => {
                const el = document.getElementById(contId);
                if (!el) return null;
                // display:block 강제 (fncSelectMenuTab 미작동 시 폴백)
                const prevDisplay = el.style.display;
                el.style.display = 'block';
                const text = el.innerText.trim();
                el.style.display = prevDisplay;
                return text;
            }
            """, contId)

            if content and len(content) > 10:
                menuResult[tabName] = content
                print(f"    ✅ {tabName}: {len(content)}자")
    else:
        # 탭 없는 경우 — 전체 모달 콘텐츠
        content = await page.evaluate("""
        () => {
            const popup = document.getElementById('menuPopup');
            const menuArea = popup.querySelector('.menuPanArea') || popup.querySelector('.layerCont');
            return menuArea ? menuArea.innerText.trim() : null;
        }
        """)
        if content and len(content) > 10:
            menuResult["MENU"] = content
            print(f"    ✅ MENU: {len(content)}자")

    # 모달 닫기
    await page.evaluate("""
    () => {
        const popup = document.getElementById('menuPopup');
        if (popup) {
            const closeBtn = popup.querySelector('.btnClose');
            if (closeBtn) closeBtn.click();
        }
    }
    """)
    await page.wait_for_timeout(500)

    if not menuResult:
        print(f"    [SKIP] 메뉴 콘텐츠 없음")
        return None

    tabNames = list(menuResult.keys())
    totalChars = sum(len(v) for v in menuResult.values())

    return {
        "hotel": hotelId,
        "hotel_name": hotelName,
        "restaurant_name": restaurant["name"],
        "restaurant_name_en": restaurant["name_en"],
        "modal_title": title,
        "url": url,
        "menu_tabs": menuResult,
        "crawled_at": datetime.now().isoformat()
    }


async def main():
    """전체 호텔 레스토랑 메뉴 크롤링"""
    print("=" * 60)
    print("🍽️  조선호텔 전체 레스토랑 메뉴 크롤링 시작")
    print("=" * 60)

    allMenus = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ko-KR"
        )
        page = await context.new_page()

        for hotelId, hotelInfo in RESTAURANTS.items():
            hotelName = hotelInfo["hotel_name"]
            baseUrl = hotelInfo["base_url"]
            print(f"\n{'='*50}")
            print(f"🏨 {hotelName} ({hotelId})")
            print(f"{'='*50}")

            for restaurant in hotelInfo["pages"]:
                url = f"{baseUrl}/{restaurant['slug']}"
                result = await crawlRestaurantMenu(page, url, hotelId, hotelName, restaurant)
                if result:
                    allMenus.append(result)

        await browser.close()

    # 결과 저장
    outputPath = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "dining_menus_raw.json")
    outputPath = os.path.normpath(outputPath)
    os.makedirs(os.path.dirname(outputPath), exist_ok=True)

    with open(outputPath, "w", encoding="utf-8") as f:
        json.dump(allMenus, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ 크롤링 완료! {len(allMenus)}개 레스토랑 메뉴 저장")
    print(f"📁 저장 경로: {outputPath}")
    print(f"{'='*60}")

    return allMenus


if __name__ == "__main__":
    asyncio.run(main())
