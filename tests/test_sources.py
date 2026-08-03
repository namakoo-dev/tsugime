"""sources.py: 各アダプタが正しく「鍵 -> Where」を返すか、正規化・除外・エラー経路を検査する。

fixture はすべて tmp_path 上に作る。ホームディレクトリや実環境のファイルは読まない。
"""
from __future__ import annotations

import sqlite3

import pytest

import sources

# ---------------------------------------------------------------------------
# Where.__str__ の書式
# ---------------------------------------------------------------------------

def test_where_str_format_with_and_without_line() -> None:
    """Where.__str__ は line があれば path:line、無ければ path のみを返す。"""
    assert str(sources.Where("a/b.md", 5)) == "a/b.md:5"
    assert str(sources.Where("a/b.md")) == "a/b.md"
    assert str(sources.Where("a/b.md", None)) == "a/b.md"


# ---------------------------------------------------------------------------
# 各アダプタが Where を返すこと（行番号を持つもの / 持たないもの）
# ---------------------------------------------------------------------------

def test_dir_returns_where_without_line(tmp_path) -> None:
    """dir アダプタは行番号を持たない Where を返す。"""
    d = tmp_path / "items"
    d.mkdir()
    (d / "a.txt").write_text("x", encoding="utf-8")
    keys = sources.read({"kind": "dir", "path": str(d), "only": "files"})
    w = keys["a.txt"]
    assert w.line is None
    assert str(w) == str(d / "a.txt")


def test_markdown_links_line_numbers_are_one_based(tmp_path) -> None:
    """markdown_links は 2 行目・3 行目のリンクの行番号を 1 始まりで正しく返す。"""
    f = tmp_path / "index.md"
    f.write_text(
        "# タイトル\n"
        "[one](target-one.md)\n"
        "[two](target-two.md)\n",
        encoding="utf-8",
    )
    keys = sources.read({"kind": "markdown_links", "path": str(f)})
    assert keys["target-one.md"].line == 2
    assert keys["target-two.md"].line == 3
    assert str(keys["target-one.md"]) == f"{f}:2"


def test_wikilinks_line_numbers_are_one_based(tmp_path) -> None:
    """wikilinks も 2 行目・3 行目の [[...]] の行番号を 1 始まりで正しく返す。"""
    f = tmp_path / "note.md"
    f.write_text(
        "見出し\n"
        "[[Alpha]] について\n"
        "[[Beta|表示名]] も参照\n",
        encoding="utf-8",
    )
    keys = sources.read({"kind": "wikilinks", "path": str(f)})
    assert keys["Alpha"].line == 2
    assert keys["Beta"].line == 3
    assert str(keys["Beta"]) == f"{f}:3"


def test_headings_line_numbers_are_one_based(tmp_path) -> None:
    """headings も 2 行目・3 行目の見出しの行番号を 1 始まりで正しく返す。"""
    f = tmp_path / "doc.md"
    f.write_text(
        "intro\n"
        "## foo-skill\n"
        "## bar-skill\n",
        encoding="utf-8",
    )
    keys = sources.read({"kind": "headings", "path": str(f), "level": 2})
    assert keys["foo-skill"].line == 2
    assert keys["bar-skill"].line == 3


def test_markdown_links_line_numbers_survive_crlf(tmp_path) -> None:
    """CRLF 改行のファイルでも行番号が崩れないこと（Windows 実ファイル対策）。"""
    f = tmp_path / "index.md"
    f.write_bytes(
        b"# title\r\n"
        b"[one](target-one.md)\r\n"
        b"[two](target-two.md)\r\n"
    )
    keys = sources.read({"kind": "markdown_links", "path": str(f)})
    assert keys["target-one.md"].line == 2
    assert keys["target-two.md"].line == 3


def test_frontmatter_returns_where_without_line(tmp_path) -> None:
    """frontmatter アダプタは行番号を持たない Where を返す。"""
    d = tmp_path / "notes"
    d.mkdir()
    (d / "n.md").write_text("---\nslug: hello\n---\nbody\n", encoding="utf-8")
    keys = sources.read({"kind": "frontmatter", "path": str(d), "field": "slug"})
    assert keys["hello"].line is None
    assert str(keys["hello"]) == str(d / "n.md")


def test_json_returns_where_without_line(tmp_path) -> None:
    """json アダプタは行番号を持たない Where を返す。"""
    f = tmp_path / "data.json"
    f.write_text('{"a": 1, "b": 2}', encoding="utf-8")
    keys = sources.read({"kind": "json", "path": str(f)})
    assert keys["a"].line is None
    assert str(keys["a"]) == str(f)


def test_sqlite_returns_where_without_line(tmp_path) -> None:
    """sqlite アダプタは行番号を持たない Where を返す。"""
    db = tmp_path / "x.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (name TEXT)")
    conn.execute("INSERT INTO t VALUES ('foo')")
    conn.commit()
    conn.close()
    keys = sources.read({"kind": "sqlite", "path": str(db), "query": "SELECT name FROM t"})
    assert keys["foo"].line is None
    assert str(keys["foo"]) == str(db)


# ---------------------------------------------------------------------------
# 正規化の組み合わせ
# ---------------------------------------------------------------------------

def test_normalize_strip_suffix_basename_lower_combined(tmp_path) -> None:
    """strip_suffix -> basename -> lower の順で鍵が正規化されることを固定する。"""
    f = tmp_path / "index.md"
    f.write_text("[link](Notes/Sub/File.md)\n", encoding="utf-8")
    keys = sources.read({
        "kind": "markdown_links",
        "path": str(f),
        "strip_suffix": ".md",
        "basename": True,
        "lower": True,
    })
    assert set(keys) == {"file"}


def test_strip_suffix_is_case_sensitive(tmp_path) -> None:
    """strip_suffix は大文字小文字を区別する。lower を併用しない限り .MD は剥がれない。"""
    f = tmp_path / "index.md"
    f.write_text("[link](Notes/File.MD)\n", encoding="utf-8")
    keys = sources.read({"kind": "markdown_links", "path": str(f), "strip_suffix": ".md"})
    assert set(keys) == {"Notes/File.MD"}


def test_basename_handles_both_slash_styles(tmp_path) -> None:
    """basename はフォワードスラッシュ・バックスラッシュどちらの区切りでも効く。"""
    backslash_target = "Folder" + "\\" + "Sub" + "\\" + "two.txt"  # Folder\Sub\two.txt
    f = tmp_path / "index.md"
    f.write_text(
        "[a](Folder/Sub/one.txt)\n"
        f"[b]({backslash_target})\n",
        encoding="utf-8",
    )
    keys = sources.read({"kind": "markdown_links", "path": str(f), "basename": True})
    assert set(keys) == {"one.txt", "two.txt"}


# ---------------------------------------------------------------------------
# exclude — 正規化の前と後、両方で効く
# ---------------------------------------------------------------------------

def test_exclude_applies_before_and_after_normalization(tmp_path) -> None:
    """exclude は正規化前の生の鍵にも、正規化後の鍵にも効く（実装は両方で照合している）。"""
    d = tmp_path / "items"
    d.mkdir()
    (d / "SKIP.txt").write_text("", encoding="utf-8")     # 正規化前の生の鍵で一致
    (d / "Final.TXT").write_text("", encoding="utf-8")    # lower 後 "final.txt" で一致
    (d / "keep.txt").write_text("", encoding="utf-8")
    keys = sources.read({
        "kind": "dir",
        "path": str(d),
        "only": "files",
        "lower": True,
        "exclude": ["SKIP.txt", "final.txt"],
    })
    assert set(keys) == {"keep.txt"}


# ---------------------------------------------------------------------------
# エラー経路 — すべて SourceError になること
# ---------------------------------------------------------------------------

def test_dir_missing_path_raises_source_error(tmp_path) -> None:
    """存在しないディレクトリを指すと SourceError。"""
    missing = tmp_path / "no-such-dir"
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "dir", "path": str(missing)})


def test_unknown_kind_raises_source_error() -> None:
    """知らない kind を指定すると SourceError。"""
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "no-such-kind"})


def test_frontmatter_without_field_raises_source_error(tmp_path) -> None:
    """frontmatter アダプタに field 指定が無いと SourceError。"""
    d = tmp_path / "notes"
    d.mkdir()
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "frontmatter", "path": str(d)})


def test_json_pointer_unreachable_raises_source_error(tmp_path) -> None:
    """json pointer が届かない場所を指すと SourceError。"""
    f = tmp_path / "data.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "json", "path": str(f), "pointer": "/b/c"})


def test_sqlite_non_select_query_raises_source_error(tmp_path) -> None:
    """sqlite の query が SELECT で始まらないと SourceError。"""
    db = tmp_path / "x.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (n TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "sqlite", "path": str(db), "query": "DELETE FROM t"})


# ---------------------------------------------------------------------------
# sqlite は読み取り専用で開いていること
# ---------------------------------------------------------------------------

def _make_db(path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (name TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [("a",), ("b",)])
    conn.commit()
    conn.close()


def _read_rows(path) -> list[str]:
    conn = sqlite3.connect(str(path))
    rows = [r[0] for r in conn.execute("SELECT name FROM t ORDER BY name")]
    conn.close()
    return rows


def test_sqlite_delete_query_rejected_and_db_unchanged(tmp_path) -> None:
    """DELETE を query に渡すと SourceError になり、DB の中身は変わらない。"""
    db = tmp_path / "ro.db"
    _make_db(db)
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "sqlite", "path": str(db), "query": "DELETE FROM t"})
    assert _read_rows(db) == ["a", "b"]


def test_sqlite_update_query_rejected_and_db_unchanged(tmp_path) -> None:
    """UPDATE を query に渡すと SourceError になり、DB の中身は変わらない。"""
    db = tmp_path / "ro.db"
    _make_db(db)
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "sqlite", "path": str(db), "query": "UPDATE t SET name = 'z'"})
    assert _read_rows(db) == ["a", "b"]
