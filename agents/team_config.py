"""
조선호텔 RAG 챗봇 - Agent Team 설정
4개 전문 에이전트가 병렬로 각 문제를 해결

사용법:
    python agents/run_team.py                  # 전체 팀 실행
    python agents/run_team.py --agent speed    # 특정 에이전트만 실행
    python agents/run_team.py --dry-run        # 프롬프트만 확인
"""

from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """에이전트 설정 정의"""
    name: str                          # 에이전트 이름
    role: str                          # 역할 설명 (한글)
    model: str                         # 모델 (opus, sonnet, haiku)
    systemPrompt: str                  # 시스템 프롬프트
    taskPrompt: str                    # 실행할 작업 프롬프트
    ownerFiles: list[str] = field(default_factory=list)   # 담당 파일 (수정 가능)
    readOnlyFiles: list[str] = field(default_factory=list) # 참조 파일 (읽기만)
    maxTurns: int = 30                 # 최대 턴 수


# ──────────────────────────────────────────────
# 공통 컨텍스트 (모든 에이전트가 공유)
# ──────────────────────────────────────────────
PROJECT_CONTEXT = """
## 프로젝트: 조선호텔 RAG 챗봇
- 5개 호텔 (조선 팰리스, 그랜드 조선 부산/제주, 레스케이프, 그래비티 판교)
- LangGraph 9노드 파이프라인: queryRewrite → preprocess → clarificationCheck → retrieve → evidenceGate → answerCompose → answerVerify → policyFilter → log
- 로컬 실행 (16GB 노트북), Ollama qwen2.5:7b (Q4 양자화)
- Vector(70%) + BM25(30%) 하이브리드 검색 + Cross-Encoder 리랭킹
- "No Retrieval, No Answer" 정책 강제
- 현재 정확도: 100% (50/50), 할루시네이션: 0% (기본 테스트셋)

## 핵심 제약
- 변수/함수: camelCase, 클래스: PascalCase, 상수: UPPER_SNAKE_CASE
- 주석: 한글
- 기존 테스트(50개 golden QA + 22턴 멀티턴)가 깨지지 않아야 함
- 근거 없는 답변/추정/일반론 금지
"""


# ──────────────────────────────────────────────
# Agent 1: 정확도 개선 에이전트
# ──────────────────────────────────────────────
ACCURACY_AGENT = AgentConfig(
    name="accuracy",
    role="정확도 개선 전문가",
    model="opus",
    ownerFiles=[
        "rag/graph.py",        # answerComposeNode 개선
    ],
    readOnlyFiles=[
        "rag/constants.py",
        "rag/grounding.py",
        "rag/verify.py",
        "data/supplementary/dining_menu.json",
        "data/supplementary/package_info.json",
        "tests/golden_qa.json",
    ],
    maxTurns=30,
    systemPrompt=f"""당신은 RAG 챗봇의 답변 정확도를 개선하는 전문가입니다.

{PROJECT_CONTEXT}

## 당신의 역할
- answerComposeNode에서 복수 청크의 정보를 **교차 참조하여 조합**하는 로직 강화
- 링크/URL에 숨어있는 상세 정보를 단순히 URL만 던지지 않고 **핵심 내용을 추출하여 답변에 포함**
- retrieved_chunks에서 관련 정보를 병합하여 완성도 높은 답변 생성

## 제약
- rag/graph.py만 수정 가능
- 다른 파일은 읽기만 가능
- 기존 노드 구조(9노드)를 유지할 것
- 기존 테스트가 깨지지 않도록 할 것
""",
    taskPrompt="""다음 작업을 순서대로 수행하세요:

1. rag/graph.py의 answerComposeNode 함수를 분석하세요
2. 현재 복수 청크를 어떻게 처리하는지 파악하세요
3. 다음을 개선하세요:
   a. 복수 청크에서 관련 정보를 교차 참조하여 조합하는 로직
   b. URL 상세 정보를 답변에 포함하는 로직
   c. 청크 간 중복 제거 및 정보 병합
4. 변경 사항을 rag/graph.py에 적용하세요
5. 변경 내용 요약을 작성하세요

주의: 기존 동작이 깨지지 않도록 방어적으로 코딩하세요.
""",
)


# ──────────────────────────────────────────────
# Agent 2: 할루시네이션 제거 에이전트
# ──────────────────────────────────────────────
HALLUCINATION_AGENT = AgentConfig(
    name="hallucination",
    role="할루시네이션 탐지/제거 전문가",
    model="opus",
    ownerFiles=[
        "rag/grounding.py",   # GroundingGate 강화
        "rag/verify.py",      # AnswerVerifier 강화
    ],
    readOnlyFiles=[
        "rag/graph.py",
        "rag/constants.py",
        "rag/entity.py",
        "data/config/known_names.json",
        "data/config/forbidden_patterns.json",
        "tests/golden_qa.json",
    ],
    maxTurns=30,
    systemPrompt=f"""당신은 RAG 챗봇의 할루시네이션을 탐지하고 제거하는 전문가입니다.

{PROJECT_CONTEXT}

## 당신의 역할
- GroundingGate의 문장 단위 검증 로직 강화
- AnswerVerifier의 다층 검증 패턴 확장
- 새로운 유형의 할루시네이션 패턴 발견 및 차단 룰 추가

## 현재 검증 체계
- SUSPICIOUS_PATTERNS: 27개 정규식 (constants.py)
- GroundingGate: 문장별 근거 매칭 (grounding.py)
- AnswerVerifier: 숫자/고유명사/교통편/카테고리 오염 검증 (verify.py)
- known_names.json: 486개 화이트리스트 (브랜드, 레스토랑, 시설)

## 제약
- rag/grounding.py, rag/verify.py만 수정 가능
- 기존 테스트 결과(100% 정확도)를 유지할 것
- 검증이 너무 엄격해서 정상 답변을 거부하지 않도록 주의
""",
    taskPrompt="""다음 작업을 순서대로 수행하세요:

1. rag/grounding.py의 GroundingGate 클래스를 분석하세요
2. rag/verify.py의 AnswerVerifier 클래스를 분석하세요
3. 현재 검증 로직의 약점을 파악하세요:
   a. 어떤 유형의 할루시네이션이 통과할 수 있는가?
   b. 수치 정보 검증이 충분한가?
   c. 엔티티 교차 오염이 방지되는가?
4. 개선사항을 구현하세요:
   a. 새로운 할루시네이션 패턴 탐지 룰 추가
   b. 근거 매칭 정확도 향상
   c. 엣지 케이스 처리 강화
5. 변경 내용 요약을 작성하세요

주의: False positive(정상 답변 거부)가 증가하지 않도록 균형을 유지하세요.
""",
)


# ──────────────────────────────────────────────
# Agent 3: 속도 최적화 에이전트
# ──────────────────────────────────────────────
SPEED_AGENT = AgentConfig(
    name="speed",
    role="응답 속도 최적화 전문가",
    model="sonnet",
    ownerFiles=[
        "rag/llm_provider.py",  # LLM 호출 최적화
        "rag/reranker.py",      # 리랭커 최적화
    ],
    readOnlyFiles=[
        "rag/graph.py",
        "rag/server.py",
        "rag/constants.py",
        "pipeline/indexer.py",
    ],
    maxTurns=25,
    systemPrompt=f"""당신은 RAG 챗봇의 응답 속도를 최적화하는 전문가입니다.

{PROJECT_CONTEXT}

## 당신의 역할
- LLM 호출 횟수 최소화 (현재 9노드 중 LLM 사용 노드 식별)
- 리랭커(BAAI/bge-reranker-v2-m3) 성능 최적화
- 캐싱 전략 수립 및 구현
- 불필요한 연산 제거

## 현재 병목 예상
- queryRewriteNode: LLM 호출 1회
- answerComposeNode: LLM 호출 1회
- answerVerifyNode: LLM 호출 1회 (또는 다수)
- Cross-Encoder 리랭킹: 모델 추론 1회
- 총 최소 3~4회 LLM 호출 = 30초 이상

## 제약
- rag/llm_provider.py, rag/reranker.py만 수정 가능
- 답변 품질(정확도, 할루시네이션율)이 하락하면 안 됨
- 로컬 16GB 환경에서 동작해야 함
""",
    taskPrompt="""다음 작업을 순서대로 수행하세요:

1. rag/graph.py를 읽고 LLM을 호출하는 모든 노드를 식별하세요
2. rag/llm_provider.py를 분석하세요:
   a. 현재 LLM 호출 방식 (timeout, max_tokens 등)
   b. 캐싱이 있는지 확인
3. rag/reranker.py를 분석하세요:
   a. 모델 로딩 방식
   b. 배치 처리 여부
4. 개선사항을 구현하세요:
   a. LLM 응답 캐싱 (동일/유사 쿼리)
   b. 리랭커 배치 최적화
   c. 불필요한 LLM 호출 스킵 조건 추가
5. 변경 내용 요약 및 예상 속도 개선 효과를 작성하세요

주의: 속도 개선이 답변 품질을 떨어뜨리면 안 됩니다.
""",
)


# ──────────────────────────────────────────────
# Agent 4: 데이터 파이프라인 에이전트
# ──────────────────────────────────────────────
DATA_AGENT = AgentConfig(
    name="data",
    role="데이터 파이프라인 자동화 전문가",
    model="sonnet",
    ownerFiles=[
        "pipeline/index_supplementary.py",  # 증분 인덱싱
    ],
    readOnlyFiles=[
        "pipeline/indexer.py",
        "pipeline/index_all.py",
        "pipeline/chunker.py",
        "data/supplementary/dining_menu.json",
        "data/supplementary/package_info.json",
        "data/supplementary/event_info.json",
        "data/supplementary/dining_corkage.json",
    ],
    maxTurns=25,
    systemPrompt=f"""당신은 RAG 챗봇의 데이터 파이프라인을 자동화하는 전문가입니다.

{PROJECT_CONTEXT}

## 당신의 역할
- 보충 데이터(supplementary) 인입 시 자동 검증 로직 구현
- 증분 인덱싱(기존 인덱스에 새 데이터만 추가) 로직 개선
- 데이터 품질 검증 (필수 필드, 형식, 중복 체크) 자동화

## 현재 데이터 구조
- data/supplementary/: 10개 JSON (패키지 51, 이벤트 19 등)
- pipeline/index_all.py: 전체 재구축 (느림)
- pipeline/index_supplementary.py: 보충 데이터만 (빠름)
- 총 638 청크 인덱싱됨

## 제약
- pipeline/index_supplementary.py만 수정 가능
- 기존 인덱스를 손상시키지 않을 것
- 새 데이터 추가 시 기존 데이터와의 일관성 유지
""",
    taskPrompt="""다음 작업을 순서대로 수행하세요:

1. pipeline/index_supplementary.py를 분석하세요
2. pipeline/indexer.py의 인덱싱 방식을 파악하세요
3. data/supplementary/ 내 JSON 파일들의 구조를 확인하세요
4. 개선사항을 구현하세요:
   a. 데이터 검증 함수 (필수 필드, 형식, 중복 체크)
   b. 증분 인덱싱 (변경된 데이터만 업데이트)
   c. 인덱싱 결과 리포트 (추가/수정/삭제 건수)
5. 변경 내용 요약을 작성하세요

주의: 기존 인덱스를 손상시키지 마세요.
""",
)


# ──────────────────────────────────────────────
# 팀 전체 설정
# ──────────────────────────────────────────────
TEAM_AGENTS = {
    "accuracy": ACCURACY_AGENT,
    "hallucination": HALLUCINATION_AGENT,
    "speed": SPEED_AGENT,
    "data": DATA_AGENT,
}

# 실행 순서 (의존성 기반)
EXECUTION_PHASES = [
    {
        "phase": 1,
        "name": "속도 + 데이터 (독립 작업)",
        "agents": ["speed", "data"],
        "parallel": True,
        "description": "속도 최적화와 데이터 파이프라인은 서로 독립적이므로 병렬 실행",
    },
    {
        "phase": 2,
        "name": "정확도 + 할루시네이션 (독립 작업)",
        "agents": ["accuracy", "hallucination"],
        "parallel": True,
        "description": "정확도 개선과 할루시네이션 제거는 담당 파일이 분리되어 병렬 가능",
    },
]
