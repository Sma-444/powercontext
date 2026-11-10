"""复习清单：把「记忆」变成可执行的三件事。

1. 你标记过没看懂、但还没弄懂的概念；
2. 没读完的资料（按剩余比例排序）；
3. 还没碰过的资料（最多 3 篇，避免堆一屏）。

每条都带一个可点击的动作（去问 / 继续读），前端直接渲染，不需要额外文案。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from duban.memory import MemorySnapshot


@dataclass
class ReviewItem:
    kind: str  # weak | unfinished | unread
    title: str
    detail: str
    action: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "title": self.title, "detail": self.detail, "action": self.action}


def build_review(
    snapshot: MemorySnapshot, documents: list[dict[str, object]], *, unread_limit: int = 3
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for weak in snapshot.weak:
        items.append(
            ReviewItem(
                kind="weak",
                title=weak.term,
                detail=(weak.note or f"已标记 {weak.count} 次，仍待复习"),
                action={"type": "ask", "question": f"{weak.term} 到底是什么？用最基础的说法解释"},
            )
        )

    by_id = {str(document["doc_id"]): document for document in documents}
    progress = snapshot.progress
    unfinished: list[tuple[float, str]] = []
    for doc_id, item in progress.items():
        if item.ratio < 0.99 and doc_id in by_id:
            unfinished.append((item.ratio, doc_id))
    for ratio, doc_id in sorted(unfinished):
        document = by_id[doc_id]
        page = int(document.get("page_count") or 0)
        stop = progress[doc_id].page
        items.append(
            ReviewItem(
                kind="unfinished",
                title=str(document["title"]),
                detail=f"读到 {stop}/{page} 页" if page else f"已读 {int(ratio * 100)}%",
                action={"type": "open", "doc_id": doc_id, "page": stop},
            )
        )

    untouched = [doc for doc_id, doc in by_id.items() if doc_id not in progress]
    untouched.sort(key=lambda doc: int(doc.get("chunk_count") or 0))
    for document in untouched[:unread_limit]:
        items.append(
            ReviewItem(
                kind="unread",
                title=str(document["title"]),
                detail=f"还没开始读 · {document.get('chunk_count')} 段",
                action={"type": "open", "doc_id": str(document["doc_id"]), "page": 0},
            )
        )
    return items
