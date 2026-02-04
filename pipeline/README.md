# 데이터 파이프라인

크롤링된 원본 데이터를 정제하고 청킹하여 Vector DB 인덱싱용 데이터를 생성합니다.

## 파이프라인 흐름

```
data/raw/ (크롤링 원본)
    ↓ cleaner.py
data/clean/ (정제된 문서)
    ↓ chunker.py
data/chunks/ (청크)
    ↓ indexer.py (다음 단계)
data/index/ (Vector DB)
```

## 사용법

```bash
PYTHON=~/.pyenv/versions/3.11.7/bin/python3

# 1. 데이터 정제
$PYTHON pipeline/cleaner.py

# 특정 호텔만 정제
$PYTHON pipeline/cleaner.py --hotel josun_palace

# 2. 데이터 청킹
$PYTHON pipeline/chunker.py

# 특정 호텔만 청킹
$PYTHON pipeline/chunker.py --hotel josun_palace

# 인덱싱용 통합 파일만 생성
$PYTHON pipeline/chunker.py --export

# 3. Vector DB 인덱싱
$PYTHON pipeline/indexer.py

# 특정 호텔만 인덱싱
$PYTHON pipeline/indexer.py --hotel josun_palace

# 재인덱싱 (기존 삭제 후)
$PYTHON pipeline/indexer.py --hotel josun_palace --reindex

# 인덱스 통계 확인
$PYTHON pipeline/indexer.py --stats

# 검색 테스트
$PYTHON pipeline/indexer.py --search "체크인 시간"
$PYTHON pipeline/indexer.py --search "주차 요금" --hotel josun_palace
```

## 출력 파일

### data/clean/{hotel}/
- `{doc_id}.json` - 정제된 개별 문서

### data/chunks/{hotel}/
- `{chunk_id}.json` - 개별 청크
- `_all_chunks.json` - 호텔별 전체 청크 (통합)

### data/chunks/
- `_all_hotels_chunks.json` - 전체 호텔 통합 청크 (인덱싱용)

## 청크 구조

```json
{
  "chunk_id": "josun_palace_faq_20260204_000_000_c000",
  "doc_id": "josun_palace_faq_20260204_000_000",
  "hotel": "josun_palace",
  "hotel_name": "조선 팰리스",
  "page_type": "faq",
  "url": "https://jpg.josunhotel.com/about/faq.do",
  "category": "부대시설",
  "language": "ko",
  "updated_at": "2026-02-04T09:58:24.409681",
  "chunk_index": 0,
  "chunk_text": "Q: 피트니스 휴관일이 있나요?\nA: 조선 웰니스 클럽은 매월 첫번째 월요일이 휴관일 입니다.",
  "metadata": {"question": "...", "answer": "..."}
}
```

## 청킹 전략

- **FAQ**: Q/A 쌍 단위 유지 (분할 없음)
- **정책**: 항목별 분할, 긴 항목은 300~600자 단위
- **일반**: 섹션별 분할, 긴 섹션은 문단/문장 단위

## 카테고리 자동 분류

키워드 기반으로 자동 분류:
- 체크인/아웃, 주차, 조식, 객실, 부대시설
- 위치/교통, 환불/취소, 반려동물, 금연, 결제, 멤버십

## Vector DB 인덱싱

### 임베딩 모델
- **모델**: `intfloat/multilingual-e5-small`
- **차원**: 384
- **특징**: 다국어 지원 (한/영/일), 로컬 실행 가능 (~470MB)

### Chroma DB
- **저장 위치**: `data/index/chroma/`
- **컬렉션**: `josun_hotels`
- **영구 저장**: PersistentClient 사용

### 검색 기능
```python
from pipeline.indexer import Indexer

indexer = Indexer()

# 기본 검색
results = indexer.search("체크인 시간", topK=5)

# 호텔 필터링
results = indexer.search("주차", hotel="josun_palace")

# 카테고리 필터링
results = indexer.search("환불", category="환불/취소")
```

### 인덱스 통계 (현재)
- 총 문서: 189개
- 조선 팰리스: 40개
- 그랜드 조선 부산: 39개
- 그랜드 조선 제주: 37개
- 레스케이프: 36개
- 그래비티 판교: 37개
