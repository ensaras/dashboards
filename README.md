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

## Intended deployment flow

Changes merged into `development` run validation and deploy to staging. A pull request from `development` to `main` deploys production previews for Admin review. Merging to `main` deploys the changes to production. Dashboard changes are made through Git; direct Grafana dashboard editing is disabled.
