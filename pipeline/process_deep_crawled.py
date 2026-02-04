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

        name = item.get("name", "")
        hotelName = item.get("hotel_name", "")
        category = item.get("category", "")

        if name:
            parts.append(f"{hotelName} {name} ({category})")

        # 기본 정보
        info = item.get("info", {})
        if info:
            infoText = []
            keyMap = {
                "LOCATION": "위치",
                "INQUIRY": "문의",
                "CAPACITY": "좌석 수",
                "DRESS CODE": "드레스 코드",
                "HOURS": "운영시간"
            }
            for key, val in info.items():
                korKey = keyMap.get(key, key)
                infoText.append(f"- {korKey}: {val}")
            if infoText:
                parts.append("\n".join(infoText))

        # 운영시간
        hours = item.get("hours", "")
        if hours and "HOURS" not in info:
            parts.append(f"운영시간: {hours}")

        # 설명
        desc = item.get("description", "")
        if desc:
            parts.append(desc)

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

    def processItem(self, item: dict, hotel: str, idx: int) -> list[Chunk]:
        """개별 아이템을 청크로 변환"""
        chunks = []

        itemType = item.get("type", item.get("section", "general"))
        section = item.get("section", itemType)

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
