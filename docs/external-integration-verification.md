# External integration setup and verification

These steps require access to GitHub, AWS, Grafana production, and the Portal production database. The repository workflows and commands have not been run against those systems.

## GitHub Actions and AWS for Grafana

1. In GitHub Actions variables for the `production` environment, set `AWS_REGION` and `GRAFANA_PROD_URL`. Set `GRAFANA_PROD_TOKEN_SSM_PREFIX` only if the default `/grafana/dashboards/production` is not the chosen prefix.
2. Add `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as `production` environment secrets. The identity must be limited to `ssm:GetParameter` on `/grafana/dashboards/production/*/service-account-token` (or the configured prefix) and `kms:Decrypt` on the key used by those SecureStrings, when a customer-managed key is used.
3. For every `sites/<org_slug>.yaml`, create an SSM `SecureString` at `<prefix>/<org_slug>/service-account-token`. Store that Org's Grafana service-account token there. Do not put the token in GitHub variables or dashboard files.
4. In each corresponding Grafana Org, verify that the token belongs to a service account with the Grafana `Admin` role. The workflows set folder ACLs, which is why the chosen integration role is Admin.
5. Ensure the `production` GitHub environment does not require a manual reviewer approval for its jobs. Preview publishing must run when the `development` to `main` PR is opened or updated; production deployment must run immediately after merge.

## Grafana v12.3.1+security-01 checks

Using the supplied production version, verify all six active Orgs (and any later Org) against these conditions:

- Customers have Grafana `Viewer` access and cannot save dashboard edits.
- The service account can create/update dashboards and set folder permissions in its Org.
- The first qualifying PR creates that Org's `Preview` folder with an Admin-only ACL. A later commit updates the same PR dashboard UIDs and removes only stale dashboards belonging to that PR.
- A second PR has separate preview UIDs and cleanup does not remove the first PR's previews.
- Closing or merging a PR removes only its previews and leaves the `Preview` folder in place.
- Merging a reviewed PR updates the production team folders.
- The `Retired` folder is Admin-only, and the scheduled retention workflow deletes only dashboards whose Grafana `meta.updated` time is at least 90 days old. Missing or invalid timestamps must be skipped.

The API permission and JSON compatibility checks in the code are offline/unit-tested; these live checks are still needed to confirm behavior on the supplied secured Grafana build.

## GitHub branch rules

On `development` and `main`, require the `Dashboard CI / validate` check before merging. Confirm GitHub reports this exact check name after the workflow has run. Keep the `development` to `main` PR review as the approval gate; after merge, the `main` push triggers deployment.

## Portal worker configuration

The Portal worker needs these runtime settings:

- `DASHBOARDS_GIT_PROVISIONING_ENABLED=true`
- `DASHBOARDS_GITHUB_REPOSITORY=ensaras/dashboards`
- `DASHBOARDS_GITHUB_BASE_BRANCH=development`
- `DASHBOARDS_GITHUB_TOKEN_SSM_PARAMETER=<the exact SSM parameter name containing the GitHub token>`
- `REGION_NAME=<AWS region containing that parameter>`

Grant the worker's AWS identity `ssm:GetParameter` and, for a SecureString encrypted with a customer-managed key, `kms:Decrypt` on that specific parameter/key. Give the GitHub token the repository access needed to create branches, write contents, and create/update pull requests. Then verify one Org creation and one Team creation queue a task and create/update the expected per-Org PR without blocking the Portal request. These are Portal worker settings, not GitHub Actions settings.

## Retirement reference check

Offline validation now blocks retirement when a dashboard JSON link in the same Org still points at the retired dashboard UID. Portal report links live in the database, so inspect them before merging a retirement PR. In a Django shell, run:

```python
from onboarding.models.report_metric import ReportMetric as EmailReportMetric
from celerytasks.models.report_metric import ReportMetric as DailyReportMetric

list(EmailReportMetric.objects.exclude(dashboard_url="").values_list("dashboard_url", flat=True))
list(DailyReportMetric.objects.exclude(redirect_url="").values_list("redirect_url", flat=True))
```

Check any URL containing the retiring dashboard UID, update the relevant report configuration through its normal Portal workflow, and confirm no references remain before merging. This is a manual database-backed check; the dashboards repository cannot inspect the production Portal database.

## Org deletion lifecycle (Implemented)

The agreed 90-day Org lifecycle is now implemented in Portal. Deleting an Org performs a soft delete (`is_active = False`, cascades to deactivate teams, forms, and users) and preserves Grafana and Git assets during the 90-day retention period. Users of inactive Orgs are blocked from authentication (OIDC, Partner Client Credentials, userinfo). The scheduled Celery task `purge_retained_organizations` purges Grafana assets, creates a Git PR removing Org assets, and permanently hard-deletes the Org record after the 90-day retention window.

