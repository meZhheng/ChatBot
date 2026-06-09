from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.utils.logger_handler import logger
from faq.service import FaqService

@dataclass(frozen=True)
class ChatRouteDecision:
    route: str = "faq_first"
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class IntentRouter(Protocol):
    def decide(self, query: str, session_id: str) -> ChatRouteDecision:
        pass


class ChatOrchestrator:
    def __init__(
        self,
        agent_service,
        faq_service: FaqService,
        intent_router: IntentRouter | None = None,
        faq_top_k: int = 3,
        faq_score_threshold: float = 0.03,
        faq_exact_match_threshold: float = 0.015,
    ):
        self.agent_service = agent_service
        self.faq_service = faq_service
        self.intent_router = intent_router
        self.faq_top_k = faq_top_k
        self.faq_score_threshold = faq_score_threshold
        self.faq_exact_match_threshold = faq_exact_match_threshold

    def execute_stream(self, query: str, session_id: str):
        decision = self._decide_route(query, session_id)
        logger.info(
            f"[聊天路由]session={session_id} route={decision.route} category={decision.category or '-'} query={query!r}"
        )
        if decision.route == "agent":
            logger.info(f"[聊天路由]session={session_id}跳过FAQ检索，直接调用agent。")
            yield from self.agent_service.execute_stream(query, session_id)
            return

        faq_hit = self._retrieve_faq_hit(query, decision.category, session_id)
        if faq_hit is not None:
            logger.info(
                "[聊天路由]session="
                f"{session_id}采用FAQ回复 faq_id={self._field(faq_hit, 'faq_id', '-')} "
                f"score={self._field(faq_hit, 'score', '-')} matched_question={self._field(faq_hit, 'matched_question', '')!r}"
            )
            yield from self._faq_hit_stream(query, session_id, faq_hit, decision)
            return

        logger.info(f"[聊天路由]session={session_id}未采用FAQ，fallback到agent。")
        yield from self.agent_service.execute_stream(query, session_id)

    def _decide_route(self, query: str, session_id: str) -> ChatRouteDecision:
        if self.intent_router is None:
            return ChatRouteDecision()

        decision = self.intent_router.decide(query, session_id)
        if isinstance(decision, ChatRouteDecision):
            return decision
        return ChatRouteDecision(
            route=getattr(decision, "route", "faq_first"),
            category=getattr(decision, "category", None),
            metadata=getattr(decision, "metadata", {}) or {},
        )

    def _retrieve_faq_hit(self, query: str, category: str | None, session_id: str):
        try:
            response = self.faq_service.retrieve(query, top_k=self.faq_top_k, category=category)
        except Exception as e:
            logger.warning(f"[聊天路由]session={session_id} FAQ检索失败，fallback到agent。reason={e}")
            return None
  
        if not response:
            logger.info(f"[聊天路由]session={session_id} FAQ无候选结果。")
            return None

        candidate = response[0]
        if self._is_faq_hit(query, candidate):
            return candidate

        logger.info(
            "[聊天路由]session="
            f"{session_id} FAQ候选低于直出阈值 faq_id={self._field(candidate, 'faq_id', '-')} "
            f"score={self._field(candidate, 'score', '-')} matched_question={self._field(candidate, 'matched_question', '')!r}"
        )
        return None

    def _is_faq_hit(self, query: str, result) -> bool:
        if not (self._field(result, "answer", "") or "").strip():
            return False

        score = float(self._field(result, "score", 0.0) or 0.0)
        normalized_query = self._normalize_question(query)
        matched_question = self._normalize_question(self._field(result, "matched_question", ""))
        standard_question = self._normalize_question(self._field(result, "question", ""))
        is_exact_match = normalized_query in {matched_question, standard_question}
        if is_exact_match and score >= self.faq_exact_match_threshold:
            return True

        sources = set(self._field(result, "sources", []) or [])
        return {"bm25", "vector"}.issubset(sources) and score >= self.faq_score_threshold

    def _faq_hit_stream(
        self,
        query: str,
        session_id: str,
        faq_hit,
        decision: ChatRouteDecision,
    ):
        seq = 0
        answer = (self._field(faq_hit, "answer", "") or "").strip()
        metadata = self._faq_metadata(faq_hit, decision)

        def event(event_type: str, **payload):
            nonlocal seq
            seq += 1
            return {
                "type": event_type,
                "session_id": session_id,
                "seq": seq,
                **payload,
            }

        yield event("thinking", role="assistant", content="已命中常见问题，正在返回答案。", metadata=metadata)
        yield event("input", role="user", content=query, metadata={"route": "faq"})
        yield event("output_delta", role="assistant", content=answer, metadata=metadata)
        yield event("output", role="assistant", content=answer, metadata=metadata)
        yield event("done", role="assistant", metadata=metadata)

    def _faq_metadata(self, faq_hit, decision: ChatRouteDecision) -> dict[str, Any]:
        metadata = {
            "route": "faq",
            "intent_route": decision.route,
            "faq_id": self._field(faq_hit, "faq_id"),
            "question": self._field(faq_hit, "question"),
            "category": self._field(faq_hit, "category"),
            "score": self._field(faq_hit, "score"),
            "sources": self._field(faq_hit, "sources", []),
            "matched_question": self._field(faq_hit, "matched_question"),
            "matched_doc_type": self._field(faq_hit, "matched_doc_type"),
            "matched_doc_id": self._field(faq_hit, "matched_doc_id"),
        }
        if decision.metadata:
            metadata["decision"] = decision.metadata
        return {key: value for key, value in metadata.items() if value is not None}

    @staticmethod
    def _field(value, key: str, default=None):
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    @staticmethod
    def _normalize_question(value: str) -> str:
        return "".join((value or "").strip().lower().split())
