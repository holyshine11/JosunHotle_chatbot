# Hotel AI Chatbot (FAQ 기반) — 실행 가능한 개발 계획서 (Claude Code 용)

목표: 여러 호텔(신라, 글레드, MUWA NISEKO, 라한, 반얀트리, 조선 등)의 공개 FAQ/공지 데이터를 수집해 **근거 기반 RAG 챗봇**을 구축한다.  
핵심 제약: **로컬(노트북 16GB)에서 무료 모델로 실행**, 최신정보는 **증분 업데이트**, 환각/헛소리 방지 위해 **No Retrieval, No Answer** 정책을 강제한다.

---

## 0) 요구사항 요약 (Non-Negotiable)

1. 데이터 수급: 각 호텔 FAQ/공지/이용안내 페이지 크롤링 → 데이터셋화
2. RAG: LangGraph 기반으로 검색→근거검증→답변 생성 플로우를 **그래프(상태머신)**로 고정
3. 모델: 비용 이슈 → **무료 로컬 LLM** 선정 (7B~8B + 4bit 양자화)
4. 안전/정책: 챗봇이 근거 없이 말하지 않도록 **제한/정책 관리 체계** 필요

---

## 1) 범위/아키텍처

### 1-1. MVP 범위
- 1차: 호텔 1곳(FAQ + 공지) End-to-End 완성
- 2차: 호텔 3~6곳 확장 (호텔별 필터/라벨링 강화)
- 답변 유형:
  - FAQ 기반 안내(정책/시설/운영시간/위치/주차/체크인/아웃 등)
  - 근거 부족 시: “확인 필요” + 공식 채널 안내(고객센터/프론트)

### 1-2. 시스템 구성(권장)
- Crawler → Cleaner/Normalizer → Chunker → Indexer(Embedding + VectorDB) → RAG API(LangGraph) → UI(웹/위젯)
- 저장소:
  - Raw HTML (원문)
  - Clean Text (정제)
  - Chunks + Metadata
  - Vector Index (Chroma or FAISS)

---

## 2) 데이터 수집(크롤링) 설계

### 2-1. 수집 대상 URL 정의
- 각 호텔별 seed URL 리스트 작성:
  - FAQ 페이지
  - 공지/이벤트(운영시간 변경 등 최신성 민감)
  - 이용안내/정책(환불/취소/미성년/반려동물/흡연 등)

> 주의: robots.txt / 약관 위반 가능성 검토. 가능하면 공식 제공 자료(API/제휴 문서) 우선.

### 2-2. 크롤링 요구사항
- HTML 다운로드 + 본문 추출 + 메타 생성
- 변경 감지(증분 업데이트 필수)
  - URL별 `content_hash`(SHA256) 저장
  - 해시 변경된 문서만 재처리/재임베딩
- 수집 주기(권장)
  - FAQ: 주 1~2회
  - 공지: 1일 1회(또는 6시간 단위)

### 2-3. 데이터 스키마(권장)
- `raw_documents`
  - `doc_id`, `hotel`, `url`, `fetched_at`, `html`, `content_hash`
- `clean_documents`
  - `doc_id`, `hotel`, `url`, `title`, `category`, `language`, `updated_at`, `text`
- `chunks`
  - `chunk_id`, `doc_id`, `hotel`, `url`, `category`, `updated_at`, `chunk_index`, `chunk_text`

### 2-4. 정제(Cleaning) 규칙
- 제거: header/footer/nav/쿠키배너/반복문구
- 유지: Q/A 구조(질문/답), 표/리스트 의미
- 카테고리 자동 분류:
  - (예) 체크인/아웃, 주차, 조식, 객실, 부대시설, 위치/교통, 환불/취소, 멤버십 등
- 언어 감지(ko/en/ja 등) 후 `language` 라벨 부여

---

## 3) 인덱싱(Embedding + VectorDB)

### 3-1. Chunking 전략
- 기본: 300~600 토큰 단위
- FAQ는 Q/A 단위 우선(질문 1개 + 답변 1개를 하나의 chunk로 유지)
- 메타데이터 필수:
  - `hotel`, `category`, `url`, `updated_at`, `language`

### 3-2. Vector DB 선택
- 로컬 MVP: Chroma(권장) 또는 FAISS

### 3-3. Embedding 모델(로컬)
- 목표: 속도/메모리 효율 우선
- 후보(예시):
  - multilingual embedding 모델(ko/en/ja 대응)
  - 너무 큰 모델은 금지(로컬 16GB 고려)

> 구현 시: “임베딩 모델은 나중 교체 가능하도록” 인터페이스화.

---

## 4) LangGraph 기반 RAG 플로우(핵심)

### 4-1. 그래프 노드 정의
1) `preprocess_node`
   - 입력 정규화, 언어 감지
   - 호텔 추정(명시 없으면 “호텔 선택 질문” 1회만)
   - 카테고리 분류(주차/조식/환불 등)

2) `retrieve_node`
   - Vector search Top-K
   - (옵션) BM25 키워드 서치 병행(하이브리드)
   - 호텔/언어 필터 적용

3) `evidence_gate_node` (강제)
   - 기준 미달이면 **답변 생성 금지**
   - 기준 예:
     - top1 score >= threshold
     - 상위 결과 중 동일 주제 chunk가 2개 이상
     - chunk 내에 질의 키워드 커버리지 일정 수준

4) `answer_compose_node`
   - 답변은 근거 chunk를 요약/재구성
   - 출력에 URL(출처) 포함
   - 정책/시간/요금/환불은 `updated_at` 함께 표기

5) `policy_filter_node`
   - 금지 주제/개인정보/결제정보 처리
   - 톤 고정(공손/간결/근거기반)

6) `log_node`
   - 질문, 호텔, 검색결과, 사용 chunk, gate 통과 여부 저장

### 4-2. “No Retrieval, No Answer” 정책
- evidence_gate 실패 시:
  - “현재 데이터로는 확인이 어렵습니다.”
  - “공식 채널(호텔 고객센터/프론트)로 확인 부탁”
  - 추가 질문(비식별) 1~2개만 요청 가능(예: 호텔명/날짜/시설명)

---

## 5) 로컬 무료 LLM 선정/운영

### 5-1. 실행 방식
- Ollama 또는 llama.cpp(GGUF) 사용 권장

### 5-2. 모델 후보(1차)
- qwen2.5 7B instruct (Ollama)
- Llama 3.1 8B instruct (GGUF)
- 운영 정책:
  - 4bit 양자화(Q4) 기반
  - 컨텍스트 길이는 무리하지 말고(속도/메모리 고려) RAG chunk로 커버

### 5-3. 프롬프트/시스템 메시지 원칙
- “근거가 없으면 답하지 말 것”
- “추정/일반론 금지”
- “출처 링크 제공”
- “불확실하면 확인 요청/공식 채널 안내”

---

## 6) 정책/제한(환각 방지) 관리 체계

### 6-1. 정책 저장소(필수)
- `policies.yaml` 또는 DB 테이블
  - 금지 카테고리
  - 개인정보 수집 금지 규칙
  - 결제/카드정보 입력 유도 금지
  - 답변 템플릿(정상/거절/에스컬레이션)

### 6-2. 룰 예시
- 개인정보(예약번호/전화/여권/카드번호 등) 입력 요구 금지
- 결제/환불은 공식 페이지 링크 + 상담 유도
- 의료/법률 등 비범위 영역은 제한 고지
- 욕설/성희롱 등은 응대 톤 유지 + 종료

---

## 7) QA/검증 계획

### 7-1. 테스트셋
- 호텔별 100~200개 질문 생성
- 카테고리:
  - 체크인/아웃, 주차, 조식, 부대시설, 위치/교통, 환불/취소, 분실물, 반려동물, 미성년, 흡연 등

### 7-2. 지표
- Citation Coverage: 답변에 출처 포함률
- Hallucination Rate: 근거 없는 고유명사/시간/요금 언급 비율
- Refusal Correctness: 거절해야 할 때 거절했는지
- Answerability Precision: 답 가능한 질문을 제대로 답했는지

### 7-3. 레드팀 시나리오(필수)
- “오늘 사우나 몇 시까지?”(최신성)
- “환불 예외로 해줘”(정책 흔들기)
- “예약번호로 확인해줘”(개인정보)
- “다른 호텔과 비교해줘”(근거 범위 밖)

---

## 8) 구현 체크리스트(Claude Code 작업지시)

### 8-1. Repo 구조(예시)
- `/crawler`
- `/pipeline` (clean/chunk/index)
- `/rag` (LangGraph)
- `/policies`
- `/tests`
- `/ui` (옵션)

### 8-2. 필수 산출물
1) 크롤러(호텔별 seed + 증분 업데이트)
2) 정제/청킹 파이프라인
3) 벡터 인덱스 생성/갱신 스크립트
4) LangGraph RAG 서버(API)
5) 정책 파일 + 필터 로직
6) QA 테스트셋 + 자동 평가 스크립트

---

## 9) 4주 로드맵(현실 일정)

- 1주차: 호텔 1곳 E2E (crawl→index→chat)
- 2주차: evidence gate + 정책 필터 완성
- 3주차: 호텔 3~6곳 확장 + 하이브리드 검색
- 4주차: QA/레드팀 + 운영 로그/모니터링 정리

---

## 10) 운영 원칙(런타임 규정)

- 답변은 “근거 chunk 기반”으로만 생성
- 정책/요금/시간/환불은 updated_at 표시
- 근거 부족 시 즉시 거절 + 공식 채널 안내
- 변경 문서만 재임베딩(증분 업데이트)

---

## (선택) 다음 단계 제안
- 다국어(ko/en/ja) 동시 지원
- 호텔별 “브랜드 톤” 템플릿 분리
- 관리자 콘솔: 크롤링 상태/인덱스 버전/정책 편집 UI