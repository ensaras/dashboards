"""Unit tests for semantic diff tool."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from grafana_dashboards.tools.diff import (
    diff_dashboard,
    generate_diff,
    parse_uid_from_filename,
    run_diff_for_org,
)
from grafana_dashboards.tools.normalizer import normalize_dashboard, serialize_dashboard


def test_parse_uid_from_filename():
    assert (
        parse_uid_from_filename("cbg-production__c53aefd4-413c.json") == "c53aefd4-413c"
    )
    assert parse_uid_from_filename("dashboard-only.json") == "dashboard-only"


def test_generate_diff():
    a = '{\n  "a": 1\n}\n'
    b = '{\n  "a": 2\n}\n'
    diff = generate_diff(a, b, "test.json")
    assert '-  "a": 1' in diff
    assert '+  "a": 2' in diff


def test_diff_dashboard_identical(tmp_path: Path):
    raw = {
        "title": "Test Dashboard",
        "uid": "uid-100",
        "editable": False,
        "tags": ["managed-by-git"],
    }
    normalized = normalize_dashboard(raw)
    file_path = tmp_path / "test__uid-100.json"
    file_path.write_text(serialize_dashboard(normalized), encoding="utf-8")

    # When remote matches, returns None
    result = diff_dashboard(file_path, raw)
    assert result is None


def test_diff_dashboard_missing_remote(tmp_path: Path):
    file_path = tmp_path / "test__uid-100.json"
    file_path.write_text("{}", encoding="utf-8")

    result = diff_dashboard(file_path, None)
    assert "MISSING in Grafana" in result


def test_run_diff_for_org_offline_mode(tmp_path: Path):
    orgs_root = tmp_path / "orgs"
    team_dir = orgs_root / "test-org" / "team-a"
    team_dir.mkdir(parents=True)

    raw_dashboard = {
        "title": "Offline Dashboard",
        "uid": "off-01",
        "editable": False,
        "tags": ["managed-by-git"],
    }
    normalized = normalize_dashboard(raw_dashboard)
    local_file = team_dir / "offline-dashboard__off-01.json"
    local_file.write_text(serialize_dashboard(normalized), encoding="utf-8")

    # Reference dir with matching raw file
    ref_dir = tmp_path / "ref"
    ref_dir.mkdir()
    (ref_dir / "raw-off-01.json").write_text(
        json.dumps(raw_dashboard), encoding="utf-8"
    )

    site_config = {
        "site": {"name": "Test Org", "slug": "test-org", "org_id": 99},
        "team_folders": {"team-a": {"folder_uid": "fld-a"}},
    }

    matches, diffs = run_diff_for_org(
        client=None,
        site_config=site_config,
        orgs_root=orgs_root,
        reference_root=ref_dir,
    )

    assert matches == 1
    assert diffs == 0


def test_run_diff_for_org_live_client(tmp_path: Path):
    orgs_root = tmp_path / "orgs"
    team_dir = orgs_root / "test-org" / "team-a"
    team_dir.mkdir(parents=True)

    raw_dashboard = {
        "title": "Live Dashboard",
        "uid": "live-01",
        "editable": False,
        "tags": ["managed-by-git"],
    }
    normalized = normalize_dashboard(raw_dashboard)
    local_file = team_dir / "live-dashboard__live-01.json"
    local_file.write_text(serialize_dashboard(normalized), encoding="utf-8")

    mock_client = MagicMock()
    mock_client.get_dashboard.return_value = raw_dashboard

    site_config = {
        "site": {"name": "Test Org", "slug": "test-org", "org_id": 99},
        "team_folders": {"team-a": {"folder_uid": "fld-a"}},
    }

    matches, diffs = run_diff_for_org(
        client=mock_client,
        site_config=site_config,
        orgs_root=orgs_root,
    )

    assert matches == 1
    assert diffs == 0
    mock_client.get_dashboard.assert_called_once_with(org_id=99, uid="live-01")
