"""Deterministic Grafana dashboard JSON normalizer.

Ensures exported dashboard JSON is reproducible, clean, and safe:
1. Strips volatile runtime fields (id, version, iteration, meta timestamps).
2. Enforces safety invariants: "editable": false and tags containing "managed-by-git".
3. Recursively sorts dictionary keys for deterministic git diffs.
4. Serializes with standard 2-space indentation and newline termination.
"""

from __future__ import annotations

import copy
import json
from typing import Any

# Top-level volatile runtime fields injected by Grafana database/engine
VOLATILE_TOP_LEVEL_KEYS: set[str] = {
    "id",
    "version",
    "iteration",
}

# Any nested runtime fields or counters that cause false git diffs
VOLATILE_NESTED_KEYS: set[str] = {
    "iteration",
}

# Tag injected into every git-managed dashboard
MANAGED_TAG: str = "managed-by-git"


def _clean_dict(data: dict[str, Any], is_top_level: bool = False) -> dict[str, Any]:
    """Recursively strip volatile keys and sort dictionary items."""
    cleaned: dict[str, Any] = {}

    keys_to_skip = VOLATILE_TOP_LEVEL_KEYS if is_top_level else VOLATILE_NESTED_KEYS

    # Sort keys alphabetically for deterministic serialization
    for key in sorted(data.keys()):
        if key in keys_to_skip:
            continue

        value = data[key]
        if isinstance(value, dict):
            cleaned[key] = _clean_dict(value, is_top_level=False)
        elif isinstance(value, list):
            cleaned[key] = _clean_list(value)
        else:
            cleaned[key] = value

    return cleaned


def _clean_list(items: list[Any]) -> list[Any]:
    """Recursively clean elements inside a list."""
    cleaned: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            cleaned.append(_clean_dict(item, is_top_level=False))
        elif isinstance(item, list):
            cleaned.append(_clean_list(item))
        else:
            cleaned.append(item)
    return cleaned


def normalize_dashboard(raw: dict[str, Any] | str) -> dict[str, Any]:
    """Normalize a Grafana dashboard dictionary or JSON string.

    Args:
        raw: Dashboard JSON object or string (can be raw /api/dashboards/uid response
             or the 'dashboard' sub-key).

    Returns:
        Cleaned, invariant-enforced dashboard dictionary with sorted keys.
    """
    if isinstance(raw, str):
        payload = json.loads(raw)
    else:
        payload = copy.deepcopy(raw)

    # If the payload is wrapped in the Grafana API envelope {"dashboard": {...}, "meta": {...}}
    if "dashboard" in payload and isinstance(payload["dashboard"], dict):
        dashboard = payload["dashboard"]
    else:
        dashboard = payload

    # 1. Recursively strip volatile fields and sort keys
    normalized = _clean_dict(dashboard, is_top_level=True)

    # 2. Enforce invariants: "editable": false
    normalized["editable"] = False

    # 3. Enforce invariants: "managed-by-git" tag
    raw_tags = normalized.get("tags", [])
    if not isinstance(raw_tags, list):
        raw_tags = []
    tag_set = {str(t).strip() for t in raw_tags if t}
    tag_set.add(MANAGED_TAG)
    normalized["tags"] = sorted(tag_set)

    # 4. Final key sort to guarantee top-level order
    return {k: normalized[k] for k in sorted(normalized.keys())}


def serialize_dashboard(dashboard: dict[str, Any]) -> str:
    """Serialize a normalized dashboard dictionary to a deterministic JSON string.

    Uses 2-space indentation, stable keys, and ends with a single trailing newline.
    """
    return json.dumps(dashboard, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
