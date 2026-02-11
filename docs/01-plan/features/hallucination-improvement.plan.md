# hallucination-improvement Planning Document

> **Summary**: RAG 챗봇 할루시네이션 방어 체계 고도화 - 임계값 통일, 테스트 강화, 동적 화이트리스트
>
> **Project**: josun_chatbot
> **Author**: 박성광
> **Date**: 2026-02-11
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

현재 100% 정확도(50/50 골든 QA + 22/22 멀티턴)를 달성했으나, 할루시네이션 방어 코드에 구조적 개선 여지가 존재한다. 임계값 불일치, 하드코딩된 화이트리스트, 테스트 커버리지 부족 등을 해결하여 **견고하고 유지보수 가능한 할루시네이션 방어 체계**를 구축한다.

### 1.2 Background

Phase 18까지의 반복 개선으로 다층 방어 아키텍처(6단계 검증)를 구축했으나:
- `EVIDENCE_THRESHOLD`가 2곳에서 다른 값으로 사용 (0.65 vs 0.45)
- 고유명사 화이트리스트(`knownNames`)가 `grounding.py`에 하드코딩 (20개+)
- 교통편/숫자/고유명사 날조에 대한 테스트 케이스 부재
- `graph.py`가 2,575줄로 비대해 할루시네이션 검증 로직 분리 필요

### 1.3 Related Documents

- PDCA 보고서: `docs/04-report/features/rag.report.md`
- Gap 분석: `docs/03-analysis/rag.analysis.md`
- 변경 이력: `doc/changelog.md`

---

## 2. Scope

### 2.1 In Scope

- [ ] 임계값 통일 및 상수 관리 일원화
- [ ] 고유명사 화이트리스트 외부 JSON 분리
- [ ] 할루시네이션 공격 테스트 케이스 추가 (10개+)
- [ ] answerVerifyNode 검증 로직 모듈 분리
- [ ] 시간/거리 추정 표현 감지 강화

### 2.2 Out of Scope

- LLM 모델 변경 (qwen2.5:7b 유지)
- 별도 검증 LLM 도입 (로컬 16GB 제약)
- 사용자 피드백 루프 시스템 구축
- 다국어 할루시네이션 검증

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | `EVIDENCE_THRESHOLD` 단일 소스 관리 (`constants.py`에서만 정의) | High | Pending |
| FR-02 | 고유명사 화이트리스트를 `data/config/known_names.json`으로 분리 | High | Pending |
| FR-03 | 할루시네이션 공격 테스트 케이스 10개 이상 추가 | High | Pending |
| FR-04 | `answerVerifyNode` 검증 로직을 `rag/verify.py`로 분리 | Medium | Pending |
| FR-05 | 시간/거리 추정 표현 감지 ("약 30분", "도보 10분" 등) | Medium | Pending |
| FR-06 | 금지 표현 패턴 외부 설정 파일 분리 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 정확도 | 골든 QA 100% 유지 (50/50) | `python tests/evaluate.py --save` |
| 정확도 | 멀티턴 100% 유지 (22/22) | `python tests/test_multiturn.py --save` |
| 성능 | 응답 시간 기존 대비 10% 이내 증가 | 로그 기반 측정 |
| 유지보수성 | `graph.py` 2,575줄 → 2,000줄 이하 | `wc -l rag/graph.py` |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 기존 테스트 100% 통과 유지 (50/50 + 22/22)
- [ ] 신규 할루시네이션 공격 테스트 전부 통과
- [ ] 임계값 단일 소스 확인 (grep으로 중복 없음 검증)
- [ ] 고유명사 JSON 외부 파일 로딩 정상 동작
- [ ] 코드 리뷰 완료

### 4.2 Quality Criteria

- [ ] 할루시네이션율 0.0% 유지
- [ ] 거부율(false rejection) 증가 없음
- [ ] `graph.py` 라인 수 감소

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 리팩토링 중 기존 검증 로직 파손 | High | Medium | 단계별 리팩토링 + 매 단계 테스트 실행 |
| 임계값 변경으로 거부율 증가 | High | Low | 기존 값 유지하되 소스 통일만 수행 |
| 신규 테스트 케이스 오탐 | Medium | Medium | 실제 서비스 데이터 기반 케이스 작성 |
| 외부 JSON 파일 로딩 실패 | Medium | Low | fallback으로 하드코딩 값 유지 |

---

## 6. Architecture Considerations

### 6.1 Project Level

| Level | Selected |
|-------|:--------:|
| **Dynamic** | ✅ |

기존 프로젝트 구조 유지. Python + FastAPI + LangGraph 기반.

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 검증 모듈 분리 | graph.py 내 유지 / verify.py 분리 | verify.py 분리 | graph.py 2,575줄 → 유지보수성 향상 |
| 화이트리스트 관리 | 하드코딩 / JSON 파일 / DB | JSON 파일 | 단순성 + 비개발자 수정 가능 |
| 임계값 관리 | 분산 정의 / constants.py 일원화 | constants.py 일원화 | 단일 진실 소스 원칙 |

### 6.3 모듈 구조 변경안

```
현재:
rag/
├── graph.py          (2,575줄 - 9노드 + 검증 메서드 전부)
├── grounding.py      (GroundingGate + CategoryConsistencyChecker)
├── constants.py      (상수/설정)
└── reranker.py       (Cross-Encoder)

변경 후:
rag/
├── graph.py          (~1,800줄 - 9노드 로직만)
├── verify.py         (NEW - answerVerifyNode 검증 메서드 분리)
├── grounding.py      (GroundingGate + CategoryConsistencyChecker)
├── constants.py      (모든 임계값 통합 관리)
├── reranker.py       (Cross-Encoder)
data/config/
├── known_names.json  (NEW - 호텔별 고유명사 화이트리스트)
└── forbidden_patterns.json (NEW - 금지 표현 패턴)
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` has coding conventions section
- [x] 변수/함수: camelCase, 클래스: PascalCase, 상수: UPPER_SNAKE_CASE
- [x] 주석: 한글, 커밋: 영문

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **Naming** | exists | verify.py 내 함수명 규칙 | High |
| **Folder structure** | exists | data/config/ 디렉토리 규칙 | Medium |
| **Import order** | missing | rag/ 패키지 내 import 순서 | Low |

---

## 8. Implementation Priority

| 순서 | 작업 | 예상 영향 | 위험도 |
|------|------|----------|--------|
| 1 | 임계값 통일 (FR-01) | 코드 정리 | Low |
| 2 | 할루시네이션 공격 테스트 추가 (FR-03) | 커버리지 향상 | Low |
| 3 | 고유명사 JSON 분리 (FR-02) | 유지보수성 | Low |
| 4 | 시간/거리 추정 감지 (FR-05) | 방어력 강화 | Medium |
| 5 | answerVerifyNode 모듈 분리 (FR-04) | 구조 개선 | Medium |
| 6 | 금지 패턴 외부 분리 (FR-06) | 유지보수성 | Low |

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`hallucination-improvement.design.md`)
2. [ ] 리뷰 및 승인
3. [ ] 구현 시작 (우선순위 순)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-11 | Initial draft | 박성광 |
