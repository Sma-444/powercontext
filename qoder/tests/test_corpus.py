"""切块与位置标注：引用必须能回到原文。"""

from __future__ import annotations

from pathlib import Path

from duban.corpus import load_corpus


def test_markdown_sections_keep_line_ranges(corpus_dir: Path) -> None:
    report = load_corpus(corpus_dir)
    documents = {document.doc_id: document for document in report.documents}
    assert set(documents) == {"notes/raft", "notes/dynamo"}

    raft = documents["notes/raft"]
    assert raft.title == "Raft 笔记"
    assert raft.chunks, "至少要切出一个片段"
    for chunk in raft.chunks:
        assert chunk.anchor.startswith("L")
        assert chunk.line_start >= 1
        assert chunk.line_end >= chunk.line_start
        assert chunk.body.strip()
        # 片段正文必须真的是原文的子串
        source = (corpus_dir / "notes/raft.md").read_text(encoding="utf-8")
        assert chunk.body.splitlines()[0].strip() in source


def test_chunk_ids_are_stable_and_unique(corpus_dir: Path) -> None:
    first = load_corpus(corpus_dir)
    second = load_corpus(corpus_dir)
    ids_first = [chunk.chunk_id for document in first.documents for chunk in document.chunks]
    ids_second = [chunk.chunk_id for document in second.documents for chunk in document.chunks]
    assert ids_first == ids_second
    assert len(ids_first) == len(set(ids_first))


def test_revision_follows_content(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    path = corpus / "a.md"
    path.write_text("# 标题\n\n第一版内容。", encoding="utf-8")
    before = load_corpus(corpus).documents[0].revision
    path.write_text("# 标题\n\n第二版内容。", encoding="utf-8")
    after = load_corpus(corpus).documents[0].revision
    assert before != after


def test_long_section_is_split_with_offsets(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    body = "。".join(["这是一句用来凑长度的话"] * 200)
    (corpus / "long.md").write_text(f"# 长文\n\n{body}", encoding="utf-8")
    document = load_corpus(corpus, max_chars=300).documents[0]
    assert len(document.chunks) > 1
    assert all(len(chunk.body) <= 320 for chunk in document.chunks)
    assert [chunk.char_start for chunk in document.chunks] == sorted(
        chunk.char_start for chunk in document.chunks
    )
