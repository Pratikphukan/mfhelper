---
name: mfhelper-workflow
description: Standard development pattern for implementing new features or tracks in MFHelper using OpenSpec, standalone modules under mfhelper/, unit tests under tests/, safe dev sandboxing, CI/CD sync, and documentation.
---

For each track we decide to implement, we will follow the repo's established pattern:

1. OpenSpec Specification:
- Create openspec/changes/<feature_name>/:
  - proposal.md (Motivation, scope, expected behavior).
  - design.md (Data schemas, function signatures, error handling, sheet schemas).
  - tasks.md (Checklist of tasks).

⛔ STOP & CONFIRM GATE:
- Present all design questions, trade-offs, and assumptions to the user.
- STOP execution here. Await the user's answers and explicit sign-off.
- DO NOT proceed to Step 2 (Core Logic & Unit Tests) without explicit user approval.

2. Core Logic & Unit Tests (Only after design approval):
- Implement standalone modules under mfhelper/.
- Write comprehensive unit tests under tests/ and verify they pass (pytest).

3. Integration & Safe Testing:
- Integrate with --dev flag support so tests run without affecting your primary Google Sheet.

4. CI/CD & Cloud Sync:
- Update .github/workflows/daily_nav.yml if new artifacts or cache files are involved.

5. Documentation:
- Update README.md with configuration options and usage guides.
