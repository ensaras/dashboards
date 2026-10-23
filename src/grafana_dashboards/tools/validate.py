"""Offline validation for dashboard JSON and repository conventions."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from grafana_dashboards.tools.export import load_site_config

logger = logging.getLogger(__name__)
ORG_ROOT = Path("orgs")
SITE_ROOT = Path("sites")
UID_SUFFIX = re.compile(r"^[^/\\]+__(.+)\.json$")
DATASOURCE_KEYS = {
    "postgres": {"postgres", "postgresql", "grafana-postgresql-datasource"},
    "influxdb": {"influxdb", "influx"},
}


def _walk_datasources(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "datasource":
                yield child
            yield from _walk_datasources(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_datasources(child)


def _walk_link_urls(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"url", "linkUrl"} and isinstance(child, str):
                yield child
            yield from _walk_link_urls(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_link_urls(child)


def _datasource_logical_type(ref: dict[str, Any]) -> str | None:
    dtype = str(ref.get("type", "")).lower()
    for logical_type, aliases in DATASOURCE_KEYS.items():
        if dtype in aliases:
            return logical_type
    return None


def _validate_dashboard(
    path: Path,
    orgs_dir: Path,
    data: Any,
    site_config: dict[str, Any],
    errors: list[str],
) -> tuple[str | None, str | None]:
    rel = path.relative_to(orgs_dir)
    if len(rel.parts) < 2:
        errors.append(f"{path}: expected orgs/<org>/<team>/<dashboard>.json or orgs/<org>/Retired/<dashboard>.json")
        return None, None

    org_slug = rel.parts[0]
    team_slug = rel.parts[1]
    retired_directory = team_slug.casefold() == "retired"
    site = site_config.get("site", {})
    if site.get("slug") != org_slug:
        errors.append(f"{path}: organization directory does not match site slug")
    folder = site_config.get("team_folders", {}).get(team_slug)
    if not retired_directory and (not isinstance(folder, dict) or not folder.get("folder_uid")):
        errors.append(f"{path}: team/folder {team_slug!r} is not configured in sites")

    if not isinstance(data, dict):
        errors.append(f"{path}: dashboard JSON root must be an object")
        return org_slug, None

    uid = data.get("uid")
    title = data.get("title")
    if not isinstance(uid, str) or not uid.strip():
        errors.append(f"{path}: dashboard must have a non-empty string uid")
        uid = None
    match = UID_SUFFIX.match(path.name)
    if not match:
        errors.append(f"{path}: filename must use <dashboard_slug>__<uid>.json")
    elif uid and match.group(1) != uid:
        errors.append(f"{path}: filename UID {match.group(1)!r} does not match JSON UID {uid!r}")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"{path}: dashboard must have a non-empty string title")
        title = None
    if data.get("editable") is not False:
        errors.append(f"{path}: editable must be false (dashboard JSON is Git-managed)")
    if retired_directory and data.get("retired") is not True:
        errors.append(f"{path}: dashboards in an Org's Retired directory must set retired: true")
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        errors.append(f"{path}: tags must be an array of strings")
        tags = []
    if "managed-by-git" not in tags:
        errors.append(f"{path}: tags must include 'managed-by-git'")

    configured_datasources = site_config.get("datasources", {})
    if not isinstance(configured_datasources, dict):
        configured_datasources = {}
    for ref in _walk_datasources(data):
        if not isinstance(ref, dict):
            continue
        logical_type = _datasource_logical_type(ref)
        if logical_type and not any(
            key in configured_datasources
            for key in DATASOURCE_KEYS[logical_type]
            if configured_datasources.get(key)
        ):
            errors.append(
                f"{path}: uses {logical_type} datasource but sites/{org_slug}.yaml does not configure one"
            )

    org_id = site.get("org_id")
    for url in _walk_link_urls(data):
        for linked_org_id in re.findall(r"(?:[?&])orgId=(\d+)", url):
            if org_id is not None and int(linked_org_id) != int(org_id):
                errors.append(
                    f"{path}: link points to Grafana orgId={linked_org_id}, expected {org_id}"
                )
    return org_slug, title


def _git_deleted_json(base_ref: str, head_ref: str, orgs_dir: Path) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "diff", "--name-status", "-M", f"{base_ref}..{head_ref}", "--", str(orgs_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    removed: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if fields[0] == "D" and fields[1].lower().endswith(".json"):
            removed.append((fields[1], Path(fields[1]).stem.rsplit("__", 1)[-1]))
    return removed


def validate_repository(
    orgs_dir: Path = ORG_ROOT,
    sites_dir: Path = SITE_ROOT,
    base_ref: str | None = None,
    head_ref: str = "HEAD",
) -> list[str]:
    """Return validation errors for checked-in dashboards and optional Git delta."""
    errors: list[str] = []
    site_configs: dict[str, dict[str, Any]] = {}
    for site_file in sorted(sites_dir.glob("*.yaml")):
        try:
            cfg = load_site_config(site_file)
            slug = cfg["site"]["slug"]
            if site_file.stem != slug:
                errors.append(f"{site_file}: filename must match site slug {slug!r}")
            if slug in site_configs:
                errors.append(f"{site_file}: duplicate site slug {slug!r}")
            site_configs[slug] = cfg
        except (KeyError, TypeError, ValueError, yaml.YAMLError, OSError) as exc:
            errors.append(f"{site_file}: invalid site configuration: {exc}")

    uids: dict[str, dict[str, Path]] = {}
    titles: dict[tuple[str, str], dict[str, Path]] = {}
    dashboards = sorted(orgs_dir.rglob("*.json")) if orgs_dir.exists() else []
    for path in dashboards:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{path}: invalid or unreadable JSON: {exc}")
            continue

        rel = path.relative_to(orgs_dir)
        org_slug = rel.parts[0] if rel.parts else ""
        config = site_configs.get(org_slug)
        if config is None:
            errors.append(f"{path}: no sites/{org_slug}.yaml configuration")
            continue
        checked_org, title = _validate_dashboard(path, orgs_dir, data, config, errors)
        uid = data.get("uid") if isinstance(data, dict) else None
        if checked_org and isinstance(uid, str):
            prior = uids.setdefault(checked_org, {}).get(uid)
            if prior:
                errors.append(f"{path}: duplicate dashboard UID {uid!r} also used by {prior}")
            else:
                uids[checked_org][uid] = path
        if checked_org and isinstance(title, str) and len(rel.parts) >= 2:
            key = (checked_org, rel.parts[1])
            prior = titles.setdefault(key, {}).get(title.casefold())
            if prior:
                errors.append(f"{path}: duplicate title {title!r} in folder also used by {prior}")
            else:
                titles[key][title.casefold()] = path

    if base_ref:
        try:
            for deleted_path, uid in _git_deleted_json(base_ref, head_ref, orgs_dir):
                deleted_org = Path(deleted_path).parts[1] if len(Path(deleted_path).parts) > 1 else ""
                replacement = next(
                    (
                        p
                        for p in dashboards
                        if p.relative_to(orgs_dir).parts[0] == deleted_org
                        and p.stem.rsplit("__", 1)[-1] == uid
                    ),
                    None,
                )
                is_retired = False
                if replacement:
                    try:
                        candidate = json.loads(replacement.read_text(encoding="utf-8"))
                        is_retired = bool(candidate.get("retired"))
                    except (json.JSONDecodeError, OSError):
                        pass
                if not is_retired:
                    errors.append(
                        f"{deleted_path}: deleting a dashboard is blocked; retain it in Git with retired: true"
                    )
        except (subprocess.CalledProcessError, OSError) as exc:
            errors.append(f"Could not inspect Git changes for deletion checks: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate dashboard JSON and repository metadata offline.")
    parser.add_argument("--orgs-dir", type=Path, default=ORG_ROOT)
    parser.add_argument("--sites-dir", type=Path, default=SITE_ROOT)
    parser.add_argument("--base-ref", help="Optional base Git ref for deleted-dashboard checks.")
    parser.add_argument("--head-ref", default="HEAD")
    args = parser.parse_args()

    errors = validate_repository(args.orgs_dir, args.sites_dir, args.base_ref, args.head_ref)
    if errors:
        for error in errors:
            logger.error(error)
        logger.error("Validation failed with %d error(s).", len(errors))
        return 1
    logger.info("Validation passed for %d dashboard JSON file(s).", len(list(args.orgs_dir.rglob("*.json"))))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
