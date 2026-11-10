# 检索评测报告

- 题目来源：`/home/senhao/qoder/corpus/eval/questions.yaml`
- 题量：21
- 候选上限：40，引用条数：5

| 指标 | 值 | 说明 |
| --- | ---: | --- |
| Hit@1 | 0.6190 | 正确页排在第一条 |
| Hit@3 | 0.9048 | 正确页在前三条 |
| Hit@5 | 0.9048 | 正确页在前五条 |
| MRR | 0.7540 | 首条正确结果的平均倒数排名 |
| must_include | 0.8571 | 回答覆盖人工标注关键词 |
| citation_valid | 1.0000 | 引用 100% 可回查 |

## 逐题结果

| # | 问题 | 标注 | 名次 | 命中 |
| --- | --- | --- | ---: | --- |
| r01 | Raft 的 Figure 8 说明了什么问题？ | papers/raft#p8 | 2 | papers/raft#p3-5, papers/raft#p9, notes/papers-index#L21-26 |
| r02 | Raft 里的 InstallSnapshot RPC 是用来做什么的？ | papers/raft#p12 | 1 | papers/raft#p12-3, papers/raft#p12-4, papers/raft#p5-5 |
| r03 | Raft 的 AppendEntries 里 prevLogIndex 和 prevLogTerm 有什么用？ | papers/raft#p4 | 1 | papers/raft#p4, notes/raft-notes#L28-36, papers/raft#p4-1 |
| r04 | Raft 为什么需要 joint consensus 才能做成员变更？ | papers/raft#p10 | 3 | papers/raft#p16-3, papers/raft#p1-4, papers/raft#p10-5 |
| r05 | Raft 的 Leader Completeness 性质保证了什么？ | papers/raft#p5 | 1 | papers/raft#p9-1, notes/raft-notes#L28-36, papers/raft#p5 |
| r06 | Raft 的 Log Matching Property 是什么？ | papers/raft#p5 | 1 | papers/raft#p7-1, papers/raft#p9-4, papers/raft#p7-2 |
| r07 | Raft 的选举限制 election restriction 为什么必要？ | papers/raft#p8 | — | papers/raft#p5-1, notes/raft-notes#L38-43, papers/raft#p1-3 |
| r08 | Raft 用快照做日志压缩之后，落后太多的 follower 怎么追上？ | papers/raft#p11 | 1 | papers/raft#p12-5, papers/raft#p13, notes/raft-notes#L54-58 |
| d01 | Dynamo 用哪种数据结构做反熵 anti-entropy？ | papers/dynamo#p8 | 1 | papers/dynamo#p8-5, papers/dynamo#p8-4, papers/dynamo#p5-6 |
| d02 | Dynamo 的向量时钟怎么判断两个版本是并发写？ | papers/dynamo#p5 | 2 | notes/dynamo-notes#L20-28, papers/dynamo#p7, papers/dynamo#p8 |
| d03 | Dynamo 的 sloppy quorum 和 hinted handoff 是什么？ | papers/dynamo#p5 | 2 | notes/dynamo-notes#L38-44, papers/dynamo#p5-6, papers/dynamo#p8-1 |
| d04 | Dynamo 的虚拟节点 virtual node 解决了什么问题？ | papers/dynamo#p6 | 1 | papers/dynamo#p6-1, papers/dynamo#p6, papers/dynamo#p6-3 |
| d05 | Dynamo 里 (N, R, W) 这三个参数分别代表什么？ | papers/dynamo#p5 | 1 | papers/dynamo#p14-5, papers/dynamo#p15, papers/dynamo#p10-3 |
| d06 | Dynamo 的一致性哈希怎么把 key 分配到节点上？ | papers/dynamo#p1 | 2 | notes/dynamo-notes#L8-13, papers/dynamo#p1-6, papers/dynamo#p2-5 |
| n01 | CAP 里的 C、A、P 三个字母的准确定义是什么？ | notes/cap-basic#三个字母的准确定义 | 1 | notes/cap-basic#L8-15, notes/cap-basic#L23-30, notes/consistency-models#L52-56 |
| n02 | 线性一致和顺序一致的区别是什么？ | notes/consistency-models#线性一致性 | 1 | notes/consistency-models#L17-19, notes/consistency-models#L9-15, notes/consistency-models#L3-7 |
| n03 | Raft 的安全性有哪两条不能省的规则？ | notes/raft-notes#安全性 | 1 | notes/raft-notes#L38-43, papers/raft#p14, papers/raft#p1-3 |
| n04 | Dynamo 的读写票数 R + W > N 为什么能保证读到最新写？ | notes/dynamo-notes#读写票数 | 2 | papers/dynamo#p11-2, notes/dynamo-notes#L30-36, papers/dynamo#p8-2 |
| n05 | 为什么 CAP 里的 CA 在分布式系统里不成立？ | notes/cap-basic#为什么 CA | 1 | notes/cap-basic#L17-21, notes/cap-basic#L23-30, notes/cap-basic#L50-56 |
| n06 | BASE 理论和 CAP 是什么关系？ | notes/cap-basic#BASE | 1 | notes/cap-basic#L32-39, papers/dynamo#p14, notes/cap-basic#L50-56 |
| x01 | 同样面对分区，Raft 和 Dynamo 分别牺牲了什么？ | notes/dynamo-notes#和 Raft | — | papers/dynamo#p5, papers/dynamo#p5-4, papers/dynamo#p9-1 |

_本报告由 `python -m duban eval` 生成，数字与 `questions.yaml`、数据库内容一一对应。_
