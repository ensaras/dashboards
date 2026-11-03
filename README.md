# Ensaras Grafana Dashboards as Code

This repository stores normalized Grafana dashboard JSON and configuration for each Portal organization. Git is the source of truth for managed dashboards; production changes flow through pull requests.

## Repository layout

- `orgs/<org_slug>/<team_slug>/<dashboard_slug>__<uid>.json` — managed dashboard definitions. The UID suffix is stable and is used to identify the Grafana dashboard.
- `sites/<org_slug>.yaml` — organization identity, timezone, team folder UIDs, and datasource mappings used by the tooling.
- `src/grafana_dashboards/tools/` — Grafana client, export, normalization, and diff commands.

See [the Portal-to-Git contract](docs/portal-git-contract.md) for how Portal organization and team changes are represented here.

## Baseline commands

```powershell
uv run python -m grafana_dashboards.tools.export --all
uv run python -m grafana_dashboards.tools.diff --all
```

Export reads dashboards from Grafana and writes normalized JSON into the repository. Diff is read-only and compares the checked-in JSON with Grafana. A clean baseline has no differences for any organization.

## Validation and deployment

Run the local blocking checks without Grafana credentials:

```powershell
make check
uv run python -m grafana_dashboards.tools.validate
uv run python -m grafana_dashboards.tools.validate --base-ref origin/development --head-ref HEAD
```

The validator checks the bundled Grafana Classic dashboard schema (`schemaVersion: 42`), path and UID consistency, per-Org UID uniqueness, per-folder title uniqueness, configured datasource types, same-Org Grafana links, `editable: false`, the `managed-by-git` tag, and dashboard removals. A retired dashboard remains in Git with `retired: true`; it can also be placed in `orgs/<org_slug>/Retired/` when a team is removed. See [the schema profile](docs/dashboard-schema.md) for its scope and version source.

Production deployment applies only changed dashboard files. The `make deploy` target and GitHub workflow target production; the development branch does not deploy to a staging Grafana because that environment has no production data.

```powershell
$env:GRAFANA_PROD_URL = "https://grafana.example.com"
$env:GRAFANA_PROD_TOKEN = "<production service-account token>"
make deploy BASE=origin/main HEAD=HEAD
```

Each site YAML defines the production organization ID, team folder UIDs, and datasource identifiers. Missing mappings fail before writing. Deployment uses existing Portal-created team folders, ensures the organization's Admin-only `Retired` Grafana folder when needed, and skips a dashboard already equal to its target state.

To manually publish a PR preview, provide the Org slug, base ref, PR number, and optionally the title. This uses the production Preview folder and requires the same production Grafana credentials as the PR workflow:

```powershell
make preview ORG=<org-slug> BASE=origin/main PR=<number> TITLE="<pull request title>"
```

## Intended deployment flow

Changes pushed to `development` run offline validation only. A pull request from `development` to `main` deploys production previews for Admin review. Closing or merging that PR removes its previews. Merging to `main` deploys the changes to production. Dashboard changes are made through Git; direct Grafana dashboard editing is disabled.
