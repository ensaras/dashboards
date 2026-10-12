# CLAUDE.md - Guidelines for grafana-dashboards

## Project Overview
This repository manages Grafana dashboards as code for Ensaras (`portal.ensaras.com`).
Dashboards are stored as normalized JSON files under:
- `orgs/<org_slug>/<team_slug>/<dashboard_slug>__<uid>.json` (team dashboards)
- `orgs/<org_slug>/master-data-management/<dashboard_slug>__<uid>.json` (portfolio dashboards)

All Python code resides as an installable package under `src/grafana_dashboards/`.
Operational CLI tools live in the subpackage `src/grafana_dashboards/tools/`.

## Key Commands
- `uv run python -m grafana_dashboards.tools.export --org <org_slug>`: Export dashboards for a single organization
- `uv run python -m grafana_dashboards.tools.export --all`: Export dashboards for all 6 organizations
- `uv run python -m grafana_dashboards.tools.diff --all`: Compare local JSON files with live Grafana (must report 0 diff)
- `uv run pytest -v`: Run unit tests
- `make export-all`: Export all organizations
- `make diff`: Run diff against live Grafana

## Package Structure
```text
src/grafana_dashboards/
├── __init__.py
└── tools/
    ├── __init__.py
    ├── client.py        # Multi-org Grafana HTTP API client (X-Grafana-Org-Id)
    ├── normalizer.py    # JSON normalization engine (strips volatile fields, stable key sort)
    ├── export.py        # CLI export orchestrator
    └── diff.py          # Semantic diff engine against live Grafana
```

## Safety Rules & Invariants
1. **Never edit Grafana directly** — All dashboard changes must be made in this repository.
2. **Never touch unmanaged dashboards** — Only dashboards tagged with `managed-by-git` and stored in this repository are managed.
3. **No cross-organization links** — Dashboards must never link across organization boundaries.
4. **Fixed UIDs** — A dashboard's UID is permanent and immutable once provisioned.
5. **Team folders belong to the Portal** — Tooling deploys into existing folders by UID and never renames or deletes them.
6. **Zero-write local operations** — Only read operations (export, diff) run locally. All writes execute via verified credentials.
7. **JSON Normalization** — All dashboard JSON files must be normalized: stripped of volatile fields (`id`, `version`, `iteration`), keys sorted alphabetically, 2-space indentation, tagged with `managed-by-git`, and `"editable": false`.
