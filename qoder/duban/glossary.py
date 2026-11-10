"""中英术语表：让中文提问也能命中英文论文。

问题出在语种对不上：用户问「落后太多的 follower 怎么追上」，论文里写的是
``InstallSnapshot`` / ``snapshot``，纯中文词项永远匹配不上英文页。

做法很朴素——维护一张人工术语表，把问题里出现的中文术语扩成英文同义词，
再把这些英文词一并送进 seekdb 的全文检索和覆盖度打分。它不依赖任何翻译模型，
增删一个词就能解释、能复现，也方便评审核对「跨语言检索」到底靠什么生效。
"""

from __future__ import annotations

GLOSSARY: dict[str, tuple[str, ...]] = {
    "快照": ("snapshot", "compaction"),
    "日志压缩": ("log compaction", "snapshot"),
    "日志": ("log",),
    "选举": ("election", "elect"),
    "成员变更": ("membership change", "membership"),
    "集群成员": ("membership", "cluster"),
    "领导者": ("leader",),
    "候选人": ("candidate",),
    "任期": ("term",),
    "多数派": ("majority", "quorum"),
    "提交": ("commit", "committed"),
    "复制": ("replicate", "replication"),
    "一致性": ("consistency", "consistent"),
    "线性一致": ("linearizable", "linearizability"),
    "顺序一致": ("sequential consistency",),
    "因果": ("causal", "causality"),
    "最终一致": ("eventual consistency", "eventually consistent"),
    "向量时钟": ("vector clock", "version vector"),
    "版本": ("version",),
    "冲突": ("conflict", "reconcile"),
    "并发": ("concurrent", "concurrently"),
    "一致性哈希": ("consistent hashing", "hash ring"),
    "虚拟节点": ("virtual node", "virtual nodes"),
    "副本": ("replica", "replication"),
    "分区": ("partition", "partitions"),
    "容错": ("fault tolerance", "tolerance"),
    "反熵": ("anti-entropy", "Merkle"),
    "提示移交": ("hinted handoff", "handoff"),
    "两阶段提交": ("two-phase commit", "2PC"),
    "协调者": ("coordinator",),
    "事务": ("transaction",),
    "可用性": ("availability", "available"),
    "幂等": ("idempotent",),
    "状态机": ("state machine",),
    "心跳": ("heartbeat",),
    "超时": ("timeout", "time-out"),
    "随机": ("randomized", "random"),
    "快照安装": ("InstallSnapshot", "snapshot"),
    "读": ("read",),
    "写": ("write",),
    "论文": ("paper",),
}


def expand(question: str) -> list[str]:
    """返回问题里中文术语对应的英文词（保持顺序、去重）。"""

    found: list[str] = []
    for term, translations in GLOSSARY.items():
        if term not in question:
            continue
        for translation in translations:
            for piece in translation.lower().split():
                if piece not in found:
                    found.append(piece)
    return found
