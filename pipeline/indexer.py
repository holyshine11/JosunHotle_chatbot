"""
Vector DB 인덱싱 모듈
- Chroma DB에 청크 데이터 임베딩 및 저장
- BM25 + Vector 하이브리드 검색 지원
- 다국어 임베딩 모델 사용 (한/영/일 지원)
"""

import json
import re
import pickle
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi


def tokenizeKorean(text: str) -> list[str]:
    """한국어 토크나이저 (간단한 형태소 분리)"""
    # 특수문자 제거 및 공백 기준 분리
    text = re.sub(r'[^\w\s가-힣a-zA-Z0-9]', ' ', text)
    tokens = text.lower().split()
    # 최소 길이 필터링
    return [t for t in tokens if len(t) >= 2]


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

        # BM25 인덱스 초기화
        self.bm25Index = None
        self.bm25Docs = []  # 원본 문서 저장
        self.bm25Path = self.indexPath / "bm25_index.pkl"
        self._loadBM25Index()

    def _loadBM25Index(self):
        """BM25 인덱스 로드"""
        if self.bm25Path.exists():
            try:
                with open(self.bm25Path, "rb") as f:
                    data = pickle.load(f)
                    self.bm25Index = data.get("index")
                    self.bm25Docs = data.get("docs", [])
                print(f"[BM25] 인덱스 로드 완료 ({len(self.bm25Docs)}개 문서)")
            except Exception as e:
                print(f"[BM25] 인덱스 로드 실패: {e}")
                self.bm25Index = None
                self.bm25Docs = []

    def _saveBM25Index(self):
        """BM25 인덱스 저장"""
        if self.bm25Index and self.bm25Docs:
            with open(self.bm25Path, "wb") as f:
                pickle.dump({
                    "index": self.bm25Index,
                    "docs": self.bm25Docs
                }, f)
            print(f"[BM25] 인덱스 저장 완료")

    def _buildBM25Index(self, chunks: list[dict]):
        """BM25 인덱스 구축"""
        print("[BM25] 인덱스 구축 중...")

        # 문서 저장 (chunk_id, text, metadata)
        self.bm25Docs = []
        tokenizedCorpus = []

        for chunk in chunks:
            text = chunk["chunk_text"]
            tokens = tokenizeKorean(text)

            self.bm25Docs.append({
                "chunk_id": chunk["chunk_id"],
                "text": text,
                "metadata": self._prepareMetadata(chunk),
                "tokens": tokens
            })
            tokenizedCorpus.append(tokens)

        # BM25 인덱스 생성
        self.bm25Index = BM25Okapi(tokenizedCorpus)
        self._saveBM25Index()
        print(f"[BM25] 인덱스 구축 완료 ({len(self.bm25Docs)}개 문서)")

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
        """청크 인덱싱 (Vector + BM25)"""
        if not chunks:
            print("[오류] 인덱싱할 청크 없음")
            return

        print(f"\n[인덱싱 시작] {len(chunks)}개 청크")

        # 1. Vector 인덱싱 (Chroma)
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

        # 2. BM25 인덱싱
        self._buildBM25Index(chunks)

        print(f"\n[인덱싱 완료] 총 {self.collection.count()}개 문서")

    def deleteHotel(self, hotelKey: str):
        """특정 호텔 데이터 삭제"""
        self.collection.delete(
            where={"hotel": hotelKey}
        )
        print(f"[삭제 완료] {hotelKey}")

    def searchVector(
        self,
        query: str,
        hotel: str = None,
        category: str = None,
        topK: int = 5
    ) -> list[dict]:
        """벡터 검색 (Semantic)"""
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
                    "score": 1 - results["distances"][0][i],  # 유사도 점수 (0~1)
                    "source": "vector"
                })

        return searchResults

    def searchBM25(
        self,
        query: str,
        hotel: str = None,
        topK: int = 5
    ) -> list[dict]:
        """BM25 키워드 검색"""
        if not self.bm25Index or not self.bm25Docs:
            return []

        # 쿼리 토크나이징
        queryTokens = tokenizeKorean(query)
        if not queryTokens:
            return []

        # BM25 점수 계산
        scores = self.bm25Index.get_scores(queryTokens)

        # 호텔 필터링 및 정렬
        scoredDocs = []
        for i, score in enumerate(scores):
            doc = self.bm25Docs[i]
            # 호텔 필터
            if hotel and doc["metadata"].get("hotel") != hotel:
                continue
            if score > 0:
                scoredDocs.append((i, score))

        # 점수 기준 정렬
        scoredDocs.sort(key=lambda x: x[1], reverse=True)

        # 상위 K개 결과
        results = []
        maxScore = scoredDocs[0][1] if scoredDocs else 1.0

        for i, (docIdx, score) in enumerate(scoredDocs[:topK]):
            doc = self.bm25Docs[docIdx]
            # BM25 점수 정규화 (0~1)
            normalizedScore = score / maxScore if maxScore > 0 else 0

            results.append({
                "chunk_id": doc["chunk_id"],
                "text": doc["text"],
                "metadata": doc["metadata"],
                "score": normalizedScore,
                "bm25_raw": score,
                "source": "bm25"
            })

        return results

    def search(
        self,
        query: str,
        hotel: str = None,
        category: str = None,
        topK: int = 5,
        hybrid: bool = True,
        vectorWeight: float = 0.7,
        bm25Weight: float = 0.3
    ) -> list[dict]:
        """하이브리드 검색 (Vector + BM25)

        Vector 검색을 기본으로 하고, BM25로 키워드 매칭 보완.
        최종 점수는 Vector 점수 기준으로 유지하여 임계값 통과.

        Args:
            hybrid: True면 하이브리드, False면 벡터만
            vectorWeight: 벡터 검색 가중치 (기본 0.7)
            bm25Weight: BM25 검색 가중치 (기본 0.3)
        """
        # 벡터 검색
        vectorResults = self.searchVector(query, hotel, category, topK=topK * 2)

        if not hybrid or not self.bm25Index:
            return vectorResults[:topK]

        # BM25 검색
        bm25Results = self.searchBM25(query, hotel, topK=topK * 2)

        # 결과 수집
        allResults = {}
        for r in vectorResults:
            allResults[r["chunk_id"]] = {
                "result": r,
                "vector_score": r["score"],
                "vector_rank": vectorResults.index(r),
                "bm25_score": 0,
                "bm25_rank": 999
            }

        for rank, r in enumerate(bm25Results):
            chunkId = r["chunk_id"]
            if chunkId in allResults:
                allResults[chunkId]["bm25_score"] = r["score"]
                allResults[chunkId]["bm25_rank"] = rank
            else:
                allResults[chunkId] = {
                    "result": r,
                    "vector_score": 0,
                    "vector_rank": 999,
                    "bm25_score": r["score"],
                    "bm25_rank": rank
                }

        # 최종 점수 계산: 벡터 점수 기반 + BM25 순위 부스트
        for chunkId, data in allResults.items():
            vectorScore = data["vector_score"]
            bm25Score = data["bm25_score"]

            # 벡터 점수를 기준으로 하되, BM25 상위 결과에 보너스
            bm25Boost = 0
            if data["bm25_rank"] < 5:  # BM25 상위 5개
                bm25Boost = 0.05 * (5 - data["bm25_rank"]) / 5  # 최대 +0.05

            # 최종 점수 = 벡터 점수 + BM25 부스트 (최대 1.0)
            finalScore = min(vectorScore + bm25Boost, 1.0)

            # 벡터 결과가 없는 경우 BM25 점수 사용 (패널티 적용)
            if vectorScore == 0:
                finalScore = bm25Score * 0.7  # BM25 전용 결과는 30% 패널티

            data["final_score"] = finalScore

        # 최종 점수 기준 정렬
        sortedItems = sorted(allResults.items(), key=lambda x: x[1]["final_score"], reverse=True)

        # 결과 반환
        finalResults = []
        for chunkId, data in sortedItems[:topK]:
            result = data["result"].copy()
            result["score"] = data["final_score"]
            result["hybrid"] = True
            result["vector_score"] = data["vector_score"]
            result["bm25_score"] = data["bm25_score"]
            finalResults.append(result)

        return finalResults

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
