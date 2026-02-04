"""
데이터 정제 모듈
- 크롤링된 원본 데이터를 정제하여 clean 데이터 생성
- Q/A 구조 보존, 불필요한 문자 제거
"""

import json
import re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class CleanDocument:
    """정제된 문서 데이터 클래스"""
    doc_id: str
    hotel: str
    hotel_name: str
    page_type: str
    url: str
    title: str
    category: str
    language: str
    updated_at: str
    text: str
    metadata: Optional[dict] = None


class Cleaner:
    """데이터 정제 클래스"""

    def __init__(self):
        self.basePath = Path(__file__).parent.parent
        self.rawPath = self.basePath / "data" / "raw"
        self.cleanPath = self.basePath / "data" / "clean"
        self.cleanPath.mkdir(parents=True, exist_ok=True)

        # 카테고리 키워드 매핑
        self.categoryKeywords = {
            "체크인/아웃": ["체크인", "체크아웃", "check-in", "check-out", "입실", "퇴실"],
            "주차": ["주차", "parking", "발렛", "valet"],
            "조식": ["조식", "breakfast", "아침", "뷔페"],
            "객실": ["객실", "room", "침대", "bed", "인원", "엑스트라"],
            "부대시설": ["피트니스", "fitness", "수영", "pool", "사우나", "sauna", "스파", "spa", "웰니스"],
            "위치/교통": ["위치", "교통", "지하철", "공항", "택시", "버스", "location"],
            "환불/취소": ["환불", "취소", "cancel", "refund", "위약금"],
            "반려동물": ["반려동물", "pet", "애완", "강아지", "고양이"],
            "금연": ["금연", "흡연", "smoking"],
            "결제": ["결제", "payment", "카드", "상품권"],
            "멤버십": ["멤버십", "membership", "회원", "포인트"],
            "연회/웨딩": ["연회", "웨딩", "wedding", "banquet"],
        }

    def _detectLanguage(self, text: str) -> str:
        """간단한 언어 감지"""
        # 한글 비율로 판단
        koreanChars = len(re.findall(r'[가-힣]', text))
        totalChars = len(re.findall(r'[a-zA-Z가-힣]', text))

        if totalChars == 0:
            return "ko"

        koreanRatio = koreanChars / totalChars
        if koreanRatio > 0.3:
            return "ko"
        return "en"

    def _detectCategory(self, text: str) -> str:
        """텍스트에서 카테고리 추정"""
        textLower = text.lower()

        for category, keywords in self.categoryKeywords.items():
            for keyword in keywords:
                if keyword.lower() in textLower:
                    return category

        return "일반"

    def _cleanText(self, text: str) -> str:
        """텍스트 정제"""
        # 연속 공백 제거
        text = re.sub(r'\s+', ' ', text)
        # 앞뒤 공백 제거
        text = text.strip()
        # HTML 엔티티 정리
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        # 특수 공백 문자 정리
        text = text.replace('\xa0', ' ')
        text = text.replace('\u200b', '')
        return text

    def cleanFaq(self, rawDoc: dict) -> list[CleanDocument]:
        """FAQ 문서 정제"""
        cleanDocs = []

        content = json.loads(rawDoc["content"])

        for idx, faq in enumerate(content):
            question = self._cleanText(faq.get("question", ""))
            answer = self._cleanText(faq.get("answer", ""))
            category = faq.get("category", "") or self._detectCategory(question + " " + answer)

            # Q&A 형식으로 텍스트 구성
            text = f"Q: {question}\nA: {answer}"

            cleanDoc = CleanDocument(
                doc_id=f"{rawDoc['doc_id']}_{idx:03d}",
                hotel=rawDoc["hotel"],
                hotel_name=rawDoc["hotel_name"],
                page_type="faq",
                url=rawDoc["url"],
                title=question[:50],
                category=category,
                language=self._detectLanguage(text),
                updated_at=rawDoc["fetched_at"],
                text=text,
                metadata={"question": question, "answer": answer}
            )
            cleanDocs.append(cleanDoc)

        return cleanDocs

    def cleanPolicy(self, rawDoc: dict) -> list[CleanDocument]:
        """정책 문서 정제"""
        cleanDocs = []

        content = json.loads(rawDoc["content"])

        for idx, policy in enumerate(content):
            title = self._cleanText(policy.get("title", ""))
            policyContent = self._cleanText(policy.get("content", ""))

            if not title or not policyContent:
                continue

            # 제목에서 번호 제거 (예: "1. 체크인" -> "체크인")
            titleClean = re.sub(r'^\d+\.\s*', '', title)
            category = self._detectCategory(titleClean + " " + policyContent)

            text = f"{titleClean}\n{policyContent}"

            cleanDoc = CleanDocument(
                doc_id=f"{rawDoc['doc_id']}_{idx:03d}",
                hotel=rawDoc["hotel"],
                hotel_name=rawDoc["hotel_name"],
                page_type="policy",
                url=rawDoc["url"],
                title=titleClean,
                category=category,
                language=self._detectLanguage(text),
                updated_at=rawDoc["fetched_at"],
                text=text,
                metadata={"original_title": title}
            )
            cleanDocs.append(cleanDoc)

        return cleanDocs

    def cleanGeneral(self, rawDoc: dict) -> list[CleanDocument]:
        """일반 문서(객실, 다이닝, 시설) 정제"""
        cleanDocs = []

        content = json.loads(rawDoc["content"])

        for idx, section in enumerate(content):
            title = self._cleanText(section.get("title", ""))
            sectionContent = self._cleanText(section.get("content", ""))

            if not sectionContent:
                continue

            text = f"{title}\n{sectionContent}" if title else sectionContent
            category = rawDoc["page_type"]  # rooms, dining, facilities

            cleanDoc = CleanDocument(
                doc_id=f"{rawDoc['doc_id']}_{idx:03d}",
                hotel=rawDoc["hotel"],
                hotel_name=rawDoc["hotel_name"],
                page_type=rawDoc["page_type"],
                url=rawDoc["url"],
                title=title or rawDoc["page_type"],
                category=category,
                language=self._detectLanguage(text),
                updated_at=rawDoc["fetched_at"],
                text=text
            )
            cleanDocs.append(cleanDoc)

        return cleanDocs

    def processDocument(self, rawDoc: dict) -> list[CleanDocument]:
        """문서 타입에 따라 정제 처리"""
        pageType = rawDoc.get("page_type", "")

        if pageType == "faq":
            return self.cleanFaq(rawDoc)
        elif pageType == "policy":
            return self.cleanPolicy(rawDoc)
        else:
            return self.cleanGeneral(rawDoc)

    def processHotel(self, hotelKey: str) -> list[CleanDocument]:
        """호텔 전체 문서 정제"""
        hotelPath = self.rawPath / hotelKey
        if not hotelPath.exists():
            print(f"[오류] 호텔 디렉토리 없음: {hotelKey}")
            return []

        cleanDocs = []
        jsonFiles = list(hotelPath.glob("*.json"))

        print(f"\n[정제 시작] {hotelKey} ({len(jsonFiles)}개 파일)")

        for jsonFile in jsonFiles:
            with open(jsonFile, "r", encoding="utf-8") as f:
                rawDoc = json.load(f)

            docs = self.processDocument(rawDoc)
            cleanDocs.extend(docs)
            print(f"  - {jsonFile.name}: {len(docs)}개 정제")

        return cleanDocs

    def processAll(self) -> list[CleanDocument]:
        """전체 호텔 정제"""
        allDocs = []

        for hotelDir in self.rawPath.iterdir():
            if hotelDir.is_dir():
                docs = self.processHotel(hotelDir.name)
                allDocs.extend(docs)

        return allDocs

    def saveDocuments(self, documents: list[CleanDocument]):
        """정제된 문서 저장"""
        for doc in documents:
            # 호텔별 디렉토리 생성
            hotelPath = self.cleanPath / doc.hotel
            hotelPath.mkdir(exist_ok=True)

            # JSON 저장
            docDict = asdict(doc)
            jsonPath = hotelPath / f"{doc.doc_id}.json"
            with open(jsonPath, "w", encoding="utf-8") as f:
                json.dump(docDict, f, ensure_ascii=False, indent=2)

        print(f"\n[저장 완료] {len(documents)}개 정제 문서")


def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(description="데이터 정제")
    parser.add_argument("--hotel", type=str, help="특정 호텔만 처리")

    args = parser.parse_args()

    cleaner = Cleaner()

    if args.hotel:
        documents = cleaner.processHotel(args.hotel)
    else:
        documents = cleaner.processAll()

    if documents:
        cleaner.saveDocuments(documents)
    else:
        print("\n[완료] 정제할 문서 없음")


if __name__ == "__main__":
    main()
