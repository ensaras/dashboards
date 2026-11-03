"""Stable Grafana preview dashboard identities."""

from __future__ import annotations

import hashlib
import re

MAX_GRAFANA_DASHBOARD_UID_LENGTH = 40
GRAFANA_DASHBOARD_UID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
PREVIEW_HASH_LENGTH = 8


def preview_uid(org_slug: str, dashboard_uid: str, pr_number: int) -> str:
    """Append the PR suffix, shortening long source UIDs with a stable hash."""
    if pr_number < 1:
        raise ValueError("PR number must be a positive integer")
    if not GRAFANA_DASHBOARD_UID.fullmatch(dashboard_uid):
        raise ValueError(
            "Source dashboard UID must contain 8 to 40 letters, digits, hyphens, or underscores"
        )

    suffix = f"-pr{pr_number}"
    candidate = f"{dashboard_uid}{suffix}"
    if len(candidate) <= MAX_GRAFANA_DASHBOARD_UID_LENGTH:
        return candidate

    digest = hashlib.sha256(f"{org_slug}:{dashboard_uid}".encode()).hexdigest()[
        :PREVIEW_HASH_LENGTH
    ]
    prefix_length = MAX_GRAFANA_DASHBOARD_UID_LENGTH - len(suffix) - len(digest) - 1
    if prefix_length < 1:
        raise ValueError("PR number is too long to create a valid Grafana preview UID")
    return f"{dashboard_uid[:prefix_length]}-{digest}{suffix}"
