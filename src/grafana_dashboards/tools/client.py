"""Multi-tenant Grafana HTTP API client with organization context switching.

Supports authentication via either:
1. Service Account / API Token (Authorization: Bearer <token>)
2. Basic Authentication credentials (admin:password)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


class GrafanaAPIError(Exception):
    """Raised when a Grafana API request fails."""

    def __init__(self, message: str, status_code: int | None = None, response_text: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class GrafanaClient:
    """Client for interacting with Grafana REST API across multiple organizations."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        auth: tuple[str, str] | None = None,
        timeout: int = 15,
    ) -> None:
        """Initialize GrafanaClient.

        Args:
            base_url: Base URL of Grafana instance (e.g. https://portal.ensaras.com/grafana).
                      Defaults to GRAFANA_URL environment variable or http://localhost:3030.
            token: Bearer token (Service Account Token).
                   Defaults to GRAFANA_ADMIN_TOKEN or GRAFANA_API_KEY environment variable.
            auth: Optional (username, password) tuple for Basic Auth.
            timeout: Request timeout in seconds.
        """
        raw_url = base_url or os.getenv("GRAFANA_URL", "http://localhost:3030")
        self.base_url = raw_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        # Configure Authentication
        resolved_token = token or os.getenv("GRAFANA_ADMIN_TOKEN") or os.getenv("GRAFANA_API_KEY")
        if resolved_token:
            self.session.headers["Authorization"] = f"Bearer {resolved_token.strip()}"
        elif auth:
            self.session.auth = auth
        else:
            admin_user = os.getenv("GRAFANA_ADMIN_USER", "admin")
            admin_password = os.getenv("GRAFANA_ADMIN_PASSWORD")
            if admin_password:
                self.session.auth = (admin_user, admin_password)

        self.session.headers["Content-Type"] = "application/json"
        self.session.headers["Accept"] = "application/json"

    def _build_url(self, endpoint: str) -> str:
        """Construct a full URL from an API endpoint path."""
        clean_endpoint = endpoint.lstrip("/")
        return f"{self.base_url}/{clean_endpoint}"

    def request(
        self,
        method: str,
        endpoint: str,
        org_id: int | None = None,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request against Grafana with optional tenant context switching.

        Args:
            method: HTTP method ('GET', 'POST', 'PUT', 'DELETE').
            endpoint: API endpoint relative to base_url (e.g. '/api/folders').
            org_id: Grafana Organization ID to switch context using 'X-Grafana-Org-Id'.
            params: URL query parameters.
            json_data: Request JSON body.

        Returns:
            Parsed JSON response from Grafana.

        Raises:
            GrafanaAPIError: If the API responds with an HTTP error status code.
        """
        url = self._build_url(endpoint)
        headers: dict[str, str] = {}
        if org_id is not None:
            headers["X-Grafana-Org-Id"] = str(org_id)

        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.error("Failed to execute request %s %s: %s", method, url, exc)
            raise GrafanaAPIError(f"Connection error connecting to Grafana at {url}: {exc}") from exc

        if not response.ok:
            error_msg = (
                f"Grafana API error ({response.status_code}) on {method} {endpoint}: "
                f"{response.text}"
            )
            logger.error(error_msg)
            raise GrafanaAPIError(error_msg, status_code=response.status_code, response_text=response.text)

        if response.status_code == 204 or not response.text.strip():
            return None

        return response.json()

    # --- Organization APIs ---

    def get_current_org(self, org_id: int | None = None) -> dict[str, Any]:
        """Fetch details of the active organization (or org_id context)."""
        return self.request("GET", "/api/org", org_id=org_id)

    def get_all_orgs(self) -> list[dict[str, Any]]:
        """List all organizations (requires server admin permissions)."""
        return self.request("GET", "/api/orgs", org_id=1)

    # --- Folder APIs ---

    def get_folders(self, org_id: int) -> list[dict[str, Any]]:
        """List all dashboard folders within an organization."""
        return self.request("GET", "/api/folders", org_id=org_id)

    def get_folder(self, org_id: int, folder_uid: str) -> dict[str, Any]:
        """Get details for a specific folder by UID."""
        return self.request("GET", f"/api/folders/{folder_uid}", org_id=org_id)

    def create_folder(self, org_id: int, title: str, uid: str | None = None) -> dict[str, Any]:
        """Create a new folder in an organization.

        Args:
            org_id: Organization ID.
            title: Title of the folder.
            uid: Optional custom UID for the folder.
        """
        payload: dict[str, Any] = {"title": title}
        if uid:
            payload["uid"] = uid
        return self.request("POST", "/api/folders", org_id=org_id, json_data=payload)

    def set_folder_permissions(
        self,
        org_id: int,
        folder_uid: str,
        permissions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update permissions for a folder.

        Overwrites folder permissions to explicitly restrict access (e.g. for Preview/Retired folders).

        Args:
            org_id: Organization ID.
            folder_uid: UID of target folder.
            permissions: List of permission items, e.g. [{"role": "Admin", "permission": 4}]
        """
        return self.request(
            "POST",
            f"/api/folders/{folder_uid}/permissions",
            org_id=org_id,
            json_data={"items": permissions},
        )

    # --- Dashboard APIs ---

    def search_dashboards(
        self,
        org_id: int,
        folder_uid: str | None = None,
        query: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search dashboards within an organization.

        Args:
            org_id: Organization ID.
            folder_uid: Optional folder UID filter.
            query: Optional search term.
            tag: Optional tag filter.
        """
        params: dict[str, Any] = {"type": "dash-db"}
        if folder_uid:
            params["folderUids"] = folder_uid
        if query:
            params["query"] = query
        if tag:
            params["tag"] = tag
        return self.request("GET", "/api/search", org_id=org_id, params=params)

    def get_dashboards_in_folder(self, org_id: int, folder_uid: str) -> list[dict[str, Any]]:
        """List all dashboard summaries located within a specific folder."""
        return self.search_dashboards(org_id=org_id, folder_uid=folder_uid)

    def get_dashboard(self, org_id: int, uid: str) -> dict[str, Any]:
        """Retrieve complete dashboard JSON model and metadata by UID."""
        return self.request("GET", f"/api/dashboards/uid/{uid}", org_id=org_id)

    def save_dashboard(
        self,
        org_id: int,
        dashboard: dict[str, Any],
        folder_uid: str | None = None,
        overwrite: bool = True,
        message: str = "Saved via Git",
    ) -> dict[str, Any]:
        """Create or update a dashboard in Grafana.

        Args:
            org_id: Target Organization ID.
            dashboard: Dashboard JSON model.
            folder_uid: Target folder UID.
            overwrite: If True, overwrite existing version.
            message: Commit/changelog message.
        """
        payload: dict[str, Any] = {
            "dashboard": dashboard,
            "overwrite": overwrite,
            "message": message,
        }
        if folder_uid:
            payload["folderUid"] = folder_uid
        return self.request("POST", "/api/dashboards/db", org_id=org_id, json_data=payload)

    def delete_dashboard(self, org_id: int, uid: str) -> dict[str, Any]:
        """Delete a dashboard by UID."""
        return self.request("DELETE", f"/api/dashboards/uid/{uid}", org_id=org_id)

    # --- Datasource APIs ---

    def get_datasources(self, org_id: int) -> list[dict[str, Any]]:
        """List all datasources provisioned in an organization."""
        return self.request("GET", "/api/datasources", org_id=org_id)
