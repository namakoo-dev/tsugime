"""後から足した部分の検査。

`after` / `until`（見出しの区間指定）と `git` アダプタは、
最初のテストが書かれた後に足した。**書いた本人が「たぶん動く」と思っている状態**は
まだ検査ではないので、ここで固定する。

`after` / `until` は実環境の誤報から生まれた。1 枚の文書に意味の違う節があり、
それを区別せずに突き合わせて、正しい記載を「消し忘れの残骸」と誤って報告した。
その再発を防ぐのがこのファイルの主目的。
"""
from __future__ import annotations

import sqlite3

import pytest

import sources

# ---------------------------------------------------------------------------
# headings: after / until
# ---------------------------------------------------------------------------

INDEX = """\
# 索引

## グローバル

### alpha
### beta

## ドメイン特化 (プロジェクト local)

以下は project local のみ。global には配置しない。

### gamma

## その他

### delta
"""


@pytest.fixture()
def index_file(tmp_path):
    p = tmp_path / "INDEX.md"
    p.write_text(INDEX, encoding="utf-8")
    return p


def test_until_stops_at_the_named_section(index_file):
    """until より後ろの見出しを拾わない（節ごとに意味が違う文書を扱えること）。"""
    keys = sources.read({
        "kind": "headings", "path": str(index_file),
        "level": 3, "until": "ドメイン特化",
    })
    assert sorted(keys) == ["alpha", "beta"]


def test_after_starts_at_the_named_section(index_file):
    """after より前の見出しを拾わない。"""
    keys = sources.read({
        "kind": "headings", "path": str(index_file),
        "level": 3, "after": "ドメイン特化",
    })
    assert sorted(keys) == ["delta", "gamma"]


def test_after_and_until_select_one_section(index_file):
    """after と until を併せると 1 つの節だけになる。"""
    keys = sources.read({
        "kind": "headings", "path": str(index_file),
        "level": 3, "after": "ドメイン特化", "until": "その他",
    })
    assert sorted(keys) == ["gamma"]


def test_without_after_until_everything_is_one_set(index_file):
    """区間を指定しないと全部が 1 つの集合になる（誤報が起きた元の挙動）。"""
    keys = sources.read({"kind": "headings", "path": str(index_file), "level": 3})
    assert sorted(keys) == ["alpha", "beta", "delta", "gamma"]


def test_after_that_never_matches_yields_nothing(index_file):
    """after が当たらなければ 0 件。**例外にはしない**（件数で気づかせる）。"""
    keys = sources.read({
        "kind": "headings", "path": str(index_file),
        "level": 3, "after": "存在しない見出し",
    })
    assert keys == {}


def test_section_bounds_keep_line_numbers(index_file):
    """区間で絞っても行番号は元の文書のまま（確かめに行けること）。"""
    keys = sources.read({
        "kind": "headings", "path": str(index_file),
        "level": 3, "after": "ドメイン特化", "until": "その他",
    })
    assert keys["gamma"].line == 12


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

def _make_repo(root, name, *, remote=None, branches=(), tags=(), packed=()):
    repo = root / name
    git = repo / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "refs" / "tags").mkdir(parents=True)
    if remote:
        (git / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n"
            f'[remote "origin"]\n\turl = {remote}\n\tfetch = +refs/heads/*\n',
            encoding="utf-8",
        )
    for b in branches:
        (git / "refs" / "heads" / b).write_text("0" * 40 + "\n", encoding="utf-8")
    for t in tags:
        (git / "refs" / "tags" / t).write_text("0" * 40 + "\n", encoding="utf-8")
    if packed:
        lines = ["# pack-refs with: peeled fully-peeled sorted"]
        lines += [f"{'1' * 40} {ref}" for ref in packed]
        (git / "packed-refs").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return repo


def test_git_repos_lists_only_directories_with_a_git(tmp_path):
    """.git を持つものだけをリポジトリと数える。"""
    _make_repo(tmp_path, "with_git")
    (tmp_path / "plain").mkdir()
    keys = sources.read({"kind": "git", "path": str(tmp_path), "what": "repos"})
    assert sorted(keys) == ["with_git"]


def test_git_remotes_reads_urls_with_line_numbers(tmp_path):
    """リモート URL を行番号つきで返す。"""
    repo = _make_repo(tmp_path, "r", remote="https://example.invalid/x.git")
    keys = sources.read({"kind": "git", "path": str(repo), "what": "remotes"})
    assert list(keys) == ["https://example.invalid/x.git"]
    assert keys["https://example.invalid/x.git"].line == 4


def test_git_branches_and_tags(tmp_path):
    """ローカルの参照をそれぞれ読む。"""
    repo = _make_repo(tmp_path, "r", branches=("main", "dev"), tags=("v1",))
    assert sorted(sources.read(
        {"kind": "git", "path": str(repo), "what": "branches"})) == ["dev", "main"]
    assert sorted(sources.read(
        {"kind": "git", "path": str(repo), "what": "tags"})) == ["v1"]


def test_git_reads_packed_refs_too(tmp_path):
    """packed-refs にしか無い参照も拾う（緩めると本物の差分を見落とす）。"""
    repo = _make_repo(tmp_path, "r", branches=("main",),
                      packed=("refs/heads/old", "refs/tags/v9"))
    assert sorted(sources.read(
        {"kind": "git", "path": str(repo), "what": "branches"})) == ["main", "old"]
    assert sorted(sources.read(
        {"kind": "git", "path": str(repo), "what": "tags"})) == ["v9"]


def test_git_follows_a_worktree_pointer_file(tmp_path):
    """.git がファイル（worktree）でも、指し先を辿る。"""
    real = _make_repo(tmp_path, "real", branches=("main",))
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {real / '.git'}\n", encoding="utf-8")
    assert sorted(sources.read(
        {"kind": "git", "path": str(wt), "what": "branches"})) == ["main"]


def test_git_rejects_an_unknown_what(tmp_path):
    """知らない `what` は黙って 0 件にせず、はっきり失敗させる。"""
    repo = _make_repo(tmp_path, "r")
    with pytest.raises(sources.SourceError) as e:
        sources.read({"kind": "git", "path": str(repo), "what": "commits"})
    assert "commits" in str(e.value)


def test_git_on_a_non_repository_is_an_error(tmp_path):
    """git ではない場所を指したら失敗する（0 件と区別する）。"""
    (tmp_path / "plain").mkdir()
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "git", "path": str(tmp_path / "plain"),
                      "what": "branches"})


def test_git_never_shells_out(tmp_path, monkeypatch):
    """外部の git コマンドを呼ばない（環境で結果が変わらないこと）。"""
    import subprocess

    def boom(*a, **k):
        raise AssertionError("外部コマンドを呼んでいる")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    repo = _make_repo(tmp_path, "r", remote="https://example.invalid/x.git",
                      branches=("main",))
    sources.read({"kind": "git", "path": str(repo), "what": "remotes"})
    sources.read({"kind": "git", "path": str(repo), "what": "branches"})


def test_git_normalisation_applies(tmp_path):
    """他のアダプタと同じ正規化が効く。"""
    _make_repo(tmp_path, "Alpha")
    _make_repo(tmp_path, "beta")
    keys = sources.read({"kind": "git", "path": str(tmp_path), "what": "repos",
                         "lower": True, "exclude": ["beta"]})
    assert sorted(keys) == ["alpha"]


def test_sqlite_is_still_read_only_after_the_new_adapters(tmp_path):
    """アダプタを足しても sqlite の読み取り専用が崩れていないこと。"""
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x TEXT)")
    con.execute("INSERT INTO t VALUES ('a')")
    con.commit()
    con.close()
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "sqlite", "path": str(db), "query": "DELETE FROM t"})
    con = sqlite3.connect(db)
    assert [r[0] for r in con.execute("SELECT x FROM t")] == ["a"]
    con.close()
