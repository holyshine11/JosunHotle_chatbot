"""
Cross-Encoder 기반 리랭커 (transformers 직접 사용)
- 검색 결과 재정렬로 관련성 향상
- 무관한 청크 필터링으로 할루시네이션 방지
- Lazy loading (첫 검색 시 모델 로드)
- 배치 처리로 추론 속도 향상
- 쿼리별 점수 캐싱으로 중복 계산 방지
"""

import re
import time
import hashlib
from functools import lru_cache
import numpy as np


class Reranker:
    """Cross-Encoder 리랭커 (transformers 직접 사용)"""

    # 모델 옵션
    DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"  # 다국어(한국어 포함) 지원

    # 리랭킹 설정
    MIN_KEEP = 2  # 최소 유지 청크 수
    # 최고 점수 대비 상대 임계값 (최고 점수의 35% 미만은 제거)
    RELATIVE_THRESHOLD = 0.35
    # 조건부 스킵: 벡터 검색 top score가 이 값 이상이면 리랭킹 생략
    SKIP_THRESHOLD = 0.90
    # 절대 raw score 임계값: 최고 점수가 이 값 미만이면 전체 결과 "저품질" 판정
    # (모든 결과가 쿼리와 무관할 때 min-max 정규화가 품질을 은폐하는 것을 방지)
    ABSOLUTE_RAW_SCORE_FLOOR = -5.0
    # 추론 최적화
    MAX_LENGTH = 512  # 토크나이저 최대 길이 (원본 유지, MPS 가속으로 충분히 빠름)

    def __init__(self, modelName: str = None, device: str = "cpu"):
        self.modelName = modelName or self.DEFAULT_MODEL
        self.device = device
        self._model = None
        self._tokenizer = None
        self._loadFailed = False
        self._scoreCache = {}  # 쿼리-청크 쌍별 점수 캐시
        self._cacheHits = 0
        self._cacheMisses = 0

    def _loadModel(self):
        """모델 로드 (첫 호출 시)"""
        if self._model is not None or self._loadFailed:
            return

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import torch

            print(f"[리랭커] 모델 로딩: {self.modelName}...")
            startTime = time.time()

            self._tokenizer = AutoTokenizer.from_pretrained(self.modelName)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.modelName
            )
            self._model.eval()

            # MPS(Metal GPU) 가속 시도
            try:
                import torch
                if torch.backends.mps.is_available():
                    self._model = self._model.to("mps")
                    self.device = "mps"
                    print(f"[리랭커] MPS(Metal GPU) 가속 활성화")
            except Exception as e:
                print(f"[리랭커] MPS 불가, CPU 유지: {e}")

            elapsed = time.time() - startTime
            print(f"[리랭커] 로딩 완료 ({elapsed:.1f}초)")

        except Exception as e:
            print(f"[리랭커] 모델 로드 실패: {e}")
            self._loadFailed = True

    def _generateChunkKey(self, query: str, chunkText: str) -> str:
        """쿼리-청크 쌍의 캐시 키 생성"""
        content = f"{query}|{chunkText[:200]}"  # 청크 텍스트는 앞 200자만 사용
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def rerank(self, query: str, chunks: list, topK: int = 5) -> list:
        """검색 결과 리랭킹

        Args:
            query: 사용자 질문
            chunks: 검색된 청크 목록 (각 청크는 "text" 키 필수)
            topK: 반환할 최대 청크 수

        Returns:
            리랭킹된 청크 목록 (rerank_score, original_score 필드 추가)
        """
        if not chunks:
            return []

        self._loadModel()

        if self._model is None:
            print("[리랭커] 모델 없음, 원본 순서 유지")
            return chunks[:topK]

        # Cross-Encoder 점수 계산 (배치 처리 + 캐싱)
        try:
            import torch

            startTime = time.time()
            rawScores = []
            pairsToCompute = []
            indexMap = []  # 계산할 청크의 원본 인덱스

            # 캐시 체크
            for i, chunk in enumerate(chunks):
                text = chunk.get("text", "")
                cacheKey = self._generateChunkKey(query, text)

                if cacheKey in self._scoreCache:
                    # 캐시 히트
                    rawScores.append(self._scoreCache[cacheKey])
                    self._cacheHits += 1
                else:
                    # 캐시 미스: 계산 필요
                    rawScores.append(None)  # 나중에 채울 자리
                    pairsToCompute.append([query, text])
                    indexMap.append(i)
                    self._cacheMisses += 1

            # 캐시 미스 청크만 배치 처리
            if pairsToCompute:
                with torch.no_grad():
                    # 배치 토크나이징 (padding으로 길이 통일)
                    inputs = self._tokenizer(
                        pairsToCompute,
                        padding=True,
                        truncation=True,
                        return_tensors="pt",
                        max_length=self.MAX_LENGTH
                    )

                    # MPS/GPU 사용 시 입력 텐서 디바이스 이동
                    if self.device != "cpu":
                        inputs = {k: v.to(self.device) for k, v in inputs.items()}

                    # 배치 추론 (한 번에 모든 점수 계산)
                    logits = self._model(**inputs, return_dict=True).logits
                    computedScores = logits.view(-1).float().tolist()

                    # 계산된 점수를 캐시에 저장 및 결과에 반영
                    for idx, score in zip(indexMap, computedScores):
                        rawScores[idx] = score
                        text = chunks[idx].get("text", "")
                        cacheKey = self._generateChunkKey(query, text)
                        self._scoreCache[cacheKey] = score

                        # 캐시 크기 제한 (500개 초과 시 오래된 항목 제거)
                        if len(self._scoreCache) > 500:
                            # 가장 오래된 항목 제거 (FIFO)
                            oldestKey = next(iter(self._scoreCache))
                            del self._scoreCache[oldestKey]

            elapsed = time.time() - startTime
            totalRequests = self._cacheHits + self._cacheMisses
            hitRate = (self._cacheHits / totalRequests * 100) if totalRequests > 0 else 0
            print(f"[리랭커] {len(chunks)}개 청크 점수 계산 ({elapsed * 1000:.0f}ms, 캐시: {self._cacheHits}/{totalRequests} = {hitRate:.1f}%)")

        except Exception as e:
            print(f"[리랭커] 점수 계산 실패: {e}")
            return chunks[:topK]

        # 절대 품질 판정: 최고 raw score가 임계값 미만이면 전체 "저품질"
        bestRawScore = max(rawScores)
        isLowQuality = bestRawScore < self.ABSOLUTE_RAW_SCORE_FLOOR
        if isLowQuality:
            print(f"[리랭커] 절대 품질 미달: 최고 raw={bestRawScore:.2f} < floor={self.ABSOLUTE_RAW_SCORE_FLOOR}")

        # min-max 정규화 (0~1 범위)
        scores = np.array(rawScores)
        scoreMin, scoreMax = scores.min(), scores.max()
        if scoreMax - scoreMin > 0.01:
            normalizedScores = (scores - scoreMin) / (scoreMax - scoreMin)
        else:
            # 모든 점수가 비슷하면 균등 배분
            normalizedScores = np.ones_like(scores) * 0.5

        # 청크에 점수 추가
        scoredChunks = []
        for i, chunk in enumerate(chunks):
            scoredChunks.append({
                **chunk,
                "rerank_score": float(normalizedScores[i]),
                "rerank_raw": float(rawScores[i]),
                "original_score": chunk.get("score", 0),
                "_rerank_quality": "poor" if isLowQuality else "ok",
            })

        # 리랭크 점수 기준 정렬
        scoredChunks.sort(key=lambda x: x["rerank_score"], reverse=True)

        # 상대 임계값 필터링 (최고 점수 대비) + 쿼리 키워드 매칭
        topRerankScore = scoredChunks[0]["rerank_score"] if scoredChunks else 0
        relativeThreshold = topRerankScore * self.RELATIVE_THRESHOLD
        queryKeywords = self._extractQueryKeywords(query)

        filtered = []
        for chunk in scoredChunks:
            keepByScore = chunk["rerank_score"] >= relativeThreshold
            keepByMinKeep = len(filtered) < self.MIN_KEEP
            keepByKeyword = (not keepByScore and not keepByMinKeep
                             and self._hasQueryKeyword(chunk, queryKeywords))

            if keepByScore or keepByMinKeep or keepByKeyword:
                if keepByKeyword:
                    chunk["_kept_by_keyword"] = True
                filtered.append(chunk)

        result = filtered[:topK]

        # 로그
        removed = len(chunks) - len(result)
        if removed > 0:
            print(f"[리랭커] {removed}개 저관련 청크 제거")
        for chunk in scoredChunks:
            if chunk in result:
                status = "K" if chunk.get("_kept_by_keyword") else "O"
            else:
                status = "X"
            print(f"  [{status}] rerank={chunk['rerank_score']:.3f} raw={chunk['rerank_raw']:.2f} orig={chunk['original_score']:.3f} | {chunk['text'][:60]}...")

        return result

    def _extractQueryKeywords(self, query: str) -> list[str]:
        """쿼리에서 2글자 이상 한글 핵심 키워드 추출 (조사/일반어 제거)"""
        # 먼저 단어 추출 (한글 2글자 이상)
        words = re.findall(r'[가-힣]{2,}', query)
        # 각 단어 끝의 조사만 제거 (단어 중간 글자 보호)
        suffixes = r'(에서|에는|에도|해줘|해요|인가요|인지|입니까|할까|인데|하고|해도|대해|관해|은|는|이|가|을|를|의|도|만|에|로|으로)$'
        cleaned = []
        for w in words:
            w = re.sub(suffixes, '', w)
            if len(w) >= 2:
                cleaned.append(w)
        stopwords = {"어떻게", "언제", "어디", "무엇", "얼마", "여기", "거기",
                     "호텔", "정보", "안내", "문의", "운영", "이용", "서비스",
                     "레스토랑", "객실", "시설", "소개", "가능", "알려줘"}
        return [w for w in cleaned if w not in stopwords]

    def _hasQueryKeyword(self, chunk: dict, queryKeywords: list[str]) -> bool:
        """청크 텍스트에 쿼리 핵심 키워드가 포함되어 있는지 확인"""
        if not queryKeywords:
            return False
        chunkText = chunk.get("text", "").lower()
        return any(kw.lower() in chunkText for kw in queryKeywords)

    @property
    def isAvailable(self) -> bool:
        """모델 사용 가능 여부"""
        self._loadModel()
        return self._model is not None

    def getCacheStats(self) -> dict:
        """캐시 통계 반환"""
        totalRequests = self._cacheHits + self._cacheMisses
        hitRate = (self._cacheHits / totalRequests * 100) if totalRequests > 0 else 0

        return {
            "cache_hits": self._cacheHits,
            "cache_misses": self._cacheMisses,
            "hit_rate": round(hitRate, 2),
            "cache_size": len(self._scoreCache),
        }

    def clearCache(self):
        """캐시 초기화"""
        self._scoreCache.clear()
        self._cacheHits = 0
        self._cacheMisses = 0
        print("[리랭커] 캐시 초기화 완료")


# 싱글톤 인스턴스 (lazy loading)
_rerankerInstance = None


def getReranker() -> Reranker:
    """리랭커 싱글톤 반환"""
    global _rerankerInstance
    if _rerankerInstance is None:
        _rerankerInstance = Reranker()
    return _rerankerInstance
