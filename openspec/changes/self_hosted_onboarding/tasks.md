# Tasks: Private self-hosted onboarding

- [x] Choose GitHub template setup for the first release.
- [x] Sanitize tracked funds, settings, analytics, and benchmark configuration.
- [x] Add optional upstream Actions secret overrides for personal funds, settings, and benchmark YAML.
- [x] Support ignored local `*.private.yaml` overrides.
- [x] Stop tracking generated portfolio and mapping state.
- [x] Stop tracking the generated dashboard HTML, which embeds fund performance and holdings data.
- [x] Gate template scheduled workflows until setup is complete and keep dashboard publishing opt-in for template copies.
- [x] Document private template setup, required secrets, and manual update tradeoff.
- [x] Use private settings in the Sheets utilities and resolve private alert settings before checking for the file.
- [ ] Mark the upstream repository as a template after this change is merged.
- [ ] Verify all tests and inspect workflow behavior before release.
