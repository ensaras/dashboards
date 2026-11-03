# CI/CD and Grafana permissions

## Branch lifecycle

- Pushes to `development` and pull requests targeting `development` or `main` run repository validation, Ruff, and the existing unit suite. The development environment has no production data, so this stage does not publish Grafana previews.
- A pull request from `development` to `main` publishes the changed dashboards to each affected Org's `Preview` folder in production Grafana. Preview dashboards are updated in place on later PR commits. A PR closed by merge or by closing it removes that PR's preview dashboards and keeps the Org's `Preview` folder.
- Merging to `main` deploys the changed dashboards to production immediately.
- A weekly workflow removes dashboards from each Org's `Retired` folder after 90 days. It uses Grafana's `meta.updated` timestamp as the retention clock and skips dashboards when that timestamp is absent or invalid.
- Configure branch protection for `development` and `main` to require the `Dashboard CI / validate` check before merge. The production deployment runs from the resulting push to `main`.

## Grafana permissions

- Each Org/environment requires its own Grafana service-account token. Production deployment, Preview folder provisioning, and Retired folder management require a Grafana **Admin** service account in that Org because the pipeline must set folder ACLs.
- Preview and Retired folder ACLs are set to the Grafana `Admin` role only. Customer accounts remain Viewer and cannot edit dashboards. Managed dashboard JSON is written with `editable: false`.
- Service-account tokens are read from AWS Systems Manager Parameter Store with decryption enabled. The Actions AWS identity needs `ssm:GetParameter` for these parameter paths and KMS decrypt permission for their customer-managed key, if applicable.

## GitHub Actions configuration

Configure these repository or `production` environment values:

| Name | Kind | Purpose |
| --- | --- | --- |
| `AWS_REGION` | Actions variable | AWS region containing the parameters |
| `GRAFANA_PROD_URL` | Actions variable | Production Grafana base URL |
| `GRAFANA_PROD_TOKEN_SSM_PREFIX` | Actions variable, optional | Defaults to `/grafana/dashboards/production` |
| `AWS_ACCESS_KEY_ID` | Actions secret | AWS identity used by the workflows |
| `AWS_SECRET_ACCESS_KEY` | Actions secret | AWS identity used by the workflows |

For each Org slug, store its token at `{GRAFANA_PROD_TOKEN_SSM_PREFIX}/{org_slug}/service-account-token` as a `SecureString`. The workflow retrieves one Org token at a time and does not print it. The AWS identity must also be able to decrypt the selected SSM SecureString key.

The workflow expects the production URL, AWS region, AWS access credentials, and one production service-account parameter for every Org in `sites/`. The development CI does not require Grafana or AWS credentials.

## Preview identity and retention

Preview dashboard UIDs are deterministic per Org, source dashboard UID, and PR number, so synchronize events update the existing preview. Preview dashboards receive PR-specific tags and titles. Cleanup deletes only dashboards carrying the matching PR tag; it does not delete the folder or dashboards for another PR. The weekly Retired cleanup is fail-closed when a dashboard's timestamp cannot be read.
