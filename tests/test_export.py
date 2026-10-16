"""Comprehensive unit tests for dashboard export orchestrator and path layout.

Tests:
- Slug generation from various title formats.
- Standard hybrid filename generation (<dashboard_slug>__<uid>.json).
- Path layout derivation for:
  * Standard site teams (orgs/<org_slug>/<team_slug>/<filename>)
  * Master Data Management (orgs/<org_slug>/master-data-management/<filename>)
  * Retired dashboards (orgs/<org_slug>/<team_slug>/retired/<filename>)
- Declarative site configuration loading and validation.
- Live Grafana export flow including active, MDM, retired, and API error resilience.
- Offline directory ingestion including relative path derivation and retired handling.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grafana_dashboards.tools.client import GrafanaAPIError
from grafana_dashboards.tools.export import (
    export_from_grafana,
    get_dashboard_filename,
    get_dashboard_path,
    ingest_from_directory,
    load_site_config,
    slugify,
)


def test_slugify():
    assert slugify("CBG Production") == "cbg-production"
    assert slugify("Riverview City 2000 KLD WTP") == "riverview-city-2000-kld-wtp"
    assert slugify("Meerut CBG - Data Health") == "meerut-cbg-data-health"
    assert slugify("Master Data Management") == "master-data-management"
    assert (
        slugify("  Special @#% Characters & Spaces!  ") == "special-characters-spaces"
    )
    assert slugify("---Leading-and-Trailing---") == "leading-and-trailing"
    assert slugify("") == ""


def test_get_dashboard_filename():
    assert (
        get_dashboard_filename("CBG Production", "c53aefd4-413c")
        == "cbg-production__c53aefd4-413c.json"
    )
    assert (
        get_dashboard_filename("Global Scientific – Portfolio", "port-01")
        == "global-scientific-portfolio__port-01.json"
    )
    # Empty title fallback
    assert get_dashboard_filename("", "uid-empty") == "dashboard__uid-empty.json"


def test_get_dashboard_path():
    root = Path("orgs")

    # 1. Standard team folder
    std_path = get_dashboard_path(
        org_slug="circle-cbg-india-pvt-ltd",
        team_slug="meerut-cbg-plant",
        title="Digester Data",
        uid="e5586707",
        retired=False,
        output_root=root,
    )
    assert (
        std_path
        == root
        / "circle-cbg-india-pvt-ltd"
        / "meerut-cbg-plant"
        / "digester-data__e5586707.json"
    )

    # 2. Master Data Management folder
    mdm_path = get_dashboard_path(
        org_slug="global-scientific-inc",
        team_slug="master-data-management",
        title="Global Scientific - Portfolio",
        uid="port-gsi",
        retired=False,
        output_root=root,
    )
    assert (
        mdm_path
        == root
        / "global-scientific-inc"
        / "master-data-management"
        / "global-scientific-portfolio__port-gsi.json"
    )

    # 3. Retired dashboard subdirectory
    retired_path = get_dashboard_path(
        org_slug="circle-h2o-pvt-ltd",
        team_slug="riverview-city-wtp",
        title="Legacy Flow Meter",
        uid="leg-999",
        retired=True,
        output_root=root,
    )
    assert (
        retired_path
        == root
        / "circle-h2o-pvt-ltd"
        / "riverview-city-wtp"
        / "retired"
        / "legacy-flow-meter__leg-999.json"
    )


def test_load_site_config(tmp_path: Path):
    yaml_file = tmp_path / "test-org.yaml"
    yaml_file.write_text(
        """
site:
  name: "Test Org"
  slug: "test-org"
  org_id: 10
team_folders:
  master-data-management:
    name: "Master Data Management"
    folder_uid: "fld-mdm"
""",
        encoding="utf-8",
    )

    config = load_site_config(yaml_file)
    assert config["site"]["name"] == "Test Org"
    assert config["site"]["slug"] == "test-org"
    assert "master-data-management" in config["team_folders"]


def test_load_site_config_invalid(tmp_path: Path):
    yaml_file = tmp_path / "invalid.yaml"
    yaml_file.write_text("random_key: 123\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing 'site' block"):
        load_site_config(yaml_file)


def test_export_from_grafana_with_mdm_and_retired(tmp_path: Path):
    mock_client = MagicMock()

    # Two folders: MDM and Team A
    def mock_get_dashboards(org_id, folder_uid):
        if folder_uid == "fld-mdm":
            return [{"uid": "uid-mdm", "title": "Portfolio Overview"}]
        if folder_uid == "fld-team":
            return [
                {"uid": "uid-active", "title": "Active Overview"},
                {"uid": "uid-retired", "title": "Old Decommissioned Sensor"},
            ]
        return []

    mock_client.get_dashboards_in_folder.side_effect = mock_get_dashboards

    def mock_get_dashboard(org_id, uid):
        if uid == "uid-retired":
            return {
                "title": "Old Decommissioned Sensor",
                "uid": "uid-retired",
                "retired": True,
                "tags": ["retired"],
            }
        if uid == "uid-mdm":
            return {
                "title": "Portfolio Overview",
                "uid": "uid-mdm",
                "editable": True,
            }
        return {
            "title": "Active Overview",
            "uid": uid,
            "editable": True,
        }

    mock_client.get_dashboard.side_effect = mock_get_dashboard

    site_config = {
        "site": {"name": "Test Org", "slug": "test-org", "org_id": 10},
        "team_folders": {
            "master-data-management": {
                "name": "Master Data Management",
                "folder_uid": "fld-mdm",
            },
            "plant-alpha": {
                "name": "Plant Alpha",
                "folder_uid": "fld-team",
            },
        },
    }

    output_root = tmp_path / "orgs"
    files = export_from_grafana(mock_client, site_config, output_root=output_root)

    assert len(files) == 3

    # Check MDM path
    mdm_file = (
        output_root
        / "test-org"
        / "master-data-management"
        / "portfolio-overview__uid-mdm.json"
    )
    assert mdm_file.exists()

    # Check Active team path
    active_file = (
        output_root / "test-org" / "plant-alpha" / "active-overview__uid-active.json"
    )
    assert active_file.exists()

    # Check Retired team path
    retired_file = (
        output_root
        / "test-org"
        / "plant-alpha"
        / "retired"
        / "old-decommissioned-sensor__uid-retired.json"
    )
    assert retired_file.exists()


def test_export_from_grafana_api_error_handling(tmp_path: Path):
    mock_client = MagicMock()
    mock_client.get_dashboards_in_folder.side_effect = GrafanaAPIError(
        "Folder 500 error", status_code=500
    )

    site_config = {
        "site": {"name": "Test Org", "slug": "test-org", "org_id": 10},
        "team_folders": {
            "failing-team": {
                "name": "Failing Team",
                "folder_uid": "fld-err",
            },
            "skipped-no-uid": {
                "name": "No UID Team",
            },
        },
    }

    output_root = tmp_path / "orgs"
    # Should not raise exception; skips failed and missing folder_uid gracefully
    files = export_from_grafana(mock_client, site_config, output_root=output_root)
    assert files == []


def test_ingest_from_directory_active_and_retired(tmp_path: Path):
    source_dir = tmp_path / "source"
    active_dir = source_dir / "orgs" / "circle-cbg-india-pvt-ltd" / "meerut-cbg-plant"
    retired_dir = active_dir / "retired"
    active_dir.mkdir(parents=True)
    retired_dir.mkdir(parents=True)

    active_json = {
        "id": 99,
        "title": "Raw Active Dashboard",
        "uid": "raw-active-123",
        "editable": True,
    }
    retired_json = {
        "id": 100,
        "title": "Raw Retired Dashboard",
        "uid": "raw-retired-456",
        "retired": True,
    }

    (active_dir / "Active-123.json").write_text(
        json.dumps(active_json), encoding="utf-8"
    )
    (retired_dir / "Retired-456.json").write_text(
        json.dumps(retired_json), encoding="utf-8"
    )

    output_root = tmp_path / "dest_orgs"
    files = ingest_from_directory(source_dir, {}, output_root=output_root)

    assert len(files) == 2
    expected_active = (
        output_root
        / "circle-cbg-india-pvt-ltd"
        / "meerut-cbg-plant"
        / "raw-active-dashboard__raw-active-123.json"
    )
    expected_retired = (
        output_root
        / "circle-cbg-india-pvt-ltd"
        / "meerut-cbg-plant"
        / "retired"
        / "raw-retired-dashboard__raw-retired-456.json"
    )

    assert expected_active.exists()
    assert expected_retired.exists()
