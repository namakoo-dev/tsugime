"""reconcile.py: load_rules の検証、check() の方向 3 種、回帰テスト（幽霊エントリ）。

fixture はすべて tmp_path 上に作る。ホームディレクトリや実環境のファイルは読まない。
"""
from __future__ import annotations

import pytest

import reconcile

# ---------------------------------------------------------------------------
# check() — 方向 3 種すべて
# ---------------------------------------------------------------------------

def _make_two_dirs(tmp_path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    (left_dir / "shared.txt").write_text("", encoding="utf-8")
    (right_dir / "shared.txt").write_text("", encoding="utf-8")
    (left_dir / "only-left.txt").write_text("", encoding="utf-8")
    (right_dir / "only-right.txt").write_text("", encoding="utf-8")
    return left_dir, right_dir


def test_direction_left_subset_right_ignores_right_only_items(tmp_path) -> None:
    """left_subset_right は左の不足だけを見る。右にしか無い項目は無視する。"""
    left_dir, right_dir = _make_two_dirs(tmp_path)
    rule = reconcile.Rule(
        name="r",
        direction="left_subset_right",
        left={"kind": "dir", "path": str(left_dir), "only": "files"},
        right={"kind": "dir", "path": str(right_dir), "only": "files"},
        left_label="左ラベル",
        right_label="右ラベル",
    )
    out = reconcile.check(rule)
    assert [d.key for d in out.drift] == ["only-left.txt"]
    assert out.drift[0].missing_from == "右ラベル"


def test_direction_right_subset_left_ignores_left_only_items(tmp_path) -> None:
    """right_subset_left は右の不足だけを見る。左にしか無い項目は無視する。"""
    left_dir, right_dir = _make_two_dirs(tmp_path)
    rule = reconcile.Rule(
        name="r",
        direction="right_subset_left",
        left={"kind": "dir", "path": str(left_dir), "only": "files"},
        right={"kind": "dir", "path": str(right_dir), "only": "files"},
        left_label="左ラベル",
        right_label="右ラベル",
    )
    out = reconcile.check(rule)
    assert [d.key for d in out.drift] == ["only-right.txt"]
    assert out.drift[0].missing_from == "左ラベル"


def test_direction_equal_reports_drift_on_both_sides_with_correct_labels(tmp_path) -> None:
    """equal は両側の不足をそれぞれ正しいラベルの missing_from で報告する。"""
    left_dir, right_dir = _make_two_dirs(tmp_path)
    rule = reconcile.Rule(
        name="r",
        direction="equal",
        left={"kind": "dir", "path": str(left_dir), "only": "files"},
        right={"kind": "dir", "path": str(right_dir), "only": "files"},
        left_label="左ラベル",
        right_label="右ラベル",
    )
    out = reconcile.check(rule)
    by_key = {d.key: d.missing_from for d in out.drift}
    assert by_key == {
        "only-left.txt": "右ラベル",   # 左にしか無い -> 右に無いと報告
        "only-right.txt": "左ラベル",  # 右にしか無い -> 左に無いと報告
    }


# ---------------------------------------------------------------------------
# load_rules の検証 — RuleError とその具体的なメッセージ
# ---------------------------------------------------------------------------

def _write_toml(tmp_path, content: str):
    p = tmp_path / "rules.toml"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_rules_without_rule_table_raises_rule_error(tmp_path) -> None:
    """`[[rule]]` が 1 つも無ければ RuleError で、その旨がメッセージに出る。"""
    p = _write_toml(tmp_path, 'title = "empty"\n')
    with pytest.raises(reconcile.RuleError, match=r"\[\[rule\]\]"):
        reconcile.load_rules(p)


def test_load_rules_missing_name_raises_rule_error(tmp_path) -> None:
    """name の無い規則は RuleError で、何番目の規則かがメッセージに出る。"""
    p = _write_toml(tmp_path, """
[[rule]]
direction = "left_subset_right"

[rule.left]
kind = "dir"
path = "."

[rule.right]
kind = "dir"
path = "."
""")
    with pytest.raises(reconcile.RuleError, match=r"1 番目"):
        reconcile.load_rules(p)


def test_load_rules_duplicate_name_raises_rule_error(tmp_path) -> None:
    """規則名が重複していれば RuleError で、重複した名前がメッセージに出る。"""
    p = _write_toml(tmp_path, """
[[rule]]
name = "dup"

[rule.left]
kind = "dir"
path = "."

[rule.right]
kind = "dir"
path = "."

[[rule]]
name = "dup"

[rule.left]
kind = "dir"
path = "."

[rule.right]
kind = "dir"
path = "."
""")
    with pytest.raises(reconcile.RuleError, match="dup"):
        reconcile.load_rules(p)


def test_load_rules_invalid_direction_raises_rule_error(tmp_path) -> None:
    """direction が不正な値なら RuleError で、規則名と与えた値がメッセージに出る。"""
    p = _write_toml(tmp_path, """
[[rule]]
name = "bad-dir"
direction = "sideways"

[rule.left]
kind = "dir"
path = "."

[rule.right]
kind = "dir"
path = "."
""")
    with pytest.raises(reconcile.RuleError) as ei:
        reconcile.load_rules(p)
    msg = str(ei.value)
    assert "bad-dir" in msg
    assert "sideways" in msg


def test_load_rules_missing_left_raises_rule_error(tmp_path) -> None:
    """`[rule.left]` が無ければ RuleError で、規則名と欠けている側がメッセージに出る。"""
    p = _write_toml(tmp_path, """
[[rule]]
name = "no-left"

[rule.right]
kind = "dir"
path = "."
""")
    with pytest.raises(reconcile.RuleError) as ei:
        reconcile.load_rules(p)
    msg = str(ei.value)
    assert "no-left" in msg
    assert "left" in msg


def test_load_rules_missing_right_raises_rule_error(tmp_path) -> None:
    """`[rule.right]` が無ければ RuleError で、規則名と欠けている側がメッセージに出る。"""
    p = _write_toml(tmp_path, """
[[rule]]
name = "no-right"

[rule.left]
kind = "dir"
path = "."
""")
    with pytest.raises(reconcile.RuleError) as ei:
        reconcile.load_rules(p)
    msg = str(ei.value)
    assert "no-right" in msg
    assert "right" in msg


# ---------------------------------------------------------------------------
# 回帰テスト: 索引に項目があるのに実体が無い（INDEX.md:362 の blender-web-pipeline 再現）
# ---------------------------------------------------------------------------

def test_regression_index_entry_with_no_real_entity_reports_line_number(tmp_path) -> None:
    """索引にあって実体が無いケースで missing_from と found_at（行番号込み）が正しく出る。

    実環境で実際に起きた欠陥（INDEX.md:362 の blender-web-pipeline）の再現。
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "real-skill-a").mkdir()
    (skills_dir / "real-skill-b").mkdir()

    index = tmp_path / "INDEX.md"
    index.write_text(
        "# skills index\n"
        "### real-skill-a\n"
        "### real-skill-b\n"
        "### ghost-skill\n",  # 4 行目: 実体の無い項目
        encoding="utf-8",
    )

    rule = reconcile.Rule(
        name="skills-no-ghosts",
        direction="left_subset_right",
        left={
            "kind": "headings",
            "path": str(index),
            "level": 3,
            "pattern": "^([a-z0-9-]+)",
        },
        right={"kind": "dir", "path": str(skills_dir), "only": "dirs"},
        left_label="INDEX.md",
        right_label="実体",
    )
    out = reconcile.check(rule)

    assert [d.key for d in out.drift] == ["ghost-skill"]
    d = out.drift[0]
    assert d.missing_from == "実体"
    assert d.found_at == f"{index}:4"


def test_one_broken_rule_does_not_take_down_the_others(tmp_path, monkeypatch):
    """★アダプタが想定外の例外を投げても、他の規則の判定は残る。

    1 本の書き損じで全部の結果が消えると、「今どこがずれているか」を
    答えるという役目そのものが果たせなくなる。
    """
    import reconcile as R
    import sources

    left = tmp_path / "left"
    left.mkdir()
    (left / "a.md").write_text("x", encoding="utf-8")
    idx = tmp_path / "idx.md"
    idx.write_text("- [a](a.md)\n", encoding="utf-8")
    toml = tmp_path / "t.toml"
    toml.write_text(
        f'[[rule]]\nname = "healthy"\n'
        f'[rule.left]\nkind = "dir"\npath = {str(left)!r}\nglob = "*.md"\n'
        f'[rule.right]\nkind = "markdown_links"\npath = {str(idx)!r}\n'
        f'[[rule]]\nname = "explodes"\n'
        f'[rule.left]\nkind = "dir"\npath = {str(left)!r}\nglob = "boom"\n'
        f'[rule.right]\nkind = "markdown_links"\npath = {str(idx)!r}\n',
        encoding="utf-8",
    )

    real = sources.read

    def sometimes_explodes(spec):
        if spec.get("glob") == "boom":
            raise TypeError("想定外")
        return real(spec)

    monkeypatch.setattr(R, "read", sometimes_explodes)

    out = R.check_all(R.load_rules(toml))
    by_name = {o.rule.name: o for o in out}
    assert by_name["healthy"].ok, "健全な規則の判定が失われた"
    assert by_name["explodes"].error is not None
    assert "TypeError" in by_name["explodes"].error
    assert R.summarise(out)["errored"] == 1
