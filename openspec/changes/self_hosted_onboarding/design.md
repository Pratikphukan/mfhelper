# Design: Private self-hosted onboarding

## Template flow

Use a GitHub template repository. Users create a private repository, edit their own config files, add required Actions secrets, then set `MFHELPER_SETUP_COMPLETE=true` to enable the scheduled job. The public source repository must be marked as a template after the sanitized change is merged.

Template repositories start with independent history; updates are manual. The onboarding guide should make that tradeoff clear and tell users to preserve their config and secrets while bringing in code updates.

## Public config and local overrides

- Tracked `funds.yaml`, `settings.yaml`, `analytics_funds.yaml`, and `benchmarks.yaml` contain safe examples or empty mappings.
- Local maintainers can keep `*.private.yaml` config overrides; these are ignored by Git and preferred by config loaders.
- The upstream scheduled workflow may reconstruct its maintainer-specific funds, settings, and benchmarks from `MFHELPER_*_YAML` repository secrets.
- Private template users edit the YAML files in their own private repository; they do not need those optional config secrets.

## Workflow safety

- A new template copy skips the scheduled job until `MFHELPER_SETUP_COMPLETE=true` is set.
- The existing upstream repository keeps its existing schedule and public dashboard through its own Actions variables; template-created repositories start without those variables.
- Template copies do not publish the dashboard unless `PUBLISH_PUBLIC_DASHBOARD=true` is explicitly set. The page can reveal portfolio-derived data.
- OAuth files, user configuration reconstructed from secrets, and alert config are removed before the Pages artifact is assembled.

## Generated data

Remove generated portfolio snapshots and mapping caches from tracked Git files and add them to `.gitignore`. GitHub Actions may recreate them per user's own repository and cache them there.

## Privacy limitation

The current public repository history and prior public Pages deployments may already contain the old configuration or generated portfolio data. This change prevents future commits and template copies from including them, but does not erase earlier public history or deployed snapshots. History rewriting or disabling/removing Pages requires a separate explicit decision.
