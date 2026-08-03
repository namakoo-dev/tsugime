"""http_json アダプタの検査。

外部サービスと突き合わせるための唯一の窓口なので、**ネットワークには一切出ない**
（`urllib.request.urlopen` を差し替えて応答を作る）。実データの形（配列 / オブジェクト
/ field / pointer）に加え、秘密の扱い（token_env、URL のクエリ文字列の落とし方）と
危険な入り口（file:// スキーム、GET 以外）を封じられているかを検査する。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

import sources


class _FakeResponse:
    """urlopen の戻り値（with 文で使われる）の最小限の代役。"""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _install(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", handler)


def _ok(body):
    def handler(req, timeout=None):
        return _FakeResponse(json.dumps(body).encode("utf-8"))
    return handler


def _refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """urlopen が呼ばれたら即失敗させる（「そもそも送っていない」ことの検査用）。"""
    def boom(req, timeout=None):
        raise AssertionError("送ってはいけない場面でリクエストを送っている")
    _install(monkeypatch, boom)


# ---------------------------------------------------------------------------
# 配列 / オブジェクト / field / pointer
# ---------------------------------------------------------------------------

def test_array_root_becomes_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """ルートが配列（pointer 省略）なら要素そのものを鍵にする。"""
    _install(monkeypatch, _ok(["a", "b", "c"]))
    keys = sources.read({"kind": "http_json", "url": "https://api.example.com/x"})
    assert sorted(keys) == ["a", "b", "c"]


def test_object_root_keys_become_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """ルートがオブジェクトなら、そのキーを鍵にする。"""
    _install(monkeypatch, _ok({"foo": 1, "bar": 2}))
    keys = sources.read({"kind": "http_json", "url": "https://api.example.com/x"})
    assert sorted(keys) == ["bar", "foo"]


def test_field_extracts_item_from_array_of_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    """配列の要素がオブジェクトのとき、field で指定した項目を鍵にする。"""
    _install(monkeypatch, _ok([{"id": "u1", "name": "Alice"}, {"id": "u2", "name": "Bob"}]))
    keys = sources.read(
        {"kind": "http_json", "url": "https://api.example.com/users", "field": "id"}
    )
    assert sorted(keys) == ["u1", "u2"]


def test_pointer_navigates_into_nested_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """pointer（`/a/b` 形式）でネストした先を取り出せる。"""
    _install(monkeypatch, _ok({"a": {"b": ["x", "y"]}}))
    keys = sources.read(
        {"kind": "http_json", "url": "https://api.example.com/x", "pointer": "/a/b"}
    )
    assert sorted(keys) == ["x", "y"]


def test_pointer_that_does_not_reach_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """pointer が届かない場合は 0 件にせず、はっきり失敗させる。"""
    _install(monkeypatch, _ok({"a": {}}))
    with pytest.raises(sources.SourceError):
        sources.read(
            {"kind": "http_json", "url": "https://api.example.com/x", "pointer": "/a/b"}
        )


def test_pointer_target_that_is_neither_array_nor_object_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pointer の先がスカラーだと鍵の集合にできないので失敗させる。"""
    _install(monkeypatch, _ok({"a": 1}))
    with pytest.raises(sources.SourceError):
        sources.read(
            {"kind": "http_json", "url": "https://api.example.com/x", "pointer": "/a"}
        )


def test_where_path_contains_url_and_pointer_with_no_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where.path には URL と pointer が入り、line は無い（HTTP 応答に行番号は無い）。"""
    _install(monkeypatch, _ok({"a": {"b": ["x"]}}))
    keys = sources.read(
        {"kind": "http_json", "url": "https://api.example.com/x", "pointer": "/a/b"}
    )
    w = keys["x"]
    assert w.line is None
    assert "https://api.example.com/x" in w.path
    assert "/a/b" in w.path


def test_missing_url_is_an_error() -> None:
    """url を指定しなければ、リクエストを送る前にはっきり失敗させる。"""
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "http_json"})


# ---------------------------------------------------------------------------
# メソッド固定 / スキーム制限
# ---------------------------------------------------------------------------

def test_method_is_always_get(monkeypatch: pytest.MonkeyPatch) -> None:
    """送るメソッドは常に GET（POST 等は無い）。"""
    captured = {}

    def handler(req, timeout=None):
        captured["method"] = req.get_method()
        return _FakeResponse(json.dumps(["a"]).encode("utf-8"))

    _install(monkeypatch, handler)
    sources.read({"kind": "http_json", "url": "https://api.example.com/x"})
    assert captured["method"] == "GET"


def test_rejects_file_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    """file:// はローカル読み出しの抜け穴になるので拒否する（リクエストも送らない）。"""
    _refuse(monkeypatch)
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "http_json", "url": "file:///etc/passwd"})


def test_rejects_other_unknown_schemes(monkeypatch: pytest.MonkeyPatch) -> None:
    """http/https 以外のスキーム全般を拒否する。"""
    _refuse(monkeypatch)
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "http_json", "url": "ftp://example.com/x.json"})


# ---------------------------------------------------------------------------
# token_env
# ---------------------------------------------------------------------------

def test_token_env_adds_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """token_env が設定されていれば、実際の Request に Authorization: Bearer <値> が載る。"""
    monkeypatch.setenv("TSUGIME_TEST_TOKEN", "s3cr3t-value")
    captured = {}

    def handler(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        return _FakeResponse(json.dumps(["a"]).encode("utf-8"))

    _install(monkeypatch, handler)
    sources.read(
        {
            "kind": "http_json",
            "url": "https://api.example.com/x",
            "token_env": "TSUGIME_TEST_TOKEN",
        }
    )
    assert captured["auth"] == "Bearer s3cr3t-value"


def test_missing_token_env_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """token_env で指定した環境変数が無ければ、未認証で投げず失敗する（401 に化けさせない）。"""
    monkeypatch.delenv("TSUGIME_TEST_TOKEN_MISSING", raising=False)
    _refuse(monkeypatch)
    with pytest.raises(sources.SourceError):
        sources.read(
            {
                "kind": "http_json",
                "url": "https://api.example.com/x",
                "token_env": "TSUGIME_TEST_TOKEN_MISSING",
            }
        )


def test_extra_headers_are_sent_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """headers で指定した追加ヘッダも実際のリクエストに載る。"""
    captured = {}

    def handler(req, timeout=None):
        captured["accept"] = req.get_header("Accept")
        return _FakeResponse(json.dumps(["a"]).encode("utf-8"))

    _install(monkeypatch, handler)
    sources.read(
        {
            "kind": "http_json",
            "url": "https://api.example.com/x",
            "headers": {"Accept": "application/vnd.custom+json"},
        }
    )
    assert captured["accept"] == "application/vnd.custom+json"


# ---------------------------------------------------------------------------
# エラー経路: HTTP エラー / タイムアウト / 不正な JSON
# ---------------------------------------------------------------------------

def test_http_error_becomes_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP エラー応答（例: 500）は SourceError になる。"""
    def handler(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", None, None)

    _install(monkeypatch, handler)
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "http_json", "url": "https://api.example.com/x"})


def test_connection_failure_becomes_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """名前解決失敗などの URLError も SourceError になる。"""
    def handler(req, timeout=None):
        raise urllib.error.URLError("name resolution failed")

    _install(monkeypatch, handler)
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "http_json", "url": "https://api.example.com/x"})


def test_timeout_becomes_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """タイムアウトは SourceError になる。"""
    def handler(req, timeout=None):
        raise TimeoutError("timed out")

    _install(monkeypatch, handler)
    with pytest.raises(sources.SourceError):
        sources.read(
            {"kind": "http_json", "url": "https://api.example.com/x", "timeout": 1}
        )


def test_non_json_body_becomes_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON でない応答（HTML など）は SourceError になる。"""
    def handler(req, timeout=None):
        return _FakeResponse(b"<html>not json</html>")

    _install(monkeypatch, handler)
    with pytest.raises(sources.SourceError):
        sources.read({"kind": "http_json", "url": "https://api.example.com/x"})


# ---------------------------------------------------------------------------
# 秘密がエラーメッセージに漏れないこと
# ---------------------------------------------------------------------------

def test_error_message_never_contains_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """例外メッセージに token の値が出ないこと（token_env 経由の場合）。"""
    monkeypatch.setenv("TSUGIME_TEST_TOKEN2", "top-secret-abc123")

    def handler(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", None, None)

    _install(monkeypatch, handler)
    with pytest.raises(sources.SourceError) as exc_info:
        sources.read(
            {
                "kind": "http_json",
                "url": "https://api.example.com/x",
                "token_env": "TSUGIME_TEST_TOKEN2",
            }
        )
    assert "top-secret-abc123" not in str(exc_info.value)


def test_query_string_is_dropped_from_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """クエリ文字列に秘密が入り得るので、失敗時のメッセージからは `?` 以降を落とす。"""
    def handler(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", None, None)

    _install(monkeypatch, handler)
    with pytest.raises(sources.SourceError) as exc_info:
        sources.read(
            {
                "kind": "http_json",
                "url": "https://api.example.com/x?token=super-secret-query",
            }
        )
    assert "super-secret-query" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# 正規化（既存アダプタと共通の仕組み）
# ---------------------------------------------------------------------------

def test_normalisation_applies_lower_exclude_strip_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """他のアダプタと同じ正規化（lower / exclude / strip_suffix）が効く。"""
    _install(monkeypatch, _ok(["Foo.md", "Bar.md", "Baz.md"]))
    keys = sources.read(
        {
            "kind": "http_json",
            "url": "https://api.example.com/x",
            "lower": True,
            "strip_suffix": ".md",
            "exclude": ["baz"],
        }
    )
    assert sorted(keys) == ["bar", "foo"]
