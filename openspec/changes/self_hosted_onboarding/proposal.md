# Proposal: Private self-hosted onboarding

## Problem

New MFHelper users need to configure funds, Google Sheets access, email alerts, and a daily schedule. A shared service would require central storage for each user's portfolio and credentials, which the project wants to avoid.

## Proposed change

Make the public repository a safe GitHub template. Each user creates a private repository from it, configures their own files and secrets, and runs the included GitHub Actions workflow on their own account.

The public upstream will contain example configuration only. Its current maintainer can provide personal workflow configuration through repository Actions secrets. Generated portfolio state and mappings are not tracked in Git.

## Goals

- Let users create private, isolated MFHelper installations with a short setup guide.
- Keep fund lists, sheet settings, benchmark mappings, and credentials out of public tracked files.
- Avoid a shared database and central collection of user data.
- Prevent template copies from running before configuration is complete or publishing personal dashboards by default.

## Out of scope

- Central multi-tenant hosting or a shared portfolio database.
- Automatic upstream code synchronization for template-generated repositories.
- Publishing a private user's dashboard by default.
