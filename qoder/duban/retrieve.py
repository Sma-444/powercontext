"""检索：多路召回 + 重排 + 引用。

思路和「把问题丢给一个向量库」不一样，这里每一步都能解释：

1. **查询改写**：原问题、内容词串、技术词串三路，各自去 seekdb 取候选；
2. **合并**：同一片段被多路命中就保留最高分（按路内归一化，避免长句占便宜）；
3. **重排**：seekdb 的 FTS 分 + 词项覆盖率 + 标题命中 + 邻近度 + 阅读进度微调；
4. **去重**：每篇资料最多留 2 条，除非问题本身在比较两篇以上资料；
5. **薄弱点补正**：如果问题里出现你标记过「没看懂」的概念，额外取一条更基础的片段。

排序结果全部带 ``chunk_id`` 与 ``path#anchor``，可以点回原文。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from duban.memory import MemorySnapshot
from duban.store import CorpusStore, Hit
from duban import glossary

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_ASCII = re.compile(r"[A-Za-z][A-Za-z0-9_\-\.]{1,}")
_STOP = {
    "什么", "为什么", "怎么", "怎样", "如何", "哪些", "哪个", "多少", "是否", "可以", "我们",
    "这个", "那个", "一个", "以及", "但是", "因为", "所以", "如果", "就是", "还是", "然后",
    "the", "and", "for", "with", "what", "why", "how", "does", "did", "are", "was", "were",
    "this", "that", "from", "into", "about", "which", "there", "their", "have", "has",
}
_STOP_CHARS = set("的了吗呢吧啊呀是在有和与及或就都也还很更最把被让给对从向以为所之其")


# 目录/清单页会命中所有主题（hub），按 IR 里的老办法降权，避免它们挤掉真正的正文页。
_HUB_MARKERS = ("清单", "目录", "索引", "index", "readme")


def _is_hub(hit: Hit) -> bool:
    text = f"{hit.doc_title} {hit.section}".lower()
    return any(marker.lower() in text for marker in _HUB_MARKERS)


def _ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    ascii_letters = sum(1 for char in text if char.isascii() and char.isalpha())
    return ascii_letters / len(text)


def _cut(text: str) -> list[str]:
    """中文分词：优先 jieba（PowerContext 自带依赖），没有就退回 2 字切分。"""

    global _JIEBA
    if _JIEBA is None:
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import jieba

                jieba.setLogLevel("ERROR")
            _JIEBA = jieba
        except Exception:  # noqa: BLE001 - 没装 jieba 也能用
            _JIEBA = False
    if _JIEBA:
        return list(_JIEBA.cut(text))
    tokens: list[str] = []
    for run in _CJK.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    tokens.extend(_ASCII.findall(text))
    return tokens


_JIEBA = None


def terms_of(text: str) -> list[str]:
    """把一段中英文混排的文本拆成可比较的词项。"""

    terms: list[str] = []
    for token in _cut(text):
        raw = token.strip()
        term = raw.lower()
        if not term or not re.search(r"[0-9a-z\u4e00-\u9fff]", term):
            continue
        if term in _STOP:
            continue
        if len(term) == 1:
            # 单字：保留 N/R/W 这类大写参数名、数字（Figure 8）与「熵」这类中文关键词；
            # 常见字交给 IDF 压权。
            if term.isascii():
                if not (raw.isupper() or term.isdigit()):
                    continue
            elif term in _STOP_CHARS:
                continue
        if len(term) <= 4 and term.isupper():
            term = term.lower()
        terms.append(term)
    seen: dict[str, None] = {}
    for term in terms:
        if term not in seen:
            seen[term] = None
    return list(seen)


@dataclass
class Retrieval:
    query: str
    terms: list[str]
    hits: list[Hit]
    candidates: int
    variants: dict[str, int] = field(default_factory=dict)
    primer: Hit | None = None
    weak_terms: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, list[str]] = field(default_factory=dict)


class Retriever:
    def __init__(self, store: CorpusStore, *, top_k: int = 5, candidates: int = 40) -> None:
        self.store = store
        self.top_k = top_k
        self.candidates = candidates
        self._idf: dict[str, float] | None = None
        self._default_idf = 1.0

    async def _ensure_idf(self) -> dict[str, float]:
        """用全库片段的文档频率算 IDF：越常见的词（Raft、Dynamo）权重越低。"""

        if self._idf is not None:
            return self._idf
        chunks = await self.store.all_chunks()
        frequencies: dict[str, int] = {}
        for chunk in chunks:
            for term in set(terms_of(chunk.body)):
                frequencies[term] = frequencies.get(term, 0) + 1
        total = max(1, len(chunks))
        self._idf = {
            term: math.log((total + 1) / (count + 0.5)) + 1.0 for term, count in frequencies.items()
        }
        self._default_idf = math.log(total + 1) + 1.0
        return self._idf

    def _weight(self, term: str) -> float:
        return (self._idf or {}).get(term, self._default_idf)

    async def search(self, question: str, snapshot: MemorySnapshot | None = None) -> Retrieval:
        await self._ensure_idf()
        question = question.strip()
        terms = terms_of(question)
        for extra in glossary.expand(question):
            if extra not in terms:
                terms.append(extra)
        variants = self._variants(question, terms)
        raw: dict[str, float] = {}
        best: dict[str, float] = {}
        best_variant: dict[str, str] = {}
        rows: dict[str, Hit] = {}
        variant_hits: dict[str, int] = {}
        for name, query in variants.items():
            found = await self.store.search(query, limit=self.candidates)
            variant_hits[name] = len(found)
            if not found:
                continue
            scores = [hit.score for hit in found]
            low, high = min(scores), max(scores)
            for hit in found:
                normalized = 0.5 if high <= low else (hit.score - low) / (high - low)
                rows.setdefault(hit.chunk_id, hit)
                raw[hit.chunk_id] = max(raw.get(hit.chunk_id, 0.0), normalized)
                if hit.score > best.get(hit.chunk_id, -1.0):
                    best[hit.chunk_id] = hit.score
                    best_variant[hit.chunk_id] = name
        if not rows:
            return Retrieval(question, terms, [], 0, variant_hits)

        weak_terms = self._weak_overlap(terms, snapshot)
        primer = None
        if weak_terms:
            primer_hits = await self.store.search(weak_terms[0], limit=3)
            primer = primer_hits[0] if primer_hits else None

        ranked: list[tuple[float, Hit, list[str]]] = []
        for chunk_id, hit in rows.items():
            score, reasons = self._rerank(hit, raw[chunk_id], terms, best_variant[chunk_id])
            if snapshot and hit.doc_id in snapshot.progress:
                progress = snapshot.progress[hit.doc_id]
                if progress.page and hit.page and abs(hit.page - progress.page) <= 2:
                    score += 0.02
                    reasons.append("near_progress")
            if hit.chunk_id == getattr(primer, "chunk_id", None):
                score += 0.02
                reasons.append("weak_primer")
            ranked.append((score, hit, reasons))
        ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))

        multi_doc_question = any(word in question for word in ("区别", "对比", "比较", "差异", "versus", "vs"))
        # 单篇问题别被「每篇最多 2 条」卡住：问 Raft 的细节时，前五条本来就该都来自 Raft。
        per_doc_limit = 3 if multi_doc_question else 5
        picked: list[tuple[float, Hit, list[str]]] = []
        counts: dict[str, int] = {}
        for score, hit, reasons in ranked:
            if counts.get(hit.doc_id, 0) >= per_doc_limit:
                continue
            counts[hit.doc_id] = counts.get(hit.doc_id, 0) + 1
            picked.append((score, hit, reasons))
            if len(picked) >= self.top_k:
                break
        return Retrieval(
            query=question,
            terms=terms,
            hits=[hit for _, hit, _ in picked],
            candidates=len(rows),
            variants=variant_hits,
            primer=primer,
            weak_terms=weak_terms,
            scores={hit.chunk_id: round(score, 4) for score, hit, _ in picked},
            reasons={hit.chunk_id: reasons for _, hit, reasons in picked},
        )

    # ------------------------------------------------------------------ internals

    def _variants(self, question: str, terms: list[str]) -> dict[str, str]:
        variants: dict[str, str] = {"question": question}
        content = [term for term in terms if len(term) > 1 or term.isascii()]
        if content:
            variants["terms"] = " ".join(content[:18])
        technical = [term for term in terms if term.isascii() or (len(term) == 2 and term.isupper())]
        if technical and len(technical) < len(content):
            variants["technical"] = " ".join(technical[:10])
        return variants

    def _rerank(
        self, hit: Hit, base: float, terms: list[str], variant: str
    ) -> tuple[float, list[str]]:
        body_terms = set(terms_of(hit.body))
        heading_terms = set(terms_of(f"{hit.section} {hit.doc_title}"))
        ascii_heavy = _ascii_ratio(hit.body) > 0.6
        # 中文问题问英文论文时，中文虚词（「说明」「问题」）不该拖低英文页的覆盖率；
        # 反过来，术语表扩出来的英文词也不该拖低中文笔记的覆盖率。按片段语种取词。
        if ascii_heavy:
            scoring_terms = [term for term in terms if term.isascii()]
        else:
            scoring_terms = [term for term in terms if not term.isascii()]
        scoring_terms = scoring_terms or terms
        matched = [term for term in scoring_terms if term in body_terms]
        total_weight = sum(self._weight(term) for term in scoring_terms)
        # 英文片段只按英文词计覆盖，但分母不能小于「查询里最有信息量的那个词」：
        # 否则一页只要出现 Raft 这种高频词就能拿满覆盖，把真正的证据页挤下去。
        strongest = max((self._weight(term) for term in terms), default=1.0)
        total_weight = max(total_weight, strongest, 1e-6)
        coverage = min(1.0, sum(self._weight(term) for term in matched) / total_weight)
        heading = 1.0 if any(term in heading_terms for term in scoring_terms) else 0.0
        proximity = self._proximity(hit.body, matched)
        length_penalty = 0.0 if 120 <= len(hit.body) <= 1200 else 0.05
        hub_penalty = 0.20 if _is_hub(hit) else 0.0
        question_penalty = 0.08 if hit.body.count("？") + hit.body.count("?") >= 3 else 0.0
        score = (
            0.45 * base
            + 0.35 * coverage
            + 0.10 * heading
            + 0.10 * proximity
            - length_penalty
            - hub_penalty
            - question_penalty
        )
        reasons = [f"variant:{variant}", f"coverage:{len(matched)}/{len(scoring_terms)}"]
        if heading:
            reasons.append("heading")
        if proximity > 0:
            reasons.append(f"proximity:{proximity:.2f}")
        if hub_penalty:
            reasons.append("hub_penalty")
        if question_penalty:
            reasons.append("question_penalty")
        return score, reasons

    @staticmethod
    def _proximity(body: str, matched: list[str]) -> float:
        """命中的词项在正文里是否聚在一起（只看前 6 个命中词的位置跨度）。"""

        if len(matched) < 2:
            return 0.0
        positions = sorted(body.find(term) for term in matched[:6] if body.find(term) >= 0)
        if len(positions) < 2:
            return 0.0
        span = positions[-1] - positions[0]
        return 1.0 / (1.0 + math.log1p(span / max(1, len(body) / 6)))

    @staticmethod
    def _weak_overlap(terms: list[str], snapshot: MemorySnapshot | None) -> list[str]:
        if snapshot is None:
            return []
        hits: list[str] = []
        for item in snapshot.weak:
            weak_terms = set(terms_of(item.term))
            if not weak_terms:
                continue
            overlap = len(weak_terms & set(terms))
            if overlap >= max(1, len(weak_terms) // 2):
                hits.append(item.term)
        return hits
