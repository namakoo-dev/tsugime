"""server.py: config_path() の探索順、MCP ツール 3 本を関数として直接呼ぶテスト。

mcp パッケージが入っていない環境では server.py を import できない。
その場合はこのファイル全体を、理由を明示した上で skip する
（pytest.importorskip は使わない — 理由が pytest の既定メッセージに埋もれるため）。

fixture はすべて tmp_path 上に作る。ホームディレクトリや実環境のファイルは読まない。
FastMCP は起動しない（stdio サーバを立てず、ツール関数を直接呼ぶ）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

if importlib.util.find_spec("mcp") is None:
    pytest.skip(
        "mcp パッケージが未インストールのため server.py を import できない。"
        "このファイルの全テストを skip する。有効化するには `pip install mcp`。",
        allow_module_level=True,
    )

import reconcile
import server

# ---------------------------------------------------------------------------
# config_path() の探索順
# ---------------------------------------------------------------------------

def test_config_path_uses_tsugime_config_env_when_it_exists(tmp_path, monkeypatch) -> None:
    """TSUGIME_CONFIG が指すファイルが存在すれば、それを最優先で使う。"""
    cfg = tmp_path / "rules.toml"
    cfg.write_text("", encoding="utf-8")
    monkeypatch.setenv("TSUGIME_CONFIG", str(cfg))
    assert server.config_path() == cfg


def test_config_path_refuses_to_fall_back_when_tsugime_config_missing(
    tmp_path, monkeypatch
) -> None:
    """★TSUGIME_CONFIG が存在しないパスなら、別の候補を探さずに失敗する。

    以前はホーム配下へフォールバックしていた。**それは誤りだった** —
    「A を指したつもりで B を検査して緑が出る」のは、この道具が防ごうとしている
    ものそのもの。指定された先が無いなら、黙って別のものを見てはいけない。
    """
    missing_env = tmp_path / "does-not-exist.toml"
    monkeypatch.setenv("TSUGIME_CONFIG", str(missing_env))

    fake_home = tmp_path / "fake-home"
    (fake_home / ".nagi").mkdir(parents=True)
    (fake_home / ".nagi" / "tsugime.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    with pytest.raises(reconcile.RuleError) as e:
        server.config_path()
    assert "does-not-exist.toml" in str(e.value)

def test_config_path_raises_when_nowhere_found(tmp_path, monkeypatch) -> None:
    """どこにも規則ファイルが無ければ RuleError で、探した場所が全部メッセージに出る。

    TSUGIME_CONFIG は設定しない。設定されていて存在しない場合はその時点で
    失敗する規約になったので、この探索経路には入らない
    (test_config_path_refuses_to_fall_back_when_tsugime_config_missing を参照)。
    """
    monkeypatch.delenv("TSUGIME_CONFIG", raising=False)

    fake_home = tmp_path / "fake-home2"  # .nagi/tsugime.toml は作らない
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    fake_cwd = tmp_path / "fake-cwd2"
    fake_cwd.mkdir()  # tsugime.toml は作らない
    monkeypatch.setattr(Path, "cwd", lambda: fake_cwd)

    # モジュール隣（server.py と同じディレクトリ）の実際の tsugime.toml を
    # 「無い」ことにして隔離する。実ファイルは削除も読み込みもしない。
    module_cfg = Path(server.__file__).resolve().parent / "tsugime.toml"
    orig_is_file = Path.is_file

    def fake_is_file(self):
        if self.resolve() == module_cfg:
            return False
        return orig_is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    with pytest.raises(reconcile.RuleError) as ei:
        server.config_path()
    msg = str(ei.value)
    assert str(fake_home / ".nagi" / "tsugime.toml") in msg
    assert str(fake_cwd / "tsugime.toml") in msg
    assert str(module_cfg) in msg


# ---------------------------------------------------------------------------
# MCP ツール 3 本を関数として直接呼ぶ（FastMCP は起動しない）
# ---------------------------------------------------------------------------

@pytest.fixture
def configured_rule(tmp_path, monkeypatch):
    """left 3 件・right 0 件の left_subset_right 規則を 1 本作り、TSUGIME_CONFIG で指させる。"""
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    for i in range(3):
        (left_dir / f"item{i}.txt").write_text("", encoding="utf-8")

    rules_toml = tmp_path / "rules.toml"
    rules_toml.write_text(
        "[[rule]]\n"
        'name = "sample"\n'
        'title = "サンプル規則"\n'
        'direction = "left_subset_right"\n'
        'left_label = "左"\n'
        'right_label = "右"\n'
        'note = "テスト用"\n'
        "\n"
        "[rule.left]\n"
        'kind = "dir"\n'
        f'path = "{left_dir.as_posix()}"\n'
        'only = "files"\n'
        "\n"
        "[rule.right]\n"
        'kind = "dir"\n'
        f'path = "{right_dir.as_posix()}"\n'
        'only = "files"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TSUGIME_CONFIG", str(rules_toml))
    return rules_toml, left_dir, right_dir


def test_tsugime_rules_called_directly(configured_rule) -> None:
    """tsugime_rules を関数として直接呼び、規則一覧が正しく返る。"""
    rules_toml, _, _ = configured_rule
    result = server.tsugime_rules()
    assert result["config"] == str(rules_toml)
    assert [r["name"] for r in result["rules"]] == ["sample"]
    assert result["rules"][0]["direction"] == "left_subset_right"


def test_tsugime_check_summary_has_five_keys(configured_rule) -> None:
    """tsugime_check の summary は rules/in_sync/drifted/errored/drift_items の 5 キー。"""
    _ = configured_rule
    result = server.tsugime_check()
    assert set(result["summary"]) == {"rules", "in_sync", "drifted", "errored", "drift_items"}
    assert result["summary"] == {
        "rules": 1,
        "in_sync": 0,
        "drifted": 1,
        "errored": 0,
        "drift_items": 3,
    }


def test_tsugime_check_drift_items_have_three_keys(configured_rule) -> None:
    """tsugime_check の results[].drift[] は key/missing_from/found_at の 3 キー。"""
    _ = configured_rule
    result = server.tsugime_check()
    drift = result["results"][0]["drift"]
    assert len(drift) == 3
    for item in drift:
        assert set(item) == {"key", "missing_from", "found_at"}


def test_tsugime_check_limit_zero_truncates_everything(configured_rule) -> None:
    """limit=0 なら drift は空になり、truncated に全件数が残る。"""
    _ = configured_rule
    result = server.tsugime_check(limit=0)
    r = result["results"][0]
    assert r["drift"] == []
    assert r["truncated"] == 3


def test_tsugime_check_limit_exceeding_drift_count_has_no_truncation(configured_rule) -> None:
    """limit がずれ件数を超えていれば、全件返って truncated は 0。"""
    _ = configured_rule
    result = server.tsugime_check(limit=100)
    r = result["results"][0]
    assert len(r["drift"]) == 3
    assert r["truncated"] == 0


def test_tsugime_explain_called_directly(configured_rule) -> None:
    """tsugime_explain を関数として直接呼び、左右それぞれの鍵と件数が正しく返る。"""
    _ = configured_rule
    result = server.tsugime_explain("sample")
    assert result["left"]["count"] == 3
    assert result["right"]["count"] == 0
    assert set(result["left"]["keys"]) == {"item0.txt", "item1.txt", "item2.txt"}
