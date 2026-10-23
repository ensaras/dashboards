"""Remove PR preview dashboards while retaining the per-Org Preview folder."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from grafana_dashboards.tools.client import GrafanaAPIError, GrafanaClient
from grafana_dashboards.tools.preview import PREVIEW_TAG, PREVIEW_TITLE

logger = logging.getLogger(__name__)


def cleanup_preview(client: GrafanaClient, org_id: int, pr_number: int) -> int:
    """Delete only dashboards tagged for the selected PR; preserve the folder."""
    matches = [folder for folder in client.get_folders(org_id) if folder.get("title") == PREVIEW_TITLE]
    if len(matches) > 1:
        raise ValueError(f"Grafana org {org_id} has multiple {PREVIEW_TITLE!r} folders")
    if not matches:
        return 0
    folder_uid = matches[0].get("uid")
    if not isinstance(folder_uid, str) or not folder_uid:
        raise ValueError("Preview folder has no UID")
    tag = f"{PREVIEW_TAG}-{pr_number}"
    dashboards = client.search_dashboards(org_id, folder_uid=folder_uid, tag=tag)
    deleted = 0
    for dashboard in dashboards:
        uid = dashboard.get("uid")
        if not isinstance(uid, str) or not uid:
            raise ValueError("Grafana returned a preview without a dashboard UID")
        client.delete_dashboard(org_id, uid)
        logger.info("Deleted PR #%d preview dashboard %s", pr_number, uid)
        deleted += 1
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete dashboards for a closed PR preview.")
    parser.add_argument("--org-id", type=int, required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    args = parser.parse_args()
    url = os.environ.get("GRAFANA_PROD_URL")
    token = os.environ.get("GRAFANA_PROD_TOKEN")
    if not url or not token:
        logger.error("GRAFANA_PROD_URL and GRAFANA_PROD_TOKEN are required")
        return 1
    try:
        count = cleanup_preview(GrafanaClient(base_url=url, token=token), args.org_id, args.pr_number)
        logger.info("Removed %d preview dashboard(s) for PR #%d", count, args.pr_number)
        return 0
    except (GrafanaAPIError, ValueError) as exc:
        logger.error("Preview cleanup failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
