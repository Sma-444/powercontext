"""PowerContext 里的「关于你的记忆」。

四类 artifact，都是只追加、不覆盖，所以进程重启或写到一半崩溃都不会毁掉历史：

``duban.profile``   阅读偏好（解释深度、语言、关注方向），取最大 ``seq``
``duban.weak``      薄弱点（用户标记「没看懂」的概念），读取时按 term 去重计数
``duban.progress``  每篇资料读到哪一页，取每篇的最大 ``seq``
``duban.turn``      每次问答的摘要，用来做「上次你问到哪」

这些记忆不是装饰：``retrieve`` 用薄弱点做补正召回、``answer`` 用偏好决定给几条要点、
``review`` 用薄弱点 + 未读页生成复习清单。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PROFILE = "duban.profile"
WEAK = "duban.weak"
PROGRESS = "duban.progress"
TURN = "duban.turn"

DEFAULT_PROFILE = {
    "depth": "standard",  # brief | standard | deep
    "language": "zh",
    "interests": [],
    "note": "",
}


@dataclass
class WeakPoint:
    term: str
    note: str
    seq: int
    count: int = 1
    source: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"term": self.term, "note": self.note, "seq": self.seq, "count": self.count, "source": self.source}


@dataclass
class Progress:
    doc_id: str
    page: int
    anchor: str
    ratio: float
    seq: int
    read_at: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "page": self.page,
            "anchor": self.anchor,
            "ratio": round(self.ratio, 3),
            "seq": self.seq,
            "read_at": self.read_at,
        }


@dataclass
class Turn:
    question: str
    citations: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    seq: int = 0
    asked_at: str = ""


@dataclass
class MemorySnapshot:
    profile: dict[str, object]
    weak: list[WeakPoint]
    progress: dict[str, Progress]
    turns: list[Turn]
    artifact_ids: list[str]

    def weak_terms(self) -> list[str]:
        return [item.term for item in self.weak]

    def last_turn(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    def as_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "weak": [item.as_dict() for item in self.weak],
            "progress": [item.as_dict() for item in self.progress.values()],
            "turns": [
                {"question": turn.question, "citations": turn.citations, "docs": turn.docs, "seq": turn.seq}
                for turn in self.turns[-8:]
            ],
            "artifact_ids": self.artifact_ids,
        }


class Memory:
    """把画像 / 薄弱点 / 进度 / 会话读写到 PowerContext。"""

    def __init__(self, contexts, scope: str, log_path: Path, user: str) -> None:
        self.contexts = contexts
        self.scope = scope
        self.log_path = log_path
        self.user = user
        self._app = contexts.atomic_memory.for_scope(scope)

    # ------------------------------------------------------------------ write

    async def _append(self, kind: str, payload: dict[str, object], *, op: str) -> str:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        created = await self.contexts.records.create_atomic_memories(
            self.scope,
            ({ "kind": kind, "text": text, "description": f"{op} {payload.get('seq')}" },),
        )
        artifact_id = created[0].artifact_id if created else ""
        self._log(
            {
                "op": op,
                "kind": kind,
                "scope": self.scope,
                "artifact_id": artifact_id,
                "seq": payload.get("seq"),
                "payload": payload,
            }
        )
        return artifact_id

    async def update_profile(self, **changes: object) -> dict[str, object]:
        snapshot = await self.snapshot()
        profile = dict(snapshot.profile)
        profile.update(changes)
        profile["seq"] = int(profile.get("seq") or 0) + 1
        profile["updated_at"] = _now()
        await self._append(PROFILE, profile, op="profile")
        return profile

    async def mark_weak(self, term: str, *, note: str = "", source: str = "") -> dict[str, object]:
        snapshot = await self.snapshot()
        previous = next((item for item in snapshot.weak if item.term == term), None)
        payload = {
            "seq": _next_seq(snapshot.weak),
            "term": term,
            "note": note or (previous.note if previous else ""),
            "source": source or (previous.source if previous else ""),
            "marked_at": _now(),
        }
        await self._append(WEAK, payload, op="weak")
        return payload

    async def record_progress(
        self, doc_id: str, *, page: int, anchor: str, ratio: float
    ) -> dict[str, object]:
        snapshot = await self.snapshot()
        current = snapshot.progress.get(doc_id)
        payload = {
            "seq": _next_seq(snapshot.progress.values()),
            "doc_id": doc_id,
            "page": page,
            "anchor": anchor,
            "ratio": max(0.0, min(1.0, ratio)),
            "read_at": _now(),
            "previous_seq": current.seq if current else None,
        }
        await self._append(PROGRESS, payload, op="progress")
        return payload

    async def record_turn(self, question: str, *, citations: list[str], docs: list[str]) -> dict[str, object]:
        snapshot = await self.snapshot()
        payload = {
            "seq": _next_seq(snapshot.turns),
            "question": question,
            "citations": citations,
            "docs": docs,
            "asked_at": _now(),
        }
        await self._append(TURN, payload, op="turn")
        return payload

    # ------------------------------------------------------------------- read

    async def snapshot(self) -> MemorySnapshot:
        profile_items = await self._items(PROFILE)
        weak_items = await self._items(WEAK)
        progress_items = await self._items(PROGRESS)
        turn_items = await self._items(TURN)

        profile = dict(DEFAULT_PROFILE)
        for payload in profile_items:
            profile.update({key: value for key, value in payload.items() if key != "seq"})
            profile["seq"] = int(payload.get("seq") or 0)

        weak: dict[str, WeakPoint] = {}
        for payload in sorted(weak_items, key=lambda item: int(item.get("seq") or 0)):
            term = str(payload.get("term") or "").strip()
            if not term:
                continue
            entry = weak.get(term)
            if entry is None:
                weak[term] = WeakPoint(
                    term=term,
                    note=str(payload.get("note") or ""),
                    seq=int(payload.get("seq") or 0),
                    count=1,
                    source=str(payload.get("source") or ""),
                )
            else:
                entry.count += 1
                entry.seq = int(payload.get("seq") or entry.seq)
                entry.note = str(payload.get("note") or entry.note)

        progress: dict[str, Progress] = {}
        for payload in sorted(progress_items, key=lambda item: int(item.get("seq") or 0)):
            doc_id = str(payload.get("doc_id") or "")
            if not doc_id:
                continue
            progress[doc_id] = Progress(
                doc_id=doc_id,
                page=int(payload.get("page") or 0),
                anchor=str(payload.get("anchor") or ""),
                ratio=float(payload.get("ratio") or 0.0),
                seq=int(payload.get("seq") or 0),
                read_at=str(payload.get("read_at") or ""),
            )

        turns = [
            Turn(
                question=str(payload.get("question") or ""),
                citations=[str(item) for item in payload.get("citations") or []],
                docs=[str(item) for item in payload.get("docs") or []],
                seq=int(payload.get("seq") or 0),
                asked_at=str(payload.get("asked_at") or ""),
            )
            for payload in sorted(turn_items, key=lambda item: int(item.get("seq") or 0))
        ]

        artifact_ids = [item["artifact_id"] for item in self._log_entries(limit=12)]
        return MemorySnapshot(
            profile=profile,
            weak=sorted(weak.values(), key=lambda item: (-item.count, item.term)),
            progress=progress,
            turns=turns,
            artifact_ids=artifact_ids,
        )

    async def _items(self, kind: str) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            page = await self._app.list(kind=kind, limit=100, cursor=cursor)
            for item in page.items:
                text = getattr(item.artifact.content, "text", "")
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    payloads.append(payload)
            cursor = getattr(page, "next_cursor", None)
            if not cursor:
                break
        return payloads

    # ----------------------------------------------------------------- logging

    def _log(self, entry: dict[str, object]) -> None:
        record = {"ts": _now(), "scope": self.scope, "user": self.user, **entry}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _log_entries(self, *, limit: int = 20) -> list[dict[str, object]]:
        if not self.log_path.is_file():
            return []
        entries: list[dict[str, object]] = []
        with self.log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _next_seq(items) -> int:
    values = [int(getattr(item, "seq", 0) or 0) for item in items]
    return (max(values) + 1) if values else 1
