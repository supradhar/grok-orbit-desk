from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from desk.models import Asset

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> tuple[dict[str, Any], list[Asset]]:
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assets = [Asset(**{k: v for k, v in row.items() if k in Asset.__dataclass_fields__}) for row in raw["watchlist"]]
    return raw, assets
