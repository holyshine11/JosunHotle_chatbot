# Vector DB 인덱스

Chroma DB를 사용한 조선호텔 FAQ/정책 벡터 인덱스입니다.

## 저장 위치

```
data/index/
└── chroma/           # Chroma DB 영구 저장소
    ├── chroma.sqlite3
    └── ...
```

## 인덱스 정보

| 항목 | 값 |
|-----|---|
| Vector DB | Chroma (PersistentClient) |
| 컬렉션명 | josun_hotels |
| 임베딩 모델 | intfloat/multilingual-e5-small |
| 차원 | 384 |
| 총 문서 | 189개 |

## 호텔별 문서 수

| 호텔 키 | 호텔명 | 문서 수 |
|--------|-------|--------|
| josun_palace | 조선 팰리스 | 40개 |
| grand_josun_busan | 그랜드 조선 부산 | 39개 |
| grand_josun_jeju | 그랜드 조선 제주 | 37개 |
| lescape | 레스케이프 | 36개 |
| gravity_pangyo | 그래비티 판교 | 37개 |

## 사용법

### CLI 명령어

```bash
PYTHON=~/.pyenv/versions/3.11.7/bin/python3

# 인덱스 통계 확인
$PYTHON pipeline/indexer.py --stats

# 검색 테스트
$PYTHON pipeline/indexer.py --search "체크인 시간"

# 호텔 필터링 검색
$PYTHON pipeline/indexer.py --search "주차" --hotel josun_palace

# 재인덱싱
$PYTHON pipeline/indexer.py --reindex
```

### Python 코드에서 사용

```python
from pipeline.indexer import Indexer

# 인덱서 초기화 (모델 로딩 포함)
indexer = Indexer()

# 기본 검색
results = indexer.search("체크인 시간이 어떻게 되나요?", topK=5)

for r in results:
    print(f"호텔: {r['metadata']['hotel_name']}")
    print(f"점수: {r['score']:.3f}")
    print(f"텍스트: {r['text']}")
    print(f"URL: {r['metadata']['url']}")
    print("---")

# 호텔 필터링 검색
results = indexer.search(
    query="주차 요금",
    hotel="josun_palace",
    topK=3
)

# 카테고리 필터링 검색
results = indexer.search(
    query="환불 정책",
    category="환불/취소",
    topK=3
)

# 호텔 + 카테고리 동시 필터링
results = indexer.search(
    query="수영장",
    hotel="grand_josun_jeju",
    category="부대시설",
    topK=3
)
```

### 검색 결과 구조

```python
{
    "chunk_id": "josun_palace_faq_20260204_000_005_c000",
    "text": "Q: 체크인과 체크아웃 시간은 언제입니까?\nA: 체크인 시간은 오후 3시...",
    "metadata": {
        "doc_id": "josun_palace_faq_20260204_000_005",
        "hotel": "josun_palace",
        "hotel_name": "조선 팰리스",
        "page_type": "faq",
        "url": "https://jpg.josunhotel.com/about/faq.do",
        "category": "객실",
        "language": "ko",
        "updated_at": "2026-02-04T09:58:24.409681",
        "chunk_index": "0"
    },
    "distance": 0.185,   # 거리 (낮을수록 유사)
    "score": 0.815       # 유사도 점수 (높을수록 유사)
}
```

## 직접 Chroma 접근

```python
import chromadb
from chromadb.config import Settings

# Chroma 클라이언트 직접 생성
client = chromadb.PersistentClient(
    path="data/index/chroma",
    settings=Settings(anonymized_telemetry=False)
)

# 컬렉션 가져오기
collection = client.get_collection("josun_hotels")

# 문서 수 확인
print(f"총 문서: {collection.count()}")

# 특정 호텔 문서 조회
results = collection.get(
    where={"hotel": "josun_palace"},
    include=["documents", "metadatas"]
)

# ID로 직접 조회
results = collection.get(
    ids=["josun_palace_faq_20260204_000_000_c000"],
    include=["documents", "metadatas", "embeddings"]
)
```

## 인덱스 재구축

```bash
PYTHON=~/.pyenv/versions/3.11.7/bin/python3

# 1. 크롤링 (원본 데이터 갱신)
$PYTHON crawler/josun_crawler.py --force

# 2. 정제
$PYTHON pipeline/cleaner.py

# 3. 청킹
$PYTHON pipeline/chunker.py

# 4. 재인덱싱
$PYTHON pipeline/indexer.py --reindex
```

## 주의사항

- 임베딩 모델 첫 로딩 시 HuggingFace에서 다운로드 (~470MB)
- `chroma/` 디렉토리 삭제 시 인덱스 전체 재구축 필요
- E5 모델은 query/passage prefix 사용 (indexer.py에서 자동 처리)
