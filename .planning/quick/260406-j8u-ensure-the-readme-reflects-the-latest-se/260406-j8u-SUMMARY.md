# Quick Task 260406-j8u: Update README to reflect latest setup

## Summary

Synced the README.md environment variable reference tables with the actual `.env.*.example` files. The Description and How It Works sections were preserved exactly.

## Changes

### README.md

1. **`.env.app` table** — Added `SMS_RATE_LIMIT_WINDOW_SECONDS` and `SMS_RATE_LIMIT_MAX` (present in `.env.app.example` but missing from README)
2. **`.env.jaeger-query` table** — Fixed incorrect variable: `SPAN_STORAGE_TYPE` → `OTEL_EXPORTER_OTLP_ENDPOINT` (actual env var in `.env.jaeger-query.example`)
3. **`.env.opensearch` table** — Added `OPENSEARCH_JAVA_OPTS` (present in `.env.opensearch.example` but missing from README)
4. **`.env.grafana` table** — Added `GF_AUTH_ANONYMOUS_ENABLED` and `GF_AUTH_ANONYMOUS_ORG_ROLE` (present in `.env.grafana.example` but missing from README)

## Verification

- All `.env.*.example` files compared against README tables
- All missing variables added, incorrect variable fixed
- Description and How It Works sections untouched
