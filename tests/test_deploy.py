"""Unit coverage for safe offline deployment decisions."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from grafana_dashboards.tools.client import GrafanaAPIError
from grafana_dashboards.tools.deploy import deploy_paths


def dashboard(uid="uid-1", **extra):
    return {
        "uid": uid,
        "title": "Overview",
        "schemaVersion": 42,
        "editable": True,
        "tags": [],
        "panels": [],
        **extra,
    }


def site_config(tmp_path: Path, *, folders=None, environments=None):
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir(exist_ok=True)
    config = {
        "site": {"name": "Test Org", "slug": "test-org", "org_id": 11},
        "team_folders": (
            folders if folders is not None else {"team-a": {"folder_uid": "fld-a"}}
        ),
        "datasources": {"postgres": "pg-test"},
    }
    if environments is not None:
        config["environments"] = environments
    (sites_dir / "test-org.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    return sites_dir


def dashboard_file(tmp_path: Path, folder="team-a", data=None):
    orgs_dir = tmp_path / "orgs"
    path = orgs_dir / "test-org" / folder / "overview__uid-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data or dashboard()), encoding="utf-8")
    return orgs_dir, path


def test_deploy_saves_managed_dashboard_with_traceable_message(tmp_path: Path):
    sites_dir = site_config(tmp_path)
    orgs_dir, path = dashboard_file(tmp_path)
    client = MagicMock()
    client.get_dashboard.side_effect = GrafanaAPIError("not found", status_code=404)

    deployed = deploy_paths(
        [path], sites_dir, "production", client, "abc123", "27", "pradeep", orgs_dir
    )

    assert deployed == 1
    client.save_dashboard.assert_called_once()
    saved = client.save_dashboard.call_args.kwargs
    assert saved["org_id"] == 11
    assert saved["folder_uid"] == "fld-a"
    assert saved["overwrite"] is True
    assert saved["dashboard"]["editable"] is False
    assert "managed-by-git" in saved["dashboard"]["tags"]
    assert "PR #27" in saved["message"]
    assert "Commit abc123" in saved["message"]
    assert "Author pradeep" in saved["message"]


def test_deploy_skips_dashboard_already_identical_in_target_folder(tmp_path: Path):
    sites_dir = site_config(tmp_path)
    orgs_dir, path = dashboard_file(tmp_path, data=dashboard(editable=False, tags=["managed-by-git"]))
    client = MagicMock()
    client.get_dashboard.return_value = {
        "dashboard": dashboard(editable=False, tags=["managed-by-git"]),
        "meta": {"folderUid": "fld-a"},
    }

    deployed = deploy_paths(
        [path], sites_dir, "production", client, "abc123", orgs_dir=orgs_dir
    )

    assert deployed == 0
    client.save_dashboard.assert_not_called()


def test_deploy_retired_uses_admin_only_org_retired_folder(tmp_path: Path):
    sites_dir = site_config(tmp_path)
    orgs_dir, path = dashboard_file(
        tmp_path, "Retired/team-a", dashboard(retired=True)
    )
    client = MagicMock()
    client.get_folders.return_value = [{"title": "Retired", "uid": "ret-uid"}]
    client.get_dashboard.side_effect = GrafanaAPIError("not found", status_code=404)

    deployed = deploy_paths(
        [path], sites_dir, "production", client, "abc123", orgs_dir=orgs_dir
    )

    assert deployed == 1
    client.set_folder_permissions.assert_called_once_with(
        11, "ret-uid", [{"role": "Admin", "permission": 4}]
    )
    saved = client.save_dashboard.call_args.kwargs
    assert saved["folder_uid"] == "ret-uid"
    assert saved["dashboard"]["title"].startswith("[RETIRED]")


def test_deploy_fails_closed_when_active_folder_mapping_is_missing(tmp_path: Path):
    sites_dir = site_config(tmp_path, folders={})
    orgs_dir, path = dashboard_file(tmp_path)
    client = MagicMock()

    with pytest.raises(ValueError, match="refusing to create or guess"):
        deploy_paths(
            [path], sites_dir, "production", client, "abc123", orgs_dir=orgs_dir
        )

    client.get_dashboard.assert_not_called()
    client.save_dashboard.assert_not_called()


def test_staging_deploy_fails_closed_without_environment_mapping(tmp_path: Path):
    sites_dir = site_config(tmp_path)
    orgs_dir, path = dashboard_file(tmp_path)
    client = MagicMock()

    with pytest.raises(ValueError, match="no environments.staging block"):
        deploy_paths(
            [path], sites_dir, "staging", client, "abc123", orgs_dir=orgs_dir
        )

    client.get_dashboard.assert_not_called()


def test_staging_deploy_maps_datasource_uids(tmp_path: Path):
    sites_dir = site_config(
        tmp_path,
        environments={
            "staging": {
                "site": {"org_id": 91},
                "team_folders": {"team-a": {"folder_uid": "stage-folder"}},
                "datasource_uid_map": {"prod-pg": "stage-pg"},
            }
        },
    )
    orgs_dir, path = dashboard_file(
        tmp_path,
        data=dashboard(
            datasource={"type": "postgres", "uid": "prod-pg"},
        ),
    )
    client = MagicMock()
    client.get_dashboard.side_effect = GrafanaAPIError("not found", status_code=404)

    deployed = deploy_paths(
        [path], sites_dir, "staging", client, "abc123", orgs_dir=orgs_dir
    )

    assert deployed == 1
    saved = client.save_dashboard.call_args.kwargs
    assert saved["org_id"] == 91
    assert saved["folder_uid"] == "stage-folder"
    assert saved["dashboard"]["datasource"]["uid"] == "stage-pg"
