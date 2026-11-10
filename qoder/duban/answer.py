"""抽取式作答：不调用任何外部模型。

为什么坚持抽取式：评审拿到仓库时不一定有 API Key，而「哪一条结论来自哪一页」
必须是可核对的。所以默认路径是——从检索到的原文里挑句子、按原顺序给出，
每一条都挂 ``path#anchor``；模型只在用户自己配置时才参与（见 README 的「可选」一节）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from duban.memory import MemorySnapshot
from duban.retrieve import Retrieval, terms_of
from duban.store import Hit

_DEPTH_BULLETS = {"brief": 2, "standard": 3, "deep": 4}
_SENTENCE_END = "。！？!?；;"


@dataclass
class Bullet:
    text: str
    chunk_id: str
    citation: str
    location: str
    doc_title: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "chunk_id": self.chunk_id,
            "citation": self.citation,
            "location": self.location,
            "doc_title": self.doc_title,
            "score": round(self.score, 4),
        }


@dataclass
class Citation:
    chunk_id: str
    doc_id: str
    doc_title: str
    path: str
    anchor: str
    page: int
    section: str
    location: str
    citation: str
    snippet: str
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "path": self.path,
            "anchor": self.anchor,
            "page": self.page,
            "section": self.section,
            "location": self.location,
            "citation": self.citation,
            "snippet": self.snippet,
            "score": round(self.score, 4),
            "reasons": self.reasons,
        }


@dataclass
class Answer:
    question: str
    headline: str
    bullets: list[Bullet]
    citations: list[Citation]
    mode: str
    memory_note: str
    memory_used: list[str]
    primer: Citation | None
    stats: dict[str, object]
    followups: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "headline": self.headline,
            "bullets": [bullet.as_dict() for bullet in self.bullets],
            "citations": [citation.as_dict() for citation in self.citations],
            "mode": self.mode,
            "memory_note": self.memory_note,
            "memory_used": self.memory_used,
            "primer": self.primer.as_dict() if self.primer else None,
            "stats": self.stats,
            "followups": self.followups,
        }


def build_answer(
    question: str,
    retrieval: Retrieval,
    snapshot: MemorySnapshot | None = None,
) -> Answer:
    depth = "standard"
    if snapshot:
        depth = str(snapshot.profile.get("depth") or "standard")
    budget = _DEPTH_BULLETS.get(depth, 3)

    bullets: list[Bullet] = []
    seen: list[str] = []
    for hit in retrieval.hits:
        for sentence, score in _rank_sentences(hit, retrieval.terms):
            if _duplicate(sentence, seen):
                continue
            seen.append(sentence)
            bullets.append(
                Bullet(
                    text=_trim(sentence),
                    chunk_id=hit.chunk_id,
                    citation=hit.citation,
                    location=hit.location,
                    doc_title=hit.doc_title,
                    score=score,
                )
            )
            if len(bullets) >= budget:
                break
        if len(bullets) >= budget:
            break

    citations = [
        Citation(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            doc_title=hit.doc_title,
            path=hit.path,
            anchor=hit.anchor,
            page=hit.page,
            section=hit.section,
            location=hit.location,
            citation=hit.citation,
            snippet=_snippet(hit.body),
            score=retrieval.scores.get(hit.chunk_id, hit.score),
            reasons=retrieval.reasons.get(hit.chunk_id, []),
        )
        for hit in retrieval.hits
    ]

    memory_used: list[str] = []
    notes: list[str] = []
    if retrieval.weak_terms:
        memory_used.extend(f"weak:{term}" for term in retrieval.weak_terms)
        notes.append(f"你之前标记过「{retrieval.weak_terms[0]}」没看懂，这次先补一条更基础的说明。")
    if snapshot and snapshot.last_turn() and snapshot.last_turn().question != question:
        last = snapshot.last_turn()
        if last.docs:
            memory_used.append(f"turn:{last.seq}")
            notes.append(f"上次你问的是「{_trim(last.question, 24)}」，这轮接着往下走。")
    if snapshot and snapshot.progress:
        finished = [item for item in snapshot.progress.values() if item.ratio >= 0.99]
        if finished:
            memory_used.append(f"progress:{len(finished)}")

    headline = _headline(question, retrieval)
    primer = None
    if retrieval.primer is not None:
        primer = Citation(
            chunk_id=retrieval.primer.chunk_id,
            doc_id=retrieval.primer.doc_id,
            doc_title=retrieval.primer.doc_title,
            path=retrieval.primer.path,
            anchor=retrieval.primer.anchor,
            page=retrieval.primer.page,
            section=retrieval.primer.section,
            location=retrieval.primer.location,
            citation=retrieval.primer.citation,
            snippet=_snippet(retrieval.primer.body),
            score=0.0,
            reasons=["weak_primer"],
        )

    return Answer(
        question=question,
        headline=headline,
        bullets=bullets,
        citations=citations,
        mode="extractive",
        memory_note=" ".join(notes),
        memory_used=memory_used,
        primer=primer,
        stats={
            "candidates": retrieval.candidates,
            "hits": len(retrieval.hits),
            "terms": retrieval.terms[:16],
            "variants": retrieval.variants,
        },
        followups=_followups(retrieval, snapshot),
    )


# ----------------------------------------------------------------------- helpers


def _rank_sentences(hit: Hit, terms: list[str]) -> list[tuple[str, float]]:
    sentences = sentences_of(hit.body)
    term_set = set(terms)
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(sentences):
        if not _usable(sentence):
            continue
        body_terms = set(terms_of(sentence))
        matched = len(term_set & body_terms)
        coverage = matched / len(term_set) if term_set else 0.0
        position = 1.0 / (1.0 + index * 0.35)
        length = min(len(sentence), 180) / 180
        scored.append((0.6 * coverage + 0.25 * position + 0.15 * length, index, sentence))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(sentence.strip(), score) for score, _, sentence in scored[:2]]


def _usable(sentence: str) -> bool:
    """句子要能当「结论」用：太短、标题、表格、自测问句都排除。"""

    text = sentence.strip()
    if len(text) < 12:
        return False
    if text.endswith("？") or text.endswith("?"):
        return False
    if text.startswith(("#", "|", "```", "---")):
        return False
    return True


def sentences_of(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    pieces: list[str] = []
    cursor = 0
    for index, char in enumerate(normalized):
        if char in _SENTENCE_END:
            piece = normalized[cursor : index + 1].strip()
            if piece:
                pieces.append(piece)
            cursor = index + 1
    tail = normalized[cursor:].strip()
    if tail:
        pieces.append(tail)
    return pieces or ([normalized] if normalized else [])


def _duplicate(sentence: str, previous: list[str]) -> bool:
    """同一段落里的近义句只留一条：前缀相同或词项重合超过 70% 视为重复。"""

    term_set = set(terms_of(sentence))
    for item in previous:
        if sentence[:24] == item[:24]:
            return True
        other = set(terms_of(item))
        if term_set and other:
            overlap = len(term_set & other) / len(term_set)
            if overlap >= 0.7:
                return True
    return False


def _trim(text: str, limit: int = 220) -> str:
    text = re.sub(r"\*\*|`", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = max(text.rfind("。", 0, limit), text.rfind("；", 0, limit), text.rfind("，", 0, limit))
    if cut > 40:
        return text[: cut + 1]
    # 英文按词边界截断，避免出现 "responsi- bility" 这种半截词
    space = text.rfind(" ", 0, limit)
    if space > limit * 0.6:
        return text[:space].rstrip(" ,;:-") + "…"
    return text[:limit] + "…"


def _snippet(body: str) -> str:
    text = re.sub(r"\*\*|`", "", body)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:200] + ("…" if len(text) > 200 else "")


def _headline(question: str, retrieval: Retrieval) -> str:
    if not retrieval.hits:
        return "资料库里没有找到直接相关的段落。换个说法，或先把相关资料放进 corpus/ 再导入。"
    documents = list(dict.fromkeys(hit.doc_title for hit in retrieval.hits))
    return f"在《{documents[0]}》" + (
        f"等 {len(documents)} 份资料里找到 {len(retrieval.hits)} 处相关段落，"
        if len(documents) > 1
        else f"里找到 {len(retrieval.hits)} 处相关段落，"
    ) + "下面每一条都能点回原文。"


def _followups(retrieval: Retrieval, snapshot: MemorySnapshot | None) -> list[str]:
    ideas: list[str] = []
    if retrieval.hits:
        first = retrieval.hits[0]
        ideas.append(f"把《{first.doc_title}》{first.location.split(' ', 1)[-1]} 的上下文再展开讲讲")
    if retrieval.weak_terms:
        ideas.append(f"我已经弄懂「{retrieval.weak_terms[0]}」了，帮我从薄弱点里划掉")
    if snapshot and snapshot.progress:
        unfinished = [item for item in snapshot.progress.values() if item.ratio < 0.99]
        if unfinished:
            ideas.append(f"接着读《{unfinished[0].doc_id}》，从上次停下的地方继续")
    if retrieval.terms:
        ideas.append(f"「{retrieval.terms[0]}」在这几份资料里的说法一致吗")
    return ideas[:3]
