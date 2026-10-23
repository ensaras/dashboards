"""Dashboard export orchestrator CLI.

Discovers and exports Grafana dashboards based on declarative site configurations:
- `sites/<org_slug>.yaml` defines organization ID, team folders, and MDM folder.
- Retrieves live dashboard JSON from Grafana (or ingests from an external directory).
- Normalizes JSON via `normalizer.py`.
- Saves to standard canonical path:
  `orgs/<org_slug>/<team_slug>/<dashboard_slug>__<uid>.json`
  or for retired dashboards:
  `orgs/<org_slug>/<team_slug>/retired/<dashboard_slug>__<uid>.json`
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from grafana_dashboards.tools.client import GrafanaAPIError, GrafanaClient
from grafana_dashboards.tools.normalizer import normalize_dashboard, serialize_dashboard

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to URL-safe lowercase slug."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def get_dashboard_filename(title: str, uid: str) -> str:
    """Generate standard hybrid dashboard filename: <dashboard_slug>__<uid>.json."""
    title_slug = slugify(title) or "dashboard"
    return f"{title_slug}__{uid}.json"


def get_dashboard_path(
    org_slug: str,
    team_slug: str,
    title: str,
    uid: str,
    retired: bool = False,
    output_root: Path = Path("orgs"),
) -> Path:
    """Derive canonical repository path for a dashboard.

    Args:
        org_slug: Organization slug (e.g. 'circle-cbg-india-pvt-ltd').
        team_slug: Team slug (e.g. 'meerut-cbg-plant' or 'master-data-management').
        title: Dashboard title.
        uid: Dashboard UID.
        retired: If True, place in dedicated 'retired/' subdirectory.
        output_root: Root directory (default: 'orgs').

    Returns:
        Canonical Path: orgs/<org_slug>/<team_slug>[/retired]/<dashboard_slug>__<uid>.json
    """
    filename = get_dashboard_filename(title, uid)
    if retired:
        return output_root / org_slug / team_slug / "retired" / filename
    return output_root / org_slug / team_slug / filename


def load_site_config(site_file: Path) -> dict[str, Any]:
    """Load and validate declarative site YAML configuration."""
    with open(site_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config or "site" not in config:
        raise ValueError(
            f"Invalid site configuration in {site_file}: missing 'site' block"
        )

    return config


def export_from_grafana(
    client: GrafanaClient,
    site_config: dict[str, Any],
    output_root: Path = Path("orgs"),
) -> list[Path]:
    """Export all dashboards for an organization using live Grafana API client.

    Args:
        client: Authenticated GrafanaClient instance.
        site_config: Parsed site configuration dictionary.
        output_root: Root directory for dashboard files (default: 'orgs').

    Returns:
        List of written dashboard file paths.
    """
    site_info = site_config["site"]
    org_slug = site_info["slug"]
    org_id = site_info["org_id"]
    team_folders = site_config.get("team_folders", {})

    logger.info(
        "Exporting organization: %s (slug: %s, org_id: %s)",
        site_info["name"],
        org_slug,
        org_id,
    )

    exported_files: list[Path] = []

    for team_slug, folder_info in team_folders.items():
        folder_uid = folder_info.get("folder_uid")
        folder_name = folder_info.get("name", team_slug)

        if not folder_uid:
            logger.warning("  [-] Skipping team %s: missing folder_uid", team_slug)
            continue

        try:
            dashboards = client.get_dashboards_in_folder(
                org_id=org_id, folder_uid=folder_uid
            )
        except GrafanaAPIError as exc:
            logger.error(
                "  [-] Failed to list dashboards in folder '%s' (%s): %s",
                folder_name,
                folder_uid,
                exc,
            )
            continue

        logger.info(
            "  [+] Folder '%s' (%s): found %d dashboard(s)",
            folder_name,
            folder_uid,
            len(dashboards),
        )

        for dash_summary in dashboards:
            uid = dash_summary["uid"]
            summary_title = dash_summary.get("title", uid)

            try:
                raw_dash = client.get_dashboard(org_id=org_id, uid=uid)
            except GrafanaAPIError as exc:
                logger.error(
                    "    [-] Failed to fetch dashboard '%s' (uid: %s): %s",
                    summary_title,
                    uid,
                    exc,
                )
                continue

            # Normalize and serialize
            normalized = normalize_dashboard(raw_dash)
            content = serialize_dashboard(normalized)

            title = normalized.get("title") or summary_title

            is_retired = bool(
                normalized.get("retired") or "retired" in normalized.get("tags", [])
            )
            target_path = get_dashboard_path(
                org_slug=org_slug,
                team_slug=team_slug,
                title=title,
                uid=uid,
                retired=is_retired,
                output_root=output_root,
            )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            logger.info("    -> Saved %s", target_path)
            exported_files.append(target_path)

    return exported_files


def ingest_from_directory(
    source_dir: Path,
    site_configs: dict[str, dict[str, Any]],
    output_root: Path = Path("orgs"),
) -> list[Path]:
    """Ingest raw dashboard JSON files from an input directory structure into canonical repo format.

    Supports reading raw exports (e.g. from docs/grafana_dashboards_json/orgs/<org_slug>/<team_slug>/*.json).

    Args:
        source_dir: Root directory containing raw orgs/... structure or flat JSONs.
        site_configs: Mapping of org_slug -> site_config.
        output_root: Root directory for output (default: 'orgs').

    Returns:
        List of written dashboard file paths.
    """
    logger.info("Ingesting raw dashboard files from: %s", source_dir)
    exported_files: list[Path] = []

    json_files = list(source_dir.rglob("*.json"))
    logger.info("Found %d JSON file(s) in %s", len(json_files), source_dir)

    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("  [-] Skipping unreadable file %s: %s", json_file, exc)
            continue

        normalized = normalize_dashboard(raw_data)
        uid = normalized.get("uid")
        title = normalized.get("title", "dashboard")

        if not uid:
            logger.warning(
                "  [-] Skipping %s: no uid found in dashboard JSON", json_file
            )
            continue

        # Determine org_slug and team_slug from file path relative to source_dir
        rel_parts = json_file.relative_to(source_dir).parts
        org_slug = None
        team_slug = None

        if len(rel_parts) >= 3 and rel_parts[0] == "orgs":
            org_slug = rel_parts[1]
            team_slug = rel_parts[2]
        elif len(rel_parts) >= 2:
            org_slug = rel_parts[0]
            team_slug = rel_parts[1]

        if not org_slug or not team_slug:
            # Fallback to searching site_configs if not in structured path
            logger.warning(
                "  [-] Could not infer org/team from path %s; skipping", json_file
            )
            continue

        is_retired = bool(
            "retired" in rel_parts
            or normalized.get("retired")
            or "retired" in normalized.get("tags", [])
        )
        target_path = get_dashboard_path(
            org_slug=org_slug,
            team_slug=team_slug,
            title=title,
            uid=uid,
            retired=is_retired,
            output_root=output_root,
        )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = serialize_dashboard(normalized)

        target_path.write_text(content, encoding="utf-8")
        logger.info("  [+] Ingested '%s' -> %s", title, target_path)
        exported_files.append(target_path)

    return exported_files


def main() -> int:
    """CLI Entry point for export tool."""
    parser = argparse.ArgumentParser(
        description="Export and normalize Grafana dashboards as code."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--org", help="Export dashboards for a specific organization slug."
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Export dashboards for all organizations in sites/.",
    )
    group.add_argument(
        "--ingest",
        type=str,
        help="Ingest raw dashboard JSONs from a directory (e.g. docs/grafana_dashboards_json).",
    )

    parser.add_argument(
        "--sites-dir",
        type=str,
        default="sites",
        help="Path to directory containing site YAML configuration files (default: 'sites').",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="orgs",
        help="Path to root output directory for exported dashboards (default: 'orgs').",
    )

    args = parser.parse_args()

    sites_path = Path(args.sites_dir)
    output_path = Path(args.output_dir)

    if not sites_path.exists():
        logger.error("Sites directory not found: %s", sites_path)
        return 1

    site_files = sorted(sites_path.glob("*.yaml"))
    site_configs: dict[str, dict[str, Any]] = {}
    for sf in site_files:
        try:
            cfg = load_site_config(sf)
            slug = cfg["site"]["slug"]
            site_configs[slug] = cfg
        except (ValueError, yaml.YAMLError, OSError) as exc:
            logger.error("Failed to load site config %s: %s", sf, exc)
            return 1

    # Ingest from external directory
    if args.ingest:
        source_path = Path(args.ingest)
        if not source_path.exists():
            logger.error("Ingest source directory not found: %s", source_path)
            return 1
        ingest_from_directory(source_path, site_configs, output_root=output_path)
        return 0

    # Live Grafana API export
    client = GrafanaClient()

    targets: list[str] = []
    if args.all:
        targets = sorted(site_configs.keys())
    elif args.org:
        if args.org not in site_configs:
            logger.error(
                "Unknown org slug '%s'. Available: %s",
                args.org,
                list(site_configs.keys()),
            )
            return 1
        targets = [args.org]

    total_exported = 0
    for slug in targets:
        cfg = site_configs[slug]
        try:
            files = export_from_grafana(client, cfg, output_root=output_path)
            total_exported += len(files)
        except (GrafanaAPIError, OSError) as exc:
            logger.error("Export failed for %s: %s", slug, exc)
            return 1

    logger.info(
        "Export completed successfully. Total dashboards exported: %d", total_exported
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
