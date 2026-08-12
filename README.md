# tsugime（継ぎ目）

**道具どうしの継ぎ目に、成り立っているべき対応関係を宣言しておく。ずれたら教えてもらう。**

MCP サーバです。[English](README.en.md)

```
規則 5 件 — 一致 4 / ずれ 1 / 読めず 0   ずれた項目 1 件

[skills-no-ghosts] INDEX.md の skill に実体がある
  実体 41 件 / 実体 40 件 — 左のすべてが右に現れる
  ✗ 実体 に無い 1 件:
      blender-web-pipeline    （~\.agents\skills\INDEX.md:362 にはある）
  » 実体の無い項目は、消した skill の残骸
```

---

## 何のためのものか

道具が増えると、**同じことを 2 箇所に書く**状態が必ずできます。

- 記憶ファイルの実体と、それを読み込むための索引
- リポジトリと、README に並べたリポジトリ一覧
- 出荷した商品と、商品ページ
- タスクと、それを指しているノート

そして片方だけが更新されます。**壊れないので気づきません。** 索引に載っていない
ファイルは、消えたわけではなく、ただ読まれなくなるだけです。

tsugime は、その対応関係を先に宣言しておき、**今ずれているものを答えます。**

## 既にあるものとの違い

MCP サーバは 2,000 本以上あります。そのほとんどは **実行する側** です。
Zapier も n8n もゲートウェイの類も「A が起きたら B をやれ」という命令形です。

tsugime は実行しません。**一致しているかを見るだけです。**

この考え方自体は新しくありません。インフラの世界では確立しています——
Terraform の `plan`、ArgoCD や Flux の drift detection。宣言した状態と実際の状態を
比べ続けて、ずれを出す。**それを「手元の道具どうしの継ぎ目」に持ってきたものが
無かった**ので、作りました。

## AI に何をさせるか

読み出しと差分は **決定的** です。ここに推測は入りません。同じ入力なら同じ出力で、
出どころ（パスと行番号）が必ず付きます。**報告を鵜呑みにせず、その場で確かめられます。**

曖昧な部分——「このノートとこの issue は同じものを指しているか」——だけを、
ずれを受け取った側（AI）が判断します。

**そして tsugime は何も直しません。** 索引に無いファイルを消すのか索引に足すのかは、
中身を見ないと決められないからです。自動修復を持たないのは機能不足ではなく、
**境界の置き方** です。

---

## 使ってみる

### 1. 入れる

```powershell
git clone https://github.com/namakoo-dev/tsugime.git
cd tsugime
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 2. 継ぎ目を宣言する

`tsugime.toml` に書きます。1 つの規則が言うのは 3 つだけです——**左、右、
どちらがどちらを含むべきか。**

```toml
[[rule]]
name = "memory-indexed"
title = "すべての記憶ファイルが MEMORY.md から辿れる"
direction = "left_subset_right"          # 左のすべてが右に現れるべき
note = "索引に無い記憶は毎セッション読み込まれない。書いた意味が消える"

[rule.left]
kind = "dir"                             # ディレクトリの中身
path = "~/.claude/projects/xxx/memory"
glob = "*.md"
only = "files"
exclude = ["MEMORY.md"]

[rule.right]
kind = "markdown_links"                  # Markdown の [題](先) の *先*
path = "~/.claude/projects/xxx/memory/MEMORY.md"
```

### 3. 走らせる

MCP を使わずに、そのまま確かめられます。**hook や CI から呼ぶのはこちら。**

```
usage: tsugime [-h] [-c CONFIG] [-r RULE] [--strict] [--json] [--limit LIMIT]

宣言した対応関係と実際を突き合わせ、ずれを出す（直さない）

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        規則ファイル
  -r RULE, --rule RULE  この名前の規則だけを見る
  --strict              ずれ、または読めない規則があれば exit 1
  --json                機械が読む形で出す
  --limit LIMIT         1 規則あたり表示するずれの上限（既定 20）
```

```powershell
.venv\Scripts\python cli.py                       # 全部の規則を見る
.venv\Scripts\python cli.py --rule memory-indexed  # 1 つだけ
.venv\Scripts\python cli.py --strict               # ずれがあれば exit 1
```

`-c` を省略すると、`TSUGIME_CONFIG` 環境変数 → `~/.nagi/tsugime.toml` →
カレントディレクトリの `tsugime.toml` → `cli.py` と同じディレクトリの `tsugime.toml`、
の順で探します。

**終了コード**で判断できます:

| exit code | 意味 |
|---|---|
| 0 | ずれなし。`--strict` を付けていなければ、ずれがあってもここに落ちます |
| 1 | `--strict` 指定時、ずれ、または読めなかった規則があった |
| 2 | 規則ファイル（`tsugime.toml`）が無い・壊れている |

CI から使う例（GitHub Actions）:

```yaml
- run: python cli.py --strict
```

### 4. Claude Code に繋ぐ

```json
{
  "mcpServers": {
    "tsugime": {
      "command": "C:\\Dev\\tsugime\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Dev\\tsugime\\server.py"],
      "env": { "TSUGIME_CONFIG": "C:\\Dev\\tsugime\\tsugime.toml" }
    }
  }
}
```

---

## 読める側（アダプタ）

| 種類 | 何を鍵にするか | 主な指定 |
|---|---|---|
| `dir` | ディレクトリの中身（ファイル名 / ディレクトリ名） | `glob` `only` |
| `git` | リポジトリ名一覧、または 1 つのリポジトリのリモート URL / タグ名 / ブランチ名（`what` で選ぶ: `repos` `remotes` `tags` `branches`） | `what` `glob` |
| `markdown_links` | `[題](先)` の **先** | — |
| `wikilinks` | `[[...]]` の中身。ファイルでもディレクトリでも可 | `glob` |
| `headings` | 見出し。深さと正規表現で絞れる | `level` `pattern` `after` `until` |
| `frontmatter` | 各ファイルの frontmatter の 1 項目 | `field` `glob` |
| `json` | JSON の配列 / オブジェクト | `pointer` `field` |
| `http_json` | HTTP GET した JSON の配列 / オブジェクト | `url` `pointer` `field` `token_env` `headers` `timeout` |
| `sqlite` | SELECT の 1 列目（**読み取り専用で開きます**） | `query` |
| `regex` | 行を正規表現で走査した鍵（値も持てる） | `pattern` `key` |

`git` は外部の `git` コマンドを呼ばず、`.git` の中を直接読みます
（走る環境によって結果が変わらないように）。

どの側にも正規化を掛けられます: `strip_suffix` / `basename` / `lower` / `exclude`。

### `regex` の 2 通りの使い方

(a) 鍵は固定、値は捕獲グループ 1:

```toml
[rule.left]
kind = "regex"
path = "pyproject.toml"
pattern = 'version\s*=\s*"([^"]+)"'
key = "version"
```

(b) 名前付きグループ `(?P<key>)` `(?P<value>)` で、1 ファイルから複数件:

```toml
[rule.right]
kind = "regex"
path = "deployed.env"
pattern = '(?P<key>[A-Z_]+)=(?P<value>.+)'
```

**方向**は 4 つです。それぞれ 1 つの問いに答えます。

- `left_subset_right` — 左のすべてが右に現れるか
- `right_subset_left` — 右のすべてが左に現れるか
- `equal` — 左と右が完全に一致するか
- `values_agree` — 両側にある鍵について、値が一致するか

## 値も見る（`values_agree`）

3 つの方向は「鍵の集合」しか見ません。同じ鍵が両側にあっても、
**その値まで一致しているかは見ていませんでした。** バージョン番号が典型例です——
索引には載っているのに、書いてある値そのものが食い違っている。

`values_agree` はこの問いに答えます: **両側にある鍵について、値が一致するか。**

```toml
[[rule]]
name = "version-matches-deploy"
title = "pyproject.toml のバージョンと、デプロイ済みの記録が一致する"
direction = "values_agree"
left_label = "pyproject.toml"
right_label = "デプロイ記録"
note = "デモ: 手元と本番でバージョンがずれている例"

[rule.left]
kind = "regex"
path = "pyproject.toml"
pattern = 'version\s*=\s*"([^"]+)"'
key = "version"

[rule.right]
kind = "regex"
path = "deployed.env"
pattern = "(?P<key>[A-Z_]+)=(?P<value>.+)"
lower = true
```

```
規則 1 件 — 一致 0 / ずれ 1 / 読めず 0   ずれた項目 1 件

[version-matches-deploy] pyproject.toml のバージョンと、デプロイ済みの記録が一致する
  pyproject.toml 1 件 / デプロイ記録 1 件 — 共通鍵 1 件 — 両側にある鍵について、値が一致する
  ✗ 値が食い違う 1 件:
      version    pyproject.toml='1.2.0' (pyproject.toml:3)  /  デプロイ記録='1.1.0' (deployed.env:1)
  » デモ: 手元と本番でバージョンがずれている例
```

設計上、意図して決めていることが 4 つあります。

- **片側にしか無い鍵は報告しません。** 1 つの規則は 1 つの問いに答えます。存在まで見たいなら、
  `left_subset_right` などの規則を別に書いてください
- **どちらが正しいかは tsugime には決められません。** だから両側の値と両側の出どころを
  そのまま出します。判断は人（か AI）に渡します
- **値を持てない源を `values_agree` に使うとエラーになります。** 黙って「全部一致」と
  言わせないためです。使えるのは `frontmatter` / `http_json` / `json` / `regex` / `sqlite` だけです
- **共通鍵が 0 件でも「一致」とは出ません。** 「何も見ていない」ことが件数として必ず出ます
  （上の出力の「共通鍵 N 件」）

既存のアダプタにも、値を返せるようになったものがあります:

- `sqlite`: `query` が 2 列返すと、1 列目が鍵・2 列目が値になります（3 列以上は失敗）
- `json` / `http_json`: `pointer` の先がオブジェクトなら、キーが鍵・値がそのまま値になります
  （配列のままなら今どおり値は持ちません）
- `frontmatter`: `value_field` を指定すると、`field` の値を鍵にしつつ、`value_field` の値を
  値として添えます

## 秘密の扱い（`http_json`）

`http_json` は外部サービスに繋ぐ唯一の入口なので、秘密の扱いだけ切り出して書いておきます。

- **設定ファイルにトークンを直接書かせません。** 書くのは環境変数名（`token_env`）だけです
- **その環境変数が無ければ、黙って未認証で投げず、失敗します**（401 を「読めなかった」と誤認しないため）
- **失敗メッセージには URL のクエリ文字列以降とトークンの値を含めません**
- **GET しか送りません。** 実装で固定してあり、設定から変える手段はありません

```toml
[rule.right]
kind = "http_json"
url = "https://api.github.com/repos/OWNER/REPO/releases"
field = "tag_name"
token_env = "GITHUB_TOKEN"          # 値ではなく環境変数名を書く
headers = { Accept = "application/vnd.github+json" }
timeout = 10
```

## MCP のツール

| ツール | 何をするか |
|---|---|
| `tsugime_rules` | 宣言されている対応関係を並べる。まだ読み出さない |
| `tsugime_check` | 突き合わせて、ずれた項目を出どころ付きで返す |
| `tsugime_explain` | 1 つの規則について、左右の鍵を全部並べる |

3 つとも読み取り専用です。**書き込むツールはありません。**

`tsugime_explain` は、ずれが腑に落ちないときに使います。たいていは
**「鍵の作り方が意図と違う」**（拡張子が付いている、大文字小文字、パスかファイル名か）で、
それは左右を並べれば分かります。

---

## 作った日に見つかったもの

自分の環境に当てて、最初の実行で 3 件出ました。

**記憶ファイルが 2 件、索引に載っていませんでした。**
`feedback_verify_before_asserting.md` と `project_idfu_unwired_aws_publisher.md`。
どちらも書かれてから一度も読み込まれていませんでした。索引が毎セッション読み込まれる
仕組みなので、**索引に無いものは書いた瞬間から存在しないのと同じ**です。

しかも片方は「確かめずに断言するな」という規律を書き留めたものでした。
**それを守るための仕組みが、それ自身を落としていた**わけです。

**3 件目は、自分の宣言の誤りでした。** `INDEX.md:362` の `blender-web-pipeline` に
実体が無い、と報告されました。消した skill の残骸だと思いました。**違いました。**

同じ文書の 3 行上にこう書いてありました——「以下は project local
(`stg/.agents/skills/`) のみ、**global には配置しない**」。実体は別の場所にあり、
無いのが正しかったのです。**書いた規則が、文書の節の違いを見ていなかった。**

**もし tsugime が自動で直す作りだったら、この行は消えていました。** 正しい記載が、
規則の書き手の不注意で失われるところでした。自動修復を持たないのは、
そういう理由です。

規則を直しました——`headings` に `after` / `until` を足して節ごとに見るようにし、
project local 節は別の場所と突き合わせる規則を新しく書きました。
**その過程で、宣言を 3 回間違えました**（節を分けていない、突き合わせ先のパスが違う、
`equal` が強すぎる）。**そのたびに tsugime が教えてくれました。**
規則は一度で正しく書けるものではなく、**ずれの報告を読みながら削っていくもの**です。

## 分かっている限界

- **鍵の一致は文字列の一致です。** 表記ゆれは拾えません。それは受け取った側（AI）の仕事です
- **`values_agree` の値の比較も、文字列化してから行います**（`str(左) != str(右)`）。
  型が違っても文字列表現が同じなら一致とみなします（例: JSON の数値 `1` と文字列 `"1"`）
- **frontmatter は YAML を解析しません。** `名前: 値` の行を拾うだけで、入れ子や配列は読めません
- **読めなかったものは黙って落とします。** frontmatter が無いファイル、届かない
  `pointer` などは例外になりますが、**「対象が 0 件だった」ことは異常として扱いません。**
  規則が何も見ていない状態でも「ずれなし」と出ます。件数（`left_count` / `right_count`）を
  必ず見てください
- **直しません。** 自動修復はありません
- **`http_json` の認証は `Authorization: Bearer` 一形式だけです。** Basic 認証や署名付きヘッダなど、他の認証方式には対応していません
- **`http_json` はページングを追いません。** 応答 1 回分だけを見ます。ページ分割された API では、その分だけ鍵が欠けます
- **`http_json` は応答をキャッシュしません。** その URL を使う規則の数だけ、毎回リクエストします

## ライセンス

MIT
