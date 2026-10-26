# Grafana dashboard schema profile

The repository uses Grafana's **Classic dashboard JSON model** and pins its dashboard schema migration level to **42**. Production runs **Grafana v12.3.1+security-01 (0f182e66b0)**, as confirmed by the environment owner on 2026-10-26. Every one of the 197 checked-in dashboards currently has `schemaVersion: 42`.

The bundled [`grafana_v12_classic_dashboard_v42.schema.json`](../tools/schemas/grafana_v12_classic_dashboard_v42.schema.json) validates the common Classic dashboard structure, UID/title/schema version, and core panel layout types. Plugin-specific panel, query, transformation, and option properties remain extensible because their valid shapes depend on Grafana plugins. Repository-specific rules such as `editable: false`, tags, path identity, and datasource mappings remain in `validate.py`.

Grafana documents Classic JSON separately from the newer V1 Resource and V2 Resource models. Grafana's dashboard migration source identifies schema version 42 as the final version for the V1 legacy dashboard API. The supplied production release now pins the runtime compatibility target. The bundled JSON Schema remains a **repository-owned validation profile**, not Grafana's complete upstream schema; Grafana's upstream release-tagged dashboard schema is authored in CUE and plugin-specific properties remain extensible here.

References:

- [Grafana v12.3.1 dashboard CUE schema](https://github.com/grafana/grafana/blob/v12.3.1/kinds/dashboard/dashboard_kind.cue)
- [Grafana dashboard JSON model](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/view-dashboard-json-model/)
- [Grafana dashboard migration notes](https://github.com/grafana/grafana/blob/main/apps/dashboard/pkg/migration/README.md)
- [Grafana dashboard migrator source](https://github.com/grafana/grafana/blob/main/public/app/features/dashboard/state/DashboardMigrator.ts)
