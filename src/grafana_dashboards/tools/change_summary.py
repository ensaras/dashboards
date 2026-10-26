"""Build a concise Markdown summary of dashboard changes between Git refs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from grafana_dashboards.tools.export import slugify
from grafana_dashboards.tools.preview_identity import preview_uid

ORG_ROOT = Path("orgs")
SITE_ROOT = Path("sites")


@dataclass(frozen=True)
class DashboardChange:
    org_slug: str
    team_slug: str
    title: str
    action: str
    panel_summary: str
    uid: str | None = None


def _git_name_status(
    base_ref: str, head_ref: str, orgs_dir: Path
) -> list[tuple[str, str | None, str | None]]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "-M",
            f"{base_ref}..{head_ref}",
            "--",
            str(orgs_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    changes = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        status = fields[0]
        if status.startswith(("R", "C")):
            changes.append((status[0], fields[1], fields[2]))
        elif status == "A":
            changes.append((status, None, fields[1]))
        elif status == "D":
            changes.append((status, fields[1], None))
        elif status == "M":
            changes.append((status, fields[1], fields[1]))
    return changes


def _read_json_at_ref(ref: str, path: str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _flatten_panels(dashboard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    flattened: dict[str, dict[str, Any]] = {}

    def visit(panels: Any, parent: str = "root") -> None:
        if not isinstance(panels, list):
            return
        for index, panel in enumerate(panels):
            if not isinstance(panel, dict):
                continue
            key = str(panel.get("id") or panel.get("refId") or f"{parent}.{index}")
            flattened[key] = panel
            visit(panel.get("panels"), key)

    visit(dashboard.get("panels"))
    return flattened


def panel_change_summary(
    previous: dict[str, Any] | None, current: dict[str, Any] | None
) -> str:
    if previous is None or current is None:
        return "—"
    old_panels = _flatten_panels(previous)
    new_panels = _flatten_panels(current)
    added = len(new_panels.keys() - old_panels.keys())
    removed = len(old_panels.keys() - new_panels.keys())
    modified = sum(
        old_panels[key] != new_panels[key]
        for key in old_panels.keys() & new_panels.keys()
    )
    parts = []
    if added:
        parts.append(f"{added} added")
    if modified:
        parts.append(f"{modified} modified")
    if removed:
        parts.append(f"{removed} removed")
    return "; ".join(parts) if parts else "No panel changes"


def _is_retired(path: str, data: dict[str, Any] | None) -> bool:
    parts = Path(path).parts
    return (len(parts) > 2 and parts[2].casefold() == "retired") or bool(
        data and data.get("retired") is True
    )


def collect_changes(
    base_ref: str,
    head_ref: str,
    orgs_dir: Path = ORG_ROOT,
) -> list[DashboardChange]:
    changes = []
    for status, old_path, new_path in _git_name_status(base_ref, head_ref, orgs_dir):
        previous = _read_json_at_ref(base_ref, old_path)
        current = _read_json_at_ref(head_ref, new_path)
        path_for_identity = new_path or old_path
        if path_for_identity is None:
            continue
        parts = Path(path_for_identity).parts
        if len(parts) < 3:
            continue
        org_slug = parts[1]
        team_slug = "/".join(parts[2:-1])
        title = str(
            (current or previous or {}).get("title") or Path(path_for_identity).stem
        )
        uid = (current or previous or {}).get("uid")
        if current and _is_retired(new_path or path_for_identity, current):
            action = "Retired"
        elif status == "A":
            action = "Added"
        elif status == "D":
            action = "Removed"
        elif status in {"R", "C"} and old_path != new_path:
            action = "Moved"
        else:
            action = "Modified"
        changes.append(
            DashboardChange(
                org_slug=org_slug,
                team_slug=team_slug,
                title=title,
                action=action,
                panel_summary=panel_change_summary(previous, current),
                uid=str(uid) if uid else None,
            )
        )
    return changes


def _markdown_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value).replace("|", "\\|")


def _preview_url(
    change: DashboardChange,
    sites_dir: Path,
    base_url: str | None,
    pr_number: int | None,
) -> str:
    if not base_url or pr_number is None or not change.uid:
        return "—"
    site_path = sites_dir / f"{change.org_slug}.yaml"
    try:
        config = yaml.safe_load(site_path.read_text(encoding="utf-8"))
        org_id = config["site"]["org_id"]
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        return "—"
    if not isinstance(org_id, int):
        return "—"
    dashboard_preview_uid = preview_uid(change.org_slug, change.uid, pr_number)
    title_slug = slugify(f"PR {pr_number} · {change.title}")
    url = f"{base_url.rstrip('/')}/d/{quote(dashboard_preview_uid)}/{quote(title_slug)}?orgId={org_id}"
    return f"[Preview]({url})"


def render_summary(
    changes: list[DashboardChange],
    sites_dir: Path = SITE_ROOT,
    preview_base_url: str | None = None,
    pr_number: int | None = None,
) -> str:
    if not changes:
        return "No dashboard JSON changes were found."
    lines = [
        "## Dashboard change summary",
        "",
        "| Org | Team / Folder | Dashboard | Action | Panels changed | Preview |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for change in changes:
        preview = _preview_url(change, sites_dir, preview_base_url, pr_number)
        cells = (
            change.org_slug,
            change.team_slug,
            change.title,
            change.action,
            change.panel_summary,
            preview,
        )
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize dashboard changes between Git refs."
    )
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--orgs-dir", type=Path, default=ORG_ROOT)
    parser.add_argument("--sites-dir", type=Path, default=SITE_ROOT)
    parser.add_argument("--preview-base-url")
    parser.add_argument("--pr-number", type=int)
    args = parser.parse_args()
    try:
        changes = collect_changes(args.base_ref, args.head_ref, args.orgs_dir)
        print(
            render_summary(
                changes,
                sites_dir=args.sites_dir,
                preview_base_url=args.preview_base_url,
                pr_number=args.pr_number,
            )
        )
        return 0
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Could not create dashboard change summary: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
