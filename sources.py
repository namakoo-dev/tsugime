"""突き合わせる 2 つの側を、それぞれ「鍵の集合」として読み出す。

各アダプタは **鍵 -> 出どころ** を返す。鍵は突き合わせに使う文字列、
出どころは「その鍵をどこで見つけたか」を人が確かめられる形（パスと行）。

出どころを必ず持ち回るのは、ずれを報告したときに
**「本当にそうか」を利用者がその場で検証できるようにするため。**
出どころの無い差分は、こちらの読み違いと区別がつかない。

外部依存なし。標準ライブラリのみ。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SourceError(Exception):
    """読み出せない。設定の誤りか、対象が存在しないか。"""


# 「値を持てなかった」を示す印。None（JSON の null や、実際に空の値）と
# 区別する必要があるので、None をデフォルトにはしない。
NO_VALUE = object()


@dataclass(frozen=True)
class Where:
    """鍵を見つけた場所。値を持てる源では `value` も添える（既定は NO_VALUE = 値なし）。"""

    path: str
    line: int | None = None
    value: Any = NO_VALUE

    def __str__(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


Keys = dict[str, Where]

# 値を持てる源の種類。values_agree はこれ以外の kind を拒む
# （値を持てない源で「一致」を語らせないため）。
VALUE_CAPABLE_KINDS = frozenset({"regex", "sqlite", "json", "http_json", "frontmatter"})

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


def _expand(p: str) -> Path:
    return Path(p).expanduser()


def _norm(key: str, spec: dict[str, Any]) -> str:
    if spec.get("strip_suffix"):
        suf = spec["strip_suffix"]
        if key.endswith(suf):
            key = key[: -len(suf)]
    if spec.get("basename"):
        key = key.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if spec.get("lower"):
        key = key.lower()
    return key.strip()


def _apply(keys: dict[str, Where], spec: dict[str, Any]) -> Keys:
    exclude = set(spec.get("exclude") or ())
    out: Keys = {}
    for k, w in keys.items():
        if k in exclude:
            continue
        nk = _norm(k, spec)
        if not nk or nk in exclude:
            continue
        out.setdefault(nk, w)
    return out


# --------------------------------------------------------------------------
# アダプタ
# --------------------------------------------------------------------------

def _dir(spec: dict[str, Any]) -> Keys:
    """ディレクトリの中身を鍵にする。ファイル名、またはサブディレクトリ名。"""
    root = _expand(spec["path"])
    if not root.is_dir():
        raise SourceError(f"ディレクトリが無い: {root}")
    glob = spec.get("glob", "*")
    only = spec.get("only", "any")  # any | files | dirs
    found: dict[str, Where] = {}
    for p in sorted(root.glob(glob)):
        if only == "files" and not p.is_file():
            continue
        if only == "dirs" and not p.is_dir():
            continue
        found[p.name] = Where(str(p))
    return _apply(found, spec)


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise SourceError(f"読めない: {path} ({e})") from e


def _markdown_links(spec: dict[str, Any]) -> Keys:
    """Markdown の `[題](先)` の *先* を鍵にする。索引ファイル向け。"""
    path = _expand(spec["path"])
    if not path.is_file():
        raise SourceError(f"ファイルが無い: {path}")
    found: dict[str, Where] = {}
    for i, line in enumerate(_lines(path), 1):
        for m in MD_LINK_RE.finditer(line):
            found.setdefault(m.group(1), Where(str(path), i))
    return _apply(found, spec)


def _wikilinks(spec: dict[str, Any]) -> Keys:
    """`[[...]]` の中身を鍵にする。path はファイルでもディレクトリでもよい。"""
    root = _expand(spec["path"])
    files = ([root] if root.is_file()
             else sorted(root.rglob(spec.get("glob", "*.md"))) if root.is_dir()
             else [])
    if not files:
        raise SourceError(f"対象が無い: {root}")
    found: dict[str, Where] = {}
    for f in files:
        for i, line in enumerate(_lines(f), 1):
            for m in WIKILINK_RE.finditer(line):
                found.setdefault(m.group(1).strip(), Where(str(f), i))
    return _apply(found, spec)


def _headings(spec: dict[str, Any]) -> Keys:
    """見出しを鍵にする。`level` で深さを、`pattern` で見出し文からの抽出を指定。

    `after` / `until` で文書の一部だけに絞れる（どちらも見出し行に当てる正規表現）。
    1 枚の文書が節ごとに違う意味を持つのは普通のことで、
    **文書全体を 1 つの集合として扱うと、節の違いが差分に化ける。**
    """
    path = _expand(spec["path"])
    if not path.is_file():
        raise SourceError(f"ファイルが無い: {path}")
    level = int(spec.get("level", 0))
    prefix = "#" * level + " " if level else None
    pat = re.compile(spec["pattern"]) if spec.get("pattern") else None
    after = re.compile(spec["after"]) if spec.get("after") else None
    until = re.compile(spec["until"]) if spec.get("until") else None
    live = after is None
    found: dict[str, Where] = {}
    for i, line in enumerate(_lines(path), 1):
        if not line.startswith("#"):
            continue
        if not live:
            if after.search(line):
                live = True
            continue
        if until and until.search(line):
            break
        if prefix and not line.startswith(prefix):
            continue
        text = line.lstrip("#").strip()
        if pat:
            m = pat.search(text)
            if not m:
                continue
            text = m.group(1) if m.groups() else m.group(0)
        found.setdefault(text, Where(str(path), i))
    return _apply(found, spec)


def _frontmatter(spec: dict[str, Any]) -> Keys:
    """各ファイルの frontmatter から 1 つの項目を取り出して鍵にする。

    YAML は解析しない。`名前: 値` の行を拾うだけ。**入れ子や配列は読めない。**
    読めなかったファイルは `missing` として報告する側に回す（黙って落とさない）。

    `value_field` を指定すると、`field` の値を鍵にするのは変わらず、
    さらに `value_field` の値をその鍵の値として添える。
    指定が無ければ今どおり（値なし）。
    """
    root = _expand(spec["path"])
    if not root.is_dir():
        raise SourceError(f"ディレクトリが無い: {root}")
    field = spec.get("field")
    if not field:
        raise SourceError("frontmatter には `field` が要る")
    value_field = spec.get("value_field")
    fre = re.compile(rf"^{re.escape(field)}\s*:\s*(.+?)\s*$", re.M)
    vre = (re.compile(rf"^{re.escape(value_field)}\s*:\s*(.+?)\s*$", re.M)
           if value_field else None)
    found: dict[str, Where] = {}
    for p in sorted(root.glob(spec.get("glob", "*.md"))):
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = FRONTMATTER_RE.match(text)
        if not fm:
            continue
        m = fre.search(fm.group(1))
        if not m:
            continue
        val = m.group(1).strip().strip("\"'")
        if vre:
            vm = vre.search(fm.group(1))
            where = (Where(str(p), value=vm.group(1).strip().strip("\"'"))
                     if vm else Where(str(p)))
            found.setdefault(val, where)
        else:
            found.setdefault(val, Where(str(p)))
    return _apply(found, spec)


def _json_keys(spec: dict[str, Any]) -> Keys:
    """JSON の中の配列 / オブジェクトを鍵の集合にする。

    `pointer` は `/a/b` 形式（RFC 6901 の簡易版）。
    配列なら要素そのもの（または `field` を指定して各要素の項目）、
    オブジェクトならキーを鍵にする。

    オブジェクトのときは、キー=鍵に加えて値も添える。値が dict/list なら
    比較・表示できるよう JSON 文字列にする。配列のときは今どおり値を持たない。
    """
    path = _expand(spec["path"])
    if not path.is_file():
        raise SourceError(f"ファイルが無い: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SourceError(f"JSON として読めない: {path} ({e})") from e
    node: Any = data
    for part in [p for p in (spec.get("pointer") or "").split("/") if p]:
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError) as e:
                raise SourceError(f"pointer が届かない: {spec['pointer']}") from e
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise SourceError(f"pointer が届かない: {spec['pointer']}")
    field = spec.get("field")
    found: dict[str, Where] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            val = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            found.setdefault(str(k), Where(str(path), value=val))
    elif isinstance(node, list):
        for e in node:
            key = e.get(field) if (field and isinstance(e, dict)) else e
            if key is not None:
                found.setdefault(str(key), Where(str(path)))
    else:
        raise SourceError("pointer の先が配列でもオブジェクトでもない")
    return _apply(found, spec)


def _redact_url(url: str) -> str:
    # クエリ文字列に秘密（トークンなど）が入りうるので、報告からは落とす。
    return url.split("?", 1)[0]


def _http_json(spec: dict[str, Any]) -> Keys:
    """HTTP GET した JSON から鍵の集合を取る。外部サービスとの突き合わせ用。

    `pointer` / `field` の意味は json アダプタと同じ（`/a/b` 形式、配列なら要素か
    `field` で指定した項目、オブジェクトならキー）。

    `token_env` は環境変数名を指定し、その値で `Authorization: Bearer <値>` を付ける。
    **設定ファイルに秘密を直接書かせないための入口。** 指定した環境変数が無ければ、
    黙って未認証で投げず、はっきり失敗させる（401 を「読めなかった」と誤認しないため）。

    `http://` / `https://` 以外のスキームは拒否する（`file://` はローカル読み出しの
    抜け穴になるため）。メソッドは GET 固定。

    例外メッセージにトークンやヘッダの値は絶対に含めない。URL は含めるが、
    クエリ文字列は秘密が入りうるので `?` 以降を落とす。
    """
    url = spec.get("url")
    if not url:
        raise SourceError("http_json には `url` が要る")
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise SourceError(f"http_json は http/https のみ許可: {scheme!r}")
    safe_url = _redact_url(url)

    headers = dict(spec.get("headers") or {})
    token_env = spec.get("token_env")
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise SourceError(f"環境変数が無い: {token_env}")
        headers["Authorization"] = f"Bearer {token}"

    timeout = spec.get("timeout", 10)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP エラー: {safe_url} ({e.code})") from e
    except urllib.error.URLError as e:
        raise SourceError(f"接続できない: {safe_url} ({e.reason})") from e
    except TimeoutError as e:
        raise SourceError(f"タイムアウト: {safe_url}") from e

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise SourceError(f"JSON として読めない: {safe_url} ({e})") from e

    pointer = spec.get("pointer") or ""
    node: Any = data
    for part in [p for p in pointer.split("/") if p]:
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError) as e:
                raise SourceError(f"pointer が届かない: {safe_url} {pointer}") from e
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise SourceError(f"pointer が届かない: {safe_url} {pointer}")

    field = spec.get("field")
    where = Where(f"{safe_url}#{pointer}" if pointer else safe_url)
    found: dict[str, Where] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            val = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            found.setdefault(str(k), Where(where.path, value=val))
    elif isinstance(node, list):
        for e in node:
            key = e.get(field) if (field and isinstance(e, dict)) else e
            if key is not None:
                found.setdefault(str(key), where)
    else:
        raise SourceError("pointer の先が配列でもオブジェクトでもない")
    return _apply(found, spec)


def _sqlite(spec: dict[str, Any]) -> Keys:
    """SQLite の 1 列を鍵にする。**読み取り専用で開く。**

    `query` が 2 列返すなら、1 列目を鍵、2 列目を値にする。3 列以上は SourceError。
    """
    path = _expand(spec["path"])
    if not path.is_file():
        raise SourceError(f"DB が無い: {path}")
    query = spec.get("query")
    if not query:
        raise SourceError("sqlite には `query` が要る（1 列か 2 列を返すこと）")
    if not query.lstrip().lower().startswith("select"):
        raise SourceError("sqlite の `query` は SELECT でなければならない")
    uri = f"file:{path.as_posix()}?mode=ro"
    found: dict[str, Where] = {}
    try:
        with sqlite3.connect(uri, uri=True) as db:
            cur = db.execute(query)
            ncols = len(cur.description) if cur.description else 0
            if ncols > 2:
                raise SourceError(
                    f"sqlite の `query` は 1 列か 2 列でなければならない（{ncols} 列返された）"
                )
            for row in cur:
                if row and row[0] is not None:
                    if ncols == 2:
                        found.setdefault(str(row[0]), Where(str(path), value=row[1]))
                    else:
                        found.setdefault(str(row[0]), Where(str(path)))
    except sqlite3.Error as e:
        raise SourceError(f"問い合わせに失敗: {e}") from e
    return _apply(found, spec)


def _git(spec: dict[str, Any]) -> Keys:
    """git リポジトリから鍵を取る。`what` で何を見るかを決める。

    - `repos`   : `path` の下にある .git を持つディレクトリの名前
    - `remotes` : `path` のリポジトリのリモート URL
    - `tags`    : タグ名
    - `branches`: ローカルブランチ名

    `git` を子プロセスで呼ばず、**.git の中を直接読む。**
    外部コマンドに依存すると、走る環境によって静かに結果が変わるため。
    """
    root = _expand(spec["path"])
    what = spec.get("what", "repos")
    found: dict[str, Where] = {}

    if what == "repos":
        if not root.is_dir():
            raise SourceError(f"ディレクトリが無い: {root}")
        for p in sorted(root.glob(spec.get("glob", "*"))):
            if p.is_dir() and (p / ".git").exists():
                found[p.name] = Where(str(p))
        return _apply(found, spec)

    gitdir = root / ".git"
    if gitdir.is_file():  # worktree: `gitdir: <path>` の 1 行
        line = gitdir.read_text(encoding="utf-8", errors="replace").strip()
        gitdir = Path(line.split(":", 1)[1].strip()) if ":" in line else gitdir
    if not gitdir.is_dir():
        raise SourceError(f"git リポジトリではない: {root}")

    if what == "remotes":
        conf = gitdir / "config"
        if not conf.is_file():
            raise SourceError(f"git config が無い: {conf}")
        name = None
        for i, line in enumerate(_lines(conf), 1):
            s = line.strip()
            m = re.match(r'\[remote\s+"([^"]+)"\]', s)
            if m:
                name = m.group(1)
                continue
            if name and s.startswith("url"):
                url = s.split("=", 1)[1].strip() if "=" in s else ""
                if url:
                    found.setdefault(url, Where(str(conf), i))
                name = None
        return _apply(found, spec)

    if what in ("tags", "branches"):
        sub = "tags" if what == "tags" else "heads"
        refdir = gitdir / "refs" / sub
        if refdir.is_dir():
            for p in sorted(refdir.rglob("*")):
                if p.is_file():
                    found.setdefault(p.relative_to(refdir).as_posix(), Where(str(p)))
        packed = gitdir / "packed-refs"
        if packed.is_file():
            pre = f"refs/{sub}/"
            for i, line in enumerate(_lines(packed), 1):
                if line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[1].strip().startswith(pre):
                    found.setdefault(parts[1].strip()[len(pre):], Where(str(packed), i))
        return _apply(found, spec)

    raise SourceError(
        f"git の `what` が不正: {what}（repos / remotes / tags / branches）"
    )


def _regex(spec: dict[str, Any]) -> Keys:
    """ファイルを行単位で走査し、正規表現で鍵と値を取る。値を持てる源。

    使い方は 2 通り。

    (a) 固定の鍵 + 捕獲した値: `key` を指定する。鍵はその固定値、
        値はパターンの捕獲グループ 1。1 ファイル内で複数回マッチしたら
        最初の 1 件を採る（`_apply` の setdefault と同じ流儀）。

    (b) 名前付きグループで複数件: `key` を指定せず、パターンに
        名前付きグループ `key` と `value` の両方を使う。

    `key` の指定と名前付きグループ（key/value 両方）の併用は SourceError。
    どちらでもない（`key` も無く、名前付きグループも揃っていない）場合も SourceError。
    `path` は必須。
    """
    if not spec.get("path"):
        raise SourceError("regex には `path` が要る")
    path = _expand(spec["path"])
    if not path.is_file():
        raise SourceError(f"ファイルが無い: {path}")

    pattern = spec.get("pattern")
    if not pattern:
        raise SourceError("regex には `pattern` が要る")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise SourceError(f"正規表現として読めない: {pattern!r} ({e})") from e

    fixed_key = spec.get("key")
    named = rx.groupindex
    has_named_pair = "key" in named and "value" in named

    if fixed_key and has_named_pair:
        raise SourceError(
            "regex は `key` の指定と名前付きグループ (key/value) を併用できない"
        )
    if not fixed_key and not has_named_pair:
        raise SourceError(
            "regex には `key`（固定鍵 + 捕獲グループ 1 の値）か、"
            "名前付きグループ key/value の両方のどちらかが要る"
        )
    if fixed_key and not rx.groups:
        raise SourceError(f"regex: `key` 指定時は捕獲グループが要る: {pattern!r}")

    found: dict[str, Where] = {}
    for i, line in enumerate(_lines(path), 1):
        for m in rx.finditer(line):
            if fixed_key:
                found.setdefault(fixed_key, Where(str(path), i, value=m.group(1)))
            else:
                k = m.group("key")
                if k is None:
                    continue
                found.setdefault(k, Where(str(path), i, value=m.group("value")))
    return _apply(found, spec)


ADAPTERS = {
    "dir": _dir,
    "git": _git,
    "regex": _regex,
    "markdown_links": _markdown_links,
    "wikilinks": _wikilinks,
    "headings": _headings,
    "frontmatter": _frontmatter,
    "json": _json_keys,
    "http_json": _http_json,
    "sqlite": _sqlite,
}


def read(spec: dict[str, Any]) -> Keys:
    kind = spec.get("kind")
    if kind not in ADAPTERS:
        raise SourceError(
            f"知らない種類: {kind!r}（使えるのは {', '.join(sorted(ADAPTERS))}）"
        )
    return ADAPTERS[kind](spec)
