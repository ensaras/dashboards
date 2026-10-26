"""Offline repository validation coverage."""

import json
from pathlib import Path

import yaml

from grafana_dashboards.tools import validate
from grafana_dashboards.tools.validate import validate_repository


def dashboard(uid: str, title: str, **extra):
    return {
        "uid": uid,
        "title": title,
        "schemaVersion": 42,
        "editable": False,
        "tags": ["managed-by-git"],
        "panels": [],
        **extra,
    }


def repository(tmp_path: Path):
    orgs_dir = tmp_path / "orgs"
    sites_dir = tmp_path / "sites"
    orgs_dir.mkdir()
    sites_dir.mkdir()
    (sites_dir / "test-org.yaml").write_text(
        yaml.safe_dump(
            {
                "site": {"name": "Test Org", "slug": "test-org", "org_id": 11},
                "team_folders": {"team-a": {"folder_uid": "fld-a"}},
                "datasources": {"postgres": "pg-test", "influxdb": "influx-test"},
            }
        ),
        encoding="utf-8",
    )
    return orgs_dir, sites_dir


def write_dashboard(
    orgs_dir: Path, folder: str, data: dict, filename: str | None = None
):
    path = (
        orgs_dir / "test-org" / folder / (filename or f"dashboard__{data['uid']}.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_dashboard_passes_offline_validation(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(orgs_dir, "team-a", dashboard("uid-1", "Overview"))

    assert validate_repository(orgs_dir, sites_dir) == []


def test_schema_validation_rejects_wrong_schema_version(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(
        orgs_dir, "team-a", dashboard("uid-1", "Overview", schemaVersion="42")
    )

    errors = validate_repository(orgs_dir, sites_dir)

    assert any("Grafana dashboard schema error" in error for error in errors)


def test_identity_validation_rejects_duplicate_uid_and_title(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(orgs_dir, "team-a", dashboard("uid-1", "Overview"))
    write_dashboard(
        orgs_dir,
        "team-a",
        dashboard("uid-1", "Overview"),
        "second__uid-1.json",
    )

    errors = validate_repository(orgs_dir, sites_dir)

    assert any("duplicate dashboard UID" in error for error in errors)
    assert any("duplicate title" in error for error in errors)


def test_validation_rejects_unconfigured_folder_datasource_and_cross_org_link(
    tmp_path: Path,
):
    orgs_dir, sites_dir = repository(tmp_path)
    config = yaml.safe_load((sites_dir / "test-org.yaml").read_text(encoding="utf-8"))
    config["datasources"] = {}
    (sites_dir / "test-org.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    data = dashboard(
        "uid-1",
        "Overview",
        links=[{"url": "/grafana/d/other?orgId=22"}],
        panels=[
            {
                "id": 1,
                "type": "timeseries",
                "title": "Panel",
                "datasource": {"type": "postgres", "uid": "pg-uid"},
            }
        ],
    )
    write_dashboard(orgs_dir, "missing-team", data)

    errors = validate_repository(orgs_dir, sites_dir)

    assert any("not configured in sites" in error for error in errors)
    assert any("does not configure one" in error for error in errors)
    assert any("expected 11" in error for error in errors)


def test_retired_dashboard_requires_retired_flag(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(orgs_dir, "Retired/team-a", dashboard("uid-1", "Overview"))

    errors = validate_repository(orgs_dir, sites_dir)

    assert any("must set retired: true" in error for error in errors)


def test_retired_dashboard_with_flag_passes_without_team_mapping(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(
        orgs_dir,
        "Retired/team-a",
        dashboard("uid-1", "Overview", retired=True),
    )

    assert validate_repository(orgs_dir, sites_dir) == []


def test_dashboard_link_target_must_exist_in_same_org(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(
        orgs_dir,
        "team-a",
        dashboard(
            "source-uid",
            "Source",
            links=[{"url": "/grafana/d/missing-uid/target"}],
        ),
    )

    errors = validate_repository(orgs_dir, sites_dir)

    assert any("dashboard link target UID 'missing-uid'" in error for error in errors)


def test_dashboard_link_to_existing_same_org_target_passes(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(orgs_dir, "team-a", dashboard("target-uid", "Target"))
    write_dashboard(
        orgs_dir,
        "team-a",
        dashboard(
            "source-uid",
            "Source",
            links=[{"url": "/grafana/d/target-uid/target"}],
        ),
    )

    assert validate_repository(orgs_dir, sites_dir) == []


def test_retirement_is_blocked_when_active_dashboard_links_to_uid(tmp_path: Path):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(
        orgs_dir, "Retired/team-a", dashboard("old-uid", "Old", retired=True)
    )
    write_dashboard(
        orgs_dir,
        "team-a",
        dashboard("active-uid", "Active", links=[{"url": "/d/old-uid/old"}]),
    )

    errors = validate_repository(orgs_dir, sites_dir)

    assert any("retirement blocked" in error and "old-uid" in error for error in errors)


def test_git_deletion_guard_allows_retained_retired_replacement(
    tmp_path: Path, monkeypatch
):
    orgs_dir, sites_dir = repository(tmp_path)
    write_dashboard(
        orgs_dir,
        "Retired/team-a",
        dashboard("uid-1", "Overview", retired=True),
    )
    monkeypatch.setattr(
        validate,
        "_git_deleted_json",
        lambda *args: [("orgs/test-org/team-a/overview__uid-1.json", "uid-1")],
    )

    errors = validate_repository(orgs_dir, sites_dir, base_ref="main")

    assert not any("deleting a dashboard is blocked" in error for error in errors)


def test_git_deletion_guard_blocks_missing_retired_replacement(
    tmp_path: Path, monkeypatch
):
    orgs_dir, sites_dir = repository(tmp_path)
    monkeypatch.setattr(
        validate,
        "_git_deleted_json",
        lambda *args: [("orgs/test-org/team-a/overview__uid-1.json", "uid-1")],
    )

    errors = validate_repository(orgs_dir, sites_dir, base_ref="main")

    assert any("deleting a dashboard is blocked" in error for error in errors)
