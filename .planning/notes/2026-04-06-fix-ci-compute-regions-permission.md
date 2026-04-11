---
date: "2026-04-06 21:20"
promoted: false
---

Fix the non-blocking 403 warning in CD Dev: CI service account is missing `compute.regions.list` permission. Add `compute.viewer` role (or custom role with `compute.regions.list`) to the CI service account for the dev project.
