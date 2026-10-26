"""Publish Git-managed dashboards to per-Org, Admin-only PR preview folders."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from grafana_dashboards.tools.client import GrafanaAPIError, GrafanaClient
from grafana_dashboards.tools.deploy import changed_dashboard_paths
from grafana_dashboards.tools.export import load_site_config, slugify
from grafana_dashboards.tools.normalizer import MANAGED_TAG
from grafana_dashboards.tools.preview_identity import preview_uid
from grafana_dashboards.tools.validate import validate_repository

logger = logging.getLogger(__name__)
ORG_ROOT = Path("orgs")
SITE_ROOT = Path("sites")
PREVIEW_TITLE = "Preview"
PREVIEW_TAG = "pr-preview"


def _get_or_create_preview_folder(client: GrafanaClient, org_id: int) -> str:
    matches = [
        folder
        for folder in client.get_folders(org_id)
        if folder.get("title") == PREVIEW_TITLE
    ]
    if len(matches) > 1:
        raise ValueError(f"Grafana org {org_id} has multiple {PREVIEW_TITLE!r} folders")
    folder = matches[0] if matches else client.create_folder(org_id, PREVIEW_TITLE)
    folder_uid = folder.get("uid")
    if not isinstance(folder_uid, str) or not folder_uid:
        raise ValueError("Grafana did not return a UID for the Preview folder")
    # Reassert the ACL on each run so accidental permission drift is corrected.
    client.set_folder_permissions(
        org_id, folder_uid, [{"role": "Admin", "permission": 4}]
    )
    return folder_uid


def preview_paths(
    paths: list[Path],
    org_slug: str,
    sites_dir: Path,
    client: GrafanaClient,
    pr_number: int,
    pr_title: str,
    commit_sha: str,
    orgs_dir: Path = ORG_ROOT,
) -> list[str]:
    """Create or update the selected Org's preview dashboards and return URLs."""
    config = load_site_config(sites_dir / f"{org_slug}.yaml")
    org_id = config.get("site", {}).get("org_id")
    if not isinstance(org_id, int):
        raise TypeError(f"sites/{org_slug}.yaml is missing an integer site.org_id")
    folder_uid = _get_or_create_preview_folder(client, org_id)
    expected_uids: set[str] = set()
    for path in paths:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        source_uid = dashboard.get("uid")
        if not isinstance(source_uid, str) or not source_uid:
            raise ValueError(f"{path}: dashboard UID is missing")
        expected_uids.add(preview_uid(org_slug, source_uid, pr_number))

    # Keep the open PR preview in sync with its current diff, while preserving
    # dashboards that are still part of the PR so their UIDs update in place.
    pr_tag = f"{PREVIEW_TAG}-{pr_number}"
    for existing in client.search_dashboards(org_id, folder_uid=folder_uid, tag=pr_tag):
        existing_uid = existing.get("uid")
        if isinstance(existing_uid, str) and existing_uid not in expected_uids:
            client.delete_dashboard(org_id, existing_uid)

    links: list[str] = []
    for path in paths:
        if path.relative_to(orgs_dir).parts[0] != org_slug:
            continue
        dashboard: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        source_uid = dashboard.get("uid")
        if not isinstance(source_uid, str) or not source_uid:
            raise ValueError(f"{path}: dashboard UID is missing")
        dashboard["uid"] = preview_uid(org_slug, source_uid, pr_number)
        dashboard.pop("id", None)
        dashboard.pop("version", None)
        dashboard["editable"] = False
        source_title = str(dashboard.get("title", source_uid))
        dashboard["title"] = f"PR {pr_number} · {source_title}"
        tags = {str(tag) for tag in dashboard.get("tags", []) if tag}
        tags.update({MANAGED_TAG, PREVIEW_TAG, f"{PREVIEW_TAG}-{pr_number}"})
        dashboard["tags"] = sorted(tags)
        client.save_dashboard(
            org_id=org_id,
            dashboard=dashboard,
            folder_uid=folder_uid,
            overwrite=True,
            message=f"PR #{pr_number} preview | Commit {commit_sha} | {pr_title}",
        )
        links.append(
            f"{client.base_url}/d/{dashboard['uid']}/{slugify(dashboard['title'])}?orgId={org_id}"
        )
        logger.info("Published PR #%d preview for %s", pr_number, path)
    return links


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish Admin-only Grafana PR previews."
    )
    parser.add_argument("--org", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--pr-title", default="Dashboard changes")
    parser.add_argument("--sites-dir", type=Path, default=SITE_ROOT)
    parser.add_argument("--orgs-dir", type=Path, default=ORG_ROOT)
    args = parser.parse_args()
    errors = validate_repository(
        args.orgs_dir, args.sites_dir, args.base_ref, args.head_ref
    )
    if errors:
        for error in errors:
            logger.error(error)
        return 1
    try:
        paths = changed_dashboard_paths(args.base_ref, args.head_ref, args.orgs_dir)
        paths = [
            path
            for path in paths
            if path.relative_to(args.orgs_dir).parts[0] == args.org
        ]
        url = os.environ.get("GRAFANA_PROD_URL")
        token = os.environ.get("GRAFANA_PROD_TOKEN")
        if not url or not token:
            raise ValueError("GRAFANA_PROD_URL and GRAFANA_PROD_TOKEN are required")
        client = GrafanaClient(base_url=url, token=token)
        links = preview_paths(
            paths,
            args.org,
            args.sites_dir,
            client,
            args.pr_number,
            args.pr_title,
            args.head_ref,
            args.orgs_dir,
        )
        for link in links:
            print(link)
        return 0
    except (
        GrafanaAPIError,
        OSError,
        TypeError,
        ValueError,
        yaml.YAMLError,
        subprocess.CalledProcessError,
    ) as exc:
        logger.error("Preview deployment failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
