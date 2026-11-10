# 读伴 DuBan — 会记住你的资料阅读助手

> OceanBase 2026 比赛 · Qoder 赛题作品
> 用 **seekdb** 做资料检索、用 **PowerContext** 做长期记忆，解决「论文与笔记散落在各处、
> 读完就忘、下次还得从头找」这个真实痛点。

- 项目网站：<https://duban-naubk8w0zwr.qoder.website>（Qoder Sites 发布，公开可访问）
- 镜像站点：<https://sma-444.github.io/duban/>（GitHub Pages，内容相同）
- 代码仓库：本目录（`powercontext` 的 `2026-competition-ecosystem` 分支下 `qoder/`）；独立镜像 <https://github.com/Sma-444/duban>
- 运行说明：[`docs/运行说明.md`](docs/运行说明.md)

---

## 一、它解决什么问题

读研/读论文的人都有三个反复出现的动作：

1. **找**：这句话在哪篇论文第几页？翻 PDF、翻笔记，十分钟过去了。
2. **懂**：上次没看懂的概念，这次还是没看懂——因为没人记得你卡在哪。
3. **续**：上周读到一半的资料，这周打开已经忘了读到哪、为什么停。

读伴把这三件事变成一次提问、一条引用、一份复习清单：

- **找**：中文提问也能命中英文论文（内置术语表做跨语言查询扩展），回答里的每条结论都带
  `papers/raft.pdf 第 8 页` 或 `notes/cap-basic.md 第 23-30 行`，点开就是原文。
- **懂**：你说「这段没看懂」，它记进 PowerContext；下次相关提问会先补一条更基础的说明。
- **续**：每读一页记一次进度，重启进程、换一天再打开，复习清单还是接着上次的地方。

## 二、技术上怎么做的

```
             ┌────────────────────────────── 读伴 ──────────────────────────────┐
  提问 ──────►  查询改写（分词 / 术语表 / 多路）                                    │
             │        │                                                        │
             │        ▼                                                        │
             │   seekdb（嵌入式）                                                │
             │   ├─ duban_documents   文档清单与修订号                            │
             │   ├─ duban_chunks      片段（页/小节），NGRAM 全文索引              │
             │   └─ MATCH … AGAINST 取候选 + SQL 日志                            │
             │        │                                                        │
             │        ▼                                                        │
             │   重排：FTS 分 + IDF 覆盖 + 标题 + 邻近 + hub/问句惩罚              │
             │        │                          ▲                             │
             │        ▼                          │ 偏好 / 薄弱点 / 进度 / 上次提问   │
             │   抽取式作答（句子级引用）          │                              │
             │        │                     PowerContext（atomic-memory）        │
             │        ▼                          │                              │
  回答 ◄─────┤   带 path#anchor 的要点 ────────────┘ 每次问答与标记写回                │
             └──────────────────────────────────────────────────────────────────┘
```

两套技术的分工是明确的、可以逐条核对的：

| 技术 | 在项目里做什么 | 证据文件 |
| --- | --- | --- |
| **seekdb** | 资料与片段的存储；`WITH PARSER NGRAM` 全文索引；`MATCH … AGAINST` 取候选；结构化过滤（按文档） | `records/db/queries.jsonl`（每条 SQL、参数、行数、耗时） |
| **PowerContext** | 画像（解释深度）、薄弱点、阅读进度、每次问答摘要；跨进程复用 | `records/memory/events.jsonl` + `python -m duban state` |
| **Qoder** | 项目开发与 Qoder Sites 发布 | `docs/Qoder开发记录.md`（含每阶段提示词与截图清单） |

> seekdb 不是「装了个数据库」：检索结果直接决定回答引用哪一页；PowerContext 也不是「写了个日志」：
> 薄弱点会改变下一次回答的召回与措辞，进度会改变复习清单。

## 三、五分钟跑起来

前置：Linux / macOS / Windows，Python 3.12，能访问 PyPI。

```bash
cd qoder
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m duban init            # 建表 + 导入 corpus/（7 篇资料 / 275 个片段）
python -m duban ask "Raft 的 Figure 8 说明了什么问题？"
python -m duban serve           # 浏览器打开 http://127.0.0.1:8765
```

`python -m duban serve` 之后，界面上：

- 左栏是资料库与复习清单（资料进度来自 PowerContext）；
- 中间提问，回答里每条要点后面挂着可点击的 `文件#页/行`；
- 右栏是记忆：解释深度、薄弱点、上次提问、最近写入的 artifact id。

## 四、可核对的验证

```bash
python -m pytest                 # 9 个测试：切块、检索、引用回查、记忆重启、增量导入
python -m duban eval             # 21 道人工标注题，输出 records/eval/report.md
python -m duban demo             # 入库 → 提问 → 标记薄弱点 → 再提问（记忆生效）→ 复习清单
```

当前实测（Linux x86_64 / Python 3.12.16 / seekdb-v1.4.0.0 嵌入式）：

| 指标 | 值 | 含义 |
| --- | ---: | --- |
| Hit@3 | 0.9048 | 21 题里 19 题的正确证据落在前三条引用 |
| MRR | 0.7540 | 首条正确结果的平均倒数排名 |
| must_include | 0.8571 | 抽取式回答覆盖人工标注关键词的比例 |
| citation_valid | 1.0000 | 返回的引用 100% 能在库里回查到原文 |
| 用例 | 9 passed | `tests/` 全部通过 |
| 语料 | 7 篇 / 275 片段 | 2 篇英文论文（Raft、Dynamo）+ 5 篇中文笔记 |

详细的分步验证见 [`docs/验证样例.md`](docs/验证样例.md)。

## 五、目录结构

```
qoder/
├── duban/                Python 包
│   ├── corpus.py         资料读取与切块（md / txt / pdf，保留页与行号）
│   ├── store.py          seekdb 建表、增量入库、MATCH 查询、SQL 日志
│   ├── retrieve.py       查询改写、多路召回、IDF 重排、hub/问句降权
│   ├── glossary.py       中英术语表（中文提问命中英文论文）
│   ├── answer.py         抽取式作答（句子级引用，不调用外部模型）
│   ├── memory.py         PowerContext：画像 / 薄弱点 / 进度 / 会话
│   ├── review.py         复习清单
│   ├── evaluate.py       标注集跑分
│   ├── server.py         标准库 HTTP + 静态前端
│   └── cli.py            命令行
├── web/                  前端（原生 HTML/CSS/JS，无构建步骤）
├── corpus/               示例资料：papers/*.pdf + notes/*.md + eval/questions.yaml
├── tests/                pytest
├── docs/                 运行说明 / 验证样例 / 技术结合 / Qoder 记录 / 提交清单
├── site/                 Qoder Sites 用的静态项目网站
└── records/              运行时生成的证据（SQL 日志、记忆日志、评测报告、截图）
```

## 六、边界与取舍（写清楚，避免误解）

- **默认不调用任何模型**。回答是从原文里抽句子，所以「不知道」时会明确说没找到，
  不会编造。需要生成式改写时，可在 `answer.py` 里接一个模型，但引用契约必须保留。
- **中文问题问英文论文靠术语表**，不是机器翻译。术语表是人工维护的，
  见 `duban/glossary.py`，加一行就能覆盖新领域。
- **PDF 只做文本层抽取**（pypdf），扫描件没有 OCR，会被跳过并记进 `duban ingest` 的日志。
- **单机单用户**。`DUBAN_USER` 决定 PowerContext 作用域，可以做多人隔离，但没有做鉴权。

## 七、许可与来源

- 论文：Raft（Ongaro & Ousterhout, 2014，`raft.github.io/raft.pdf`）、
  Dynamo（DeCandia et al., SOSP 2007，Amazon 官方 PDF），仅作示例语料；
- 中文笔记：本项目自写，用于演示跨资料对照；
- 代码：本项目原创，依赖 `powercontext[seekdb]==1.5.0`、`pypdf`、`PyYAML`、`jieba`。
