#!/usr/bin/env python3
"""
심층 크롤링 데이터 처리 모듈
- deep_crawled JSON 파일을 청크로 변환
- 기존 indexer와 호환되는 형식으로 출력
"""

import json
import re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Chunk:
    """청크 데이터 클래스"""
    chunk_id: str
    doc_id: str
    hotel: str
    hotel_name: str
    page_type: str
    url: str
    category: str
    language: str
    updated_at: str
    chunk_index: int
    chunk_text: str
    metadata: Optional[dict] = None


class DeepCrawledProcessor:
    """심층 크롤링 데이터 처리기"""

    MAX_CHUNK_SIZE = 800  # 최대 문자 수

    def __init__(self):
        self.basePath = Path(__file__).parent.parent
        self.deepPath = self.basePath / "data" / "raw" / "deep_crawled"
        self.chunkPath = self.basePath / "data" / "chunks"
        self.chunkPath.mkdir(parents=True, exist_ok=True)

    def _cleanText(self, text: str) -> str:
        """텍스트 정제"""
        text = re.sub(r'\s+', ' ', text)
        text = text.replace('\xa0', ' ')
        text = text.replace('\u200b', '')
        return text.strip()

    def _detectCategory(self, section: str, name: str = "") -> str:
        """카테고리 감지"""
        categoryMap = {
            "rooms": "객실",
            "dining": "다이닝",
            "facilities": "부대시설",
            "faq": "FAQ",
            "policy": "정책",
            "meeting": "연회",
            "offers": "패키지",
            "about": "소개",
        }
        return categoryMap.get(section, section)

    def _buildRoomText(self, item: dict) -> str:
        """객실 정보를 텍스트로 변환"""
        parts = []

        name = item.get("name", "")
        hotelName = item.get("hotel_name", "")
        category = item.get("category", "")

        if name:
            parts.append(f"{hotelName} {name} 객실 ({category})")

        # 개요 정보
        overview = item.get("overview", {})
        if overview:
            overviewText = []
            keyMap = {
                "LOCATION": "위치",
                "BEDS": "침대",
                "SIZE": "크기",
                "ROOM FEATURES": "객실 구성",
                "VIEW": "전망",
                "CHECK-IN/CHECK-OUT": "체크인/아웃"
            }
            for key, val in overview.items():
                korKey = keyMap.get(key, key)
                overviewText.append(f"- {korKey}: {val}")
            if overviewText:
                parts.append("객실 정보:\n" + "\n".join(overviewText))

        # 가격
        price = item.get("price", "")
        if price:
            parts.append(f"정상가: {price}")

        # 어메니티
        amenities = item.get("amenities", [])
        if amenities:
            parts.append(f"어메니티: {', '.join(amenities)}")

        # 안내사항
        notices = item.get("notices", [])
        if notices:
            parts.append("안내사항:\n" + "\n".join([f"- {n}" for n in notices]))

        # 서비스
        services = item.get("services", [])
        if services:
            svcText = [f"- {s['name']}: {s.get('hours', '')}" for s in services]
            if svcText:
                parts.append("이용 가능 시설:\n" + "\n".join(svcText))

        return "\n\n".join(parts)

    def _buildDiningText(self, item: dict) -> str:
        """다이닝 정보를 텍스트로 변환"""
        parts = []

        hotelName = item.get("hotel_name", "")
        title = item.get("title", "")
        content = item.get("content", "")
        url = item.get("url", "")

        # 레스토랑명 추출 (title에서 또는 content에서)
        restaurantName = ""
        if title:
            # "다이닝 - 아리아(Aria) | 그랜드 조선 부산" -> "아리아(Aria)"
            import re
            match = re.search(r'다이닝\s*[-–]\s*([^|]+)', title)
            if match:
                restaurantName = match.group(1).strip()
            elif "subMain" not in url:
                restaurantName = title.split("|")[0].strip()

        # 레스토랑 목록 페이지 (subMain.do)
        if "subMain" in url:
            parts.append(f"{hotelName} 레스토랑 안내")
            if content:
                # 레스토랑 목록 추출
                lines = content.split("\n")
                restaurants = []
                for line in lines:
                    line = line.strip()
                    if any(kw in line for kw in ["자세히보기", "다이닝예약"]):
                        continue
                    if len(line) > 5 and len(line) < 100:
                        restaurants.append(line)
                if restaurants[:10]:
                    parts.append("레스토랑 목록:\n" + "\n".join([f"- {r}" for r in restaurants[:10]]))
        else:
            # 개별 레스토랑 상세
            if restaurantName:
                parts.append(f"{hotelName} 레스토랑: {restaurantName}")
            else:
                parts.append(f"{hotelName} 레스토랑")

        # 기본 정보
        info = item.get("info", {})
        if info:
            infoText = []
            keyMap = {
                "LOCATION": "위치",
                "INQUIRY": "문의/예약",
                "CAPACITY": "좌석 수",
                "DRESS CODE": "드레스 코드",
                "HOURS OF OPERATION": "운영시간",
                "HOURS": "운영시간",
                "MENU": "메뉴"
            }
            for key, val in info.items():
                if key == "MENU" and "자세히" in val:
                    continue  # 메뉴 링크는 제외
                korKey = keyMap.get(key, key)
                infoText.append(f"- {korKey}: {val}")
            if infoText:
                parts.append("\n".join(infoText))

        # 운영시간
        hours = item.get("hours", "")
        if hours and "HOURS" not in str(info):
            parts.append(f"- 운영시간: {hours}")

        # 설명 (content에서 추출)
        if content and "subMain" not in url:
            # 첫 2-3문장 추출
            sentences = content.split(".")[:3]
            desc = ". ".join(sentences).strip()
            if desc and len(desc) > 30:
                desc = self._cleanText(desc)
                if len(desc) > 300:
                    desc = desc[:300] + "..."
                parts.append(f"\n{desc}")

        return "\n\n".join(parts)

    def _buildFacilityText(self, item: dict) -> str:
        """시설 정보를 텍스트로 변환"""
        parts = []

        name = item.get("name", "")
        hotelName = item.get("hotel_name", "")

        if name:
            parts.append(f"{hotelName} {name}")

        # 기본 정보
        info = item.get("info", {})
        if info:
            infoText = []
            keyMap = {
                "LOCATION": "위치",
                "HOURS": "운영시간",
                "INQUIRY": "문의",
                "AMENITY": "제공 물품"
            }
            for key, val in info.items():
                korKey = keyMap.get(key, key)
                infoText.append(f"- {korKey}: {val}")
            if infoText:
                parts.append("\n".join(infoText))

        # 안내사항
        notices = item.get("notices", [])
        if notices:
            parts.append("이용 안내:\n" + "\n".join([f"- {n}" for n in notices]))

        return "\n\n".join(parts)

    def _buildGeneralText(self, item: dict) -> str:
        """일반 콘텐츠를 텍스트로 변환"""
        parts = []

        name = item.get("name", "")
        title = item.get("title", "")
        content = item.get("content", "")

        if name:
            parts.append(name)
        if title and title != name:
            parts.append(title)
        if content:
            # 콘텐츠가 너무 길면 잘라냄
            cleanContent = self._cleanText(content)
            if len(cleanContent) > 1500:
                cleanContent = cleanContent[:1500] + "..."
            parts.append(cleanContent)

        return "\n\n".join(parts)

    def _extractServiceInfo(self, content: str, hotelName: str) -> list[str]:
        """콘텐츠에서 서비스 정보 (조식, 피트니스 등) 추출"""
        import re
        extraChunks = []

        # 조식/LA MAISON BOUTIQUE 정보 추출
        breakfastPatterns = [
            r'(LA MAISON BOUTIQUE[^\.]*?Breakfast[^\.]*?\d{2}:\d{2}[^\.]*)',
            r'(조식[^\.]*?\d{2}:\d{2}[^\.]*)',
            r'(Breakfast\s*\d{2}:\d{2}\s*[-–]\s*\d{2}:\d{2})',
        ]
        for pattern in breakfastPatterns:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                text = match.group(1).strip()
                # 더 완전한 정보 추출
                startIdx = content.find("LA MAISON BOUTIQUE")
                if startIdx >= 0:
                    endIdx = content.find("FITNESS", startIdx)
                    if endIdx < 0:
                        endIdx = startIdx + 500
                    serviceText = content[startIdx:endIdx].strip()
                    if serviceText and len(serviceText) > 50:
                        extraChunks.append(f"{hotelName} 조식 안내\n\n{serviceText}")
                break

        # 피트니스 정보 추출
        fitnessMatch = re.search(r'(FITNESS[^\.]*?24\s*Hours|FITNESS[^\.]*?\d{2}:\d{2}[^\.]*)', content, re.IGNORECASE)
        if fitnessMatch:
            startIdx = content.find("FITNESS")
            if startIdx >= 0:
                endIdx = min(startIdx + 300, len(content))
                fitnessText = content[startIdx:endIdx].strip()
                if fitnessText and len(fitnessText) > 30:
                    extraChunks.append(f"{hotelName} 피트니스 안내\n\n{fitnessText}")

        return extraChunks

    def _extractCheckinInfo(self, content: str, hotelName: str) -> list[str]:
        """체크인/체크아웃 정보 추출"""
        import re
        extraChunks = []

        # 체크인 패턴들
        patterns = [
            # "체크인은 15:00, 체크아웃은 11:00입니다"
            r'체크인[은는]?\s*(\d{1,2}[:시]\d{0,2})[^체]*체크아웃[은는]?\s*(\d{1,2}[:시]\d{0,2})',
            # "체크인 오후 3시 이후, 체크아웃 오전 11시"
            r'체크인\s*(오[전후]\s*\d{1,2}시[^,]*)[,\s]*체크아웃\s*(오[전후]\s*\d{1,2}시)',
            # "체크인 15시부터, 체크아웃 11시"
            r'체크인[은는]?\s*(\d{1,2}시)[^체]*체크아웃[은는]?\s*(\d{1,2}시)',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                checkin = match.group(1).strip()
                checkout = match.group(2).strip()

                # 시간 정규화
                checkin = checkin.replace("시", ":00").replace(":00:00", ":00")
                checkout = checkout.replace("시", ":00").replace(":00:00", ":00")

                # 오전/오후 변환
                if "오후 3" in checkin or "오후 15" in checkin:
                    checkin = "15:00"
                elif "15" in checkin:
                    checkin = "15:00"

                if "오전 11" in checkout:
                    checkout = "11:00"
                elif "11" in checkout:
                    checkout = "11:00"
                elif "12" in checkout:
                    checkout = "12:00"

                chunkText = f"""{hotelName} 체크인/체크아웃 안내

Q: {hotelName} 체크인 시간이 어떻게 되나요?
A: 체크인은 {checkin}부터 가능합니다.

Q: {hotelName} 체크아웃 시간은 언제인가요?
A: 체크아웃은 {checkout}까지입니다.

체크인: {checkin}
체크아웃: {checkout}"""

                extraChunks.append(chunkText)
                break

        return extraChunks

    def _extractFAQPairs(self, content: str, hotelName: str) -> list[str]:
        """FAQ Q&A 쌍 추출"""
        import re
        extraChunks = []

        # FAQ 페이지에서 Q&A 쌍 추출
        # 패턴: "질문?\n상세내용 보기\n답변"
        qaPairs = re.findall(
            r'([^\n]+\?)\s*상세내용 보기\s*([^\n]+(?:\n[^\n]+)*?)(?=\n[^\n]+\?|\n전체|\Z)',
            content,
            re.MULTILINE
        )

        for question, answer in qaPairs[:10]:  # 최대 10개
            question = question.strip()
            answer = answer.strip()

            if len(question) < 10 or len(answer) < 10:
                continue

            # 중요 FAQ만 선별
            importantKeywords = [
                "체크인", "체크아웃", "주차", "조식", "인원", "추가", "취소", "환불",
                "반려", "애완", "수영", "피트니스", "사우나", "예약", "결제"
            ]

            if any(kw in question for kw in importantKeywords):
                chunkText = f"""{hotelName} FAQ

Q: {question}
A: {answer}"""
                extraChunks.append(chunkText)

        return extraChunks

    def processItem(self, item: dict, hotel: str, idx: int) -> list[Chunk]:
        """개별 아이템을 청크로 변환"""
        chunks = []

        itemType = item.get("type", item.get("section", "general"))
        section = item.get("section", itemType)
        hotelName = item.get("hotel_name", "")
        content = item.get("content", "")
        url = item.get("url", "")

        # 콘텐츠에서 서비스 정보 추출 (조식, 피트니스 등)
        if content:
            extraTexts = self._extractServiceInfo(content, hotelName)
            for extraIdx, extraText in enumerate(extraTexts):
                extraDocId = f"{hotel}_{section}_{idx:03d}_svc{extraIdx}"
                extraChunk = Chunk(
                    chunk_id=f"{extraDocId}_c000",
                    doc_id=extraDocId,
                    hotel=hotel,
                    hotel_name=hotelName,
                    page_type="service",
                    url=url,
                    category="서비스",
                    language="ko",
                    updated_at=item.get("crawled_at", datetime.now().isoformat()),
                    chunk_index=0,
                    chunk_text=extraText,
                    metadata={"name": item.get("name", ""), "type": "service_info"}
                )
                chunks.append(extraChunk)

        # 체크인/체크아웃 정보 추출 (객실 페이지에서)
        if content and ("체크인" in content or "check-in" in content.lower()):
            checkinTexts = self._extractCheckinInfo(content, hotelName)
            for extraIdx, extraText in enumerate(checkinTexts):
                extraDocId = f"{hotel}_checkin_{idx:03d}_{extraIdx}"
                extraChunk = Chunk(
                    chunk_id=f"{extraDocId}_c000",
                    doc_id=extraDocId,
                    hotel=hotel,
                    hotel_name=hotelName,
                    page_type="policy",
                    url=url,
                    category="체크인/아웃",
                    language="ko",
                    updated_at=item.get("crawled_at", datetime.now().isoformat()),
                    chunk_index=0,
                    chunk_text=extraText,
                    metadata={"name": "체크인/체크아웃", "type": "policy_info"}
                )
                chunks.append(extraChunk)

        # FAQ 페이지에서 Q&A 추출
        if "faq" in url.lower():
            faqTexts = self._extractFAQPairs(content, hotelName)
            for extraIdx, extraText in enumerate(faqTexts):
                extraDocId = f"{hotel}_faq_{idx:03d}_{extraIdx}"
                extraChunk = Chunk(
                    chunk_id=f"{extraDocId}_c000",
                    doc_id=extraDocId,
                    hotel=hotel,
                    hotel_name=hotelName,
                    page_type="faq",
                    url=url,
                    category="FAQ",
                    language="ko",
                    updated_at=item.get("crawled_at", datetime.now().isoformat()),
                    chunk_index=0,
                    chunk_text=extraText,
                    metadata={"name": "FAQ", "type": "faq_info"}
                )
                chunks.append(extraChunk)

        # 타입별 텍스트 생성
        if itemType == "room":
            text = self._buildRoomText(item)
        elif itemType == "dining":
            text = self._buildDiningText(item)
        elif itemType == "facility":
            text = self._buildFacilityText(item)
        else:
            text = self._buildGeneralText(item)

        if not text or len(text) < 20:
            return chunks

        # 청크 분할 (너무 긴 경우)
        texts = [text] if len(text) <= self.MAX_CHUNK_SIZE else self._splitText(text)

        for chunkIdx, chunkText in enumerate(texts):
            docId = f"{hotel}_{section}_{idx:03d}"
            chunk = Chunk(
                chunk_id=f"{docId}_c{chunkIdx:03d}",
                doc_id=docId,
                hotel=hotel,
                hotel_name=item.get("hotel_name", ""),
                page_type=section,
                url=item.get("url", ""),
                category=self._detectCategory(section, item.get("name", "")),
                language="ko",
                updated_at=item.get("crawled_at", datetime.now().isoformat()),
                chunk_index=chunkIdx,
                chunk_text=chunkText,
                metadata={
                    "name": item.get("name", ""),
                    "type": itemType
                }
            )
            chunks.append(chunk)

        return chunks

    def _splitText(self, text: str) -> list[str]:
        """긴 텍스트 분할"""
        if len(text) <= self.MAX_CHUNK_SIZE:
            return [text]

        chunks = []
        paragraphs = text.split("\n\n")
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 <= self.MAX_CHUNK_SIZE:
                current = current + "\n\n" + para if current else para
            else:
                if current:
                    chunks.append(current)
                current = para

        if current:
            chunks.append(current)

        return chunks

    def processFile(self, filepath: Path) -> list[Chunk]:
        """JSON 파일 처리"""
        print(f"\n[처리 중] {filepath.name}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        hotel = data.get("hotel", "")
        hotelName = data.get("hotel_name", "")
        items = data.get("data", [])

        print(f"  호텔: {hotelName}, 아이템: {len(items)}개")

        chunks = []
        for idx, item in enumerate(items):
            # 호텔 정보 주입
            item["hotel"] = hotel
            item["hotel_name"] = hotelName

            itemChunks = self.processItem(item, hotel, idx)
            chunks.extend(itemChunks)

        print(f"  -> {len(chunks)}개 청크 생성")
        return chunks

    def processAll(self) -> list[Chunk]:
        """모든 deep_crawled 파일 처리"""
        allChunks = []

        # _complete.json 파일 (완전 크롤링) - 우선 사용
        completeFiles = list(self.deepPath.glob("*_complete.json"))

        # _complete.json이 없으면 _deep.json 사용
        if not completeFiles:
            completeFiles = list(self.deepPath.glob("*_deep.json"))

        # MCP 크롤링 파일 (rooms, dining, facilities)
        mcpFiles = list(self.deepPath.glob("*_rooms.json"))
        mcpFiles += list(self.deepPath.glob("*_dining.json"))
        mcpFiles += list(self.deepPath.glob("*_facilities.json"))

        allFiles = completeFiles + mcpFiles
        print(f"[심층 크롤링 데이터 처리] {len(allFiles)}개 파일")

        for filepath in allFiles:
            chunks = self.processFile(filepath)
            allChunks.extend(chunks)

        return allChunks

    def saveChunks(self, chunks: list[Chunk]):
        """청크 저장"""
        # 호텔별로 분류
        hotelChunks = {}
        for chunk in chunks:
            if chunk.hotel not in hotelChunks:
                hotelChunks[chunk.hotel] = []
            hotelChunks[chunk.hotel].append(chunk)

        # 호텔별 저장
        for hotel, hotelChunkList in hotelChunks.items():
            hotelPath = self.chunkPath / hotel
            hotelPath.mkdir(exist_ok=True)

            # 호텔별 통합 파일 저장
            allChunksPath = hotelPath / "_all_chunks.json"
            with open(allChunksPath, "w", encoding="utf-8") as f:
                json.dump([asdict(c) for c in hotelChunkList], f, ensure_ascii=False, indent=2)

            print(f"  [{hotel}] {len(hotelChunkList)}개 청크 -> {allChunksPath}")

        # 전체 통합 파일
        exportPath = self.chunkPath / "_all_hotels_chunks.json"
        with open(exportPath, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in chunks], f, ensure_ascii=False, indent=2)

        print(f"\n[저장 완료] 총 {len(chunks)}개 청크 -> {exportPath}")


def main():
    """메인 실행"""
    processor = DeepCrawledProcessor()
    chunks = processor.processAll()

    if chunks:
        processor.saveChunks(chunks)
    else:
        print("\n[완료] 처리할 데이터 없음")


if __name__ == "__main__":
    main()
