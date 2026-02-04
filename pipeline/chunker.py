"""
청킹 모듈
- 정제된 문서를 Vector DB 인덱싱용 청크로 분할
- FAQ는 Q/A 단위 유지, 긴 텍스트는 300~600 토큰 단위 분할
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


class Chunker:
    """청킹 클래스"""

    # 토큰 추정: 한글 1자 ≈ 1.5토큰, 영어 1단어 ≈ 1.3토큰
    # 안전하게 문자 기준으로 처리 (한글 기준 400자 ≈ 600토큰)
    MIN_CHUNK_SIZE = 200  # 최소 문자 수
    MAX_CHUNK_SIZE = 600  # 최대 문자 수
    OVERLAP_SIZE = 50     # 오버랩 문자 수

    def __init__(self):
        self.basePath = Path(__file__).parent.parent
        self.cleanPath = self.basePath / "data" / "clean"
        self.chunkPath = self.basePath / "data" / "chunks"
        self.chunkPath.mkdir(parents=True, exist_ok=True)

    def _estimateTokens(self, text: str) -> int:
        """토큰 수 추정 (대략적)"""
        # 한글: 1자당 약 1.5토큰
        # 영어/숫자: 1단어당 약 1.3토큰
        koreanChars = len(re.findall(r'[가-힣]', text))
        otherChars = len(text) - koreanChars
        return int(koreanChars * 1.5 + otherChars * 0.3)

    def _splitByParagraph(self, text: str) -> list[str]:
        """문단 단위로 분할"""
        # 줄바꿈 기준 분할
        paragraphs = re.split(r'\n{2,}', text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _splitBySentence(self, text: str) -> list[str]:
        """문장 단위로 분할"""
        # 한글/영어 문장 종결 패턴
        sentences = re.split(r'(?<=[.!?。])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _mergeSmallChunks(self, chunks: list[str]) -> list[str]:
        """작은 청크들을 병합"""
        merged = []
        current = ""

        for chunk in chunks:
            if len(current) + len(chunk) < self.MAX_CHUNK_SIZE:
                current = current + "\n" + chunk if current else chunk
            else:
                if current:
                    merged.append(current)
                current = chunk

        if current:
            merged.append(current)

        return merged

    def _splitLongText(self, text: str) -> list[str]:
        """긴 텍스트를 적절한 크기로 분할"""
        if len(text) <= self.MAX_CHUNK_SIZE:
            return [text]

        chunks = []

        # 1단계: 문단 단위 분할 시도
        paragraphs = self._splitByParagraph(text)
        if len(paragraphs) > 1:
            # 문단을 적절히 병합
            chunks = self._mergeSmallChunks(paragraphs)
        else:
            # 2단계: 문장 단위 분할
            sentences = self._splitBySentence(text)
            if len(sentences) > 1:
                chunks = self._mergeSmallChunks(sentences)
            else:
                # 3단계: 강제 분할 (오버랩 포함)
                for i in range(0, len(text), self.MAX_CHUNK_SIZE - self.OVERLAP_SIZE):
                    chunk = text[i:i + self.MAX_CHUNK_SIZE]
                    chunks.append(chunk)

        return chunks

    def chunkFaq(self, cleanDoc: dict) -> list[Chunk]:
        """FAQ 문서 청킹 - Q/A 쌍 단위 유지"""
        # FAQ는 이미 Q/A 단위로 정제되어 있으므로 그대로 청크화
        chunk = Chunk(
            chunk_id=f"{cleanDoc['doc_id']}_c000",
            doc_id=cleanDoc["doc_id"],
            hotel=cleanDoc["hotel"],
            hotel_name=cleanDoc["hotel_name"],
            page_type=cleanDoc["page_type"],
            url=cleanDoc["url"],
            category=cleanDoc["category"],
            language=cleanDoc["language"],
            updated_at=cleanDoc["updated_at"],
            chunk_index=0,
            chunk_text=cleanDoc["text"],
            metadata=cleanDoc.get("metadata")
        )
        return [chunk]

    def chunkPolicy(self, cleanDoc: dict) -> list[Chunk]:
        """정책 문서 청킹"""
        text = cleanDoc["text"]
        chunks = []

        # 긴 정책은 분할
        textChunks = self._splitLongText(text)

        for idx, chunkText in enumerate(textChunks):
            chunk = Chunk(
                chunk_id=f"{cleanDoc['doc_id']}_c{idx:03d}",
                doc_id=cleanDoc["doc_id"],
                hotel=cleanDoc["hotel"],
                hotel_name=cleanDoc["hotel_name"],
                page_type=cleanDoc["page_type"],
                url=cleanDoc["url"],
                category=cleanDoc["category"],
                language=cleanDoc["language"],
                updated_at=cleanDoc["updated_at"],
                chunk_index=idx,
                chunk_text=chunkText,
                metadata={"title": cleanDoc["title"]}
            )
            chunks.append(chunk)

        return chunks

    def chunkGeneral(self, cleanDoc: dict) -> list[Chunk]:
        """일반 문서 청킹"""
        text = cleanDoc["text"]
        chunks = []

        textChunks = self._splitLongText(text)

        for idx, chunkText in enumerate(textChunks):
            chunk = Chunk(
                chunk_id=f"{cleanDoc['doc_id']}_c{idx:03d}",
                doc_id=cleanDoc["doc_id"],
                hotel=cleanDoc["hotel"],
                hotel_name=cleanDoc["hotel_name"],
                page_type=cleanDoc["page_type"],
                url=cleanDoc["url"],
                category=cleanDoc["category"],
                language=cleanDoc["language"],
                updated_at=cleanDoc["updated_at"],
                chunk_index=idx,
                chunk_text=chunkText,
                metadata={"title": cleanDoc.get("title", "")}
            )
            chunks.append(chunk)

        return chunks

    def processDocument(self, cleanDoc: dict) -> list[Chunk]:
        """문서 타입에 따라 청킹 처리"""
        pageType = cleanDoc.get("page_type", "")

        if pageType == "faq":
            return self.chunkFaq(cleanDoc)
        elif pageType == "policy":
            return self.chunkPolicy(cleanDoc)
        else:
            return self.chunkGeneral(cleanDoc)

    def processHotel(self, hotelKey: str) -> list[Chunk]:
        """호텔 전체 문서 청킹"""
        hotelPath = self.cleanPath / hotelKey
        if not hotelPath.exists():
            print(f"[오류] 호텔 디렉토리 없음: {hotelKey}")
            return []

        chunks = []
        jsonFiles = list(hotelPath.glob("*.json"))

        print(f"\n[청킹 시작] {hotelKey} ({len(jsonFiles)}개 문서)")

        for jsonFile in jsonFiles:
            with open(jsonFile, "r", encoding="utf-8") as f:
                cleanDoc = json.load(f)

            docChunks = self.processDocument(cleanDoc)
            chunks.extend(docChunks)

        print(f"  -> {len(chunks)}개 청크 생성")
        return chunks

    def processAll(self) -> list[Chunk]:
        """전체 호텔 청킹"""
        allChunks = []

        for hotelDir in self.cleanPath.iterdir():
            if hotelDir.is_dir():
                chunks = self.processHotel(hotelDir.name)
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

            # 개별 청크 저장
            for chunk in hotelChunkList:
                chunkDict = asdict(chunk)
                jsonPath = hotelPath / f"{chunk.chunk_id}.json"
                with open(jsonPath, "w", encoding="utf-8") as f:
                    json.dump(chunkDict, f, ensure_ascii=False, indent=2)

            # 호텔별 통합 파일도 저장 (인덱싱 편의용)
            allChunksPath = hotelPath / "_all_chunks.json"
            with open(allChunksPath, "w", encoding="utf-8") as f:
                json.dump([asdict(c) for c in hotelChunkList], f, ensure_ascii=False, indent=2)

        print(f"\n[저장 완료] {len(chunks)}개 청크")

    def exportForIndexing(self) -> list[dict]:
        """인덱싱용 전체 청크 내보내기"""
        allChunks = []

        for hotelDir in self.chunkPath.iterdir():
            if hotelDir.is_dir():
                allChunksFile = hotelDir / "_all_chunks.json"
                if allChunksFile.exists():
                    with open(allChunksFile, "r", encoding="utf-8") as f:
                        chunks = json.load(f)
                        allChunks.extend(chunks)

        # 전체 통합 파일 저장
        exportPath = self.chunkPath / "_all_hotels_chunks.json"
        with open(exportPath, "w", encoding="utf-8") as f:
            json.dump(allChunks, f, ensure_ascii=False, indent=2)

        print(f"\n[내보내기 완료] {len(allChunks)}개 청크 -> {exportPath}")
        return allChunks


def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(description="데이터 청킹")
    parser.add_argument("--hotel", type=str, help="특정 호텔만 처리")
    parser.add_argument("--export", action="store_true", help="인덱싱용 통합 파일 생성")

    args = parser.parse_args()

    chunker = Chunker()

    if args.export:
        chunker.exportForIndexing()
        return

    if args.hotel:
        chunks = chunker.processHotel(args.hotel)
    else:
        chunks = chunker.processAll()

    if chunks:
        chunker.saveChunks(chunks)
        chunker.exportForIndexing()
    else:
        print("\n[완료] 청킹할 문서 없음")


if __name__ == "__main__":
    main()
