# Grafana dashboard schema profile

The repository uses Grafana's **Classic dashboard JSON model** and pins its dashboard schema migration level to **42**. The proposed approach calls for the Grafana 12 schema, and every one of the 197 checked-in dashboards currently has `schemaVersion: 42`.

The bundled [`grafana_v12_classic_dashboard_v42.schema.json`](../tools/schemas/grafana_v12_classic_dashboard_v42.schema.json) validates the common Classic dashboard structure, UID/title/schema version, and core panel layout types. Plugin-specific panel, query, transformation, and option properties remain extensible because their valid shapes depend on Grafana plugins. Repository-specific rules such as `editable: false`, tags, path identity, and datasource mappings remain in `validate.py`.

Grafana documents Classic JSON separately from the newer V1 Resource and V2 Resource models. Grafana's dashboard migration source identifies schema version 42 as the final version for the V1 legacy dashboard API. This supports pinning the checked-in dashboard format at schema version 42; it does **not** identify the production Grafana server's exact patch release.

The repository and deployment configuration do not currently record the Grafana server release. Confirm and record that release before treating the runtime version portion of the schema task as complete. Do not infer the runtime release from `schemaVersion` alone.

References:

- [Grafana dashboard JSON model](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/view-dashboard-json-model/)
- [Grafana dashboard migration notes](https://github.com/grafana/grafana/blob/main/apps/dashboard/pkg/migration/README.md)
- [Grafana dashboard migrator source](https://github.com/grafana/grafana/blob/main/public/app/features/dashboard/state/DashboardMigrator.ts)
