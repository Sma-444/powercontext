"""seekdb 里的事实索引。

两张表：``duban_documents``（一篇资料一行）与 ``duban_chunks``（一个片段一行）。
``duban_chunks.searchable`` 上建 ``WITH PARSER NGRAM`` 的全文索引 —— seekdb 自带的
NGRAM 解析器能直接处理中文（默认 2 字切分），不需要外部分词服务，也不需要
额外部署数据库：PowerContext 的嵌入式 seekdb 就是这个索引的载体。

每一条 SQL 都追加到 ``records/db/queries.jsonl``，评审可以据此核对
「检索结果」到底是哪条语句、什么参数、返回几行。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from duban.corpus import Chunk, Document

DOCUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS duban_documents (
    doc_id      VARCHAR(200) NOT NULL,
    path        VARCHAR(255) NOT NULL,
    title       VARCHAR(255) NOT NULL,
    kind        VARCHAR(8)   NOT NULL,
    revision    VARCHAR(16)  NOT NULL,
    page_count  INT          NOT NULL,
    chunk_count INT          NOT NULL,
    chars       INT          NOT NULL,
    ingested_at VARCHAR(32)  NOT NULL,
    PRIMARY KEY (doc_id)
)
"""

CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS duban_chunks (
    chunk_id   VARCHAR(220) NOT NULL,
    doc_id     VARCHAR(200) NOT NULL,
    doc_title  VARCHAR(255) NOT NULL,
    path       VARCHAR(255) NOT NULL,
    kind       VARCHAR(8)   NOT NULL,
    anchor     VARCHAR(32)  NOT NULL,
    page       INT          NOT NULL,
    section    VARCHAR(255) NOT NULL,
    ordinal    INT          NOT NULL,
    line_start INT          NOT NULL,
    line_end   INT          NOT NULL,
    char_start INT          NOT NULL,
    char_end   INT          NOT NULL,
    body       LONGTEXT     NOT NULL,
    searchable LONGTEXT     NOT NULL,
    PRIMARY KEY (chunk_id)
)
"""

FTS_DDL = "CREATE FULLTEXT INDEX duban_chunks_fts ON duban_chunks (searchable) WITH PARSER NGRAM"
DOC_INDEX_DDL = "CREATE INDEX duban_chunks_doc ON duban_chunks (doc_id, page, ordinal)"

SEARCH_SQL = (
    "SELECT chunk_id, doc_id, doc_title, path, kind, anchor, page, section, ordinal, "
    "line_start, line_end, body, MATCH(searchable) AGAINST (:query) AS score "
    "FROM duban_chunks WHERE MATCH(searchable) AGAINST (:query)"
)


@dataclass(frozen=True)
class Hit:
    """一条检索结果。"""

    chunk_id: str
    doc_id: str
    doc_title: str
    path: str
    kind: str
    anchor: str
    page: int
    section: str
    ordinal: int
    line_start: int
    line_end: int
    body: str
    score: float = 0.0

    @property
    def citation(self) -> str:
        return f"{self.path}#{self.anchor}"

    @property
    def location(self) -> str:
        if self.page:
            return f"{self.path} 第 {self.page} 页"
        return f"{self.path} 第 {self.line_start}-{self.line_end} 行"


@dataclass(frozen=True)
class SyncReport:
    documents: int
    inserted: int
    unchanged: int
    removed: int
    chunks: int


class CorpusStore:
    """建表、增量入库、全文检索。"""

    def __init__(self, database, log_path: Path) -> None:
        self.database = database
        self.log_path = log_path

    # ------------------------------------------------------------------ schema

    async def ensure_schema(self) -> None:
        async with self.database.transaction() as connection:
            await connection.execute(text(DOCUMENTS_DDL))
            await connection.execute(text(CHUNKS_DDL))
            for statement in (DOC_INDEX_DDL, FTS_DDL):
                try:
                    await connection.execute(text(statement))
                except SQLAlchemyError as error:
                    message = str(error).lower()
                    if "duplicate" not in message and "already exists" not in message:
                        raise
            await self._log(connection, "ensure_schema", None, 0, started=time.perf_counter())

    async def drop_all(self) -> None:
        async with self.database.transaction() as connection:
            for statement in (
                "DROP TABLE IF EXISTS duban_chunks",
                "DROP TABLE IF EXISTS duban_documents",
            ):
                await connection.execute(text(statement))

    # --------------------------------------------------------------- ingestion

    async def sync(self, documents: list[Document], *, force: bool = False) -> SyncReport:
        """让索引与磁盘上的资料对齐：只重写变化的文件。"""

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with self.database.transaction() as connection:
            if force:
                await connection.execute(text("DELETE FROM duban_chunks"))
                await connection.execute(text("DELETE FROM duban_documents"))
            existing = {
                row["doc_id"]: row["revision"]
                for row in (
                    await connection.execute(text("SELECT doc_id, revision FROM duban_documents"))
                ).mappings()
            }
            incoming = {document.doc_id: document for document in documents}
            removed = [doc_id for doc_id in existing if doc_id not in incoming]
            changed = [doc for doc in documents if existing.get(doc.doc_id) != doc.revision]
            for doc_id in removed:
                await self._delete_document(connection, doc_id)
            for document in changed:
                await self._delete_document(connection, document.doc_id)
                await connection.execute(
                    text(
                        "INSERT INTO duban_documents "
                        "(doc_id, path, title, kind, revision, page_count, chunk_count, chars, ingested_at) "
                        "VALUES (:doc_id, :path, :title, :kind, :revision, :page_count, :chunk_count, :chars, :now)"
                    ),
                    {
                        "doc_id": document.doc_id,
                        "path": document.doc_id + ("." + document.kind if document.kind != "md" else ".md"),
                        "title": document.title,
                        "kind": document.kind,
                        "revision": document.revision,
                        "page_count": document.page_count,
                        "chunk_count": len(document.chunks),
                        "chars": document.chars,
                        "now": now,
                    },
                )
                for chunk in document.chunks:
                    await self._insert_chunk(connection, chunk)
            total = (await connection.execute(text("SELECT COUNT(*) FROM duban_chunks"))).scalar()
        return SyncReport(
            documents=len(documents),
            inserted=len(changed),
            unchanged=len(documents) - len(changed),
            removed=len(removed),
            chunks=int(total or 0),
        )

    async def _delete_document(self, connection, doc_id: str) -> None:
        await connection.execute(text("DELETE FROM duban_chunks WHERE doc_id = :doc_id"), {"doc_id": doc_id})
        await connection.execute(text("DELETE FROM duban_documents WHERE doc_id = :doc_id"), {"doc_id": doc_id})

    async def _insert_chunk(self, connection, chunk: Chunk) -> None:
        await connection.execute(
            text(
                "INSERT INTO duban_chunks "
                "(chunk_id, doc_id, doc_title, path, kind, anchor, page, section, ordinal, "
                " line_start, line_end, char_start, char_end, body, searchable) "
                "VALUES (:chunk_id, :doc_id, :doc_title, :path, :kind, :anchor, :page, :section, :ordinal, "
                " :line_start, :line_end, :char_start, :char_end, :body, :searchable)"
            ),
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "doc_title": chunk.doc_title,
                "path": chunk.path,
                "kind": chunk.kind,
                "anchor": chunk.anchor,
                "page": chunk.page,
                "section": chunk.section,
                "ordinal": chunk.ordinal,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "body": chunk.body,
                "searchable": chunk.searchable(),
            },
        )

    # --------------------------------------------------------------- retrieval

    async def search(
        self, query: str, *, limit: int, doc_ids: tuple[str, ...] = ()
    ) -> list[Hit]:
        """一条 ``MATCH … AGAINST`` 语句拿到候选（分数由 seekdb 计算）。"""

        if not query.strip() or limit <= 0:
            return []
        params: dict[str, object] = {"query": query, "limit": limit}
        sql = SEARCH_SQL
        if doc_ids:
            placeholders = ", ".join(f":doc{index}" for index in range(len(doc_ids)))
            sql += f" AND doc_id IN ({placeholders})"
            params.update({f"doc{index}": doc_id for index, doc_id in enumerate(doc_ids)})
        sql += " ORDER BY score DESC, chunk_id LIMIT :limit"
        started = time.perf_counter()
        async with self.database.transaction() as connection:
            rows = (await connection.execute(text(sql), params)).mappings().all()
            await self._log(connection, "search", sql, len(rows), started=started, params=params)
        return [_hit(row) for row in rows]

    async def page_text(self, doc_id: str, page: int) -> list[Hit]:
        sql = (
            "SELECT chunk_id, doc_id, doc_title, path, kind, anchor, page, section, ordinal, "
            "line_start, line_end, body, 0.0 AS score FROM duban_chunks "
            "WHERE doc_id = :doc_id AND page = :page ORDER BY ordinal"
        )
        started = time.perf_counter()
        async with self.database.transaction() as connection:
            rows = (
                (await connection.execute(text(sql), {"doc_id": doc_id, "page": page})).mappings().all()
            )
            await self._log(connection, "page_text", sql, len(rows), started=started)
        return [_hit(row) for row in rows]

    async def chunks_of(self, doc_id: str) -> list[Hit]:
        sql = (
            "SELECT chunk_id, doc_id, doc_title, path, kind, anchor, page, section, ordinal, "
            "line_start, line_end, body, 0.0 AS score FROM duban_chunks "
            "WHERE doc_id = :doc_id ORDER BY ordinal"
        )
        async with self.database.transaction() as connection:
            rows = (await connection.execute(text(sql), {"doc_id": doc_id})).mappings().all()
        return [_hit(row) for row in rows]

    async def all_chunks(self) -> list[Hit]:
        """取全部片段（用于 IDF 统计与引用核对，不参与排序）。"""

        sql = (
            "SELECT chunk_id, doc_id, doc_title, path, kind, anchor, page, section, ordinal, "
            "line_start, line_end, body, 0.0 AS score FROM duban_chunks ORDER BY chunk_id"
        )
        async with self.database.transaction() as connection:
            rows = (await connection.execute(text(sql))).mappings().all()
        return [_hit(row) for row in rows]

    async def documents(self) -> list[dict[str, object]]:
        sql = (
            "SELECT doc_id, path, title, kind, revision, page_count, chunk_count, chars, ingested_at "
            "FROM duban_documents ORDER BY doc_id"
        )
        async with self.database.transaction() as connection:
            rows = (await connection.execute(text(sql))).mappings().all()
        return [dict(row) for row in rows]

    async def stats(self) -> dict[str, int]:
        async with self.database.transaction() as connection:
            documents = (await connection.execute(text("SELECT COUNT(*) FROM duban_documents"))).scalar()
            chunks = (await connection.execute(text("SELECT COUNT(*) FROM duban_chunks"))).scalar()
        return {"documents": int(documents or 0), "chunks": int(chunks or 0)}

    # ----------------------------------------------------------------- logging

    async def _log(
        self,
        connection,
        operation: str,
        sql: str | None,
        rows: int,
        *,
        started: float,
        params: dict[str, object] | None = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "operation": operation,
            "sql": " ".join(sql.split()) if sql else None,
            "params": params,
            "rows": rows,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _hit(row) -> Hit:
    return Hit(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        doc_title=row["doc_title"],
        path=row["path"],
        kind=row["kind"],
        anchor=row["anchor"],
        page=int(row["page"]),
        section=row["section"] or "",
        ordinal=int(row["ordinal"]),
        line_start=int(row["line_start"]),
        line_end=int(row["line_end"]),
        body=row["body"],
        score=float(row["score"] or 0.0),
    )
