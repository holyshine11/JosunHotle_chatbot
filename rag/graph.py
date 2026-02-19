"""
LangGraph 기반 RAG 플로우 오케스트레이터
- 9개 노드를 조합하여 RAG 파이프라인 구성
- 노드 구현은 nodes_*.py 모듈에 분리
"""

import time
from functools import partial
from typing import Literal
from pathlib import Path

from langgraph.graph import StateGraph, END

from rag.state import RAGState
from rag.nodes_preprocess import queryRewriteNode, preprocessNode, clarificationCheckNode
from rag.nodes_retrieve import retrieveNode, evidenceGateNode
from rag.nodes_compose import answerComposeNode
from rag.nodes_verify import answerVerifyNode, policyFilterNode, logNode


class RAGGraph:
    """LangGraph RAG 그래프 오케스트레이터"""

    def __init__(self, indexer):
        self.indexer = indexer
        self.basePath = Path(__file__).parent.parent
        self.logPath = self.basePath / "data" / "logs"
        self.logPath.mkdir(parents=True, exist_ok=True)

        # 그래프 생성
        self.graph = self._buildGraph()

    def _buildGraph(self) -> StateGraph:
        """LangGraph 그래프 구성"""
        workflow = StateGraph(RAGState)

        # 노드 추가 (partial로 의존성 주입)
        workflow.add_node("query_rewrite", queryRewriteNode)
        workflow.add_node("preprocess", preprocessNode)
        workflow.add_node("clarification_check", clarificationCheckNode)
        workflow.add_node("retrieve", partial(retrieveNode, indexer=self.indexer))
        workflow.add_node("evidence_gate", evidenceGateNode)
        workflow.add_node("answer_compose", answerComposeNode)
        workflow.add_node("answer_verify", answerVerifyNode)
        workflow.add_node("policy_filter", policyFilterNode)
        workflow.add_node("log", partial(logNode, logPath=self.logPath))

        # 엣지 정의
        workflow.set_entry_point("query_rewrite")
        workflow.add_edge("query_rewrite", "preprocess")
        workflow.add_edge("preprocess", "clarification_check")

        # 명확화 필요 여부에 따른 분기
        workflow.add_conditional_edges(
            "clarification_check",
            self._clarificationRouter,
            {
                "clarify": "log",      # 명확화 필요 → 바로 로그로 (질문 반환)
                "proceed": "retrieve"  # 명확화 불필요 → 검색 진행
            }
        )

        workflow.add_edge("retrieve", "evidence_gate")

        # evidence_gate 조건부 분기
        workflow.add_conditional_edges(
            "evidence_gate",
            self._evidenceRouter,
            {
                "pass": "answer_compose",
                "fail": "policy_filter"
            }
        )

        workflow.add_edge("answer_compose", "answer_verify")
        workflow.add_edge("answer_verify", "policy_filter")
        workflow.add_edge("policy_filter", "log")
        workflow.add_edge("log", END)

        return workflow.compile()

    def _evidenceRouter(self, state: RAGState) -> Literal["pass", "fail"]:
        """근거 검증 결과에 따른 라우팅"""
        return "pass" if state["evidence_passed"] else "fail"

    def _clarificationRouter(self, state: RAGState) -> Literal["clarify", "proceed"]:
        """명확화 필요 여부에 따른 라우팅"""
        return "clarify" if state.get("needs_clarification", False) else "proceed"

    def chat(self, query: str, hotel: str = None, history: list = None,
             sessionCtx=None) -> dict:
        """채팅 실행

        Args:
            query: 사용자 질문
            hotel: 호텔 ID (선택)
            history: 대화 히스토리 (선택)
            sessionCtx: 세션 컨텍스트 객체 (선택, ConversationContext)
        """
        pipelineStart = time.time()

        initialState: RAGState = {
            "query": query,
            "hotel": hotel,
            "history": history,
            "rewritten_query": "",
            "language": "",
            "detected_hotel": None,
            "category": None,
            "normalized_query": "",
            "is_valid_query": True,
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "clarification_type": None,
            "retrieved_chunks": [],
            "top_score": 0.0,
            "evidence_passed": False,
            "evidence_reason": "",
            "answer": "",
            "sources": [],
            "verification_passed": True,
            "verification_issues": [],
            "verified_answer": "",
            "grounding_result": None,
            "query_intents": [],
            "conversation_topic": None,
            "effective_category": None,
            "session_context": sessionCtx,
            "policy_passed": False,
            "policy_reason": "",
            "final_answer": "",
            "log": {},
            "_pipeline_start": pipelineStart,
        }

        # 그래프 실행
        result = self.graph.invoke(initialState)

        pipelineElapsed = time.time() - pipelineStart
        print(f"[타이밍] 전체 파이프라인: {pipelineElapsed:.1f}s")

        # 세션 업데이트
        if sessionCtx:
            detectedTopic = result.get("category") or result.get("conversation_topic")
            sessionCtx.updateTopic(detectedTopic, result.get("detected_hotel"))
            sessionCtx.cacheChunks(
                result.get("retrieved_chunks", []),
                query
            )

        return {
            "answer": result["final_answer"],
            "hotel": result["detected_hotel"],
            "category": result["category"],
            "evidence_passed": result["evidence_passed"],
            "verification_passed": result.get("verification_passed", True),
            "sources": result["sources"],
            "score": result["top_score"],
            "needs_clarification": result.get("needs_clarification", False),
            "clarification_question": result.get("clarification_question", ""),
            "clarification_options": result.get("clarification_options", []),
            "clarification_type": result.get("clarification_type"),
            "clarification_subject": result.get("clarification_subject"),
            "original_query": query,
        }


    def chatWithProgress(self, query: str, hotel: str = None, history: list = None,
                         sessionCtx=None, progressCallback=None) -> dict:
        """채팅 실행 (노드별 진행 상황 콜백 포함)

        Args:
            query: 사용자 질문
            hotel: 호텔 ID
            history: 대화 히스토리
            sessionCtx: 세션 컨텍스트
            progressCallback: (nodeName: str) -> None, 각 노드 시작 시 호출
        """
        pipelineStart = time.time()

        initialState: RAGState = {
            "query": query,
            "hotel": hotel,
            "history": history,
            "rewritten_query": "",
            "language": "",
            "detected_hotel": None,
            "category": None,
            "normalized_query": "",
            "is_valid_query": True,
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "clarification_type": None,
            "retrieved_chunks": [],
            "top_score": 0.0,
            "evidence_passed": False,
            "evidence_reason": "",
            "answer": "",
            "sources": [],
            "verification_passed": True,
            "verification_issues": [],
            "verified_answer": "",
            "grounding_result": None,
            "query_intents": [],
            "conversation_topic": None,
            "effective_category": None,
            "session_context": sessionCtx,
            "policy_passed": False,
            "policy_reason": "",
            "final_answer": "",
            "log": {},
            "_pipeline_start": pipelineStart,
        }

        # 노드별 스트리밍으로 진행 상황 보고
        finalState = None
        for event in self.graph.stream(initialState):
            nodeName = list(event.keys())[0]
            finalState = event[nodeName]
            if progressCallback:
                progressCallback(nodeName)

        if finalState is None:
            finalState = initialState

        pipelineElapsed = time.time() - pipelineStart
        print(f"[타이밍] 전체 파이프라인: {pipelineElapsed:.1f}s")

        # 세션 업데이트
        if sessionCtx:
            detectedTopic = finalState.get("category") or finalState.get("conversation_topic")
            sessionCtx.updateTopic(detectedTopic, finalState.get("detected_hotel"))
            sessionCtx.cacheChunks(
                finalState.get("retrieved_chunks", []),
                query
            )

        return {
            "answer": finalState.get("final_answer", ""),
            "hotel": finalState.get("detected_hotel"),
            "category": finalState.get("category"),
            "evidence_passed": finalState.get("evidence_passed", False),
            "verification_passed": finalState.get("verification_passed", True),
            "sources": finalState.get("sources", []),
            "score": finalState.get("top_score", 0),
            "needs_clarification": finalState.get("needs_clarification", False),
            "clarification_question": finalState.get("clarification_question", ""),
            "clarification_options": finalState.get("clarification_options", []),
            "clarification_type": finalState.get("clarification_type"),
            "clarification_subject": finalState.get("clarification_subject"),
            "original_query": query,
        }


def createRAGGraph():
    """RAG 그래프 생성 헬퍼"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from pipeline.indexer import Indexer

    indexer = Indexer()
    return RAGGraph(indexer)


if __name__ == "__main__":
    # 테스트
    rag = createRAGGraph()

    testQueries = [
        "체크인 시간이 어떻게 되나요?",
        "조선팰리스 주차 요금 알려주세요",
        "제주 수영장 운영시간",
        "환불 정책이 어떻게 되나요?",
    ]

    for query in testQueries:
        print(f"\n{'='*50}")
        print(f"Q: {query}")
        result = rag.chat(query)
        print(f"A: {result['answer']}")
        print(f"호텔: {result['hotel']}, 점수: {result['score']:.3f}")
