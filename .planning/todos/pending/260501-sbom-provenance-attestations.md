---
created: 2026-05-01
title: Add SBOM + provenance attestations to GHCR image publish
area: ci/supply-chain
files:
  - .github/workflows/release.yml
  - Dockerfile
---

# SBOM + Provenance Attestations for Container Images

## Problem

The v1.1 milestone adds GHCR multi-arch image publish but defers Software Bill of Materials (SBOM) and SLSA provenance attestations. Without these, downstream consumers of the image have no machine-readable inventory of what's inside it and no signed claim about how it was built — limiting our ability to satisfy SLSA Level 2+ requirements or feed vulnerability scanners.

## Solution

Add SBOM + provenance attestations to the existing `docker buildx build --push` step in `.github/workflows/release.yml`:

- `--sbom=true` — generates a Software Bill of Materials (SPDX format) and attaches as an OCI artifact
- `--provenance=mode=max` — generates SLSA provenance with maximal metadata (build environment, source ref, build tool versions)

Verify with `docker buildx imagetools inspect --raw ghcr.io/<org>/vici:<tag>` after a publish — should show `application/vnd.in-toto+json` artifacts.

## Context

Captured during v1.1 milestone scoping (2026-05-01) when SBOM was deferred to keep the GHCR publish phase focused. The build infrastructure will already exist; this is purely an additive flag change once the registry pipeline is settled.

## Acceptance

- `release.yml` publishes images with SBOM + SLSA provenance attestations
- `imagetools inspect --raw` shows the attestation artifacts
- Brief note in `DEPLOY.md` (or equivalent) on how operators can verify and consume them
