"""
보충 데이터 인덱싱 스크립트
- 주차, 위치 등 누락된 정보를 ChromaDB에 추가
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# 상위 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.indexer import Indexer


def loadSupplementaryData() -> list[dict]:
    """보충 데이터 로드 및 청크 형식 변환"""
    dataPath = Path(__file__).parent.parent / "data" / "clean" / "supplementary_info.json"

    if not dataPath.exists():
        print(f"[오류] 보충 데이터 파일 없음: {dataPath}")
        return []

    with open(dataPath, "r", encoding="utf-8") as f:
        items = json.load(f)

    # 청크 형식으로 변환
    chunks = []
    for item in items:
        chunk = {
            "chunk_id": item["doc_id"],
            "chunk_text": item["text"],
            "doc_id": item["doc_id"],
            "hotel": item["hotel"],
            "hotel_name": item["hotel_name"],
            "page_type": item["page_type"],
            "url": item["url"],
            "category": item["category"],
            "language": item["language"],
            "updated_at": datetime.now().isoformat(),
            "chunk_index": 0
        }
        chunks.append(chunk)

    return chunks


def main():
    """보충 데이터 인덱싱 실행"""
    print("=" * 60)
    print("보충 데이터 인덱싱")
    print("=" * 60)

    # 보충 데이터 로드
    chunks = loadSupplementaryData()
    if not chunks:
        return

    print(f"\n[로드] {len(chunks)}개 보충 청크")
    for chunk in chunks:
        print(f"  - {chunk['chunk_id']}: {chunk['hotel_name']} / {chunk['category']}")

    # 인덱서 초기화
    indexer = Indexer()

    # 기존 청크 로드 (BM25 재구축용)
    existingChunks = indexer.loadChunks()

    # 보충 청크를 Vector DB에 추가
    print("\n[Vector 인덱싱]")
    indexer.indexChunks(chunks)

    # BM25 인덱스 재구축 (기존 + 보충)
    print("\n[BM25 재구축]")
    allChunks = existingChunks + chunks
    indexer._buildBM25Index(allChunks)

    print("\n" + "=" * 60)
    print(f"완료: {len(chunks)}개 보충 데이터 인덱싱")
    print(f"총 인덱스: {len(allChunks)}개 청크")
    print("=" * 60)


if __name__ == "__main__":
    main()
