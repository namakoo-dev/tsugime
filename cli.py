#!/usr/bin/env python3
"""tsugime のコマンドライン。

MCP を通さずに、そのまま走らせるための入口。**hook や CI から呼ぶのはこちら。**
`sources.py` / `reconcile.py` と同じく標準ライブラリだけで動くので、
仮想環境を有効にしていない Python でも走る。

    python cli.py                      # 全部の規則を見る
    python cli.py --rule memory-indexed
    python cli.py --strict             # ずれがあれば exit 1
    python cli.py --json               # 機械が読む形

規則ファイルは -c で指定。省略時は server.py と同じ順で探す。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import reconcile


def find_config(explicit: str | None = None) -> Path:
    """規則ファイルを探す。見つからなければ、探した場所を全部言う。

    **명示的に指定されたものは、無ければそこで失敗させる。**
    指定した先が無いときに黙って別の候補へ落ちると、
    「A を検査したつもりで B を検査して緑が出る」ことになる。
    それはこの道具が防ごうとしているものそのもの。
    """
    named_sources = (("-c", explicit),
                     ("TSUGIME_CONFIG", os.environ.get("TSUGIME_CONFIG")))
    for named, value in named_sources:
        if value:
            p = Path(value).expanduser()
            if not p.is_file():
                raise reconcile.RuleError(
                    f"{named} が指す規則ファイルが無い: {p}"
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
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tsugime",
        description="宣言した対応関係と実際を突き合わせ、ずれを出す（直さない）",
    )
    p.add_argument("-c", "--config", help="規則ファイル")
    p.add_argument("-r", "--rule", help="この名前の規則だけを見る")
    p.add_argument("--strict", action="store_true",
                   help="ずれ、または読めない規則があれば exit 1")
    p.add_argument("--json", action="store_true", help="機械が読む形で出す")
    p.add_argument("--limit", type=int, default=20,
                   help="1 規則あたり表示するずれの上限（既定 20）")
    args = p.parse_args(argv)

    try:
        path = find_config(args.config)
        rules = reconcile.load_rules(path)
        outcomes = reconcile.check_all(rules, only=args.rule)
    except reconcile.RuleError as e:
        print(f"tsugime: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "config": str(path),
            "summary": reconcile.summarise(outcomes),
            "results": [
                {
                    "rule": o.rule.name,
                    "title": o.rule.title,
                    "ok": o.ok,
                    "error": o.error,
                    "left_count": o.left_count,
                    "right_count": o.right_count,
                    "drift": [
                        {"key": d.key, "missing_from": d.missing_from,
                         "found_at": d.found_at}
                        for d in o.drift
                    ],
                }
                for o in outcomes
            ],
        }, ensure_ascii=False, indent=2))
    else:
        print(reconcile.render(outcomes, limit=args.limit))

    if args.strict:
        # **読めなかった規則も失敗として扱う。** 見ていないものを
        # 「ずれていない」と数えるのは、この道具が一番やってはいけないこと。
        if any(o.error or o.drift for o in outcomes):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
