"""コマンドラインの検査。

**exit code がこのファイルの主題。** hook や CI から呼ぶとき、
戻り値だけが判断材料になる。表示が綺麗でも戻り値が間違っていれば、
壊れた状態が緑のまま通る。
"""
from __future__ import annotations

import json

import pytest

import cli


def _write(tmp_path, *, left_extra=(), rule_name="r1", path_exists=True):
    left = tmp_path / "left"
    left.mkdir()
    (left / "a.md").write_text("x", encoding="utf-8")
    for name in left_extra:
        (left / name).write_text("x", encoding="utf-8")
    idx = tmp_path / "idx.md"
    idx.write_text("- [a](a.md)\n", encoding="utf-8")
    toml = tmp_path / "t.toml"
    src = str(left) if path_exists else str(tmp_path / "missing")
    toml.write_text(
        f'[[rule]]\nname = "{rule_name}"\ntitle = "t"\n'
        f'direction = "left_subset_right"\n'
        f'[rule.left]\nkind = "dir"\npath = {src!r}\nglob = "*.md"\n'
        f'[rule.right]\nkind = "markdown_links"\npath = {str(idx)!r}\n',
        encoding="utf-8",
    )
    return toml


def test_in_sync_returns_zero_even_with_strict(tmp_path, capsys):
    """ずれが無ければ --strict でも 0。"""
    toml = _write(tmp_path)
    assert cli.main(["-c", str(toml), "--strict"]) == 0
    assert "ずれなし" in capsys.readouterr().out


def test_drift_returns_one_only_with_strict(tmp_path, capsys):
    """ずれがあっても、--strict を付けなければ 0。付ければ 1。"""
    toml = _write(tmp_path, left_extra=["b.md"])
    assert cli.main(["-c", str(toml)]) == 0
    assert cli.main(["-c", str(toml), "--strict"]) == 1
    assert "b.md" in capsys.readouterr().out


def test_unreadable_rule_also_fails_under_strict(tmp_path):
    """★読めなかった規則も --strict では失敗にする。

    見ていないものを「ずれていない」と数えるのが、この道具の最悪の壊れ方。
    """
    toml = _write(tmp_path, path_exists=False)
    assert cli.main(["-c", str(toml), "--strict"]) == 1


def test_explicit_config_that_is_missing_fails_without_falling_back(tmp_path, capsys):
    """★-c が指す先が無いとき、別の候補を探さずに 2 で落ちる。

    黙って別のファイルに落ちると「A を検査したつもりで B が緑」になる。
    この道具が防ごうとしているものそのものなので、そこで止める。
    """
    assert cli.main(["-c", str(tmp_path / "nope.toml")]) == 2
    err = capsys.readouterr().err
    assert "nope.toml" in err
    assert "別の候補は探さない" in err


def test_no_config_anywhere_says_where_it_looked(tmp_path, monkeypatch, capsys):
    """何も指定が無くどこにも無ければ、探した場所を全部言って 2。"""
    monkeypatch.delenv("TSUGIME_CONFIG", raising=False)
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path / "nohome")
    monkeypatch.setattr(cli.Path, "cwd", lambda: tmp_path / "nocwd")
    module_cfg = cli.Path(cli.__file__).resolve().parent / "tsugime.toml"
    orig = cli.Path.is_file
    monkeypatch.setattr(
        cli.Path, "is_file",
        lambda self: False if self.resolve() == module_cfg else orig(self))
    assert cli.main([]) == 2
    assert "探した場所" in capsys.readouterr().err


def test_broken_config_returns_two(tmp_path, capsys):
    """規則が壊れているのも 2。ずれと混同しない。"""
    bad = tmp_path / "bad.toml"
    bad.write_text('[[rule]]\ntitle = "name が無い"\n', encoding="utf-8")
    assert cli.main(["-c", str(bad)]) == 2
    assert "name" in capsys.readouterr().err


def test_json_output_is_parseable_and_carries_counts(tmp_path, capsys):
    """--json は機械が読める形で、件数と出どころを落とさない。"""
    toml = _write(tmp_path, left_extra=["b.md"])
    assert cli.main(["-c", str(toml), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["summary"]) == {
        "rules", "in_sync", "drifted", "errored", "drift_items"}
    res = payload["results"][0]
    assert res["left_count"] == 2 and res["right_count"] == 1
    assert res["drift"][0]["key"] == "b.md"
    assert res["drift"][0]["found_at"]


def test_rule_filter_selects_one(tmp_path, capsys):
    """--rule で 1 つだけ見る。"""
    toml = _write(tmp_path, rule_name="only-this")
    assert cli.main(["-c", str(toml), "-r", "only-this"]) == 0
    assert "規則 1 件" in capsys.readouterr().out


def test_unknown_rule_name_returns_two(tmp_path, capsys):
    """存在しない規則名は 2。黙って全部を見たりしない。"""
    toml = _write(tmp_path)
    assert cli.main(["-c", str(toml), "-r", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_env_var_is_used_when_no_flag(tmp_path, monkeypatch, capsys):
    """-c が無ければ TSUGIME_CONFIG を使う。"""
    toml = _write(tmp_path)
    monkeypatch.setenv("TSUGIME_CONFIG", str(toml))
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 0


def test_flag_beats_env_var(tmp_path, monkeypatch):
    """-c は TSUGIME_CONFIG より強い。"""
    good = _write(tmp_path)
    monkeypatch.setenv("TSUGIME_CONFIG", str(tmp_path / "nope.toml"))
    assert cli.main(["-c", str(good), "--strict"]) == 0


def test_limit_truncates_display_but_not_the_verdict(tmp_path, capsys):
    """--limit は表示だけを削る。判定は全件で下す。"""
    toml = _write(tmp_path, left_extra=[f"x{i}.md" for i in range(5)])
    assert cli.main(["-c", str(toml), "--limit", "2", "--strict"]) == 1
    out = capsys.readouterr().out
    assert "他 3 件" in out


@pytest.mark.parametrize("args", [["--strict"], ["--json"], []])
def test_never_writes_anything(tmp_path, args, capsys):
    """どの呼び方でも、対象のファイルを書き換えない。"""
    toml = _write(tmp_path, left_extra=["b.md"])
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    cli.main(["-c", str(toml), *args])
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
