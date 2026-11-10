"""共享夹具：每个测试用独立的临时库与临时资料目录，互不干扰。"""

from __future__ import annotations

from pathlib import Path

import pytest

from duban.config import Settings

CORPUS = {
    "notes/raft.md": """# Raft 笔记

## 选举

Follower 在随机化超时内没收到心跳就转为 Candidate，拿到多数派选票后成为 Leader。
随机化的目的是避免所有节点同时竞选、同时超时，形成活锁。

## 日志复制

Leader 把日志发给 follower，多数派持久化后才提交。AppendEntries 带上
prevLogIndex 与 prevLogTerm 做一致性检查。
""",
    "notes/dynamo.md": """# Dynamo 笔记

## 分片

Dynamo 用一致性哈希把 key 分到环上，并用虚拟节点让负载更均匀。

## 版本

不用时间戳，用向量时钟判断版本的新旧；互不包含的两个版本说明是并发写。
""",
}


@pytest.fixture()
def corpus_dir(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    for relative, text in CORPUS.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture()
def settings(tmp_path: Path, corpus_dir: Path) -> Settings:
    value = Settings(
        root=tmp_path,
        corpus=corpus_dir,
        runtime=tmp_path / "runtime",
        records=tmp_path / "records",
        web=tmp_path / "web",
        user="tester",
        top_k=3,
        candidates=20,
    )
    value.ensure_dirs()
    return value
