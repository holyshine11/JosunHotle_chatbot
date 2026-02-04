"""
Vector DB 인덱싱 모듈
- Chroma DB에 청크 데이터 임베딩 및 저장
- 다국어 임베딩 모델 사용 (한/영/일 지원)
"""

import json
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


class Indexer:
    """Vector DB 인덱서"""

    # 임베딩 모델 (다국어 지원, 로컬 실행 가능)
    # multilingual-e5-small: 384차원, 약 470MB
    DEFAULT_MODEL = "intfloat/multilingual-e5-small"

    def __init__(self, modelName: str = None):
        self.basePath = Path(__file__).parent.parent
        self.chunkPath = self.basePath / "data" / "chunks"
        self.indexPath = self.basePath / "data" / "index"
        self.indexPath.mkdir(parents=True, exist_ok=True)

        # 임베딩 모델 로드
        self.modelName = modelName or self.DEFAULT_MODEL
        print(f"[모델 로딩] {self.modelName}...")
        self.model = SentenceTransformer(self.modelName)
        print(f"  -> 로딩 완료 (차원: {self.model.get_sentence_embedding_dimension()})")

        # Chroma DB 초기화 (영구 저장)
        self.client = chromadb.PersistentClient(
            path=str(self.indexPath / "chroma"),
            settings=Settings(anonymized_telemetry=False)
        )

        # 컬렉션 생성/가져오기
        self.collection = self.client.get_or_create_collection(
            name="josun_hotels",
            metadata={"description": "조선호텔 FAQ/정책 청크"}
        )

    def _prepareText(self, chunk: dict) -> str:
        """임베딩용 텍스트 준비 (E5 모델용 prefix 추가)"""
        text = chunk["chunk_text"]
        # E5 모델은 "passage: " prefix 권장
        if "e5" in self.modelName.lower():
            return f"passage: {text}"
        return text

    def _prepareMetadata(self, chunk: dict) -> dict:
        """Chroma 메타데이터 준비 (문자열만 허용)"""
        return {
            "doc_id": chunk["doc_id"],
            "hotel": chunk["hotel"],
            "hotel_name": chunk["hotel_name"],
            "page_type": chunk["page_type"],
            "url": chunk["url"],
            "category": chunk["category"],
            "language": chunk["language"],
            "updated_at": chunk["updated_at"],
            "chunk_index": str(chunk["chunk_index"]),
        }

    def loadChunks(self, hotelKey: str = None) -> list[dict]:
        """청크 데이터 로드"""
        if hotelKey:
            chunkFile = self.chunkPath / hotelKey / "_all_chunks.json"
        else:
            chunkFile = self.chunkPath / "_all_hotels_chunks.json"

        if not chunkFile.exists():
            print(f"[오류] 청크 파일 없음: {chunkFile}")
            return []

        with open(chunkFile, "r", encoding="utf-8") as f:
            chunks = json.load(f)

        print(f"[청크 로드] {len(chunks)}개")
        return chunks

    def indexChunks(self, chunks: list[dict], batchSize: int = 50):
        """청크 인덱싱"""
        if not chunks:
            print("[오류] 인덱싱할 청크 없음")
            return

        print(f"\n[인덱싱 시작] {len(chunks)}개 청크")

        # 배치 처리
        for i in range(0, len(chunks), batchSize):
            batch = chunks[i:i + batchSize]

            ids = [c["chunk_id"] for c in batch]
            texts = [self._prepareText(c) for c in batch]
            metadatas = [self._prepareMetadata(c) for c in batch]
            documents = [c["chunk_text"] for c in batch]

            # 임베딩 생성
            embeddings = self.model.encode(texts, show_progress_bar=False).tolist()

            # Chroma에 추가 (upsert로 중복 방지)
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents
            )

            print(f"  -> {i + len(batch)}/{len(chunks)} 완료")

        print(f"\n[인덱싱 완료] 총 {self.collection.count()}개 문서")

    def deleteHotel(self, hotelKey: str):
        """특정 호텔 데이터 삭제"""
        self.collection.delete(
            where={"hotel": hotelKey}
        )
        print(f"[삭제 완료] {hotelKey}")

    def search(
        self,
        query: str,
        hotel: str = None,
        category: str = None,
        topK: int = 5
    ) -> list[dict]:
        """벡터 검색"""
        # E5 모델용 query prefix
        if "e5" in self.modelName.lower():
            queryText = f"query: {query}"
        else:
            queryText = query

        # 임베딩 생성
        queryEmbedding = self.model.encode(queryText).tolist()

        # 필터 조건 구성
        whereFilter = None
        if hotel and category:
            whereFilter = {"$and": [{"hotel": hotel}, {"category": category}]}
        elif hotel:
            whereFilter = {"hotel": hotel}
        elif category:
            whereFilter = {"category": category}

        # 검색
        results = self.collection.query(
            query_embeddings=[queryEmbedding],
            n_results=topK,
            where=whereFilter,
            include=["documents", "metadatas", "distances"]
        )

        # 결과 정리
        searchResults = []
        if results["ids"] and results["ids"][0]:
            for i, chunkId in enumerate(results["ids"][0]):
                searchResults.append({
                    "chunk_id": chunkId,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                    "score": 1 - results["distances"][0][i]  # 유사도 점수 (0~1)
                })

        return searchResults

    def getStats(self) -> dict:
        """인덱스 통계"""
        count = self.collection.count()

        # 호텔별 통계
        hotelStats = {}
        for hotel in ["josun_palace", "grand_josun_busan", "grand_josun_jeju", "lescape", "gravity_pangyo"]:
            result = self.collection.get(
                where={"hotel": hotel},
                include=[]
            )
            hotelStats[hotel] = len(result["ids"])

        return {
            "total": count,
            "by_hotel": hotelStats,
            "model": self.modelName,
            "dimension": self.model.get_sentence_embedding_dimension()
        }


def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(description="Vector DB 인덱싱")
    parser.add_argument("--hotel", type=str, help="특정 호텔만 인덱싱")
    parser.add_argument("--reindex", action="store_true", help="기존 데이터 삭제 후 재인덱싱")
    parser.add_argument("--stats", action="store_true", help="인덱스 통계 출력")
    parser.add_argument("--search", type=str, help="테스트 검색 쿼리")

    args = parser.parse_args()

    indexer = Indexer()

    if args.stats:
        stats = indexer.getStats()
        print(f"\n[인덱스 통계]")
        print(f"  총 문서: {stats['total']}개")
        print(f"  모델: {stats['model']}")
        print(f"  차원: {stats['dimension']}")
        print(f"\n  호텔별:")
        for hotel, count in stats["by_hotel"].items():
            print(f"    - {hotel}: {count}개")
        return

    if args.search:
        print(f"\n[검색] '{args.search}'")
        results = indexer.search(args.search, hotel=args.hotel, topK=3)
        for i, r in enumerate(results, 1):
            print(f"\n--- 결과 {i} (점수: {r['score']:.3f}) ---")
            print(f"호텔: {r['metadata']['hotel_name']}")
            print(f"카테고리: {r['metadata']['category']}")
            print(f"텍스트: {r['text'][:200]}...")
        return

    # 인덱싱
    if args.reindex and args.hotel:
        indexer.deleteHotel(args.hotel)

    chunks = indexer.loadChunks(args.hotel)
    if chunks:
        indexer.indexChunks(chunks)

        # 통계 출력
        stats = indexer.getStats()
        print(f"\n[최종 통계] 총 {stats['total']}개 문서 인덱싱됨")


if __name__ == "__main__":
    main()
