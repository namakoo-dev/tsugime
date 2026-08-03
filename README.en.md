# tsugime

**Declare what should stay in sync across your tools. Be told when it drifts.**

An MCP server. [日本語](README.md)

```
5 rules — in sync 4 / drifted 1 / unreadable 0   drift items 1

[skills-no-ghosts] every entry in INDEX.md has a directory behind it
  actual 41 / actual 40 — everything on the left appears on the right
  ✗ 1 missing from actual:
      blender-web-pipeline    (present at C:\Users\USER\.agents\skills\INDEX.md:362)
  » an entry with nothing behind it is the residue of a deleted skill
```

---

## The problem

Once you have more than a couple of tools, you inevitably write the same fact
in two places:

- the memory files themselves, and the index that decides which ones get loaded
- your repositories, and the list of them in a README
- the products you shipped, and the pages that describe them
- a task, and the note that refers to it

Then one side gets updated and the other doesn't. **Nothing breaks, so nobody
notices.** A file missing from an index has not been deleted — it has just
stopped being read.

tsugime lets you declare those correspondences up front, and answers
**what is out of sync right now.**

## How this differs from what already exists

There are over 2,000 MCP servers. Nearly all of them are on the **doing** side.
Zapier, n8n, the gateway projects — they are all imperative: *when A happens, do B*.

tsugime does not do. **It only looks at whether things agree.**

The idea is not new. It is well established in infrastructure — `terraform plan`,
drift detection in ArgoCD and Flux: keep comparing declared state against observed
state and surface the difference. **What did not exist was that idea applied to the
seams between the tools on your desk.** So I built it.

## What the model is for

Reading and diffing are **deterministic**. No guessing. The same inputs give the
same output, and every result carries its provenance — a path and a line number —
so **you can check the claim instead of trusting it.**

Only the ambiguous part — *is this note and this issue the same thing?* — is left
to whoever receives the drift report.

**And tsugime never fixes anything.** Whether a file missing from an index should
be deleted or added cannot be decided without reading it. Having no auto-repair is
not a missing feature; it is **where the boundary belongs.**

---

## Getting started

### 1. Install

```bash
git clone https://github.com/watasisaikou/tsugime.git
cd tsugime
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
```

### 2. Declare a seam

In `tsugime.toml`. A rule says only three things — **left, right, and which
should contain which.**

```toml
[[rule]]
name = "memory-indexed"
title = "every memory file is reachable from MEMORY.md"
direction = "left_subset_right"           # everything on the left must appear on the right
note = "a memory not in the index is never loaded. writing it accomplished nothing"

[rule.left]
kind = "dir"                              # entries of a directory
path = "~/.claude/projects/xxx/memory"
glob = "*.md"
only = "files"
exclude = ["MEMORY.md"]

[rule.right]
kind = "markdown_links"                   # the *target* of [text](target)
path = "~/.claude/projects/xxx/memory/MEMORY.md"
```

### 3. Run it without MCP

**This is what hooks and CI call.**

```
usage: tsugime [-h] [-c CONFIG] [-r RULE] [--strict] [--json] [--limit LIMIT]

Reconcile what was declared against what actually exists; report drift (fixes nothing)

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        rule file
  -r RULE, --rule RULE  check only the rule with this name
  --strict              exit 1 if anything drifted, or a rule could not be read
  --json                machine-readable output
  --limit LIMIT         cap on drift items shown per rule (default 20)
```

(The actual `--help` text is in Japanese — this is a translation, same as the
sample output above.)

```bash
.venv/bin/python cli.py                       # every rule       # Windows: .venv\Scripts\python
.venv/bin/python cli.py --rule memory-indexed  # just one
.venv/bin/python cli.py --strict               # exit 1 if anything drifted
```

If `-c` is omitted, the rule file is looked up in order: the `TSUGIME_CONFIG`
environment variable → `~/.nagi/tsugime.toml` → `tsugime.toml` in the current
directory → `tsugime.toml` next to `cli.py`.

**The exit code** tells you what happened:

| exit code | meaning |
|---|---|
| 0 | no drift. Without `--strict`, drift still exits 0 |
| 1 | with `--strict`: there was drift, or a rule could not be read |
| 2 | the rule file (`tsugime.toml`) is missing or broken |

Used from CI (GitHub Actions):

```yaml
- run: python cli.py --strict
```

### 4. Connect it to Claude Code

```json
{
  "mcpServers": {
    "tsugime": {
      "command": "/path/to/tsugime/.venv/bin/python",
      "args": ["/path/to/tsugime/server.py"],
      "env": { "TSUGIME_CONFIG": "/path/to/tsugime/tsugime.toml" }
    }
  }
}
```

---

## Adapters

| kind | what becomes a key | main options |
|---|---|---|
| `dir` | directory entries (file or directory names) | `glob` `only` |
| `git` | repository names, or one repo's remote URLs / tag names / branch names (pick with `what`: `repos` `remotes` `tags` `branches`) | `what` `glob` |
| `markdown_links` | the **target** of `[text](target)` | — |
| `wikilinks` | the contents of `[[...]]`; file or directory | `glob` |
| `headings` | headings, filtered by depth and regex | `level` `pattern` `after` `until` |
| `frontmatter` | one field from each file's frontmatter | `field` `glob` |
| `json` | an array or object inside a JSON file | `pointer` `field` |
| `http_json` | an array or object inside JSON fetched via HTTP GET | `url` `pointer` `field` `token_env` `headers` `timeout` |
| `sqlite` | the first column of a SELECT (**opened read-only**) | `query` |
| `regex` | keys matched line-by-line with a regex (can carry a value too) | `pattern` `key` |

`git` never shells out to `git` — it reads `.git` directly, so the result
doesn't depend on the environment it runs in.

Either side can be normalised: `strip_suffix`, `basename`, `lower`, `exclude`.

### `regex`, two ways

(a) a fixed key, value from capture group 1:

```toml
[rule.left]
kind = "regex"
path = "pyproject.toml"
pattern = 'version\s*=\s*"([^"]+)"'
key = "version"
```

(b) named groups `(?P<key>)` `(?P<value>)`, multiple entries from one file:

```toml
[rule.right]
kind = "regex"
path = "deployed.env"
pattern = '(?P<key>[A-Z_]+)=(?P<value>.+)'
```

**Directions**: four of them, each answering one question.

- `left_subset_right` — does everything on the left appear on the right?
- `right_subset_left` — does everything on the right appear on the left?
- `equal` — do the left and right match exactly?
- `values_agree` — for keys present on both sides, do the values agree?

## Comparing values (`values_agree`)

The three directions above only look at *sets of keys*. Two keys can match on
both sides while **the values behind them have drifted apart.** A version
number is the typical case — it's present in the index, but the two copies
say different things.

`values_agree` answers that question: **for keys present on both sides, do
the values agree?**

```toml
[[rule]]
name = "version-matches-deploy"
title = "pyproject.toml's version agrees with what was deployed"
direction = "values_agree"
left_label = "pyproject.toml"
right_label = "deployed record"
note = "demo: local and production versions have drifted"

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
1 rule — in sync 0 / drifted 1 / unreadable 0   drift items 1

[version-matches-deploy] pyproject.toml's version agrees with what was deployed
  pyproject.toml 1 / deployed record 1 — common keys 1 — values agree for keys present on both sides
  ✗ 1 value mismatch:
      version    pyproject.toml='1.2.0' (pyproject.toml:3)  /  deployed record='1.1.0' (deployed.env:1)
  » demo: local and production versions have drifted
```

(This is a translation of the real Japanese output — same convention as the
`--help` text above.)

There are four deliberate design decisions behind it:

- **A key present on only one side is never reported here.** A rule answers
  one question. If you also want to know about existence, write a separate
  `left_subset_right`-style rule for that
- **tsugime cannot decide which side is right.** So it surfaces both values
  and both provenances as-is, and leaves the judgment to whoever reads the
  report
- **Using a value-incapable source with `values_agree` is an error.** This
  keeps it from silently claiming "everything agrees." The usable kinds are
  `frontmatter`, `http_json`, `json`, `regex`, and `sqlite`
- **Zero common keys is never reported as "in sync."** "Nothing was compared"
  always shows up as a count (the "common keys N" in the output above)

Some existing adapters can now carry a value too:

- `sqlite`: if `query` returns two columns, the first becomes the key and the
  second the value (three or more columns is an error)
- `json` / `http_json`: if `pointer` points at an object, each key becomes a
  key and its value becomes the value (an array root still carries no values)
- `frontmatter`: with `value_field` set, the `field` value becomes the key and
  the `value_field` value is attached as its value

## Secrets (`http_json`)

`http_json` is the only adapter that talks to an external service, so its
handling of secrets gets its own short section.

- **The config file never holds a token.** What you write is an environment
- **It only ever sends GET.** The method is hardcoded; no setting can change it.
  variable name (`token_env`)
- **If that environment variable is unset, it fails instead of sending the
  request unauthenticated** (so a 401 doesn't get misread as "could not read")
- **Failure messages never include the URL's query string or the token value**

```toml
[rule.right]
kind = "http_json"
url = "https://api.github.com/repos/OWNER/REPO/releases"
field = "tag_name"
token_env = "GITHUB_TOKEN"          # a variable name, not a value
headers = { Accept = "application/vnd.github+json" }
timeout = 10
```

## MCP tools

| tool | what it does |
|---|---|
| `tsugime_rules` | lists the declared seams. Reads nothing yet |
| `tsugime_check` | compares them and returns drift, with provenance |
| `tsugime_explain` | enumerates both sides of one rule in full |

All three are read-only. **There is no tool that writes.**

Reach for `tsugime_explain` when a drift result does not make sense. Usually the
cause is **that the keys are not built the way you intended** — an extension still
attached, a case difference, a path where you meant a filename — and putting both
sides side by side shows it.

---

## What it found on the day it was written

Pointed at its author's own machine, the first run surfaced three things.

**Two memory files were not in the index.** `feedback_verify_before_asserting.md`
and `project_idfu_unwired_aws_publisher.md`. Neither had ever been loaded since the
day it was written. The index is what gets read at the start of every session, so
**a file missing from it may as well not exist.**

One of them recorded the discipline *don't assert without checking.* **The mechanism
meant to preserve that lesson was the thing dropping it.**

**The third finding was my own rule being wrong.** `INDEX.md:362` listed
`blender-web-pipeline` with no directory behind it. I took it for the residue of a
deleted skill. **It was not.**

Three lines above it, the same document said: *the following live in the project
only (`stg/.agents/skills/`) — do not place them globally.* The directory existed
elsewhere, and its absence was correct. **My rule had not accounted for the
document having sections that mean different things.**

**Had tsugime been built to repair things automatically, that line would have been
deleted** — a correct entry destroyed by the rule author's carelessness. That is
why there is no auto-repair.

I fixed the rule: `after` / `until` were added to the `headings` adapter so a rule
can scope to a section, and the project-local section now reconciles against the
other directory. **Along the way I got the declaration wrong three times** (sections
not separated, wrong path on the other side, `equal` where subset was meant).
**Each time, tsugime told me.** Rules are not something you write correctly on the
first try; they are something you **sharpen while reading the drift reports.**

## Known limits

- **Key matching is string matching.** It will not see through naming variation.
  That is the receiving side's job
- **`values_agree` also compares values as strings** (`str(left) != str(right)`).
  Different types with the same string form count as agreeing — e.g. the JSON
  number `1` and the string `"1"`
- **`frontmatter` does not parse YAML.** It picks up `name: value` lines only —
  no nesting, no arrays
- **An empty side is not treated as an error.** A rule whose sources match nothing
  still reports "in sync". Always read `left_count` / `right_count`
- **It does not fix anything.** There is no auto-repair
- **`http_json` supports one auth form: `Authorization: Bearer`.** No Basic auth,
  no signed headers, no other scheme
- **`http_json` does not follow pagination.** It only looks at a single response.
  A paginated API will be missing whatever keys are on later pages
- **`http_json` does not cache.** It sends a fresh request for every rule that
  uses that URL

## Licence

MIT
