# 정책 관리

챗봇의 금지 주제, 개인정보 보호, 답변 템플릿을 관리합니다.

## 파일 구조

```
policies/
├── josun_policies.yaml   # 정책 설정 파일
├── policy_manager.py     # 정책 관리 모듈
└── README.md
```

## 정책 파일 구조 (josun_policies.yaml)

### 호텔 정보
```yaml
hotels:
  josun_palace:
    name: "조선 팰리스"
    phone: "02-727-7200"
    email: "rsvn@josunpalace.com"
    website: "https://jpg.josunhotel.com"
```

### 금지 키워드
```yaml
forbidden_keywords:
  personal_info:    # 개인정보
    - "예약번호"
    - "카드번호"
    - "비밀번호"
  payment_action:   # 결제 관련
    - "결제해"
    - "송금"
```

### 답변 템플릿
```yaml
response_templates:
  personal_info_block:
    message: |
      개인정보는 챗봇에서 처리할 수 없습니다.
      호텔 고객센터로 문의해 주세요: {hotel_phone}
```

### 근거 검증 설정
```yaml
evidence_gate:
  min_score: 0.5    # 최소 유사도 점수
  min_chunks: 1     # 최소 필요 청크 수
```

## 사용법

### CLI 테스트

```bash
PYTHON=~/.pyenv/versions/3.11.7/bin/python3
$PYTHON policies/policy_manager.py
```

### Python에서 사용

```python
from policies.policy_manager import PolicyManager

pm = PolicyManager()

# 호텔 정보 조회
info = pm.getHotelInfo("josun_palace")
print(info["phone"])  # 02-727-7200

# 금지 키워드 검사
forbidden, category, keyword = pm.checkForbiddenKeywords("예약번호 알려주세요")
if forbidden:
    print(f"금지: {category} - {keyword}")

# 답변 템플릿 조회
template = pm.getResponseTemplate("personal_info_block", "josun_palace")
print(template)

# 정책 적용
result = pm.applyPolicy(
    query="카드번호로 결제해주세요",
    answer="",
    hotelKey="josun_palace"
)
if not result["allowed"]:
    print(result["modified_answer"])
```

## 정책 규칙

### 금지 키워드 감지 시 동작

| 카테고리 | 감지 키워드 | 응답 |
|---------|-----------|------|
| personal_info | 예약번호, 카드번호, 비밀번호 등 | 고객센터 안내 |
| payment_action | 결제해, 송금, 이체 | 공식 웹사이트 안내 |

### 근거 검증 실패 시

- 점수 < 0.5 또는 청크 없음
- 응답: "현재 데이터로는 확인이 어렵습니다. 호텔에 문의해 주세요."

### 카테고리별 특수 규칙

| 카테고리 | 규칙 |
|---------|-----|
| 환불/취소 | 항상 업데이트 날짜 표시 + 경고 문구 |
| 가격/요금 | 항상 업데이트 날짜 표시 + 변동 가능 안내 |
| 운영시간 | 항상 업데이트 날짜 표시 + 확인 권고 |

## 정책 수정

1. `josun_policies.yaml` 파일 수정
2. 서버 재시작 (정책은 시작 시 로드됨)

### 금지 키워드 추가 예시

```yaml
forbidden_keywords:
  personal_info:
    - "예약번호"
    - "새로운키워드"  # 추가
```

### 답변 템플릿 추가 예시

```yaml
response_templates:
  new_template:
    message: |
      새로운 템플릿 메시지
      호텔 전화: {hotel_phone}
    severity: "info"
```

## 변수 치환

템플릿에서 사용 가능한 변수:

| 변수 | 설명 |
|-----|------|
| {hotel_phone} | 호텔 전화번호 |
| {hotel_website} | 호텔 웹사이트 |
| {hotel_name} | 호텔명 |
| {hotel_email} | 호텔 이메일 |
