"""资料读取与切块。

三种资料各自保留「可回查的位置」：

* ``.md``  按标题切小节，锚点是行号区间
* ``.txt`` 按空行切段，锚点同样是行号区间
* ``.pdf`` 按**物理页**切，锚点是页码（长页再按窗口细分）

所有切块都满足：``body`` 是原文的连续子串，``anchor`` 能让人翻回原文件对应位置。
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {".md", ".markdown", ".txt", ".pdf"}
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FILE_LIKE = re.compile(r"\.(doc|docx|pdf|tex|dvi)$", re.IGNORECASE)

# pypdf 对缺失字体表会打大量 warning，正文抽取本身没问题，这里只保留错误。
logging.getLogger("pypdf").setLevel(logging.ERROR)


@dataclass(frozen=True)
class Chunk:
    """一个可检索、可引用的原文片段。"""

    chunk_id: str
    doc_id: str
    doc_title: str
    path: str
    kind: str
    anchor: str
    page: int
    section: str
    ordinal: int
    body: str
    line_start: int
    line_end: int
    char_start: int
    char_end: int

    @property
    def citation(self) -> str:
        return f"{self.path}#{self.anchor}"

    @property
    def location(self) -> str:
        """人类可读的位置说明。"""

        if self.page:
            return f"{self.path} 第 {self.page} 页"
        return f"{self.path} 第 {self.line_start}-{self.line_end} 行"

    def searchable(self) -> str:
        """写进全文索引的投影：标题 + 小节名 + 正文，让标题词也能被命中。"""

        parts = [self.doc_title, self.section]
        return "\n".join(part for part in parts if part) + "\n" + self.body


@dataclass
class Document:
    doc_id: str
    path: str
    title: str
    kind: str
    revision: str
    page_count: int
    chunks: list[Chunk] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(chunk.body) for chunk in self.chunks)


@dataclass
class LoadReport:
    documents: list[Document]
    skipped: list[tuple[str, str]]


def doc_id_for(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return relative.with_suffix("").as_posix()


def revision_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def load_corpus(root: Path, *, max_chars: int = 900) -> LoadReport:
    root = root.resolve()
    documents: list[Document] = []
    skipped: list[tuple[str, str]] = []
    titles = _load_titles(root)
    if not root.is_dir():
        return LoadReport(documents, [(str(root), "目录不存在")])
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            document = _load_one(root, path, max_chars=max_chars)
        except Exception as error:  # noqa: BLE001 - 单文件失败不能拖垮整库
            skipped.append((path.name, f"{type(error).__name__}: {error}"))
            continue
        if not document.chunks:
            skipped.append((path.name, "没有可用文本"))
            continue
        override = titles.get(document.doc_id)
        if override:
            document = _retitle(document, override)
        documents.append(document)
    return LoadReport(documents, skipped)


def _load_titles(root: Path) -> dict[str, str]:
    """``corpus/manifest.yaml`` 可以给资料起个干净的显示名。"""

    path = root / "manifest.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - 清单坏了不影响正文
        return {}
    titles = payload.get("titles") if isinstance(payload, dict) else None
    return {str(key): str(value) for key, value in (titles or {}).items()}


def _retitle(document: Document, title: str) -> Document:
    return Document(
        doc_id=document.doc_id,
        path=document.path,
        title=title,
        kind=document.kind,
        revision=document.revision,
        page_count=document.page_count,
        chunks=[
            Chunk(**{**chunk.__dict__, "doc_title": title})
            for chunk in document.chunks
        ],
    )


def _load_one(root: Path, path: Path, *, max_chars: int) -> Document:
    data = path.read_bytes()
    doc_id = doc_id_for(root, path)
    revision = revision_of(data)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(root, path, doc_id, revision, max_chars=max_chars)
    text = _decode(data)
    if suffix in {".md", ".markdown"}:
        return _load_markdown(path, doc_id, revision, text, max_chars=max_chars)
    return _load_text(path, doc_id, revision, text, max_chars=max_chars)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------- markdown


def _load_markdown(path: Path, doc_id: str, revision: str, text: str, *, max_chars: int) -> Document:
    lines = text.splitlines()
    title = path.stem
    sections: list[tuple[str, int, list[str]]] = []  # (标题, 起始行, 内容行)
    current_heading = ""
    current_start = 1
    current_lines: list[str] = []
    for index, line in enumerate(lines, start=1):
        match = _HEADING.match(line)
        if match:
            if any(item.strip() for item in current_lines):
                sections.append((current_heading, current_start, current_lines))
            current_heading = match.group(2).strip()
            current_start = index
            current_lines = []
            if not sections and index == 1:
                title = current_heading or title
            continue
        current_lines.append(line)
    sections.append((current_heading, current_start, current_lines))

    chunks: list[Chunk] = []
    current_char = 0
    for heading, start_line, body_lines in sections:
        raw = "\n".join(body_lines)
        base = _offset_of_line(text, start_line - 1) + (len(raw) - len(raw.lstrip("\n")))
        body = raw.strip("\n")
        if not body.strip():
            current_char += len(body)
            continue
        for ordinal, (window, char_start) in enumerate(_windows(body, max_chars)):
            line_start, line_end = _line_span(text, base + char_start, len(window))
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#{len(chunks):04d}",
                    doc_id=doc_id,
                    doc_title=title,
                    path=doc_id + path.suffix,
                    kind="md",
                    anchor=f"L{line_start}-{line_end}",
                    page=0,
                    section=heading,
                    ordinal=len(chunks),
                    body=window,
                    line_start=line_start,
                    line_end=line_end,
                    char_start=base + char_start,
                    char_end=base + char_start + len(window),
                )
            )
        current_char = base + len(body)
    return Document(doc_id, str(path), title, "md", revision, 0, chunks)


# ------------------------------------------------------------------------- text


def _load_text(path: Path, doc_id: str, revision: str, text: str, *, max_chars: int) -> Document:
    title = path.stem
    chunks: list[Chunk] = []
    for window, char_start in _windows(text, max_chars):
        line_start, line_end = _line_span(text, char_start, len(window))
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}#{len(chunks):04d}",
                doc_id=doc_id,
                doc_title=title,
                path=doc_id + path.suffix,
                kind="txt",
                anchor=f"L{line_start}-{line_end}",
                page=0,
                section="",
                ordinal=len(chunks),
                body=window,
                line_start=line_start,
                line_end=line_end,
                char_start=char_start,
                char_end=char_start + len(window),
            )
        )
    return Document(doc_id, str(path), title, "txt", revision, 0, chunks)


# -------------------------------------------------------------------------- pdf


def _load_pdf(root: Path, path: Path, doc_id: str, revision: str, *, max_chars: int) -> Document:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    meta_title = ""
    try:
        meta_title = (reader.metadata or {}).get("/Title") or ""
    except Exception:  # noqa: BLE001 - 元数据坏了不影响正文
        meta_title = ""
    title = str(meta_title).strip() or path.stem
    if _FILE_LIKE.search(title) or title.lower().startswith("microsoft word"):
        title = path.stem
    chunks: list[Chunk] = []
    page_count = 0
    for page_number, page in enumerate(reader.pages, start=1):
        page_count = page_number
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        for part, (window, char_start) in enumerate(_windows(text, max_chars)):
            anchor = f"p{page_number}" if part == 0 else f"p{page_number}-{part}"
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#{'p%03d' % page_number}{'' if part == 0 else '-%d' % part}",
                    doc_id=doc_id,
                    doc_title=title,
                    path=doc_id + path.suffix,
                    kind="pdf",
                    anchor=anchor,
                    page=page_number,
                    section="",
                    ordinal=len(chunks),
                    body=window,
                    line_start=0,
                    line_end=0,
                    char_start=char_start,
                    char_end=char_start + len(window),
                )
            )
    return Document(doc_id, str(path), title, "pdf", revision, page_count, chunks)


# --------------------------------------------------------------------- helpers


def _windows(text: str, max_chars: int) -> list[tuple[str, int]]:
    """按空行分段再合并，保证每块不超过 ``max_chars`` 且尽量落在段落边界。"""

    paragraphs = _paragraph_spans(text)
    if not paragraphs:
        return []
    windows: list[tuple[str, int]] = []
    start = paragraphs[0][0]
    end = paragraphs[0][1]
    for para_start, para_end in paragraphs[1:]:
        if para_end - start <= max_chars:
            end = para_end
            continue
        windows.append((text[start:end].strip("\n"), start))
        start, end = para_start, para_end
    windows.append((text[start:end].strip("\n"), start))
    result: list[tuple[str, int]] = []
    for window, offset in windows:
        if len(window) <= max_chars:
            result.append((window, offset))
            continue
        result.extend(_hard_split(window, offset, max_chars))
    return [(body, offset) for body, offset in result if body.strip()]


def _hard_split(text: str, offset: int, max_chars: int) -> list[tuple[str, int]]:
    pieces: list[tuple[str, int]] = []
    cursor = 0
    while cursor < len(text):
        cut = min(cursor + max_chars, len(text))
        if cut < len(text):
            boundary = max(text.rfind("\n", cursor, cut), text.rfind("。", cursor, cut), text.rfind(". ", cursor, cut))
            if boundary > cursor + max_chars // 2:
                cut = boundary + 1
        piece = text[cursor:cut].strip("\n")
        if piece.strip():
            pieces.append((piece, offset + cursor))
        cursor = cut
    return pieces


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in re.finditer(r"\n\s*\n", text):
        span = (cursor, match.start())
        if text[span[0] : span[1]].strip():
            spans.append(span)
        cursor = match.end()
    if text[cursor:].strip():
        spans.append((cursor, len(text)))
    return spans


def _line_span(text: str, char_start: int, length: int) -> tuple[int, int]:
    start = text.count("\n", 0, max(0, char_start)) + 1
    end = text.count("\n", 0, min(len(text), char_start + length)) + 1
    return start, max(start, end)


def _offset_of_line(text: str, line_index: int) -> int:
    if line_index <= 0:
        return 0
    cursor = 0
    for _ in range(line_index):
        found = text.find("\n", cursor)
        if found < 0:
            return len(text)
        cursor = found + 1
    return cursor
