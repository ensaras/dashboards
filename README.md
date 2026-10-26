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

Run static checks without Grafana credentials:

```powershell
uv run python -m grafana_dashboards.tools.validate
uv run python -m grafana_dashboards.tools.validate --base-ref origin/development --head-ref HEAD
```

The validator checks the bundled Grafana Classic dashboard schema (`schemaVersion: 42`), path and UID consistency, per-Org UID uniqueness, per-folder title uniqueness, configured datasource types, same-Org Grafana links, `editable: false`, the `managed-by-git` tag, and dashboard removals. A retired dashboard remains in Git with `retired: true`; it can also be placed in `orgs/<org_slug>/Retired/` when a team is removed. See [the schema profile](docs/dashboard-schema.md) for its scope and version source.

Deploy only changed dashboard files by supplying the previous and current Git refs:

```powershell
$env:GRAFANA_STAGING_URL = "https://test.ensaras.com/grafana"
$env:GRAFANA_STAGING_TOKEN = "<environment secret>"
uv run python -m grafana_dashboards.tools.deploy --environment staging --base-ref $env:GITHUB_EVENT_BEFORE --head-ref $env:GITHUB_SHA
```

Production uses `GRAFANA_PROD_URL` and `GRAFANA_PROD_TOKEN`. Each site YAML must define the target environment's organization ID, team folder UIDs, and (for staging) a `datasource_uid_map` from checked-in datasource UIDs to staging datasource UIDs. Missing environment mappings fail before writing. Deployment uses existing Portal-created team folders, ensures the organization's Admin-only `Retired` Grafana folder when needed, and skips a dashboard already equal to its target state.

## Intended deployment flow

Changes merged into `development` run validation and deploy to staging. A pull request from `development` to `main` deploys production previews for Admin review. Merging to `main` deploys the changes to production. Dashboard changes are made through Git; direct Grafana dashboard editing is disabled.
