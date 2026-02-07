"""
Cross-Encoder 기반 리랭커 (transformers 직접 사용)
- 검색 결과 재정렬로 관련성 향상
- 무관한 청크 필터링으로 할루시네이션 방지
- Lazy loading (첫 검색 시 모델 로드)
"""

import time
import numpy as np


class Reranker:
    """Cross-Encoder 리랭커 (transformers 직접 사용)"""

    # 모델 옵션
    DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"  # 다국어(한국어 포함) 지원

    # 리랭킹 설정
    MIN_KEEP = 2  # 최소 유지 청크 수
    # 최고 점수 대비 상대 임계값 (최고 점수의 40% 미만은 제거)
    RELATIVE_THRESHOLD = 0.4

    def __init__(self, modelName: str = None, device: str = "cpu"):
        self.modelName = modelName or self.DEFAULT_MODEL
        self.device = device
        self._model = None
        self._tokenizer = None
        self._loadFailed = False

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

            elapsed = time.time() - startTime
            print(f"[리랭커] 로딩 완료 ({elapsed:.1f}초)")

        except Exception as e:
            print(f"[리랭커] 모델 로드 실패: {e}")
            self._loadFailed = True

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

        # Cross-Encoder 점수 계산
        try:
            import torch

            startTime = time.time()
            rawScores = []

            with torch.no_grad():
                for chunk in chunks:
                    text = chunk.get("text", "")
                    inputs = self._tokenizer(
                        [[query, text]],
                        padding=True,
                        truncation=True,
                        return_tensors="pt",
                        max_length=512
                    )
                    score = self._model(**inputs, return_dict=True).logits.view(-1,).float().item()
                    rawScores.append(score)

            elapsed = time.time() - startTime
            print(f"[리랭커] {len(chunks)}개 청크 점수 계산 ({elapsed * 1000:.0f}ms)")

        except Exception as e:
            print(f"[리랭커] 점수 계산 실패: {e}")
            return chunks[:topK]

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
            })

        # 리랭크 점수 기준 정렬
        scoredChunks.sort(key=lambda x: x["rerank_score"], reverse=True)

        # 상대 임계값 필터링 (최고 점수 대비)
        topRerankScore = scoredChunks[0]["rerank_score"] if scoredChunks else 0
        relativeThreshold = topRerankScore * self.RELATIVE_THRESHOLD

        filtered = []
        for chunk in scoredChunks:
            if chunk["rerank_score"] >= relativeThreshold or len(filtered) < self.MIN_KEEP:
                filtered.append(chunk)

        result = filtered[:topK]

        # 로그
        removed = len(chunks) - len(result)
        if removed > 0:
            print(f"[리랭커] {removed}개 저관련 청크 제거")
        for chunk in scoredChunks:
            status = "O" if chunk in result else "X"
            print(f"  [{status}] rerank={chunk['rerank_score']:.3f} raw={chunk['rerank_raw']:.2f} orig={chunk['original_score']:.3f} | {chunk['text'][:60]}...")

        return result

    @property
    def isAvailable(self) -> bool:
        """모델 사용 가능 여부"""
        self._loadModel()
        return self._model is not None


# 싱글톤 인스턴스 (lazy loading)
_rerankerInstance = None


def getReranker() -> Reranker:
    """리랭커 싱글톤 반환"""
    global _rerankerInstance
    if _rerankerInstance is None:
        _rerankerInstance = Reranker()
    return _rerankerInstance
