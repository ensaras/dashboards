"""Semantic diff engine comparing local Git dashboard JSON against Grafana.

Ensures deterministic parity between repository definitions and live dashboards:
- Parses dashboard UID from filename: `<dashboard_slug>__<uid>.json`.
- Fetches live dashboard from Grafana (or compares against a reference directory).
- Normalizes live JSON in-memory using `normalizer.py`.
- Generates a unified diff if differences exist.
- Returns Exit Code 0 if 100% parity; Exit Code 1 if differences are found.
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from grafana_dashboards.tools.client import GrafanaAPIError, GrafanaClient
from grafana_dashboards.tools.export import load_site_config
from grafana_dashboards.tools.normalizer import normalize_dashboard, serialize_dashboard

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_uid_from_filename(filename: str) -> str:
    """Extract dashboard UID from hybrid filename: <slug>__<uid>.json."""
    stem = Path(filename).stem
    if "__" in stem:
        return stem.rsplit("__", 1)[1]
    return stem


def generate_diff(local_str: str, remote_str: str, filename: str) -> str:
    """Generate a unified diff between local Git JSON and remote/live JSON."""
    diff_lines = list(
        difflib.unified_diff(
            local_str.splitlines(keepends=True),
            remote_str.splitlines(keepends=True),
            fromfile=f"local/{filename}",
            tofile=f"remote/{filename}",
        )
    )
    return "".join(diff_lines)


def diff_dashboard(
    local_path: Path,
    remote_data: dict[str, Any] | None,
) -> str | None:
    """Compare a single local dashboard file against remote data.

    Returns:
        Unified diff string if different; None if identical.
    """
    if remote_data is None:
        return f"Dashboard {local_path.name} exists locally in Git but is MISSING in Grafana!\n"

    local_text = local_path.read_text(encoding="utf-8")
    normalized_remote = normalize_dashboard(remote_data)
    remote_text = serialize_dashboard(normalized_remote)

    if local_text == remote_text:
        return None

    return generate_diff(local_text, remote_text, local_path.name)


def _find_reference_dashboard(
    reference_root: Path, uid: str, local_name: str
) -> dict[str, Any] | None:
    """Search for a reference dashboard matching either the filename or internal UID."""
    candidates = list(reference_root.rglob(f"*{uid}*.json")) + list(
        reference_root.rglob(local_name)
    )
    for cand in candidates:
        try:
            with open(cand, "r", encoding="utf-8") as f:
                data = json.load(f)
            cand_uid = data.get("uid") or (
                data.get("dashboard", {}).get("uid") if isinstance(data, dict) else None
            )
            if cand_uid == uid:
                return data
        except (json.JSONDecodeError, OSError):
            continue

    # If no file name matched the UID, scan files in reference_root matching the UID inside JSON
    for json_file in reference_root.rglob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cand_uid = data.get("uid") or (
                data.get("dashboard", {}).get("uid") if isinstance(data, dict) else None
            )
            if cand_uid == uid:
                return data
        except (json.JSONDecodeError, OSError):
            continue

    return None


def run_diff_for_org(
    client: GrafanaClient | None,
    site_config: dict[str, Any],
    orgs_root: Path = Path("orgs"),
    reference_root: Path | None = None,
) -> tuple[int, int]:
    """Execute diff for a single organization.

    Args:
        client: Optional GrafanaClient for live API checks.
        site_config: Parsed site configuration dictionary.
        orgs_root: Root directory of local Git dashboards.
        reference_root: Optional reference directory to diff against (offline mode).

    Returns:
        Tuple of (matching_count, differences_count).
    """
    site_info = site_config["site"]
    org_slug = site_info["slug"]
    org_id = site_info["org_id"]

    org_dir = orgs_root / org_slug
    if not org_dir.exists():
        logger.warning(
            "No local dashboards directory found for %s (%s)", org_slug, org_dir
        )
        return 0, 0

    local_files = list(org_dir.rglob("*.json"))
    if not local_files:
        logger.info("No local dashboards to diff for %s", org_slug)
        return 0, 0

    logger.info(
        "Checking diff for %s (found %d local dashboard(s))...",
        site_info["name"],
        len(local_files),
    )

    matches = 0
    diffs = 0

    for local_file in local_files:
        uid = parse_uid_from_filename(local_file.name)
        remote_data = None

        if reference_root:
            remote_data = _find_reference_dashboard(
                reference_root, uid, local_file.name
            )
        elif client:
            # Live Grafana API mode
            try:
                remote_data = client.get_dashboard(org_id=org_id, uid=uid)
            except GrafanaAPIError as exc:
                if exc.status_code == 404:
                    remote_data = None
                else:
                    logger.error(
                        "Error querying Grafana for %s (%s): %s",
                        local_file.name,
                        uid,
                        exc,
                    )
                    diffs += 1
                    continue

        diff_output = diff_dashboard(local_file, remote_data)
        if diff_output:
            logger.error("Diff found in %s:\n%s", local_file, diff_output)
            diffs += 1
        else:
            matches += 1

    return matches, diffs


def main() -> int:
    """CLI Entry point for semantic diff engine."""
    parser = argparse.ArgumentParser(
        description="Semantic diff engine comparing local Git JSON against Grafana."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--org", help="Run diff for a specific organization slug.")
    group.add_argument(
        "--all", action="store_true", help="Run diff for all organizations in sites/."
    )

    parser.add_argument(
        "--sites-dir",
        type=str,
        default="sites",
        help="Path to directory containing site YAML configuration files (default: 'sites').",
    )
    parser.add_argument(
        "--orgs-dir",
        type=str,
        default="orgs",
        help="Path to root directory of local Git dashboards (default: 'orgs').",
    )
    parser.add_argument(
        "--reference-dir",
        type=str,
        help="Optional directory of raw dashboards to compare against instead of live API.",
    )

    args = parser.parse_args()

    sites_path = Path(args.sites_dir)
    orgs_path = Path(args.orgs_dir)
    ref_path = Path(args.reference_dir) if args.reference_dir else None

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
        except (ValueError, OSError) as exc:
            logger.error("Failed to load site config %s: %s", sf, exc)
            return 1

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

    client = None if ref_path else GrafanaClient()

    total_matches = 0
    total_diffs = 0

    for slug in targets:
        cfg = site_configs[slug]
        matches, diffs = run_diff_for_org(
            client=client,
            site_config=cfg,
            orgs_root=orgs_path,
            reference_root=ref_path,
        )
        total_matches += matches
        total_diffs += diffs

    logger.info(
        "Diff completed: %d matching, %d difference(s).", total_matches, total_diffs
    )
    if total_diffs > 0:
        logger.error("Semantic diff check FAILED with %d difference(s).", total_diffs)
        return 1

    logger.info("Semantic diff check PASSED: 0 differences found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
