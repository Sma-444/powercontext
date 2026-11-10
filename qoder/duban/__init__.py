"""读伴 DuBan — 会记住你的资料阅读助手。

包内分层：

``corpus``    资料读取与切块（md / txt / pdf）
``store``     seekdb 里的文档与片段索引（NGRAM 全文索引）
``retrieve``  多路召回 + 重排 + 引用
``answer``    抽取式作答（不依赖外部模型）
``memory``    PowerContext 里的画像 / 薄弱点 / 进度 / 会话
``review``    复习清单
``evaluate``  标注集跑分
``server``    本地 Web 界面（标准库 HTTP）
"""

__version__ = "0.1.0"
