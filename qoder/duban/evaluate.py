"""标注集跑分：把「检索有没有用」变成可复现的数字。

``corpus/eval/questions.yaml`` 里每题标了「答案在哪一篇的哪一页 / 哪一节」，
跑分输出四组指标，写进 ``records/eval/report.md``：

* ``Hit@1/3/5``：正确页是否落在前 k 条引用里
* ``MRR``：第一条正确结果的平均倒数排名
* ``must_include``：抽取式回答是否覆盖了人工标注的关键词
* ``citation_valid``：返回的每一条引用是否都真实存在（应当恒为 1.0）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from duban.answer import build_answer
from duban.retrieve import Retriever
from duban.store import CorpusStore


@dataclass
class Outcome:
    question_id: str
    question: str
    expected: str
    rank: int | None
    hits: list[str]
    coverage: bool
    citation_valid: bool


def load_questions(path: Path) -> list[dict[str, object]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        items = payload.get("questions") or []
    else:
        items = payload or []
    return [dict(item) for item in items]


async def evaluate(
    store: CorpusStore,
    questions: list[dict[str, object]],
    *,
    top_k: int = 5,
    candidates: int = 40,
) -> dict[str, object]:
    retriever = Retriever(store, top_k=top_k, candidates=candidates)
    outcomes: list[Outcome] = []
    details: list[dict[str, object]] = []
    valid_ids = set()
    for document in await store.documents():
        for chunk in await store.chunks_of(str(document["doc_id"])):
            valid_ids.add(chunk.chunk_id)

    for item in questions:
        question = str(item.get("question") or "")
        expected_doc = str(item.get("doc") or "")
        expected_pages = [int(page) for page in (item.get("pages") or ([item["page"]] if item.get("page") else []))]
        expected_sections = [
            str(section)
            for section in (item.get("sections") or ([item["section"]] if item.get("section") else []))
        ]
        must_include = [str(text) for text in item.get("must_include") or []]
        retrieval = await retriever.search(question)
        answer = build_answer(question, retrieval)
        rank: int | None = None
        for index, hit in enumerate(retrieval.hits, start=1):
            if hit.doc_id != expected_doc:
                continue
            if expected_pages and hit.page not in expected_pages:
                continue
            if expected_sections and not any(
                section in hit.section for section in expected_sections
            ):
                continue
            rank = index
            break
        bullet_text = " ".join(bullet.text for bullet in answer.bullets).lower()
        coverage = all(text.lower() in bullet_text for text in must_include) if must_include else True
        citation_valid = all(citation.chunk_id in valid_ids for citation in answer.citations)
        expected = expected_doc + "#" + (
            f"p{expected_pages[0]}" if expected_pages else (expected_sections[0] if expected_sections else "any")
        )
        outcomes.append(
            Outcome(
                question_id=str(item.get("id") or ""),
                question=question,
                expected=expected,
                rank=rank,
                hits=[f"{hit.doc_id}#{hit.anchor}" for hit in retrieval.hits],
                coverage=coverage,
                citation_valid=citation_valid,
            )
        )
        details.append(
            {
                "id": item.get("id"),
                "question": question,
                "tag": item.get("tag"),
                "expect": expected,
                "rank": rank,
                "hits": outcomes[-1].hits,
                "must_include": must_include,
                "covered": coverage,
                "bullets": [bullet.as_dict() for bullet in answer.bullets],
                "memory_note": answer.memory_note,
            }
        )

    total = len(outcomes) or 1
    report = {
        "questions": len(outcomes),
        "hit_at_1": round(sum(1 for item in outcomes if item.rank == 1) / total, 4),
        "hit_at_3": round(sum(1 for item in outcomes if item.rank and item.rank <= 3) / total, 4),
        "hit_at_5": round(sum(1 for item in outcomes if item.rank and item.rank <= 5) / total, 4),
        "mrr": round(sum(1 / item.rank for item in outcomes if item.rank) / total, 4),
        "must_include": round(sum(1 for item in outcomes if item.coverage) / total, 4),
        "citation_valid": round(sum(1 for item in outcomes if item.citation_valid) / total, 4),
        "top_k": top_k,
        "candidates": candidates,
        "per_question": details,
    }
    return report


def render_report(report: dict[str, object], source: Path) -> str:
    lines = [
        "# 检索评测报告",
        "",
        f"- 题目来源：`{source}`",
        f"- 题量：{report['questions']}",
        f"- 候选上限：{report['candidates']}，引用条数：{report['top_k']}",
        "",
        "| 指标 | 值 | 说明 |",
        "| --- | ---: | --- |",
        f"| Hit@1 | {report['hit_at_1']:.4f} | 正确页排在第一条 |",
        f"| Hit@3 | {report['hit_at_3']:.4f} | 正确页在前三条 |",
        f"| Hit@5 | {report['hit_at_5']:.4f} | 正确页在前五条 |",
        f"| MRR | {report['mrr']:.4f} | 首条正确结果的平均倒数排名 |",
        f"| must_include | {report['must_include']:.4f} | 回答覆盖人工标注关键词 |",
        f"| citation_valid | {report['citation_valid']:.4f} | 引用 100% 可回查 |",
        "",
        "## 逐题结果",
        "",
        "| # | 问题 | 标注 | 名次 | 命中 |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in report["per_question"]:
        rank = item["rank"] if item["rank"] else "—"
        hits = ", ".join(item["hits"][:3]) or "—"
        lines.append(f"| {item['id']} | {item['question']} | {item['expect']} | {rank} | {hits} |")
    lines.append("")
    lines.append("_本报告由 `python -m duban eval` 生成，数字与 `questions.yaml`、数据库内容一一对应。_")
    return "\n".join(lines)


def write_report(report: dict[str, object], records: Path, source: Path) -> tuple[Path, Path]:
    out = records / "eval"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    md_path = out / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_report(report, source) + "\n", encoding="utf-8")
    return json_path, md_path
