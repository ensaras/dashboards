"""Unit tests for GrafanaClient."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from grafana_dashboards.tools.client import GrafanaAPIError, GrafanaClient


@pytest.fixture
def client():
    return GrafanaClient(
        base_url="https://grafana.example.com",
        token="glsa_test_token_12345",
    )


def test_client_init_headers(client):
    assert client.base_url == "https://grafana.example.com"
    assert client.session.headers["Authorization"] == "Bearer glsa_test_token_12345"
    assert client.session.headers["Content-Type"] == "application/json"


@patch.object(requests.Session, "request")
def test_client_request_with_org_context(mock_request, client):
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
def test_client_request_handles_204_no_content(mock_request, client):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 204
    mock_response.text = ""
    mock_request.return_value = mock_response

    result = client.request("DELETE", "/api/dashboards/uid/dash-1", org_id=5)
    assert result is None


@patch.object(requests.Session, "request")
def test_client_request_error_raises_grafana_api_error(mock_request, client):
    mock_response = MagicMock()
    mock_response.ok = False
    mock_response.status_code = 404
    mock_response.text = '{"message": "Dashboard not found"}'
    mock_request.return_value = mock_response

    with pytest.raises(GrafanaAPIError) as exc_info:
        client.get_dashboard(org_id=19, uid="missing-uid")

    assert exc_info.value.status_code == 404
    assert "Dashboard not found" in str(exc_info.value)


@patch.object(requests.Session, "request")
def test_client_folder_permissions(mock_request, client):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = '{"message": "Folder permissions updated"}'
    mock_response.json.return_value = {"message": "Folder permissions updated"}
    mock_request.return_value = mock_response

    perms = [{"role": "Admin", "permission": 4}, {"role": "Editor", "permission": 2}]
    client.set_folder_permissions(org_id=20, folder_uid="fld_preview", permissions=perms)

    mock_request.assert_called_once()
    kwargs = mock_request.call_args.kwargs
    assert kwargs["headers"]["X-Grafana-Org-Id"] == "20"
    assert kwargs["json"] == {"items": perms}
    assert kwargs["url"] == "https://grafana.example.com/api/folders/fld_preview/permissions"
