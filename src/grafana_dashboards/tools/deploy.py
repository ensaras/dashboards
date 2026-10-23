"""Deploy Git-managed dashboards to configured Grafana environments."""

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
from grafana_dashboards.tools.export import load_site_config
from grafana_dashboards.tools.normalizer import (
    MANAGED_TAG,
    normalize_dashboard,
    serialize_dashboard,
)
from grafana_dashboards.tools.validate import validate_repository

logger = logging.getLogger(__name__)
ORG_ROOT = Path("orgs")
SITE_ROOT = Path("sites")
RETIRED_FOLDER_TITLE = "Retired"


def changed_dashboard_paths(base_ref: str, head_ref: str, orgs_dir: Path) -> list[Path]:
    """Return existing JSON files changed between two Git refs."""
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base_ref}..{head_ref}",
            "--",
            str(orgs_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [
        Path(item)
        for item in result.stdout.splitlines()
        if item.lower().endswith(".json")
    ]
    return [path for path in paths if path.is_file()]


def _replace_datasource_uids(
    value: Any, uid_map: dict[str, str], missing: set[str]
) -> Any:
    if isinstance(value, dict):
        result = {
            key: _replace_datasource_uids(child, uid_map, missing)
            for key, child in value.items()
        }
        if "datasource" in result and isinstance(result["datasource"], dict):
            ref = result["datasource"]
            uid = ref.get("uid")
            if (
                isinstance(uid, str)
                and uid
                and not uid.startswith("$")
                and uid not in {"-- Grafana --", "-- Mixed --"}
            ):
                if uid in uid_map:
                    ref["uid"] = uid_map[uid]
                else:
                    missing.add(uid)
        return result
    if isinstance(value, list):
        return [_replace_datasource_uids(item, uid_map, missing) for item in value]
    return value


def _deployment_context(
    config: dict[str, Any], environment: str
) -> tuple[int, dict[str, Any], dict[str, str]]:
    if environment == "production":
        site = config.get("site", {})
        folders = config.get("team_folders", {})
        uid_map: dict[str, str] = {}
    else:
        env_config = config.get("environments", {}).get(environment)
        if not isinstance(env_config, dict):
            raise ValueError(
                f"site config has no environments.{environment} block; refusing to guess org, folder, or datasource IDs"
            )
        site = env_config.get("site", {})
        folders = env_config.get("team_folders", {})
        uid_map = env_config.get("datasource_uid_map", {})
        if not isinstance(uid_map, dict):
            raise ValueError(
                f"environments.{environment}.datasource_uid_map must be a mapping"
            )
    org_id = site.get("org_id")
    if org_id is None:
        raise ValueError(f"site config is missing org_id for {environment}")
    if not isinstance(org_id, int):
        raise TypeError(f"site config org_id must be an integer for {environment}")
    if not isinstance(folders, dict):
        raise TypeError(f"team_folders must be a mapping for {environment}")
    return org_id, folders, {str(key): str(value) for key, value in uid_map.items()}


def _get_or_create_retired_folder(client: GrafanaClient, org_id: int) -> str:
    folders = client.get_folders(org_id)
    matches = [
        folder for folder in folders if folder.get("title") == RETIRED_FOLDER_TITLE
    ]
    if len(matches) > 1:
        raise ValueError(
            f"Grafana org {org_id} has multiple {RETIRED_FOLDER_TITLE!r} folders"
        )
    if matches:
        folder = matches[0]
    else:
        folder = client.create_folder(org_id, RETIRED_FOLDER_TITLE)
    folder_uid = folder.get("uid")
    if not isinstance(folder_uid, str) or not folder_uid:
        raise ValueError("Grafana did not return a UID for the Retired folder")
    # Folder permissions replace the inherited role grants, leaving Grafana Admins only.
    client.set_folder_permissions(
        org_id, folder_uid, [{"role": "Admin", "permission": 4}]
    )
    return folder_uid


def deploy_paths(
    paths: list[Path],
    sites_dir: Path,
    environment: str,
    client: GrafanaClient,
    commit_sha: str,
    pull_request: str | None = None,
    author: str | None = None,
    orgs_dir: Path = ORG_ROOT,
) -> int:
    """Deploy changed dashboards; returns the number successfully deployed."""
    config_cache: dict[str, dict[str, Any]] = {}
    context_cache: dict[str, tuple[int, dict[str, Any], dict[str, str]]] = {}
    retired_folder_uids: dict[str, str] = {}
    deployed = 0

    for path in paths:
        rel = path.relative_to(orgs_dir)
        if len(rel.parts) < 2:
            raise ValueError(f"Unexpected dashboard path: {path}")
        org_slug = rel.parts[0]
        team_slug = rel.parts[1]
        if org_slug not in config_cache:
            config_path = sites_dir / f"{org_slug}.yaml"
            config_cache[org_slug] = load_site_config(config_path)
            context_cache[org_slug] = _deployment_context(
                config_cache[org_slug], environment
            )
        org_id, folders, datasource_uid_map = context_cache[org_slug]

        dashboard = json.loads(path.read_text(encoding="utf-8"))
        retired_directory = team_slug.casefold() == "retired"
        if dashboard.get("retired") is True or retired_directory:
            if dashboard.get("retired") is not True:
                raise ValueError(
                    f"{path}: dashboard in Retired directory must set retired: true"
                )
            if org_slug not in retired_folder_uids:
                retired_folder_uids[org_slug] = _get_or_create_retired_folder(
                    client, org_id
                )
            folder_uid = retired_folder_uids[org_slug]
            if not str(dashboard.get("title", "")).startswith("[RETIRED]"):
                dashboard["title"] = (
                    f"[RETIRED] {dashboard.get('title', dashboard['uid'])}"
                )
        else:
            folder = folders.get(team_slug)
            if not isinstance(folder, dict) or not folder.get("folder_uid"):
                raise ValueError(
                    f"No {environment} folder UID configured for {org_slug}/{team_slug}; refusing to create or guess Portal-owned folders"
                )
            folder_uid = folder["folder_uid"]

        if environment != "production":
            missing: set[str] = set()
            dashboard = _replace_datasource_uids(dashboard, datasource_uid_map, missing)
            if missing:
                raise ValueError(
                    f"{path}: staging datasource UID mapping is missing: {', '.join(sorted(missing))}"
                )

        dashboard["editable"] = False
        tags = {str(tag) for tag in dashboard.get("tags", []) if tag}
        tags.add(MANAGED_TAG)
        dashboard["tags"] = sorted(tags)
        message_parts = ["Deployed via Git"]
        if pull_request:
            message_parts.append(f"PR #{pull_request}")
        message_parts.append(f"Commit {commit_sha}")
        if author:
            message_parts.append(f"Author {author}")
        try:
            current = client.get_dashboard(org_id=org_id, uid=str(dashboard["uid"]))
        except GrafanaAPIError as exc:
            if exc.status_code != 404:
                raise
            current = None

        current_dashboard = (
            current.get("dashboard") if isinstance(current, dict) else None
        )
        current_folder_uid = (
            current.get("meta", {}).get("folderUid")
            if isinstance(current, dict)
            else None
        )
        if (
            isinstance(current_dashboard, dict)
            and current_folder_uid == str(folder_uid)
            and serialize_dashboard(normalize_dashboard(current_dashboard))
            == serialize_dashboard(normalize_dashboard(dashboard))
        ):
            logger.info("Already current; skipped %s", path)
            continue

        response = client.save_dashboard(
            org_id=org_id,
            dashboard=dashboard,
            folder_uid=str(folder_uid),
            overwrite=True,
            message=" | ".join(message_parts),
        )
        logger.info(
            "Deployed %s to %s/%s (dashboard UID %s): %s",
            path,
            environment,
            org_slug,
            dashboard.get("uid"),
            response,
        )
        deployed += 1
    return deployed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deploy changed Git dashboards to Grafana."
    )
    parser.add_argument(
        "--environment", choices=("staging", "production"), required=True
    )
    parser.add_argument(
        "--base-ref", required=True, help="Base commit/ref for this deployment."
    )
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--org", help="Limit deployment to one organization slug.")
    parser.add_argument("--sites-dir", type=Path, default=SITE_ROOT)
    parser.add_argument("--orgs-dir", type=Path, default=ORG_ROOT)
    parser.add_argument("--pr-number", default=os.getenv("GITHUB_PR_NUMBER"))
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", "HEAD"))
    parser.add_argument("--author", default=os.getenv("GITHUB_ACTOR"))
    args = parser.parse_args()

    errors = validate_repository(
        args.orgs_dir, args.sites_dir, args.base_ref, args.head_ref
    )
    if errors:
        for error in errors:
            logger.error(error)
        logger.error("Deployment stopped: repository validation failed.")
        return 1

    try:
        paths = changed_dashboard_paths(args.base_ref, args.head_ref, args.orgs_dir)
        if args.org:
            paths = [
                path
                for path in paths
                if path.relative_to(args.orgs_dir).parts[0] == args.org
            ]
        if not paths:
            logger.info("No changed dashboards to deploy.")
            return 0

        url = os.getenv(
            "GRAFANA_STAGING_URL"
            if args.environment == "staging"
            else "GRAFANA_PROD_URL"
        )
        token = os.getenv(
            "GRAFANA_STAGING_TOKEN"
            if args.environment == "staging"
            else "GRAFANA_PROD_TOKEN"
        )
        if not url or not token:
            raise ValueError(
                f"Set the URL and token secrets for the {args.environment} environment"
            )
        client = GrafanaClient(base_url=url, token=token)
        count = deploy_paths(
            paths=paths,
            sites_dir=args.sites_dir,
            environment=args.environment,
            client=client,
            commit_sha=args.commit_sha,
            pull_request=args.pr_number,
            author=args.author,
            orgs_dir=args.orgs_dir,
        )
        logger.info(
            "Deployment complete: %d dashboard(s) deployed to %s.",
            count,
            args.environment,
        )
        return 0
    except (
        GrafanaAPIError,
        OSError,
        TypeError,
        ValueError,
        yaml.YAMLError,
        subprocess.CalledProcessError,
    ) as exc:
        logger.error("Deployment failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
