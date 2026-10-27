# Portal-to-Git Contract

Portal remains authoritative for organizations, teams, and Grafana folders. The dashboard repository mirrors the identifiers and configuration needed to validate and deploy dashboards. It must not create, rename, or delete Portal-owned Grafana team folders.

## Ownership and identity

- An organization can have zero or more teams. A team always belongs to one organization.
- Organization and team slugs are read-only after creation and form the repository directory path.
- Display names may change without changing the slug or path.
- Portal supplies the Grafana organization ID and each team's `folder_uid`. Deployment uses that folder UID, not the display name.
- A newly created team receives a new `folder_uid`, even if a deleted team's name or slug matches.
- Dashboard files use stable Grafana dashboard UIDs in their filenames. A replacement dashboard receives a new UID.

## Repository representation

- An organization is represented under `orgs/<org_slug>/`; a team is represented beneath it at `orgs/<org_slug>/<team_slug>/`.
- Portal-generated scaffold changes add `.gitkeep` where needed so empty organization and team directories are tracked.
- `sites/<org_slug>.yaml` contains the site's organization identity and timezone, the mapping from team slug to display name and Grafana folder UID, and datasource identifiers. It contains no credentials.
- Both PostgreSQL and InfluxDB datasource configurations are organization-level in `sites/<org_slug>.yaml` (matching all checked-in dashboards). `Team.influx_database_name` in Portal is the internal timeseries database name used by MQTT ingestion and alert services, not a separate per-team Grafana datasource.
- Portal is the authoritative source for these mappings. The repository copy is generated or refreshed from Portal and remains available for offline validation.

## Provisioning events

- Creating an organization or team in Portal starts asynchronous provisioning; a team can only be created under an existing organization.
- The Portal worker provisions the Grafana organization or team folder and opens a GitHub pull request for the scaffold or metadata changes. The generated change enters the `development` workflow; Portal does not wait for the PR to merge before reporting provisioning complete.
- Creating or renaming a display name updates repository metadata while preserving the slug, directory path, and existing folder UID.
- Provisioning retries are idempotent by Portal entity identity. A retry reuses matching Grafana resources and updates or reuses the associated pull request. A mismatch is surfaced for resolution rather than overwritten.
- Portal reports provisioning status, failure details, and the pull request link. A failed GitHub operation does not roll back a successfully provisioned Grafana resource; it can be retried.

## Dashboard lifecycle boundary

Managed dashboard changes are made in Git. The deploy tool writes dashboards into Portal-created team folders by UID. Setting `retired: true` in Git moves the Grafana copy to the organization's Admin-only `Retired` folder; deleting a dashboard file alone does not delete it from Grafana.
