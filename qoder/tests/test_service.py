"""检索、记忆、服务层的集成测试（每个用例独立临时库）。"""

from __future__ import annotations

import asyncio

from duban.config import Settings
from duban.service import open_runtime


def test_ingest_and_answer(settings: Settings) -> None:
    async def main() -> None:
        async with open_runtime(settings) as app:
            await app.init()
            report = await app.ingest()
            assert report.documents == 2
            assert report.chunks > 0

            result = await app.ask("随机化超时是为了避免什么", remember=False)
            assert result.retrieval.hits, "应当检索到片段"
            assert result.answer.citations, "回答必须带引用"
            assert result.answer.citations[0].doc_id == "notes/raft"
            assert "随机" in result.answer.citations[0].snippet

    asyncio.run(main())


def test_every_citation_resolves(settings: Settings) -> None:
    async def main() -> None:
        async with open_runtime(settings) as app:
            await app.init()
            await app.ingest()
            result = await app.ask("向量时钟怎么判断并发", remember=False)
            known = {chunk.chunk_id for chunk in await app.store.all_chunks()}
            assert result.answer.citations
            assert all(citation.chunk_id in known for citation in result.answer.citations)
            resolved = await app.resolve(result.answer.citations[0].doc_id, result.answer.citations[0].anchor)
            assert resolved["found"] is True
            assert resolved["body"]

    asyncio.run(main())


def test_memory_survives_reopen(settings: Settings) -> None:
    async def write() -> None:
        async with open_runtime(settings) as app:
            await app.init()
            await app.ingest()
            await app.mark_weak("CAP", note="分不清取舍")
            await app.mark_weak("CAP", note="还是没懂")
            await app.mark_weak("sloppy quorum")
            await app.set_profile(depth="deep")
            await app.touch("notes/dynamo", page=2, anchor="L1-10", ratio=0.5)

    async def read() -> dict:
        async with open_runtime(settings) as app:
            await app.init()
            return await app.state()

    asyncio.run(write())
    state = asyncio.run(read())
    memory = state["memory"]
    terms = {item["term"]: item["count"] for item in memory["weak"]}
    assert terms["CAP"] == 2, "同一概念标记两次应当累加而不是产生两条"
    assert "sloppy quorum" in terms
    assert memory["profile"]["depth"] == "deep"
    progress = {item["doc_id"]: item for item in memory["progress"]}
    assert progress["notes/dynamo"]["ratio"] == 0.5
    assert state["review"], "有薄弱点与进度之后，复习清单不应为空"


def test_weak_point_triggers_primer(settings: Settings) -> None:
    async def main() -> None:
        async with open_runtime(settings) as app:
            await app.init()
            await app.ingest()
            await app.mark_weak("CAP")
            result = await app.ask("CAP 定理限制了什么", remember=False)
            assert result.retrieval.weak_terms, "问题里出现薄弱点时应当命中"
            assert result.answer.primer is not None, "应当补一条基础说明"
            assert "没看懂" in result.answer.memory_note

    asyncio.run(main())


def test_incremental_ingest_skips_unchanged(settings: Settings) -> None:
    async def main() -> None:
        async with open_runtime(settings) as app:
            await app.init()
            first = await app.ingest()
            second = await app.ingest()
            assert first.inserted == 2
            assert second.inserted == 0 and second.unchanged == 2
            forced = await app.ingest(force=True)
            assert forced.inserted == 2

    asyncio.run(main())
