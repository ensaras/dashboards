"""Purge dashboards from an Org's Retired folder after 90 days."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

from grafana_dashboards.tools.client import GrafanaAPIError, GrafanaClient
from grafana_dashboards.tools.deploy import RETIRED_FOLDER_TITLE

logger = logging.getLogger(__name__)
RETENTION_DAYS = 90


def purge_retired(client: GrafanaClient, org_id: int, now: datetime | None = None) -> int:
    """Delete retired dashboards whose Grafana updated time is at least 90 days old."""
    now = now or datetime.now(UTC)
    matches = [folder for folder in client.get_folders(org_id) if folder.get("title") == RETIRED_FOLDER_TITLE]
    if len(matches) > 1:
        raise ValueError(f"Grafana org {org_id} has multiple {RETIRED_FOLDER_TITLE!r} folders")
    if not matches:
        return 0
    folder_uid = matches[0].get("uid")
    if not isinstance(folder_uid, str) or not folder_uid:
        raise ValueError("Retired folder has no UID")
    client.set_folder_permissions(
        org_id, folder_uid, [{"role": "Admin", "permission": 4}]
    )
    cutoff = now - timedelta(days=RETENTION_DAYS)
    deleted = 0
    for item in client.get_dashboards_in_folder(org_id, folder_uid):
        uid = item.get("uid")
        if not isinstance(uid, str) or not uid:
            raise ValueError("Grafana returned a retired dashboard without a UID")
        detail = client.get_dashboard(org_id, uid)
        updated = detail.get("meta", {}).get("updated") if isinstance(detail, dict) else None
        if not isinstance(updated, str):
            # Fail closed: never purge when Grafana cannot provide an age.
            logger.warning("Skipping Retired dashboard %s: no Grafana updated timestamp", uid)
            continue
        try:
            updated_at = datetime.fromisoformat(updated)
        except ValueError:
            logger.warning("Skipping Retired dashboard %s: invalid updated timestamp", uid)
            continue
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        if updated_at <= cutoff:
            client.delete_dashboard(org_id, uid)
            logger.info("Purged Retired dashboard %s (updated %s)", uid, updated)
            deleted += 1
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge dashboards retained in Grafana's Retired folder.")
    parser.add_argument("--org-id", type=int, required=True)
    args = parser.parse_args()
    try:
        url = os.environ.get("GRAFANA_PROD_URL")
        token = os.environ.get("GRAFANA_PROD_TOKEN")
        if not url or not token:
            raise ValueError("GRAFANA_PROD_URL and GRAFANA_PROD_TOKEN are required")
        client = GrafanaClient(base_url=url, token=token)
        count = purge_retired(client, args.org_id)
        logger.info("Purged %d dashboard(s) from the Retired folder", count)
        return 0
    except (GrafanaAPIError, ValueError) as exc:
        logger.error("Retired dashboard purge failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
