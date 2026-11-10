from __future__ import annotations

import hashlib
from contextlib import contextmanager
from threading import Lock
from typing import NamedTuple

from langgraph.types import Command

from .store import DecisionConflict, Store


class Principal(NamedTuple):
    name: str
    project: str
    role: str


class ReviewConflict(Exception):
    pass


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:32]


class ReviewService:
    def __init__(self, graph, store: Store) -> None:
        self.graph = graph
        self.store = store
        self._gate = Lock()
        self._running: set[str] = set()

    @staticmethod
    def config(review_id: str) -> dict:
        return {"configurable": {"thread_id": review_id}}

    @contextmanager
    def _lock(self, review_id: str):
        with self._gate:
            if review_id in self._running:
                raise ReviewConflict("该复盘正在处理，请用同一请求编号重试")
            self._running.add(review_id)
        try:
            yield
        finally:
            with self._gate:
                self._running.remove(review_id)

    @staticmethod
    def _visible(snapshot, principal: Principal) -> bool:
        state = snapshot.values
        return bool(state and state["project"] == principal.project
                    and (state["requester"] == principal.name or principal.role == "reviewer"))

    def get(self, review_id: str, principal: Principal) -> dict:
        snapshot = self.graph.get_state(self.config(review_id))
        if not self._visible(snapshot, principal):
            raise LookupError(review_id)
        return self._public(snapshot, review_id)

    def _public(self, snapshot, review_id: str) -> dict:
        state = snapshot.values
        return {
            "review_id": review_id,
            "turn_id": state["turn_id"],
            "result": state.get("result") or None,
            "proposal": state.get("proposal"),
            "evidence": state.get("evidence", []),
            "status": "pending_approval" if snapshot.interrupts
                      else "running" if snapshot.next else "complete",
            "usage": self.store.usage(review_id),
        }

    def _events(self, payload, config: dict):
        review_id = config["configurable"]["thread_id"]
        yield "review", {"review_id": review_id}
        if payload is not False:
            for event in self.graph.stream(payload, config, stream_mode="updates",
                                           durability="sync"):
                for node in event:
                    if node != "__interrupt__":
                        yield "step", {"node": node}
        snapshot = self.graph.get_state(config)
        result = self._public(snapshot, review_id)
        if result["status"] == "pending_approval":
            yield "approval", result["proposal"]
        yield "result", result

    def turn(self, review_id: str, principal: Principal, request_id: str, question: str,
             rerun: bool, *, create: bool):
        config = self.config(review_id)
        turn_id = stable_id(review_id, request_id)
        with self._lock(review_id):
            snapshot = self.graph.get_state(config)
            if snapshot.values:
                if not self._visible(snapshot, principal) or principal.role != "analyst":
                    raise LookupError(review_id)
                previous = snapshot.values
                if previous["turn_id"] == turn_id:
                    if (previous["question"], previous["request_rerun"]) != (question, rerun):
                        raise ReviewConflict("请求编号已用于其他内容")
                    yield from self._events(
                        None if snapshot.next and not snapshot.interrupts else False, config
                    )
                    return
                if create:
                    # An old create retry after a follow-up must never become a new turn.
                    raise ReviewConflict("该复盘已存在，请读取当前状态")
                if snapshot.next:
                    raise ReviewConflict("请先完成当前一轮或处理待审批申请")
                seen = previous.get("seen_turns", [])
                if turn_id in seen:
                    raise ReviewConflict("该轮次已经处理")
                if len(seen) >= 40:
                    raise ReviewConflict("此复盘已到轮次上限，请新建复盘")
            elif not create:
                raise LookupError(review_id)
            else:
                seen = []
            yield from self._events({
                "review_id": review_id, "turn_id": turn_id, "project": principal.project,
                "requester": principal.name, "question": question, "request_rerun": rerun,
                "seen_turns": [*seen, turn_id],
            }, config)

    def decide(self, review_id: str, principal: Principal, proposal_id: str, approve: bool,
               reason: str):
        if principal.role != "reviewer":
            raise PermissionError("需要审批员身份")
        config = self.config(review_id)
        with self._lock(review_id):
            snapshot = self.graph.get_state(config)
            if not self._visible(snapshot, principal):
                raise LookupError(review_id)
            if snapshot.next and not snapshot.interrupts:
                self.graph.invoke(None, config, durability="sync")
                snapshot = self.graph.get_state(config)
            proposal = snapshot.values.get("proposal")
            if not proposal or proposal["proposal_id"] != proposal_id:
                raise LookupError(proposal_id)
            if not snapshot.interrupts:
                expected = "approved" if approve else "rejected"
                if (proposal["state"], proposal["reviewer"], proposal["reason"]) != (
                    expected, principal.name, reason
                ):
                    raise DecisionConflict("申请已有决策或当前状态不可审批")
                yield from self._events(False, config)
                return
            yield from self._events(Command(resume={
                "reviewer": principal.name, "approve": approve, "reason": reason,
            }), config)
