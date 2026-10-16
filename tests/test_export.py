"""Unit tests for dashboard export tool."""

from pathlib import Path
from unittest.mock import MagicMock

from grafana_dashboards.tools.export import (
    export_from_grafana,
    get_dashboard_filename,
    ingest_from_directory,
    load_site_config,
    slugify,
)


def test_slugify():
    assert slugify("CBG Production") == "cbg-production"
    assert slugify("Riverview City 2000 KLD WTP") == "riverview-city-2000-kld-wtp"
    assert slugify("Meerut CBG - Data Health") == "meerut-cbg-data-health"
    assert slugify("Master Data Management") == "master-data-management"


def test_get_dashboard_filename():
    filename = get_dashboard_filename("CBG Production", "c53aefd4-413c")
    assert filename == "cbg-production__c53aefd4-413c.json"


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


def test_export_from_grafana(tmp_path: Path):
    mock_client = MagicMock()
    mock_client.get_dashboards_in_folder.return_value = [
        {"uid": "uid-01", "title": "Overview Dashboard"},
        {"uid": "uid-02", "title": "Energy Metrics"},
    ]
    mock_client.get_dashboard.side_effect = lambda org_id, uid: {
        "id": 1,
        "version": 10,
        "title": f"Title {uid}",
        "uid": uid,
        "editable": True,
    }

    site_config = {
        "site": {"name": "Test Org", "slug": "test-org", "org_id": 10},
        "team_folders": {
            "master-data-management": {
                "name": "Master Data Management",
                "folder_uid": "fld-mdm",
            }
        },
    }

    output_root = tmp_path / "orgs"
    files = export_from_grafana(mock_client, site_config, output_root=output_root)

    assert len(files) == 2
    mdm_dir = output_root / "test-org" / "master-data-management"
    assert mdm_dir.exists()
    assert (mdm_dir / "overview-dashboard__uid-01.json").exists()
    assert (mdm_dir / "energy-metrics__uid-02.json").exists()


def test_ingest_from_directory(tmp_path: Path):
    # Setup mock source directory structure matching docs/grafana_dashboards_json
    source_dir = tmp_path / "source"
    sample_team_dir = source_dir / "orgs" / "circle-cbg-india-pvt-ltd" / "meerut-cbg-plant"
    sample_team_dir.mkdir(parents=True)

    raw_json = {
        "id": 99,
        "version": 5,
        "title": "Raw Ingested Dashboard",
        "uid": "raw-uid-123",
        "editable": True,
    }
    import json
    (sample_team_dir / "Raw Dashboard-12345.json").write_text(json.dumps(raw_json), encoding="utf-8")

    output_root = tmp_path / "dest_orgs"
    files = ingest_from_directory(source_dir, {}, output_root=output_root)

    assert len(files) == 1
    expected_path = output_root / "circle-cbg-india-pvt-ltd" / "meerut-cbg-plant" / "raw-ingested-dashboard__raw-uid-123.json"
    assert expected_path.exists()

    with open(expected_path, "r", encoding="utf-8") as f:
        content = json.load(f)
    assert "id" not in content
    assert content["editable"] is False
    assert "managed-by-git" in content["tags"]
