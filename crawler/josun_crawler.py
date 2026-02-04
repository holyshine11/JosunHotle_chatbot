"""
조선호텔 FAQ/정책 크롤러
- 5개 호텔 대상: 조선팰리스, 그랜드조선부산, 그랜드조선제주, 레스케이프, 그래비티판교
- 증분 업데이트 지원 (content_hash 기반)
"""

import json
import hashlib
import time
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

import requests
from bs4 import BeautifulSoup


@dataclass
class Document:
    """크롤링된 문서 데이터 클래스"""
    doc_id: str
    hotel: str
    hotel_name: str
    page_type: str
    url: str
    title: str
    content: str
    html: str
    content_hash: str
    fetched_at: str
    category: Optional[str] = None


class JosunCrawler:
    """조선호텔 크롤러"""

    def __init__(self, config_path: str = None):
        self.base_path = Path(__file__).parent.parent
        self.config_path = config_path or self.base_path / "crawler" / "seed_urls.json"
        self.raw_path = self.base_path / "data" / "raw"
        self.hash_path = self.base_path / "data" / "hash_store.json"

        # 디렉토리 생성
        self.raw_path.mkdir(parents=True, exist_ok=True)

        # 설정 로드
        self.config = self._loadConfig()
        self.hotels = self.config["hotels"]
        self.crawlConfig = self.config["crawl_config"]

        # 해시 저장소 로드
        self.hashStore = self._loadHashStore()

        # 세션 설정
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.crawlConfig["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
        })

    def _loadConfig(self) -> dict:
        """설정 파일 로드"""
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _loadHashStore(self) -> dict:
        """해시 저장소 로드"""
        if self.hash_path.exists():
            with open(self.hash_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _saveHashStore(self):
        """해시 저장소 저장"""
        with open(self.hash_path, "w", encoding="utf-8") as f:
            json.dump(self.hashStore, f, ensure_ascii=False, indent=2)

    def _computeHash(self, content: str) -> str:
        """콘텐츠 해시 계산"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _generateDocId(self, hotel: str, pageType: str, index: int = 0) -> str:
        """문서 ID 생성"""
        timestamp = datetime.now().strftime("%Y%m%d")
        return f"{hotel}_{pageType}_{timestamp}_{index:03d}"

    def _fetch(self, url: str) -> Optional[str]:
        """URL에서 HTML 가져오기"""
        for attempt in range(self.crawlConfig["max_retries"]):
            try:
                response = self.session.get(
                    url,
                    timeout=self.crawlConfig["timeout"]
                )
                response.raise_for_status()
                response.encoding = "utf-8"
                return response.text
            except requests.RequestException as e:
                print(f"  [오류] {url} 요청 실패 (시도 {attempt + 1}): {e}")
                if attempt < self.crawlConfig["max_retries"] - 1:
                    time.sleep(self.crawlConfig["request_delay"] * 2)
        return None

    def _extractFaqContent(self, html: str) -> list[dict]:
        """FAQ 페이지에서 Q&A 추출 (조선호텔 전용)"""
        soup = BeautifulSoup(html, "lxml")
        faqs = []

        # 조선호텔 FAQ 구조: toggleList > li > titArea(listTit, opValue) + toggleCont(toggleInner)
        faqList = soup.find(class_="toggleList")
        if faqList:
            items = faqList.find_all("li")
            for item in items:
                category = item.find(class_="listTit")
                question = item.find(class_="opValue")
                answer = item.find(class_="toggleInner")

                if question and answer:
                    faq = {
                        "question": question.get_text(strip=True),
                        "answer": answer.get_text(separator=" ", strip=True)
                    }
                    if category:
                        faq["category"] = category.get_text(strip=True)
                    faqs.append(faq)

        # fallback: 일반적인 FAQ 패턴
        if not faqs:
            # dl/dt/dd 구조
            dlItems = soup.find_all("dl", class_=re.compile(r"faq|accordion|qa", re.I))
            for dl in dlItems:
                question = dl.find("dt")
                answer = dl.find("dd")
                if question and answer:
                    faqs.append({
                        "question": question.get_text(strip=True),
                        "answer": answer.get_text(strip=True)
                    })

        return faqs

    def _extractPolicyContent(self, html: str) -> list[dict]:
        """정책 페이지에서 본문 추출 (조선호텔 전용)"""
        soup = BeautifulSoup(html, "lxml")
        policies = []

        # 불필요한 요소 제거
        for tag in soup.find_all(["script", "style", "header", "footer", "nav"]):
            tag.decompose()

        # 조선호텔 정책 구조: dl > dt(제목) + dd(내용)
        dlItems = soup.find_all("dl")
        for dl in dlItems:
            dtTags = dl.find_all("dt")
            ddTags = dl.find_all("dd")

            for dt, dd in zip(dtTags, ddTags):
                title = dt.get_text(strip=True)
                content = dd.get_text(separator="\n", strip=True)
                if title and content:
                    policies.append({
                        "title": title,
                        "content": content
                    })

        # fallback: 일반 텍스트 추출
        if not policies:
            mainContent = (
                soup.find("main") or
                soup.find(class_=re.compile(r"content|policy", re.I)) or
                soup.find("article")
            )
            if mainContent:
                return [{"title": "정책", "content": mainContent.get_text(separator="\n", strip=True)}]

        return policies

    def _extractGeneralContent(self, html: str) -> list[dict]:
        """일반 페이지(객실, 다이닝, 시설)에서 콘텐츠 추출"""
        soup = BeautifulSoup(html, "lxml")
        sections = []

        # 불필요한 요소 제거
        for tag in soup.find_all(["script", "style", "header", "footer", "nav"]):
            tag.decompose()

        # 섹션별 추출 (h2, h3 기준)
        for heading in soup.find_all(["h2", "h3"]):
            title = heading.get_text(strip=True)
            if not title:
                continue

            # 다음 형제 요소들에서 콘텐츠 수집
            content_parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ["h2", "h3"]:
                    break
                text = sibling.get_text(separator=" ", strip=True)
                if text:
                    content_parts.append(text)

            if content_parts:
                sections.append({
                    "title": title,
                    "content": " ".join(content_parts)
                })

        # fallback: 전체 텍스트
        if not sections:
            body = soup.find("body")
            if body:
                text = body.get_text(separator="\n", strip=True)
                if text:
                    sections.append({"title": "전체", "content": text[:5000]})

        return sections

    def _extractTitle(self, html: str) -> str:
        """페이지 제목 추출"""
        soup = BeautifulSoup(html, "lxml")

        # h1 태그 우선
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)

        # title 태그
        title = soup.find("title")
        if title:
            return title.get_text(strip=True).split("|")[0].strip()

        return ""

    def crawlHotel(self, hotelKey: str, forceUpdate: bool = False) -> list[Document]:
        """특정 호텔 크롤링"""
        if hotelKey not in self.hotels:
            print(f"[오류] 알 수 없는 호텔: {hotelKey}")
            return []

        hotel = self.hotels[hotelKey]
        baseUrl = hotel["base_url"]
        hotelName = hotel["name"]
        documents = []

        print(f"\n[크롤링 시작] {hotelName} ({hotelKey})")
        print("=" * 50)

        for pageType, pagePath in hotel["pages"].items():
            url = f"{baseUrl}{pagePath}"
            print(f"\n  [{pageType}] {url}")

            # HTML 가져오기
            html = self._fetch(url)
            if not html:
                print(f"    -> 실패: HTML을 가져올 수 없음")
                continue

            # 해시 계산 및 변경 확인
            contentHash = self._computeHash(html)
            hashKey = f"{hotelKey}_{pageType}"

            if not forceUpdate and hashKey in self.hashStore:
                if self.hashStore[hashKey] == contentHash:
                    print(f"    -> 스킵: 변경 없음")
                    continue

            # 콘텐츠 추출
            title = self._extractTitle(html)

            if pageType == "faq":
                data = self._extractFaqContent(html)
                content = json.dumps(data, ensure_ascii=False, indent=2)
                print(f"    -> FAQ {len(data)}개 추출")
            elif pageType == "policy":
                data = self._extractPolicyContent(html)
                content = json.dumps(data, ensure_ascii=False, indent=2)
                print(f"    -> 정책 {len(data)}개 항목 추출")
            else:
                # rooms, dining, facilities 등은 텍스트 추출
                data = self._extractGeneralContent(html)
                content = json.dumps(data, ensure_ascii=False, indent=2)
                print(f"    -> 콘텐츠 {len(data)}개 섹션 추출")

            # 문서 생성
            doc = Document(
                doc_id=self._generateDocId(hotelKey, pageType),
                hotel=hotelKey,
                hotel_name=hotelName,
                page_type=pageType,
                url=url,
                title=title,
                content=content,
                html=html,
                content_hash=contentHash,
                fetched_at=datetime.now().isoformat()
            )
            documents.append(doc)

            # 해시 저장소 업데이트
            self.hashStore[hashKey] = contentHash

            # 요청 간 딜레이
            time.sleep(self.crawlConfig["request_delay"])

        return documents

    def crawlAll(self, forceUpdate: bool = False) -> list[Document]:
        """모든 호텔 크롤링"""
        allDocuments = []

        for hotelKey in self.hotels:
            documents = self.crawlHotel(hotelKey, forceUpdate)
            allDocuments.extend(documents)

        # 해시 저장소 저장
        self._saveHashStore()

        return allDocuments

    def saveDocuments(self, documents: list[Document]):
        """문서 저장"""
        for doc in documents:
            # 호텔별 디렉토리 생성
            hotelPath = self.raw_path / doc.hotel
            hotelPath.mkdir(exist_ok=True)

            # JSON으로 저장 (HTML 제외)
            docDict = asdict(doc)
            docDict.pop("html")  # HTML은 별도 저장

            jsonPath = hotelPath / f"{doc.doc_id}.json"
            with open(jsonPath, "w", encoding="utf-8") as f:
                json.dump(docDict, f, ensure_ascii=False, indent=2)

            # HTML 원본 저장
            htmlPath = hotelPath / f"{doc.doc_id}.html"
            with open(htmlPath, "w", encoding="utf-8") as f:
                f.write(doc.html)

        print(f"\n[저장 완료] {len(documents)}개 문서 저장됨")


def main():
    """메인 실행 함수"""
    import argparse

    parser = argparse.ArgumentParser(description="조선호텔 FAQ/정책 크롤러")
    parser.add_argument("--hotel", type=str, help="특정 호텔만 크롤링 (예: josun_palace)")
    parser.add_argument("--force", action="store_true", help="변경 여부와 관계없이 강제 업데이트")
    parser.add_argument("--list", action="store_true", help="호텔 목록 출력")

    args = parser.parse_args()

    crawler = JosunCrawler()

    if args.list:
        print("\n[호텔 목록]")
        for key, hotel in crawler.hotels.items():
            print(f"  - {key}: {hotel['name']}")
        return

    # 크롤링 실행
    if args.hotel:
        documents = crawler.crawlHotel(args.hotel, forceUpdate=args.force)
    else:
        documents = crawler.crawlAll(forceUpdate=args.force)

    # 저장
    if documents:
        crawler.saveDocuments(documents)
        crawler._saveHashStore()
    else:
        print("\n[완료] 새로 크롤링된 문서 없음")


if __name__ == "__main__":
    main()
