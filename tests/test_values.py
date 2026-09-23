"""値の一致を見る機能の検査。

`values_agree` 方向（共通鍵の値比較）、`regex` アダプタの新設、
既存アダプタ（sqlite / json / http_json / frontmatter）が値を返せるようになった分、
そして既存 3 方向・既存の秘密の扱いが壊れていないことを固定する。

fixture はすべて tmp_path 上に作る。ホームディレクトリや実環境のファイルは読まない。
"""
from __future__ import annotations

import json
import sqlite3
import urllib.request

import pytest

import reconcile
import sources

# ---------------------------------------------------------------------------
# values_agree — 判定本体
# ---------------------------------------------------------------------------

def _rule(direction, left, right, **kw):
    return reconcile.Rule(
        name="r", direction=direction, left=left, right=right,
        left_label=kw.pop("left_label", "左"), right_label=kw.pop("right_label", "右"),
        **kw,
    )


def test_value_mismatch_reports_both_values_and_both_wheres(tmp_path) -> None:
    """共通鍵の値が食い違うとき、両側の値と両側の出どころが報告に出る。"""
    left = tmp_path / "left.txt"
    left.write_text("version=1.0.0\n", encoding="utf-8")
    right = tmp_path / "right.txt"
    right.write_text("version=2.0.0\n", encoding="utf-8")
    rule = _rule(
        "values_agree",
        {"kind": "regex", "path": str(left), "pattern": r"(?P<key>\w+)=(?P<value>.+)"},
        {"kind": "regex", "path": str(right), "pattern": r"(?P<key>\w+)=(?P<value>.+)"},
        left_label="左ファイル", right_label="右ファイル",
    )
    out = reconcile.check(rule)
    assert len(out.value_mismatches) == 1
    m = out.value_mismatches[0]
    assert m.key == "version"
    assert m.left_value == "1.0.0"
    assert m.right_value == "2.0.0"
    assert m.left_where == f"{left}:1"
    assert m.right_where == f"{right}:1"
    assert not out.ok


def test_values_agree_only_reports_keys_present_on_both_sides(tmp_path) -> None:
    """片側にしか無い鍵は values_agree では報告されない（存在チェックは別方向の仕事）。"""
    left = tmp_path / "left.txt"
    left.write_text("a=1\nonly_left=9\n", encoding="utf-8")
    right = tmp_path / "right.txt"
    right.write_text("a=1\nonly_right=9\n", encoding="utf-8")
    rule = _rule(
        "values_agree",
        {"kind": "regex", "path": str(left), "pattern": r"(?P<key>\w+)=(?P<value>.+)"},
        {"kind": "regex", "path": str(right), "pattern": r"(?P<key>\w+)=(?P<value>.+)"},
    )
    out = reconcile.check(rule)
    assert out.value_mismatches == []
    assert out.common_count == 1
    assert out.ok


def test_values_agree_zero_common_keys_reports_the_count(tmp_path) -> None:
    """共通鍵 0 件のときも、それが「一致」ではなく件数として見えること。"""
    left = tmp_path / "left.txt"
    left.write_text("only_left=1\n", encoding="utf-8")
    right = tmp_path / "right.txt"
    right.write_text("only_right=1\n", encoding="utf-8")
    rule = _rule(
        "values_agree",
        {"kind": "regex", "path": str(left), "pattern": r"(?P<key>\w+)=(?P<value>.+)"},
        {"kind": "regex", "path": str(right), "pattern": r"(?P<key>\w+)=(?P<value>.+)"},
    )
    out = reconcile.check(rule)
    assert out.common_count == 0
    assert out.value_mismatches == []
    rendered = reconcile.render([out])
    assert "共通鍵 0 件" in rendered


def test_values_agree_with_a_value_incapable_source_fails(tmp_path) -> None:
    """値を持てない源（dir）を values_agree に使うと失敗する。黙って「全部一致」にはしない。"""
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    (left_dir / "a.txt").write_text("", encoding="utf-8")
    (right_dir / "a.txt").write_text("", encoding="utf-8")
    rule = _rule(
        "values_agree",
        {"kind": "dir", "path": str(left_dir), "only": "files"},
        {"kind": "dir", "path": str(right_dir), "only": "files"},
    )
    out = reconcile.check(rule)
    assert out.error is not None
    assert not out.ok


def test_values_agree_with_a_value_capable_source_that_produced_no_value_fails(
    tmp_path,
) -> None:
    """kind としては値を持てても、この読み出しで実際に値が取れていなければ失敗する。

    sqlite の 1 列クエリは kind="sqlite" なので値を持てる源ではあるが、
    この特定の query では値が付かない。NO_VALUE 同士を「一致」させない。
    """
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (name TEXT)")
    con.execute("INSERT INTO t VALUES ('shared')")
    con.commit()
    con.close()
    rule = _rule(
        "values_agree",
        {"kind": "sqlite", "path": str(db), "query": "SELECT name FROM t"},
        {"kind": "sqlite", "path": str(db), "query": "SELECT name FROM t"},
    )
    out = reconcile.check(rule)
    assert out.error is not None


def test_existing_three_directions_are_unaffected_by_values_agree_addition(tmp_path) -> None:
    """既存 3 方向（left_subset_right / right_subset_left / equal）の挙動が変わっていない。"""
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    (left_dir / "shared.txt").write_text("", encoding="utf-8")
    (right_dir / "shared.txt").write_text("", encoding="utf-8")
    (left_dir / "only-left.txt").write_text("", encoding="utf-8")
    (right_dir / "only-right.txt").write_text("", encoding="utf-8")

    left_spec = {"kind": "dir", "path": str(left_dir), "only": "files"}
    right_spec = {"kind": "dir", "path": str(right_dir), "only": "files"}

    out = reconcile.check(_rule("left_subset_right", left_spec, right_spec))
    assert [d.key for d in out.drift] == ["only-left.txt"]
    assert out.value_mismatches == []
    assert out.common_count is None

    out = reconcile.check(_rule("right_subset_left", left_spec, right_spec))
    assert [d.key for d in out.drift] == ["only-right.txt"]

    out = reconcile.check(_rule("equal", left_spec, right_spec))
    assert {d.key for d in out.drift} == {"only-left.txt", "only-right.txt"}


# ---------------------------------------------------------------------------
# regex アダプタ — (a) 固定鍵 + 捕獲値
# ---------------------------------------------------------------------------

def test_regex_fixed_key_captures_group_one_as_value(tmp_path) -> None:
    """(a) key を指定すると、鍵は固定でその値、値は捕獲グループ 1。"""
    f = tmp_path / "pyproject.toml"
    f.write_text('name = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    keys = sources.read({
        "kind": "regex", "path": str(f),
        "pattern": r'version\s*=\s*"([^"]+)"', "key": "version",
    })
    assert set(keys) == {"version"}
    assert keys["version"].value == "1.2.3"


def test_regex_fixed_key_line_number_is_one_based(tmp_path) -> None:
    """regex の行番号は 1 始まりで、実際にマッチした行を指す。"""
    f = tmp_path / "pyproject.toml"
    f.write_text('name = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    keys = sources.read({
        "kind": "regex", "path": str(f),
        "pattern": r'version\s*=\s*"([^"]+)"', "key": "version",
    })
    assert keys["version"].line == 2


def test_regex_fixed_key_takes_first_match_only(tmp_path) -> None:
    """複数回マッチしたら最初の 1 件を採る（_apply の setdefault と同じ流儀）。"""
    f = tmp_path / "log.txt"
    f.write_text('version = "1.0.0"\nversion = "9.9.9"\n', encoding="utf-8")
    keys = sources.read({
        "kind": "regex", "path": str(f),
        "pattern": r'version\s*=\s*"([^"]+)"', "key": "version",
    })
    assert keys["version"].value == "1.0.0"
    assert keys["version"].line == 1


# ---------------------------------------------------------------------------
# regex アダプタ — (b) 名前付きグループで複数件
# ---------------------------------------------------------------------------

def test_regex_named_groups_extract_multiple_keys(tmp_path) -> None:
    """(b) 名前付きグループ key/value を使うと、1 ファイルから複数件取れる。"""
    f = tmp_path / "env.txt"
    f.write_text("FOO=1\nBAR=2\n", encoding="utf-8")
    keys = sources.read({
        "kind": "regex", "path": str(f), "pattern": r"(?P<key>[A-Z_]+)=(?P<value>.+)",
    })
    assert keys["FOO"].value == "1"
    assert keys["BAR"].value == "2"
    assert keys["FOO"].line == 1
    assert keys["BAR"].line == 2


def test_regex_key_and_named_groups_together_is_an_error(tmp_path) -> None:
    """key の指定と名前付きグループ (key/value) の併用は SourceError。"""
    f = tmp_path / "env.txt"
    f.write_text("FOO=1\n", encoding="utf-8")
    with pytest.raises(sources.SourceError):
        sources.read({
            "kind": "regex", "path": str(f), "key": "fixed",
            "pattern": r"(?P<key>[A-Z_]+)=(?P<value>.+)",
        })


def test_regex_neither_key_nor_named_groups_is_an_error(tmp_path) -> None:
    """key も無く、名前付きグループも揃っていなければ SourceError。"""
    f = tmp_path / "env.txt"
    f.write_text("FOO=1\n", encoding="utf-8")
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "regex", "path": str(f), "pattern": r"[A-Z_]+=(.+)"})


def test_regex_requires_path(tmp_path) -> None:
    """path は必須。"""
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "regex", "pattern": r"(?P<key>\w+)=(?P<value>.+)"})


def test_regex_normalisation_applies(tmp_path) -> None:
    """他のアダプタと同じ正規化（lower など）が鍵に効く。"""
    f = tmp_path / "env.txt"
    f.write_text("FOO=1\n", encoding="utf-8")
    keys = sources.read({
        "kind": "regex", "path": str(f),
        "pattern": r"(?P<key>[A-Z_]+)=(?P<value>.+)", "lower": True,
    })
    assert set(keys) == {"foo"}


def test_regex_reads_several_files_through_a_glob_list(tmp_path) -> None:
    """★ 索引が「入口 + 棚」に分かれていても 1 つの集合として読める（2026-09-23）。
    ディレクトリ + glob の並びで、当たったファイル全部を走査し、当たらないものは読まない。"""
    (tmp_path / "MEMORY.md").write_text("- [a](a.md) — x\n", encoding="utf-8")
    (tmp_path / "shelf_old.md").write_text("- [b](b.md) — y\n", encoding="utf-8")
    (tmp_path / "note.md").write_text("- [c](c.md) — 棚でない本文の中のリンク\n", encoding="utf-8")
    keys = sources.read({
        "kind": "regex", "path": str(tmp_path), "glob": ["MEMORY.md", "shelf_*.md"],
        "pattern": r"\]\((?P<key>[a-z]+)\.md\)(?P<value>)",
    })
    assert set(keys) == {"a", "b"}
    assert keys["b"].path.endswith("shelf_old.md") and keys["b"].line == 1


def test_regex_glob_that_matches_nothing_is_an_error(tmp_path) -> None:
    """当たるファイルが 1 つも無ければ黙って空集合にしない（equal が恒真になる）。"""
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "regex", "path": str(tmp_path), "glob": ["nope_*.md"],
                      "pattern": r"(?P<key>\w+)(?P<value>)"})


# ---------------------------------------------------------------------------
# sqlite — 2 列 / 1 列 / 3 列
# ---------------------------------------------------------------------------

def test_sqlite_two_columns_second_becomes_value(tmp_path) -> None:
    """query が 2 列返すなら、1 列目=鍵、2 列目=値。"""
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (name TEXT, ver TEXT)")
    con.execute("INSERT INTO t VALUES ('pkg-a', '1.0.0')")
    con.commit()
    con.close()
    keys = sources.read({
        "kind": "sqlite", "path": str(db), "query": "SELECT name, ver FROM t",
    })
    assert keys["pkg-a"].value == "1.0.0"


def test_sqlite_one_column_has_no_value(tmp_path) -> None:
    """query が 1 列だけなら今どおり値なし。"""
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (name TEXT)")
    con.execute("INSERT INTO t VALUES ('pkg-a')")
    con.commit()
    con.close()
    keys = sources.read({"kind": "sqlite", "path": str(db), "query": "SELECT name FROM t"})
    assert keys["pkg-a"].value is sources.NO_VALUE


def test_sqlite_three_columns_is_an_error(tmp_path) -> None:
    """3 列以上返す query は SourceError。"""
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (a TEXT, b TEXT, c TEXT)")
    con.execute("INSERT INTO t VALUES ('a', 'b', 'c')")
    con.commit()
    con.close()
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "sqlite", "path": str(db), "query": "SELECT a, b, c FROM t"})


# ---------------------------------------------------------------------------
# json — オブジェクトからの値、入れ子の JSON 文字列化
# ---------------------------------------------------------------------------

def test_json_object_values_are_attached_to_keys(tmp_path) -> None:
    """pointer の先がオブジェクトなら、キー=鍵・値=値。"""
    f = tmp_path / "data.json"
    f.write_text('{"a": 1, "b": "x"}', encoding="utf-8")
    keys = sources.read({"kind": "json", "path": str(f)})
    assert keys["a"].value == 1
    assert keys["b"].value == "x"


def test_json_nested_value_becomes_json_string(tmp_path) -> None:
    """値が dict/list なら JSON 文字列にする。"""
    f = tmp_path / "data.json"
    f.write_text('{"a": {"nested": true}, "b": [1, 2]}', encoding="utf-8")
    keys = sources.read({"kind": "json", "path": str(f)})
    assert json.loads(keys["a"].value) == {"nested": True}
    assert json.loads(keys["b"].value) == [1, 2]


def test_json_array_root_still_has_no_values(tmp_path) -> None:
    """配列のときは今どおり値を持たない（既存 92 件の前提を壊さない）。"""
    f = tmp_path / "data.json"
    f.write_text('["a", "b"]', encoding="utf-8")
    keys = sources.read({"kind": "json", "path": str(f)})
    assert keys["a"].value is sources.NO_VALUE


# ---------------------------------------------------------------------------
# frontmatter — value_field
# ---------------------------------------------------------------------------

def test_frontmatter_value_field_attaches_a_value(tmp_path) -> None:
    """value_field を指定すると、field の値=鍵、value_field の値=値。"""
    d = tmp_path / "notes"
    d.mkdir()
    (d / "n.md").write_text(
        "---\nslug: hello\nversion: \"3\"\n---\nbody\n", encoding="utf-8"
    )
    keys = sources.read({
        "kind": "frontmatter", "path": str(d), "field": "slug", "value_field": "version",
    })
    assert keys["hello"].value == "3"


def test_frontmatter_without_value_field_behaves_as_before(tmp_path) -> None:
    """value_field を指定しなければ今どおり（値なし）。"""
    d = tmp_path / "notes"
    d.mkdir()
    (d / "n.md").write_text("---\nslug: hello\n---\nbody\n", encoding="utf-8")
    keys = sources.read({"kind": "frontmatter", "path": str(d), "field": "slug"})
    assert keys["hello"].value is sources.NO_VALUE


# ---------------------------------------------------------------------------
# http_json — 値取得と、token が漏れないことが崩れていないこと
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_json_object_root_attaches_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """http_json でも pointer の先がオブジェクトなら値が付く。"""
    def handler(req, timeout=None):
        return _FakeResponse(json.dumps({"foo": "bar", "n": 5}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", handler)
    keys = sources.read({"kind": "http_json", "url": "https://api.example.com/x"})
    assert keys["foo"].value == "bar"
    assert keys["n"].value == 5


def test_http_json_token_still_does_not_leak_into_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """値取得を足しても、token が例外メッセージに漏れないことは崩れていない。"""
    import urllib.error

    monkeypatch.setenv("TSUGIME_TEST_VALUES_TOKEN", "top-secret-value-xyz")

    def handler(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", handler)
    with pytest.raises(sources.SourceError) as exc_info:
        sources.read({
            "kind": "http_json",
            "url": "https://api.example.com/x",
            "token_env": "TSUGIME_TEST_VALUES_TOKEN",
        })
    assert "top-secret-value-xyz" not in str(exc_info.value)


def test_http_json_query_string_still_dropped_from_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """値取得を足しても、URL のクエリ文字列が失敗メッセージから落ちることは崩れていない。"""
    import urllib.error

    def handler(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", handler)
    with pytest.raises(sources.SourceError) as exc_info:
        sources.read({
            "kind": "http_json",
            "url": "https://api.example.com/x?token=super-secret-query-value",
        })
    assert "super-secret-query-value" not in str(exc_info.value)
