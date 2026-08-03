#!/usr/bin/env python3
"""
tsugime MCP server.

サービスやファイルの「継ぎ目」に成り立つべき対応関係を宣言しておき、
**今ずれているものを答える。**

既存の連携ツール（Zapier、n8n、MCP ゲートウェイの類）は「A が起きたら B をやれ」
という命令形で、実行する側にある。tsugime は実行しない。**一致しているかを見る。**
インフラの世界では確立した考え方（Terraform / ArgoCD の drift detection）だが、
それを「手元の道具どうしの継ぎ目」に持ってきたものは無かった。

決定的な部分（読み出しと差分）はここで完結する。曖昧な部分——
「このノートとこの issue は同じものを指しているか」——は、
ずれを受け取った側（AI）が判断する。**その境界が設計の要。**

規則の場所:
    TSUGIME_CONFIG 環境変数 → なければ ~/.nagi/tsugime.toml
    → なければ カレントの tsugime.toml

stdio で動かす:
    python server.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

import reconcile
import sources

mcp = FastMCP("tsugime_mcp")

READ_ONLY: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def config_path() -> Path:
    """規則ファイルの場所を決める。見つからなければ、探した場所を全部言う。"""
    env = os.environ.get("TSUGIME_CONFIG")
    if env:
        # **指定された先が無いときに別の候補へ落ちない。**
        # 「A を指したつもりで B を検査して緑が出る」のは、
        # この道具が防ごうとしているものそのもの。
        p = Path(env).expanduser()
        if not p.is_file():
            raise reconcile.RuleError(
                f"TSUGIME_CONFIG が指す規則ファイルが無い: {p}"
                "（指定された先が無いとき、別の候補は探さない）"
            )
        return p
    tried: list[Path] = []
    for cand in [
        Path.home() / ".nagi" / "tsugime.toml",
        Path.cwd() / "tsugime.toml",
        Path(__file__).parent / "tsugime.toml",
    ]:
        if cand.is_file():
            return cand
        tried.append(cand)
    raise reconcile.RuleError(
        "規則ファイルが見つからない。探した場所: "
        + " / ".join(str(t) for t in tried)
        + "  TSUGIME_CONFIG で明示できる"
    )


def _load() -> tuple[Path, list[reconcile.Rule]]:
    p = config_path()
    return p, reconcile.load_rules(p)


@mcp.tool(
    name="tsugime_rules",
    annotations={"title": "List Declared Seams", **READ_ONLY},
)
def tsugime_rules() -> dict[str, Any]:
    """宣言されている対応関係の一覧を返す。まだ何も読み出さない。

    「この環境では何が一致しているべきか」を確認するために使う。
    ずれを知りたいときは tsugime_check。

    Returns:
        dict: {"config": str, "rules": [{"name", "title", "direction",
        "left", "right", "note"}]}
    """
    path, rules = _load()
    return {
        "config": str(path),
        "rules": [
            {
                "name": r.name,
                "title": r.title,
                "direction": r.direction,
                "direction_means": reconcile.DIRECTIONS[r.direction],
                "left": {"kind": r.left.get("kind"), "path": r.left.get("path")},
                "right": {"kind": r.right.get("kind"), "path": r.right.get("path")},
                "note": r.note,
            }
            for r in rules
        ],
    }


@mcp.tool(
    name="tsugime_check",
    annotations={"title": "Check Seams For Drift", **READ_ONLY},
)
def tsugime_check(rule: str | None = None, limit: int = 50) -> dict[str, Any]:
    """宣言と実際を突き合わせて、ずれている項目を返す。

    何も直さない。**気づくだけ。** 索引に無いファイルを消すのか索引に足すのかは、
    ここからは判断できない。中身を見て決めること。

    ずれの各項目には「見つかった側での出どころ」が付く。パスと行番号なので、
    報告をそのまま鵜呑みにせず、その場で確かめられる。

    Args:
        rule (Optional[str]): 名前を指定すると、その規則だけを見る。
            省略すると宣言された全部を見る。
        limit (int): 1 規則あたり返すずれの上限。既定 50。
            超えた分は truncated に件数だけ残す。

    Returns:
        dict: {"config", "summary": {...}, "results": [...]}。
        summary は rules / in_sync / drifted / errored / drift_items。
        各 result には drift（片側に無い鍵）と value_mismatches（両側にあるが
        値が食い違う鍵）の両方が入る。**drift が空でも ok とは限らない。**
        common_count は values_agree で実際に突き合わせた鍵の数。0 なら
        「一致」ではなく「何も見ていない」。
    """
    path, rules = _load()
    outcomes = reconcile.check_all(rules, only=rule)
    results = []
    for o in outcomes:
        shown = o.drift[: max(0, int(limit))]
        results.append({
            "rule": o.rule.name,
            "title": o.rule.title,
            "ok": o.ok,
            "error": o.error,
            "left_count": o.left_count,
            "right_count": o.right_count,
            "left_label": o.rule.left_label,
            "right_label": o.rule.right_label,
            "note": o.rule.note,
            "common_count": o.common_count,
            "drift": [
                {"key": d.key, "missing_from": d.missing_from, "found_at": d.found_at}
                for d in shown
            ],
            "truncated": max(0, len(o.drift) - len(shown)),
            # values_agree の結果はここにしか出ない。落とすと MCP から見たとき
            # 「drift が空 = ずれなし」に見えてしまう。
            "value_mismatches": [
                {"key": m.key,
                 "left_value": str(m.left_value), "right_value": str(m.right_value),
                 "left_at": str(m.left_where), "right_at": str(m.right_where)}
                for m in o.value_mismatches[: max(0, int(limit))]
            ],
            "value_mismatches_truncated": max(
                0, len(o.value_mismatches) - max(0, int(limit))),
        })
    return {
        "config": str(path),
        "summary": reconcile.summarise(outcomes),
        "results": results,
    }


@mcp.tool(
    name="tsugime_explain",
    annotations={"title": "Enumerate Both Sides Of A Seam", **READ_ONLY},
)
def tsugime_explain(rule: str, limit: int = 200) -> dict[str, Any]:
    """1 つの規則について、左右それぞれの鍵を全部並べる。

    tsugime_check が出したずれが腑に落ちないときに使う。
    **たいていは「鍵の作り方が意図と違う」**（拡張子が付いている、大文字小文字、
    パスかファイル名か）で、それはここを見れば分かる。

    Args:
        rule (str): 規則名。tsugime_rules で確認できる。
        limit (int): 片側あたり返す鍵の上限。既定 200。

    Returns:
        dict: {"rule", "direction", "left": {"count", "keys": {鍵: 出どころ}},
        "right": {...}}
    """
    _, rules = _load()
    target = next((r for r in rules if r.name == rule), None)
    if target is None:
        raise reconcile.RuleError(
            f"その名前の規則が無い: {rule}"
            f"（あるのは {', '.join(r.name for r in rules)}）"
        )
    out: dict[str, Any] = {
        "rule": target.name,
        "title": target.title,
        "direction": target.direction,
        "direction_means": reconcile.DIRECTIONS[target.direction],
    }
    for side, spec, label in (
        ("left", target.left, target.left_label),
        ("right", target.right, target.right_label),
    ):
        try:
            keys = sources.read(spec)
            items = sorted(keys.items())[: max(0, int(limit))]
            out[side] = {
                "label": label,
                "kind": spec.get("kind"),
                "path": spec.get("path"),
                "count": len(keys),
                "keys": {k: str(w) for k, w in items},
                "truncated": max(0, len(keys) - len(items)),
            }
        except sources.SourceError as e:
            out[side] = {"label": label, "error": str(e)}
    return out


if __name__ == "__main__":
    mcp.run()
