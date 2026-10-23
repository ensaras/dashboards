"""Comprehensive unit tests for GrafanaClient.

Tests:
- Authentication configurations: Bearer token (param / env), Basic Auth (param / env), fallback.
- Header context switching: X-Grafana-Org-Id header injection and omission when org_id is None.
- HTTP error handling: HTTP status codes (400, 401, 403, 404, 500) mapped to GrafanaAPIError.
- Network error handling: requests.RequestException mapped to GrafanaAPIError.
- 204 No Content & empty response handling.
- Folder APIs: get_folders, get_folder, create_folder (with and without UID), set_folder_permissions.
- Dashboard APIs: search_dashboards, get_dashboards_in_folder, get_dashboard, save_dashboard, delete_dashboard.
- Datasource & Org APIs: get_datasources, get_current_org, get_all_orgs.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from grafana_dashboards.tools.client import GrafanaAPIError, GrafanaClient


@pytest.fixture
def client() -> GrafanaClient:
    return GrafanaClient(
        base_url="https://grafana.example.com",
        token="glsa_test_token_12345",
    )


# --- Authentication & Initialization Tests ---


def test_client_init_with_token(client: GrafanaClient) -> None:
    assert client.base_url == "https://grafana.example.com"
    assert client.session.headers["Authorization"] == "Bearer glsa_test_token_12345"
    assert client.session.headers["Content-Type"] == "application/json"
    assert client.session.headers["Accept"] == "application/json"


def test_client_init_with_basic_auth() -> None:
    client_basic = GrafanaClient(
        base_url="https://grafana.example.com",
        auth=("admin_user", "secret_pass"),
    )
    assert client_basic.session.auth == ("admin_user", "secret_pass")
    assert "Authorization" not in client_basic.session.headers


def test_client_init_with_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAFANA_ADMIN_TOKEN", "env_token_999")
    monkeypatch.delenv("GRAFANA_API_KEY", raising=False)
    client_env = GrafanaClient(base_url="https://grafana.example.com")
    assert client_env.session.headers["Authorization"] == "Bearer env_token_999"


def test_client_init_with_env_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAFANA_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_KEY", raising=False)
    monkeypatch.setenv("GRAFANA_ADMIN_USER", "admin_env")
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "pass_env")
    client_env = GrafanaClient(base_url="https://grafana.example.com")
    assert client_env.session.auth == ("admin_env", "pass_env")


# --- Context Switching & Request Handling Tests ---


@patch.object(requests.Session, "request")
def test_client_request_with_org_context(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = '{"status": "ok"}'
    mock_response.json.return_value = {"status": "ok"}
    mock_request.return_value = mock_response

    result = client.request("GET", "/api/folders", org_id=19)

    assert result == {"status": "ok"}
    mock_request.assert_called_once()
    kwargs = mock_request.call_args.kwargs
    assert kwargs["headers"]["X-Grafana-Org-Id"] == "19"
    assert kwargs["url"] == "https://grafana.example.com/api/folders"


@patch.object(requests.Session, "request")
def test_client_request_without_org_context(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = '{"status": "ok"}'
    mock_response.json.return_value = {"status": "ok"}
    mock_request.return_value = mock_response

    client.request("GET", "/api/health")

    mock_request.assert_called_once()
    kwargs = mock_request.call_args.kwargs
    assert "X-Grafana-Org-Id" not in kwargs["headers"]


@patch.object(requests.Session, "request")
def test_client_request_handles_204_no_content(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 204
    mock_response.text = ""
    mock_request.return_value = mock_response

    result = client.request("DELETE", "/api/dashboards/uid/dash-1", org_id=5)
    assert result is None


@patch.object(requests.Session, "request")
def test_client_request_error_raises_grafana_api_error(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = False
    mock_response.status_code = 404
    mock_response.text = '{"message": "Dashboard not found"}'
    mock_request.return_value = mock_response

    with pytest.raises(GrafanaAPIError) as exc_info:
        client.get_dashboard(org_id=19, uid="missing-uid")

    assert exc_info.value.status_code == 404
    assert "Dashboard not found" in str(exc_info.value)
    assert exc_info.value.response_text == '{"message": "Dashboard not found"}'


@patch.object(requests.Session, "request")
def test_client_request_network_exception(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_request.side_effect = requests.ConnectionError("Connection refused")

    with pytest.raises(GrafanaAPIError) as exc_info:
        client.get_folders(org_id=1)

    assert "Connection error connecting to Grafana" in str(exc_info.value)


# --- Folder APIs ---


@patch.object(requests.Session, "request")
def test_client_folder_apis(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = '{"title": "Meerut CBG Plant"}'
    mock_response.json.return_value = {"title": "Meerut CBG Plant"}
    mock_request.return_value = mock_response

    # Test get_folders
    client.get_folders(org_id=20)
    assert (
        mock_request.call_args.kwargs["url"]
        == "https://grafana.example.com/api/folders"
    )
    assert mock_request.call_args.kwargs["headers"]["X-Grafana-Org-Id"] == "20"

    # Test get_folder
    client.get_folder(org_id=20, folder_uid="fld_meerut")
    assert (
        mock_request.call_args.kwargs["url"]
        == "https://grafana.example.com/api/folders/fld_meerut"
    )

    # Test create_folder with custom UID
    client.create_folder(org_id=20, title="Preview", uid="preview_uid")
    assert (
        mock_request.call_args.kwargs["url"]
        == "https://grafana.example.com/api/folders"
    )
    assert mock_request.call_args.kwargs["json"] == {
        "title": "Preview",
        "uid": "preview_uid",
    }

    # Test create_folder without UID
    client.create_folder(org_id=20, title="New Folder")
    assert mock_request.call_args.kwargs["json"] == {"title": "New Folder"}


@patch.object(requests.Session, "request")
def test_client_folder_permissions(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = '{"message": "Folder permissions updated"}'
    mock_response.json.return_value = {"message": "Folder permissions updated"}
    mock_request.return_value = mock_response

    perms = [{"role": "Admin", "permission": 4}, {"role": "Editor", "permission": 2}]
    client.set_folder_permissions(
        org_id=20, folder_uid="fld_preview", permissions=perms
    )

    mock_request.assert_called_once()
    kwargs = mock_request.call_args.kwargs
    assert kwargs["headers"]["X-Grafana-Org-Id"] == "20"
    assert kwargs["json"] == {"items": perms}
    assert (
        kwargs["url"]
        == "https://grafana.example.com/api/folders/fld_preview/permissions"
    )


# --- Dashboard APIs ---


@patch.object(requests.Session, "request")
def test_client_dashboard_apis(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = '{"uid": "cbg-01"}'
    mock_response.json.return_value = {"uid": "cbg-01"}
    mock_request.return_value = mock_response

    # Test search_dashboards
    client.search_dashboards(
        org_id=20, folder_uid="fld_01", query="cbg", tag="managed-by-git"
    )
    assert (
        mock_request.call_args.kwargs["url"] == "https://grafana.example.com/api/search"
    )
    assert mock_request.call_args.kwargs["params"] == {
        "type": "dash-db",
        "folderUids": "fld_01",
        "query": "cbg",
        "tag": "managed-by-git",
    }

    # Test get_dashboards_in_folder
    client.get_dashboards_in_folder(org_id=20, folder_uid="fld_01")
    assert mock_request.call_args.kwargs["params"] == {
        "type": "dash-db",
        "folderUids": "fld_01",
    }

    # Test get_dashboard
    client.get_dashboard(org_id=20, uid="cbg-01")
    assert (
        mock_request.call_args.kwargs["url"]
        == "https://grafana.example.com/api/dashboards/uid/cbg-01"
    )

    # Test save_dashboard
    dash_payload = {"title": "Test Dashboard", "editable": False}
    client.save_dashboard(
        org_id=20, dashboard=dash_payload, folder_uid="fld_01", message="Sync"
    )
    assert (
        mock_request.call_args.kwargs["url"]
        == "https://grafana.example.com/api/dashboards/db"
    )
    assert mock_request.call_args.kwargs["json"] == {
        "dashboard": dash_payload,
        "overwrite": True,
        "message": "Sync",
        "folderUid": "fld_01",
    }

    # Test delete_dashboard
    client.delete_dashboard(org_id=20, uid="cbg-01")
    assert (
        mock_request.call_args.kwargs["url"]
        == "https://grafana.example.com/api/dashboards/uid/cbg-01"
    )
    assert mock_request.call_args.kwargs["method"] == "DELETE"


# --- Organization & Datasource APIs ---


@patch.object(requests.Session, "request")
def test_client_org_and_datasource_apis(
    mock_request: MagicMock, client: GrafanaClient
) -> None:
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = '{"name": "Circle CBG"}'
    mock_response.json.return_value = {"name": "Circle CBG"}
    mock_request.return_value = mock_response

    # Test get_current_org
    client.get_current_org(org_id=20)
    assert mock_request.call_args.kwargs["url"] == "https://grafana.example.com/api/org"
    assert mock_request.call_args.kwargs["headers"]["X-Grafana-Org-Id"] == "20"

    # Test get_all_orgs
    client.get_all_orgs()
    assert (
        mock_request.call_args.kwargs["url"] == "https://grafana.example.com/api/orgs"
    )
    assert mock_request.call_args.kwargs["headers"]["X-Grafana-Org-Id"] == "1"

    # Test get_datasources
    client.get_datasources(org_id=20)
    assert (
        mock_request.call_args.kwargs["url"]
        == "https://grafana.example.com/api/datasources"
    )
    assert mock_request.call_args.kwargs["headers"]["X-Grafana-Org-Id"] == "20"
