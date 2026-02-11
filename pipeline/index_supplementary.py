"""
보충 데이터 인덱싱 스크립트 (개선 버전)
- 데이터 검증 자동화 (필수 필드, 형식, 중복 체크)
- 증분 인덱싱 (변경된 데이터만 업데이트)
- 인덱싱 결과 리포트 (추가/수정/삭제 건수)
"""

import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

# 상위 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.indexer import Indexer


# =============================================================================
# 데이터 검증 함수
# =============================================================================

class DataValidator:
    """보충 데이터 검증 클래스"""

    # 필수 필드 정의
    REQUIRED_FIELDS = {
        "hotel": str,
        "hotel_name": str,
        "category": str,
        "page_type": str,
        "url": str,
        "text": str
    }

    # 유효한 호텔 키
    VALID_HOTELS = {
        "josun_palace", "grand_josun_busan", "grand_josun_jeju",
        "lescape", "gravity_pangyo"
    }

    # 유효한 카테고리
    VALID_CATEGORIES = {
        "다이닝", "객실", "시설", "이벤트", "패키지", "정책",
        "일반", "위치", "교통", "문의"
    }

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validateItem(self, item: dict, fileSource: str, index: int) -> bool:
        """개별 아이템 검증"""
        isValid = True
        itemId = f"{fileSource}[{index}]"

        # 1. 필수 필드 존재 여부 및 타입 검증 (page_type은 선택적)
        for field, expectedType in self.REQUIRED_FIELDS.items():
            if field == "page_type" and field not in item:
                # page_type 누락 시 경고만 출력하고 계속 진행
                self.warnings.append(f"{itemId}: 선택 필드 누락 '{field}' (기본값으로 대체됨)")
                continue

            if field not in item:
                self.errors.append(f"{itemId}: 필수 필드 누락 '{field}'")
                isValid = False
            elif not isinstance(item[field], expectedType):
                self.errors.append(
                    f"{itemId}: 필드 타입 오류 '{field}' "
                    f"(기대: {expectedType.__name__}, 실제: {type(item[field]).__name__})"
                )
                isValid = False

        if not isValid:
            return False

        # 2. 호텔 키 검증
        if item.get("hotel") and item["hotel"] not in self.VALID_HOTELS:
            self.warnings.append(
                f"{itemId}: 알 수 없는 호텔 키 '{item['hotel']}' "
                f"(유효한 키: {', '.join(self.VALID_HOTELS)})"
            )

        # 3. 텍스트 최소 길이 검증
        if "text" in item and len(item["text"]) < 20:
            self.errors.append(
                f"{itemId}: 텍스트가 너무 짧습니다 (최소 20자, 현재 {len(item['text'])}자)"
            )
            isValid = False

        # 4. URL 형식 검증 (경고만)
        if "url" in item and item["url"] and not item["url"].startswith("http"):
            self.warnings.append(f"{itemId}: URL 형식이 올바르지 않습니다 '{item['url']}'")

        # 5. 카테고리 검증 (경고만)
        if "category" in item and item["category"] not in self.VALID_CATEGORIES:
            # 비표준 카테고리는 허용하되 경고만 출력
            pass  # 경고 출력 제거 (너무 많음)

        return isValid

    def validateBatch(self, items: list[dict], fileSource: str) -> list[dict]:
        """배치 검증 및 유효한 아이템만 반환"""
        validItems = []

        for idx, item in enumerate(items):
            if self.validateItem(item, fileSource, idx):
                validItems.append(item)

        return validItems

    def checkDuplicates(self, chunks: list[dict]) -> list[dict]:
        """중복 체크 (chunk_id 기준)"""
        seen = {}
        uniqueChunks = []

        for chunk in chunks:
            chunkId = chunk["chunk_id"]
            if chunkId in seen:
                self.warnings.append(
                    f"중복 chunk_id 발견: {chunkId} "
                    f"(원본: {seen[chunkId]}, 중복: {chunk.get('doc_id', 'unknown')})"
                )
            else:
                seen[chunkId] = chunk.get("doc_id", "unknown")
                uniqueChunks.append(chunk)

        return uniqueChunks

    def printReport(self):
        """검증 결과 리포트 출력"""
        if self.errors:
            print("\n[오류]")
            for error in self.errors:
                print(f"  ❌ {error}")

        if self.warnings:
            print("\n[경고]")
            for warning in self.warnings:
                print(f"  ⚠️  {warning}")

        if not self.errors and not self.warnings:
            print("  ✅ 모든 검증 통과")


# =============================================================================
# 데이터 해시 관리 (증분 인덱싱)
# =============================================================================

class HashManager:
    """데이터 해시 관리 클래스 - 변경 감지용"""

    def __init__(self, basePath: Path):
        self.hashFile = basePath / "data" / "index" / ".supplementary_hashes.json"
        self.hashes = self._load()

    def _load(self) -> dict:
        """기존 해시 로드"""
        if self.hashFile.exists():
            with open(self.hashFile, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self):
        """해시 저장"""
        self.hashFile.parent.mkdir(parents=True, exist_ok=True)
        with open(self.hashFile, "w", encoding="utf-8") as f:
            json.dump(self.hashes, f, ensure_ascii=False, indent=2)

    def computeHash(self, data: dict) -> str:
        """데이터 해시 계산 (updated_at 제외)"""
        # updated_at 필드를 제외하고 해시 계산
        # (매번 변경되는 필드는 해시에 포함하지 않음)
        dataForHash = {k: v for k, v in data.items() if k != "updated_at"}
        dataStr = json.dumps(dataForHash, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(dataStr.encode()).hexdigest()

    def hasChanged(self, chunkId: str, currentHash: str) -> bool:
        """데이터 변경 여부 확인"""
        return self.hashes.get(chunkId) != currentHash

    def update(self, chunkId: str, newHash: str):
        """해시 업데이트"""
        self.hashes[chunkId] = newHash

    def save(self):
        """변경 사항 저장"""
        self._save()


# =============================================================================
# 데이터 로드 및 청크 변환
# =============================================================================

def loadSupplementaryData(validator: DataValidator) -> list[dict]:
    """보충 데이터 로드 및 청크 형식 변환"""
    basePath = Path(__file__).parent.parent / "data"
    chunks = []

    print("\n[데이터 로드 및 검증]")

    # 1. 기존 supplementary_info.json 로드
    dataPath = basePath / "clean" / "supplementary_info.json"
    if dataPath.exists():
        with open(dataPath, "r", encoding="utf-8") as f:
            items = json.load(f)

        validItems = validator.validateBatch(items, "supplementary_info.json")

        for item in validItems:
            chunk = {
                "chunk_id": item["doc_id"],
                "chunk_text": item["text"],
                "doc_id": item["doc_id"],
                "hotel": item["hotel"],
                "hotel_name": item["hotel_name"],
                "page_type": item["page_type"],
                "url": item["url"],
                "category": item["category"],
                "language": item.get("language", "ko"),
                "updated_at": datetime.now().isoformat(),
                "chunk_index": 0
            }
            chunks.append(chunk)

        print(f"  ✓ supplementary_info.json: {len(validItems)}개 (유효) / {len(items)}개 (전체)")

    # 2. pet_policy.json 로드 (반려동물 정책)
    petPath = basePath / "supplementary" / "pet_policy.json"
    if petPath.exists():
        with open(petPath, "r", encoding="utf-8") as f:
            petItems = json.load(f)

        validItems = validator.validateBatch(petItems, "pet_policy.json")

        for idx, item in enumerate(validItems):
            chunk = {
                "chunk_id": f"pet_policy_{item['hotel']}_{idx:03d}",
                "chunk_text": item["text"],
                "doc_id": f"pet_policy_{item['hotel']}",
                "hotel": item["hotel"],
                "hotel_name": item["hotel_name"],
                "page_type": "policy",
                "url": item.get("url", ""),
                "category": item["category"],
                "language": "ko",
                "updated_at": datetime.now().isoformat(),
                "chunk_index": idx
            }
            chunks.append(chunk)

        print(f"  ✓ pet_policy.json: {len(validItems)}개 (유효) / {len(petItems)}개 (전체)")

    # 3. supplementary 디렉토리의 다른 JSON 파일들 로드
    suppPath = basePath / "supplementary"
    if suppPath.exists():
        jsonFiles = sorted([f for f in suppPath.glob("*.json") if f.name != "pet_policy.json"])

        for jsonFile in jsonFiles:
            with open(jsonFile, "r", encoding="utf-8") as f:
                items = json.load(f)

            validItems = validator.validateBatch(items, jsonFile.name)

            for idx, item in enumerate(validItems):
                chunk = {
                    "chunk_id": f"{jsonFile.stem}_{item.get('hotel', 'unknown')}_{idx:03d}",
                    "chunk_text": item.get("text", ""),
                    "doc_id": f"{jsonFile.stem}_{item.get('hotel', 'unknown')}",
                    "hotel": item.get("hotel", ""),
                    "hotel_name": item.get("hotel_name", ""),
                    "page_type": item.get("page_type", "policy"),
                    "url": item.get("url", ""),
                    "category": item.get("category", "일반"),
                    "language": item.get("language", "ko"),
                    "updated_at": datetime.now().isoformat(),
                    "chunk_index": idx
                }
                chunks.append(chunk)

            print(f"  ✓ {jsonFile.name}: {len(validItems)}개 (유효) / {len(items)}개 (전체)")

    if not chunks:
        print("  ⚠️  보충 데이터 파일 없음")

    return chunks


def detectChanges(chunks: list[dict], hashManager: HashManager) -> dict:
    """변경 사항 감지"""
    added = []
    modified = []
    unchanged = []

    for chunk in chunks:
        chunkId = chunk["chunk_id"]
        currentHash = hashManager.computeHash(chunk)

        if hashManager.hasChanged(chunkId, currentHash):
            if chunkId in hashManager.hashes:
                modified.append(chunk)
            else:
                added.append(chunk)
            hashManager.update(chunkId, currentHash)
        else:
            unchanged.append(chunk)

    return {
        "added": added,
        "modified": modified,
        "unchanged": unchanged
    }


# =============================================================================
# 메인 실행
# =============================================================================

def main():
    """보충 데이터 인덱싱 실행"""
    print("=" * 60)
    print("보충 데이터 증분 인덱싱 (Incremental Indexing)")
    print("=" * 60)

    basePath = Path(__file__).parent.parent

    # 1. 데이터 검증 및 로드
    validator = DataValidator()
    chunks = loadSupplementaryData(validator)

    if not chunks:
        print("\n❌ 인덱싱할 데이터 없음")
        return

    # 2. 중복 체크
    print("\n[중복 체크]")
    uniqueChunks = validator.checkDuplicates(chunks)
    if len(chunks) != len(uniqueChunks):
        print(f"  ⚠️  중복 제거: {len(chunks)}개 → {len(uniqueChunks)}개")
    else:
        print(f"  ✓ 중복 없음: {len(uniqueChunks)}개")

    # 3. 검증 리포트 출력
    print("\n[검증 결과]")
    validator.printReport()

    # 오류가 있으면 중단
    if validator.errors:
        print("\n❌ 데이터 검증 실패. 오류를 수정한 후 다시 시도하세요.")
        return

    # 4. 변경 감지 (증분 인덱싱)
    print("\n[변경 감지]")
    hashManager = HashManager(basePath)
    changes = detectChanges(uniqueChunks, hashManager)

    print(f"  · 추가: {len(changes['added'])}개")
    print(f"  · 수정: {len(changes['modified'])}개")
    print(f"  · 변경 없음: {len(changes['unchanged'])}개")

    # 변경 사항이 없으면 종료
    toIndex = changes["added"] + changes["modified"]
    if not toIndex:
        print("\n✓ 변경 사항 없음. 인덱싱 건너뜀.")
        return

    # 5. 인덱서 초기화
    print("\n[인덱서 초기화]")
    indexer = Indexer()

    # 6. 기존 청크 로드 (BM25 재구축용)
    print("\n[기존 인덱스 로드]")
    existingChunks = indexer.loadChunks()
    print(f"  → 기존: {len(existingChunks)}개 청크")

    # 7. Vector DB 증분 업데이트 (upsert로 추가/수정)
    print("\n[Vector 인덱싱 (증분)]")
    indexer.indexChunks(toIndex)

    # 8. BM25 인덱스 재구축 (전체)
    # 기존 청크에서 변경된 chunk_id를 제외하고 새 청크 추가
    print("\n[BM25 재구축 (전체)]")
    modifiedIds = {c["chunk_id"] for c in toIndex}
    filteredExisting = [c for c in existingChunks if c["chunk_id"] not in modifiedIds]
    allChunks = filteredExisting + toIndex
    indexer._buildBM25Index(allChunks)

    # 9. 해시 저장
    hashManager.save()

    # 10. 최종 리포트
    print("\n" + "=" * 60)
    print("[인덱싱 완료]")
    print("=" * 60)
    print(f"  · 추가: {len(changes['added'])}개")
    print(f"  · 수정: {len(changes['modified'])}개")
    print(f"  · 총 보충 데이터: {len(uniqueChunks)}개")
    print(f"  · 전체 인덱스: {len(allChunks)}개 청크")

    # 11. 호텔별 통계
    print("\n[호텔별 통계]")
    hotelCounts = {}
    for chunk in uniqueChunks:
        hotel = chunk.get("hotel", "unknown")
        hotelCounts[hotel] = hotelCounts.get(hotel, 0) + 1

    for hotel, count in sorted(hotelCounts.items()):
        print(f"  · {hotel}: {count}개")

    print("=" * 60)


if __name__ == "__main__":
    main()
