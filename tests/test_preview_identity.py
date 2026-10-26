import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from grafana_dashboards.tools.preview import preview_paths
from grafana_dashboards.tools.preview_identity import preview_uid


def test_short_source_uid_keeps_documented_suffix():
    assert preview_uid("example-org", "dashboard_123", 27) == "dashboard_123-pr27"


def test_long_source_uid_is_shortened_deterministically_with_hash():
    source_uid = "a" * 36

    result = preview_uid("example-org", source_uid, 123)

    assert len(result) == 40
    assert result.endswith("-pr123")
    assert result != f"{source_uid}-pr123"
    assert result == preview_uid("example-org", source_uid, 123)
    assert result != preview_uid("another-org", source_uid, 123)


@pytest.mark.parametrize("uid", ["short", "bad.uid!", "a" * 41])
def test_invalid_source_uid_fails_before_preview(uid: str):
    with pytest.raises(ValueError, match="Source dashboard UID"):
        preview_uid("example-org", uid, 27)


def test_preview_uses_documented_title_and_uid(tmp_path: Path):
    orgs_dir = tmp_path / "orgs"
    sites_dir = tmp_path / "sites"
    dashboard_path = (
        orgs_dir / "example-org" / "team-a" / "overview__dashboard_123.json"
    )
    dashboard_path.parent.mkdir(parents=True)
    sites_dir.mkdir()
    (sites_dir / "example-org.yaml").write_text(
        yaml.safe_dump({"site": {"org_id": 7}}), encoding="utf-8"
    )
    dashboard_path.write_text(
        json.dumps(
            {
                "uid": "dashboard_123",
                "title": "Overview",
                "schemaVersion": 42,
                "panels": [],
                "tags": [],
            }
        ),
        encoding="utf-8",
    )
    client = MagicMock()
    client.base_url = "https://grafana.example"
    client.get_folders.return_value = []
    client.create_folder.return_value = {"uid": "preview-folder"}
    client.search_dashboards.return_value = []

    links = preview_paths(
        [dashboard_path],
        "example-org",
        sites_dir,
        client,
        27,
        "Review",
        "abc123",
        orgs_dir,
    )

    saved_dashboard = client.save_dashboard.call_args.kwargs["dashboard"]
    assert saved_dashboard["uid"] == "dashboard_123-pr27"
    assert saved_dashboard["title"] == "PR 27 · Overview"
    assert links == [
        "https://grafana.example/d/dashboard_123-pr27/pr-27-overview?orgId=7"
    ]
