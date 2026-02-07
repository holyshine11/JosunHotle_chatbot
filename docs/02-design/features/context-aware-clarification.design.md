# 맥락 인식 명확화 시스템 설계

> Phase 13: Context-Aware Clarification System

---

## 문제 정의

### 현재 문제

```
입력: "개 대려갈게"
현재: "[조선 팰리스] 어떤 시설의 위치를 알고 싶으신가요?"
     + [호텔 위치, 수영장, 피트니스, 레스토랑, 스파]

문제점:
1. "개"가 specificTargets에 없음
2. 반려동물 맥락인데 위치 옵션 제시
3. 고정된 옵션 (맥락 무시)
```

### 기대 동작

```
입력: "개 대려갈게"
기대: "강아지를 데리고 어디를 방문하실 건가요?"
     + [객실, 레스토랑, 수영장, 로비...]

사용자: "객실"
기대: "[조선 팰리스] 반려동물 입실 가능 객실이 있습니다..."
     + 참고 정보: https://jpg.josunhotel.com/policy/hotel.do
```

---

## 설계

### 1. 맥락 감지 (Context Detection)

질문에서 맥락(topic)을 먼저 감지:

```python
CONTEXT_PATTERNS = {
    "반려동물": {
        "keywords": ["개", "강아지", "반려견", "펫", "pet", "고양이", "동반", "데려", "대려"],
        "clarification": {
            "question": "반려동물을 데리고 어디를 이용하실 예정인가요?",
            "options": ["객실 투숙", "레스토랑", "로비/공용시설", "전체 정책 확인"],
        },
        "direct_answer_trigger": ["가능", "돼", "되", "허용", "입장"],  # 이 단어 있으면 직접 답변
    },
    "어린이": {
        "keywords": ["아이", "아기", "어린이", "유아", "키즈", "애기"],
        "clarification": {
            "question": "어린이와 함께 어떤 시설을 이용하실 예정인가요?",
            "options": ["객실 투숙", "수영장", "키즈클럽", "레스토랑"],
        },
    },
    "음식": {
        "keywords": ["먹", "배고", "식사", "밥"],
        "clarification": {
            "question": "어떤 식사를 원하시나요?",
            "options": ["조식", "중식", "석식", "룸서비스"],
        },
    },
}
```

### 2. 의도 판단 로직

```
1. 맥락 감지 (CONTEXT_PATTERNS)
   ↓
2. 직접 답변 트리거 확인
   - "가능", "돼" 등 있으면 → 바로 정책 검색
   ↓
3. 트리거 없으면 → 맥락 맞춤 명확화 질문
   ↓
4. 사용자 선택 → 해당 시설 정책 검색
   ↓
5. 결과 + URL 제공
```

### 3. 코드 수정

#### 3.1 specificTargets 확장

```python
# graph.py - specificTargets에 "개" 추가
specificTargets = [
    # ... 기존 ...
    "강아지", "반려견", "반려동물", "펫", "pet", "dog", "애견",
    "고양이", "고냥이", "cat", "애완",
    "개",  # 추가!
    "데려", "대려", "동반",
]
```

#### 3.2 맥락 인식 명확화 패턴 추가

```python
# 새로운 맥락 기반 명확화 패턴
CONTEXT_CLARIFICATION = {
    "반려동물": {
        "keywords": ["개", "강아지", "반려견", "펫", "pet", "고양이", "동반", "데려", "대려"],
        "direct_triggers": ["가능", "돼", "되", "허용", "입장", "출입", "?"],  # 질문형이면 직접 답변
        "question": "반려동물을 데리고 어디를 이용하실 예정인가요?",
        "options": ["객실 투숙", "레스토랑/다이닝", "로비/공용시설", "전체 정책 확인"],
        "option_queries": {
            "객실 투숙": "반려동물 객실 입실 가능",
            "레스토랑/다이닝": "반려동물 레스토랑 입장",
            "로비/공용시설": "반려동물 공용시설 출입",
            "전체 정책 확인": "반려동물 정책",
        },
    },
}
```

#### 3.3 clarificationCheckNode 수정

```python
def clarificationCheckNode(self, state: RAGState) -> RAGState:
    query = state.get("normalized_query") or state["query"]
    queryLower = query.lower()

    # Phase 13: 맥락 기반 명확화 먼저 체크
    for contextKey, contextInfo in self.CONTEXT_CLARIFICATION.items():
        keywords = contextInfo["keywords"]
        directTriggers = contextInfo.get("direct_triggers", [])

        # 맥락 키워드 매칭
        if any(kw in queryLower for kw in keywords):
            # 직접 답변 트리거 확인 (질문형)
            if any(trigger in queryLower for trigger in directTriggers):
                # 바로 검색으로 진행 (명확화 불필요)
                return {
                    **state,
                    "needs_clarification": False,
                    "detected_context": contextKey,
                }

            # 맥락 맞춤 명확화 질문
            return {
                **state,
                "needs_clarification": True,
                "clarification_question": f"[{hotelName}] {contextInfo['question']}",
                "clarification_options": contextInfo["options"],
                "clarification_context": contextKey,
                "final_answer": f"[{hotelName}] {contextInfo['question']}",
            }

    # 기존 AMBIGUOUS_PATTERNS 로직...
```

---

## 구현 계획

### 즉시 수정 (1단계)

1. `specificTargets`에 "개" 추가
2. `AMBIGUOUS_PATTERNS["위치"]["excludes"]`에 "개" 추가

### 맥락 인식 시스템 (2단계)

1. `CONTEXT_CLARIFICATION` 패턴 추가
2. `clarificationCheckNode` 수정
3. 테스트 케이스 추가

---

## 예상 결과

```
입력: "개 대려갈게"

1단계 후 (즉시 수정):
→ 반려동물 정책 검색 시도 (명확화 질문 안 나옴)

2단계 후 (맥락 인식):
→ "반려동물을 데리고 어디를 이용하실 예정인가요?"
→ [객실 투숙, 레스토랑/다이닝, 로비/공용시설, 전체 정책 확인]
→ 사용자 선택 후 해당 정책 안내 + URL
```

---

## 파일 변경

| 파일 | 변경 |
|------|------|
| `rag/graph.py` | specificTargets에 "개" 추가, CONTEXT_CLARIFICATION 추가 |
| `tests/golden_qa.json` | "개 대려갈게" 테스트 추가 |
