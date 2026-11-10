# 论文清单与阅读顺序

这是本资料库的目录页，说明「为什么先读这两篇，再读自己的笔记」。

## 建议顺序

1. **Raft**（`papers/raft.pdf`）——先建立「共识 = 选举 + 复制 + 安全」的骨架，
   它把 Paxos 的抽象拆成了可实现的三块。
2. **Dynamo**（`papers/dynamo.pdf`）——再看「不要共识也能做成什么」：
   分片、向量时钟、可调 quorum、反熵。
3. **自己的笔记**（`notes/`）——把两篇论文的概念对齐到同一张表上，
   特别是「一致性模型」和「CAP 取舍」两节。

## 两篇论文的分工

| 论文 | 关键词 | 读完之后应该能回答 |
| --- | --- | --- |
| Raft | leader election, log replication, terms, joint consensus | 为什么随机超时能避免活锁？旧 term 条目为什么不能直接提交？ |
| Dynamo | consistent hashing, vector clock, sloppy quorum, Merkle tree | `R + W > N` 保证了什么？提示移交牺牲了什么？ |

## 怎么用这个资料库

- 直接提问，例如「Raft 的选举限制解决了什么问题」「Dynamo 为什么不用时间戳判断新旧」；
- 每条回答都带 `papers/raft.pdf 第 N 页` 或 `notes/xxx.md 第 N-M 行` 的引用，点开就是原文；
- 把没看懂的概念标记成薄弱点，下次提问会先补一条基础说明；
- 读完一页就记进度，「复习清单」会把没读完的部分列出来。

## 还没覆盖的部分

- Paxos / Multi-Paxos 的推导；
- Spanner 的 TrueTime 与外部一致性；
- 事务隔离级别与 MVCC；
- 拜占庭容错（BFT）系列。

这些留给下一轮扩库：把论文放进 `papers/`，重新 `python -m duban ingest` 即可，增量导入只处理新文件。
