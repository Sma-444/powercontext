"""服务层：把 seekdb、PowerContext、检索、作答装配成一个对象。

CLI 和 Web 走同一条路径，避免「命令行能跑、网页跑的是另一套逻辑」。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from duban.answer import Answer, build_answer
from duban.config import Settings
from duban.corpus import load_corpus
from duban.memory import Memory, MemorySnapshot
from duban.retrieve import Retriever, Retrieval
from duban.review import build_review
from duban.store import CorpusStore, SyncReport


@asynccontextmanager
async def open_runtime(settings: Settings):
    """打开 PowerContext 的内嵌运行时（seekdb 由它管理）。"""

    from powercontext.builtin.persistence.seekdb import SeekDBConfig
    from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts

    settings.ensure_dirs()
    config = BuiltinConfig(database=SeekDBConfig(path=settings.database))
    async with open_builtin_contexts(config) as contexts:
        yield Duban(contexts, settings)


@dataclass
class AskResult:
    answer: Answer
    retrieval: Retrieval
    snapshot: MemorySnapshot

    def as_dict(self) -> dict[str, object]:
        return {
            "answer": self.answer.as_dict(),
            "retrieval": {
                "candidates": self.retrieval.candidates,
                "variants": self.retrieval.variants,
                "terms": self.retrieval.terms[:16],
                "weak_terms": self.retrieval.weak_terms,
            },
            "memory": self.snapshot.as_dict(),
        }


class Duban:
    def __init__(self, contexts, settings: Settings) -> None:
        self.contexts = contexts
        self.settings = settings
        self.store = CorpusStore(contexts.database, settings.query_log)
        self.memory = Memory(contexts, settings.scope, settings.memory_log, settings.user)
        self.retriever = Retriever(self.store, top_k=settings.top_k, candidates=settings.candidates)
        self.last_skipped: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ ingest

    async def init(self) -> None:
        await self.store.ensure_schema()

    async def ingest(self, *, force: bool = False) -> SyncReport:
        report = load_corpus(self.settings.corpus, max_chars=self.settings.max_chars)
        await self.store.ensure_schema()
        sync = await self.store.sync(report.documents, force=force)
        self.last_skipped = report.skipped
        return sync

    # --------------------------------------------------------------------- ask

    async def ask(self, question: str, *, remember: bool = True) -> AskResult:
        snapshot = await self.memory.snapshot()
        retrieval = await self.retriever.search(question, snapshot)
        answer = build_answer(question, retrieval, snapshot)
        if remember and question.strip():
            await self.memory.record_turn(
                question,
                citations=[citation.citation for citation in answer.citations],
                docs=[hit.doc_id for hit in retrieval.hits],
            )
        return AskResult(answer=answer, retrieval=retrieval, snapshot=snapshot)

    # ------------------------------------------------------------------ memory

    async def mark_weak(self, term: str, note: str = "", source: str = "") -> dict[str, object]:
        return await self.memory.mark_weak(term.strip(), note=note, source=source)

    async def unmark_weak(self, term: str) -> None:
        """PowerContext 的 artifact 只追加，所以「划掉」记一条空 note 的覆盖记录。"""

        await self.memory.mark_weak(term.strip(), note="", source="resolved")

    async def set_profile(self, **changes: object) -> dict[str, object]:
        return await self.memory.update_profile(**changes)

    async def touch(self, doc_id: str, *, page: int, anchor: str, ratio: float) -> dict[str, object]:
        return await self.memory.record_progress(doc_id, page=page, anchor=anchor, ratio=ratio)

    # ------------------------------------------------------------------- state

    async def state(self) -> dict[str, object]:
        documents = await self.store.documents()
        snapshot = await self.memory.snapshot()
        stats = await self.store.stats()
        review = build_review(snapshot, documents)
        enriched = []
        for document in documents:
            progress = snapshot.progress.get(str(document["doc_id"]))
            enriched.append(
                {
                    **document,
                    "progress": progress.as_dict() if progress else None,
                }
            )
        return {
            "user": self.settings.user,
            "scope": self.settings.scope,
            "documents": enriched,
            "memory": snapshot.as_dict(),
            "review": [item.as_dict() for item in review],
            "stats": {
                **stats,
                "weak": len(snapshot.weak),
                "turns": len(snapshot.turns),
            },
            "corpus": str(self.settings.corpus),
        }

    async def page(self, doc_id: str, page: int) -> dict[str, object]:
        if page:
            chunks = await self.store.page_text(doc_id, page)
        else:
            chunks = await self.store.chunks_of(doc_id)
        return {
            "doc_id": doc_id,
            "page": page,
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "anchor": chunk.anchor,
                    "location": chunk.location,
                    "body": chunk.body,
                    "section": chunk.section,
                }
                for chunk in chunks
            ],
        }

    async def resolve(self, doc_id: str, anchor: str) -> dict[str, object]:
        """把 ``path#anchor`` 还原成原文片段（引用点击用）。"""

        page = 0
        if anchor.startswith("p"):
            digits = anchor[1:].split("-")[0]
            page = int(digits) if digits.isdigit() else 0
        if page:
            chunks = await self.store.page_text(doc_id, page)
        else:
            chunks = await self.store.chunks_of(doc_id)
        chosen = next((chunk for chunk in chunks if chunk.anchor == anchor), None)
        return {
            "doc_id": doc_id,
            "anchor": anchor,
            "found": chosen is not None,
            "body": chosen.body if chosen else "",
            "location": chosen.location if chosen else "",
            "page": chosen.page if chosen else page,
        }


def documents_summary(path: Path) -> list[tuple[str, str]]:
    report = load_corpus(path)
    return [(document.doc_id, document.title) for document in report.documents]
