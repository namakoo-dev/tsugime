"""宣言した対応関係と、実際に読み出した集合を突き合わせる。

規則は 1 つにつき「左」「右」「どちらがどちらを含むべきか」。
それだけで、索引の抜け・幽霊エントリ・二重管理のずれはほぼ表せる。

**直さない。気づくだけ。** 何を直すべきかは、ずれの中身を見た人（か AI）が決める。
自動修復を持たないのは機能不足ではなく、境界の置き方である。
索引に無いファイルを消すのか索引に足すのかは、ここからは判断できない。
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sources import Keys, SourceError, read

DIRECTIONS = {
    "left_subset_right": "左のすべてが右に現れる",
    "right_subset_left": "右のすべてが左に現れる",
    "equal": "左と右が完全に一致する",
}


class RuleError(Exception):
    """規則の書き方が誤っている。"""


@dataclass(frozen=True)
class Rule:
    name: str
    direction: str
    left: dict[str, Any]
    right: dict[str, Any]
    title: str = ""
    left_label: str = "左"
    right_label: str = "右"
    note: str = ""


@dataclass
class Drift:
    """片側にあって、もう片側に無かった鍵。"""

    key: str
    missing_from: str   # どちら側に無いか（ラベル）
    found_at: str       # 見つかった側での出どころ


@dataclass
class Outcome:
    rule: Rule
    drift: list[Drift] = field(default_factory=list)
    left_count: int = 0
    right_count: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.drift


def load_rules(path: str | Path) -> list[Rule]:
    path = Path(path).expanduser()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise RuleError(f"規則ファイルが無い: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise RuleError(f"TOML として読めない: {path} ({e})") from e

    entries = raw.get("rule")
    if not entries:
        raise RuleError("`[[rule]]` が 1 つも無い")

    seen: set[str] = set()
    rules: list[Rule] = []
    for i, e in enumerate(entries, 1):
        name = e.get("name")
        if not name:
            raise RuleError(f"{i} 番目の規則に `name` が無い")
        if name in seen:
            raise RuleError(f"規則名が重複している: {name}")
        seen.add(name)
        direction = e.get("direction", "left_subset_right")
        if direction not in DIRECTIONS:
            raise RuleError(
                f"[{name}] direction が不正: {direction}"
                f"（使えるのは {', '.join(DIRECTIONS)}）"
            )
        for side in ("left", "right"):
            if not isinstance(e.get(side), dict):
                raise RuleError(f"[{name}] `[rule.{side}]` が要る")
        rules.append(Rule(
            name=name,
            direction=direction,
            left=e["left"],
            right=e["right"],
            title=e.get("title", ""),
            left_label=e.get("left_label", "左"),
            right_label=e.get("right_label", "右"),
            note=e.get("note", ""),
        ))
    return rules


def _missing(src: Keys, dst: Keys, missing_from: str) -> list[Drift]:
    return [
        Drift(key=k, missing_from=missing_from, found_at=str(w))
        for k, w in sorted(src.items()) if k not in dst
    ]


def check(rule: Rule) -> Outcome:
    try:
        left = read(rule.left)
        right = read(rule.right)
    except SourceError as e:
        return Outcome(rule=rule, error=str(e))
    except Exception as e:
        # **1 本の規則の書き損じで、全部の結果を失わせない。**
        # アダプタは想定外の例外も投げうる（設定値の型違いなど）。
        # それをここで止めずに通すと、健全な規則の判定まで道連れになり、
        # 「今どこがずれているか」を答えるという役目そのものが果たせなくなる。
        # 種類まで出すのは、SourceError にすべき経路の取りこぼしを見つけるため。
        return Outcome(rule=rule, error=f"想定外の失敗: {type(e).__name__}: {e}")

    out = Outcome(rule=rule, left_count=len(left), right_count=len(right))
    if rule.direction in ("left_subset_right", "equal"):
        out.drift += _missing(left, right, rule.right_label)
    if rule.direction in ("right_subset_left", "equal"):
        out.drift += _missing(right, left, rule.left_label)
    return out


def check_all(rules: list[Rule], only: str | None = None) -> list[Outcome]:
    if only:
        rules = [r for r in rules if r.name == only]
        if not rules:
            raise RuleError(f"その名前の規則が無い: {only}")
    return [check(r) for r in rules]


def summarise(outcomes: list[Outcome]) -> dict[str, Any]:
    return {
        "rules": len(outcomes),
        "in_sync": sum(1 for o in outcomes if o.ok),
        "drifted": sum(1 for o in outcomes if o.error is None and o.drift),
        "errored": sum(1 for o in outcomes if o.error),
        "drift_items": sum(len(o.drift) for o in outcomes),
    }


def render(outcomes: list[Outcome], *, limit: int = 20) -> str:
    lines: list[str] = []
    s = summarise(outcomes)
    lines.append(
        f"規則 {s['rules']} 件 — 一致 {s['in_sync']} / ずれ {s['drifted']} / "
        f"読めず {s['errored']}   ずれた項目 {s['drift_items']} 件"
    )
    for o in outcomes:
        lines.append("")
        head = f"[{o.rule.name}]"
        if o.rule.title:
            head += f" {o.rule.title}"
        lines.append(head)
        if o.error:
            lines.append(f"  ✗ 読めなかった: {o.error}")
            continue
        lines.append(
            f"  {o.rule.left_label} {o.left_count} 件 / "
            f"{o.rule.right_label} {o.right_count} 件 — "
            f"{DIRECTIONS[o.rule.direction]}"
        )
        if not o.drift:
            lines.append("  ✓ ずれなし")
            continue
        by_side: dict[str, list[Drift]] = {}
        for d in o.drift:
            by_side.setdefault(d.missing_from, []).append(d)
        for side, items in by_side.items():
            lines.append(f"  ✗ {side} に無い {len(items)} 件:")
            for d in items[:limit]:
                lines.append(f"      {d.key}    （{d.found_at} にはある）")
            if len(items) > limit:
                lines.append(f"      … 他 {len(items) - limit} 件")
        if o.rule.note:
            lines.append(f"  » {o.rule.note}")
    return "\n".join(lines)
