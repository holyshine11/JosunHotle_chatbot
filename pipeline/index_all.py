"""
전체 데이터 통합 인덱싱 스크립트
- clean 데이터 (FAQ, 정책 등)
- deep processed 데이터 (객실, 다이닝, 시설 상세)
- supplementary 데이터 (반려동물, 조식 등 보충 정보)
"""

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.indexer import Indexer


def loadCleanData() -> list[dict]:
    """clean 디렉토리의 청크 데이터 로드"""
    basePath = Path(__file__).parent.parent / "data" / "clean"
    chunks = []

    hotelDirs = [d for d in basePath.iterdir() if d.is_dir()]

    for hotelDir in hotelDirs:
        for jsonFile in hotelDir.glob("*.json"):
            try:
                with open(jsonFile, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 청크 형식 통일
                chunk = {
                    "chunk_id": data.get("doc_id", jsonFile.stem),
                    "doc_id": data.get("doc_id", jsonFile.stem),
                    "hotel": data.get("hotel", ""),
                    "hotel_name": data.get("hotel_name", ""),
                    "page_type": data.get("page_type", ""),
                    "url": data.get("url", ""),
                    "category": data.get("category", ""),
                    "language": data.get("language", "ko"),
                    "updated_at": data.get("updated_at", datetime.now().isoformat()),
                    "chunk_index": 0,
                    "chunk_text": data.get("text", data.get("chunk_text", "")),
                }

                if chunk["chunk_text"] and len(chunk["chunk_text"]) > 20:
                    chunks.append(chunk)
            except Exception as e:
                print(f"  [경고] {jsonFile.name}: {e}")

    return chunks


def loadDeepProcessedData() -> list[dict]:
    """deep processed 데이터 로드"""
    chunkFile = Path(__file__).parent.parent / "data" / "chunks" / "_all_hotels_chunks.json"

    if not chunkFile.exists():
        print(f"  [경고] deep processed 파일 없음: {chunkFile}")
        return []

    with open(chunkFile, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    return chunks


def loadSupplementaryData() -> list[dict]:
    """보충 데이터 로드"""
    basePath = Path(__file__).parent.parent / "data"
    chunks = []

    # supplementary_info.json
    suppInfoPath = basePath / "clean" / "supplementary_info.json"
    if suppInfoPath.exists():
        with open(suppInfoPath, "r", encoding="utf-8") as f:
            items = json.load(f)
        for item in items:
            chunk = {
                "chunk_id": item["doc_id"],
                "doc_id": item["doc_id"],
                "hotel": item["hotel"],
                "hotel_name": item["hotel_name"],
                "page_type": item["page_type"],
                "url": item["url"],
                "category": item["category"],
                "language": item.get("language", "ko"),
                "updated_at": datetime.now().isoformat(),
                "chunk_index": 0,
                "chunk_text": item["text"],
            }
            chunks.append(chunk)

    # supplementary 디렉토리
    suppDir = basePath / "supplementary"
    if suppDir.exists():
        for jsonFile in suppDir.glob("*.json"):
            try:
                with open(jsonFile, "r", encoding="utf-8") as f:
                    items = json.load(f)
                for idx, item in enumerate(items):
                    chunk = {
                        "chunk_id": f"{jsonFile.stem}_{item.get('hotel', 'unknown')}_{idx:03d}",
                        "doc_id": f"{jsonFile.stem}_{item.get('hotel', 'unknown')}",
                        "hotel": item.get("hotel", ""),
                        "hotel_name": item.get("hotel_name", ""),
                        "page_type": item.get("page_type", "policy"),
                        "url": item.get("url", ""),
                        "category": item.get("category", "일반"),
                        "language": item.get("language", "ko"),
                        "updated_at": datetime.now().isoformat(),
                        "chunk_index": idx,
                        "chunk_text": item.get("text", ""),
                    }
                    if chunk["chunk_text"]:
                        chunks.append(chunk)
            except Exception as e:
                print(f"  [경고] {jsonFile.name}: {e}")

    return chunks


def deduplicateChunks(chunks: list[dict]) -> list[dict]:
    """중복 제거 (chunk_id 기준)"""
    seen = set()
    unique = []

    for chunk in chunks:
        chunkId = chunk["chunk_id"]
        if chunkId not in seen:
            seen.add(chunkId)
            unique.append(chunk)

    return unique


def main():
    """전체 데이터 통합 인덱싱"""
    print("=" * 60)
    print("[전체 데이터 통합 인덱싱]")
    print("=" * 60)

    # 1. Clean 데이터 로드
    print("\n[1] Clean 데이터 로드...")
    cleanChunks = loadCleanData()
    print(f"  -> {len(cleanChunks)}개 청크")

    # 2. Deep Processed 데이터 로드
    print("\n[2] Deep Processed 데이터 로드...")
    deepChunks = loadDeepProcessedData()
    print(f"  -> {len(deepChunks)}개 청크")

    # 3. Supplementary 데이터 로드
    print("\n[3] Supplementary 데이터 로드...")
    suppChunks = loadSupplementaryData()
    print(f"  -> {len(suppChunks)}개 청크")

    # 4. 통합 및 중복 제거
    print("\n[4] 데이터 통합 및 중복 제거...")
    allChunks = cleanChunks + deepChunks + suppChunks
    uniqueChunks = deduplicateChunks(allChunks)
    print(f"  -> 통합: {len(allChunks)}개 → 중복 제거 후: {len(uniqueChunks)}개")

    # 5. 호텔별 통계
    hotelStats = {}
    for chunk in uniqueChunks:
        hotel = chunk.get("hotel", "unknown")
        hotelStats[hotel] = hotelStats.get(hotel, 0) + 1

    print("\n[호텔별 청크 수]")
    for hotel, count in sorted(hotelStats.items()):
        print(f"  {hotel}: {count}개")

    # 6. 인덱서 초기화 및 기존 데이터 삭제
    print("\n[5] 인덱서 초기화...")
    indexer = Indexer()

    print("  -> 기존 인덱스 삭제...")
    indexer.client.delete_collection("josun_hotels")
    indexer.collection = indexer.client.get_or_create_collection(
        name="josun_hotels",
        metadata={"description": "조선호텔 FAQ/정책 청크"}
    )

    # 7. 인덱싱
    print("\n[6] 인덱싱 시작...")
    indexer.indexChunks(uniqueChunks)

    # 8. 최종 통계
    stats = indexer.getStats()
    print("\n" + "=" * 60)
    print("[최종 결과]")
    print("=" * 60)
    print(f"  총 인덱싱: {stats['total']}개 문서")
    print("\n  호텔별:")
    for hotel, count in stats["by_hotel"].items():
        print(f"    {hotel}: {count}개")

    # 통합 청크 파일 저장 (백업)
    outputPath = Path(__file__).parent.parent / "data" / "chunks" / "_all_merged_chunks.json"
    with open(outputPath, "w", encoding="utf-8") as f:
        json.dump(uniqueChunks, f, ensure_ascii=False, indent=2)
    print(f"\n  통합 청크 저장: {outputPath}")


if __name__ == "__main__":
    main()
