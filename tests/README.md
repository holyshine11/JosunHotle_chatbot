# 테스트 및 평가

RAG 챗봇의 품질을 검증하는 테스트 모듈입니다.

## 파일 구조

```
tests/
├── test_data.json      # 테스트 케이스 데이터
├── test_qa.py          # 테스트 실행 코드
├── results/            # 테스트 결과 저장
└── README.md
```

## 사용법

```bash
PYTHON=~/.pyenv/versions/3.11.7/bin/python3

# 테스트 실행
$PYTHON tests/test_qa.py

# 결과 저장
$PYTHON tests/test_qa.py --save

# 간략 출력
$PYTHON tests/test_qa.py --quiet
```

## 테스트 케이스

### 일반 테스트 (25개)

| 카테고리 | 테스트 수 | 설명 |
|---------|---------|-----|
| 체크인/아웃 | 4 | 체크인/아웃 시간, 얼리/레이트 |
| 주차 | 2 | 주차 요금, 가능 여부 |
| 조식 | 2 | 조식 포함, 가격 |
| 부대시설 | 4 | 피트니스, 수영장, 사우나 |
| 위치/교통 | 3 | 위치, 지하철, 공항 |
| 환불/취소 | 2 | 취소 정책, 수수료 |
| 반려동물 | 2 | 반려동물 입실 |
| 금연 | 1 | 객실 내 흡연 |
| 객실 | 5 | 미성년자, 엑스트라베드, 와이파이, 인원 |

### 레드팀 테스트 (8개)

| 카테고리 | 테스트 수 | 설명 |
|---------|---------|-----|
| 개인정보 | 4 | 예약번호, 카드번호, 비밀번호, 주민번호 |
| 정책우회 | 1 | 환불 예외 요청 |
| 범위외 | 1 | 타 호텔 비교 |
| 최신성 | 1 | 실시간 정보 요청 |
| 가격협상 | 1 | 할인 요청 |

## 평가 지표

### Citation Coverage (출처 포함률)

답변에 출처 URL이 포함된 비율

```
출처 포함 답변 수 / 전체 답변 수
```

### Answerability Precision (답변 정확도)

답변해야 할 질문에 올바르게 답변한 비율

```
올바른 답변 수 / 답변해야 할 질문 수
```

### Refusal Correctness (거절 정확도)

거절해야 할 질문을 올바르게 거절한 비율

```
올바른 거절 수 / 거절해야 할 질문 수
```

## 최신 테스트 결과

```
[일반 테스트]
  총 테스트: 25개
  통과: 19개
  통과율: 76.0%

[레드팀 테스트]
  총 테스트: 8개
  통과: 8개
  통과율: 100.0%

[주요 지표]
  Citation Coverage: 80.0%
  Answerability Precision: 76.0%
  Refusal Correctness: 100.0%
```

## 테스트 케이스 추가

`test_data.json` 파일에 새로운 케이스 추가:

```json
{
  "id": "T026",
  "query": "새로운 질문",
  "category": "카테고리",
  "hotel": "josun_palace",  // 선택사항
  "expected_keywords": ["키워드1", "키워드2"],
  "should_answer": true
}
```

### 레드팀 케이스 추가

```json
{
  "id": "R009",
  "query": "차단해야 할 질문",
  "category": "개인정보",
  "should_answer": false,
  "expected_block": "personal_info"
}
```

## 결과 파일

`tests/results/test_results_YYYYMMDD_HHMMSS.json`:

```json
{
  "timestamp": "20260204_102328",
  "metrics": {
    "citation_coverage": 0.8,
    "answerability_precision": 0.76,
    "refusal_correctness": 1.0
  },
  "normal_tests": [...],
  "red_team_tests": [...]
}
```
