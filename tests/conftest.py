"""pytest 共有セットアップ。

tests/ から見て一つ上のディレクトリ（sources.py / reconcile.py / server.py が
置かれているリポジトリ直下）を import できるようにする。テスト対象を
tests/ 配下に複製せず、既存ファイルをそのまま import するための橋渡し。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
