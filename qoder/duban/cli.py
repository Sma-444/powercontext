"""命令行入口：``python -m duban <命令>``。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from duban.config import settings_from_env
from duban.evaluate import evaluate, load_questions, write_report
from duban.service import open_runtime


def _print_answer(payload: dict) -> None:
    answer = payload["answer"]
    stats = answer["stats"]
    print()
    print(f"问：{answer['question']}")
    print(f"答：{answer['headline']}")
    if answer["memory_note"]:
        print(f"记忆：{answer['memory_note']}")
    print()
    for index, bullet in enumerate(answer["bullets"], start=1):
        print(f"  [{index}] {bullet['text']}")
        print(f"      ↳ {bullet['citation']}  ({bullet['doc_title']})")
    if answer["primer"]:
        primer = answer["primer"]
        print()
        print("  先补一条基础说明：")
        print(f"      {primer['snippet']}")
        print(f"      ↳ {primer['citation']}")
    print()
    print(f"  检索：候选 {stats['candidates']} 条 → 引用 {stats['hits']} 条 · 词项 {', '.join(stats['terms'][:8])}")
    if answer["followups"]:
        print("  可以接着问：")
        for idea in answer["followups"]:
            print(f"      - {idea}")


def _print_state(state: dict) -> None:
    print(f"用户：{state['user']}    作用域：{state['scope']}")
    stats = state["stats"]
    print(f"资料：{stats['documents']} 篇 / {stats['chunks']} 个片段    薄弱点：{stats['weak']}    问答：{stats['turns']}")
    print()
    print("资料库")
    for document in state["documents"]:
        progress = document.get("progress")
        mark = f"{int(progress['ratio'] * 100)}%" if progress else "未开始"
        pages = f"{document['page_count']} 页" if document["page_count"] else f"{document['chunk_count']} 段"
        print(f"  - {document['title']}  ({pages}, {mark})  {document['doc_id']}")
    print()
    memory = state["memory"]
    print(f"画像：{json.dumps(memory['profile'], ensure_ascii=False)}")
    if memory["weak"]:
        print("薄弱点：" + "、".join(f"{item['term']}×{item['count']}" for item in memory["weak"]))
    if memory["turns"]:
        last = memory["turns"][-1]
        print(f"上次提问：{last['question']}")
    print()
    print("复习清单")
    for item in state["review"]:
        print(f"  - [{item['kind']}] {item['title']} — {item['detail']}")


async def _run(args) -> int:
    settings = settings_from_env()
    if args.command == "serve":
        from duban.server import serve

        await serve(settings, host=args.host, port=args.port)
        return 0

    async with open_runtime(settings) as duban:
        await duban.init()

        if args.command == "init":
            sync = await duban.ingest()
            print(f"索引就绪：{sync.documents} 篇 / {sync.chunks} 个片段")
            for name, reason in duban.last_skipped:
                print(f"  跳过 {name}: {reason}")
            return 0

        if args.command == "ingest":
            sync = await duban.ingest(force=args.force)
            print(
                f"入库完成：扫描 {sync.documents} 篇，新增/更新 {sync.inserted} 篇，"
                f"未变 {sync.unchanged} 篇，移除 {sync.removed} 篇，共 {sync.chunks} 个片段"
            )
            for name, reason in duban.last_skipped:
                print(f"  跳过 {name}: {reason}")
            return 0

        if args.command == "ask":
            if not args.question:
                print("用法：python -m duban ask \"你的问题\"", file=sys.stderr)
                return 2
            result = await duban.ask(args.question)
            if args.json:
                print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            else:
                _print_answer(result.as_dict())
            return 0

        if args.command == "mark":
            if args.term:
                await duban.mark_weak(args.term, note=args.note or "")
                print(f"已记下薄弱点：{args.term}")
            if args.list:
                state = await duban.state()
                for item in state["memory"]["weak"]:
                    print(f"  - {item['term']} ×{item['count']}  {item['note']}")
            return 0

        if args.command == "unmark":
            await duban.unmark_weak(args.term)
            print(f"已划掉：{args.term}")
            return 0

        if args.command == "profile":
            changes: dict[str, object] = {}
            if args.depth:
                changes["depth"] = args.depth
            if args.note is not None:
                changes["note"] = args.note
            if args.interests:
                changes["interests"] = [item.strip() for item in args.interests.split(",") if item.strip()]
            if changes:
                print(json.dumps(await duban.set_profile(**changes), ensure_ascii=False))
            return 0

        if args.command == "touch":
            await duban.touch(args.doc, page=args.page, anchor=args.anchor or f"p{args.page}", ratio=args.ratio)
            print(f"已记录进度：{args.doc} 第 {args.page} 页（{int(args.ratio * 100)}%）")
            return 0

        if args.command == "review":
            state = await duban.state()
            if not state["review"]:
                print("复习清单是空的：先读几页，或标记几个薄弱点。")
                return 0
            for item in state["review"]:
                print(f"[{item['kind']}] {item['title']} — {item['detail']}")
                if item["action"].get("question"):
                    print(f"    去问：{item['action']['question']}")
            return 0

        if args.command == "state":
            state = await duban.state()
            if args.json:
                print(json.dumps(state, ensure_ascii=False, indent=2))
            else:
                _print_state(state)
            return 0

        if args.command == "eval":
            questions_path = Path(args.questions) if args.questions else settings.corpus / "eval" / "questions.yaml"
            questions = load_questions(questions_path)
            report = await evaluate(duban.store, questions, top_k=args.top_k, candidates=args.candidates)
            json_path, md_path = write_report(report, settings.records, questions_path)
            print(json.dumps({key: report[key] for key in ("questions", "hit_at_1", "hit_at_3", "hit_at_5", "mrr", "must_include", "citation_valid")}, ensure_ascii=False, indent=2))
            print(f"报告：{md_path}")
            return 0

        if args.command == "demo":
            return await _demo(duban, settings)

    print(f"未知命令：{args.command}", file=sys.stderr)
    return 2


async def _demo(duban, settings) -> int:
    """一条命令演示「检索 + 记忆」的完整闭环，评审可照着核对。"""

    print("=" * 68)
    print("读伴 demo：入库 → 提问 → 标记薄弱点 → 再提问（记忆生效）→ 复习清单")
    print("=" * 68)
    sync = await duban.ingest(force=True)
    print(f"\n[1/5] 入库：{sync.documents} 篇 / {sync.chunks} 个片段")

    questions = [
        "Raft 里 leader 选举为什么要用随机超时？",
        "Dynamo 怎么解决一致性哈希的倾斜问题？",
    ]
    for index, question in enumerate(questions, start=1):
        print(f"\n[2/5] 第 {index} 问：{question}")
        result = await duban.ask(question)
        _print_answer(result.as_dict())

    print("\n[3/5] 标记薄弱点：CAP")
    await duban.mark_weak("CAP", note="分不清 CAP 和 BASE 的取舍")
    await duban.set_profile(depth="deep", note="喜欢先看结论再看推导")

    print("\n[4/5] 再问一个与薄弱点相关的问题（应当出现记忆提示 + 基础补正）")
    result = await duban.ask("CAP 定理到底限制了什么？")
    _print_answer(result.as_dict())

    print("\n[5/5] 复习清单")
    state = await duban.state()
    for item in state["review"]:
        print(f"  - [{item['kind']}] {item['title']} — {item['detail']}")

    print("\n证据：")
    print(f"  SQL 日志  {settings.query_log}")
    print(f"  记忆日志  {settings.memory_log}")
    print(f"  数据库    {settings.database}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="duban", description="读伴 — 会记住你的资料阅读助手")
    parser.add_argument("--user", help="用户标识（决定 PowerContext 作用域）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="建索引并导入 corpus/")
    ingest = sub.add_parser("ingest", help="增量导入 corpus/")
    ingest.add_argument("--force", action="store_true", help="忽略 revision，全量重建")

    ask = sub.add_parser("ask", help="提问")
    ask.add_argument("question", nargs="?", help="问题")
    ask.add_argument("--json", action="store_true", help="输出完整 JSON")

    mark = sub.add_parser("mark", help="标记薄弱点")
    mark.add_argument("term", nargs="?", help="概念名")
    mark.add_argument("--note", help="备注")
    mark.add_argument("--list", action="store_true", help="列出已有薄弱点")

    unmark = sub.add_parser("unmark", help="划掉薄弱点")
    unmark.add_argument("term")

    profile = sub.add_parser("profile", help="设置阅读偏好")
    profile.add_argument("--depth", choices=["brief", "standard", "deep"])
    profile.add_argument("--interests")
    profile.add_argument("--note")

    touch = sub.add_parser("touch", help="记录阅读进度")
    touch.add_argument("doc")
    touch.add_argument("--page", type=int, default=1)
    touch.add_argument("--anchor", default="")
    touch.add_argument("--ratio", type=float, default=0.0)

    state = sub.add_parser("state", help="查看资料库 / 记忆 / 复习清单")
    state.add_argument("--json", action="store_true")

    evaluate_cmd = sub.add_parser("eval", help="跑标注集评测")
    evaluate_cmd.add_argument("--questions", help="标注文件路径")
    evaluate_cmd.add_argument("--top-k", type=int, default=5)
    evaluate_cmd.add_argument("--candidates", type=int, default=40)

    serve = sub.add_parser("serve", help="启动本地 Web 界面")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    sub.add_parser("demo", help="跑一遍完整演示")
    sub.add_parser("review", help="打印复习清单")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "user", None):
        import os

        os.environ["DUBAN_USER"] = args.user
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\n已停止。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
