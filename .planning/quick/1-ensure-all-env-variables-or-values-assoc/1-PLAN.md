---
phase: quick-1
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - .env.example
  - docker-compose.yml
  - render.yaml
autonomous: true
requirements: []
must_haves:
  truths:
    - "Every env var read by config.py has a matching declaration in .env.example"
    - "docker-compose.yml app service sets OTEL_SERVICE_NAME"
    - "render.yaml declares OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_SERVICE_NAME for production"
  artifacts:
    - path: ".env.example"
      provides: "Reference for all env vars, no typos"
    - path: "docker-compose.yml"
      provides: "App service env block includes OTEL_SERVICE_NAME"
    - path: "render.yaml"
      provides: "Production env block covers all observability vars"
  key_links:
    - from: "config.py otel_service_name field"
      to: ".env.example OTEL_SERVICE_NAME"
      via: "pydantic-settings env var name matching"
      pattern: "OTEL_SERVICE_NAME"
---

<objective>
Fix all missing or mismatched env var declarations across .env.example, docker-compose.yml, and render.yaml so every value config.py reads has a canonical reference in the .env file and is consistently declared in all deployment targets.

Purpose: Prevent silent misconfiguration — typos or omissions cause defaults to silently replace real values in all environments.
Output: Three updated config files with complete, consistent env var coverage.
</objective>

<execution_context>
@/Users/ahcarpenter/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ahcarpenter/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@src/config.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix .env.example typo and verify completeness</name>
  <files>.env.example</files>
  <action>
    Fix the typo on the OTL_SERVICE_NAME line — rename it to OTEL_SERVICE_NAME (adds the missing "E") so it matches the pydantic-settings field name `otel_service_name` in config.py. The current value (`vici`) is correct, only the key name is wrong.

    After fixing, verify the file covers every flat field declared in the Settings class in src/config.py:
    - database_url
    - webhook_base_url
    - env
    - inngest_dev
    - inngest_base_url
    - twilio_auth_token
    - twilio_account_sid
    - twilio_from_number
    - otel_exporter_otlp_endpoint
    - otel_service_name  (currently misspelled OTL_SERVICE_NAME — this is the fix)
    - openai_api_key
    - pinecone_api_key
    - pinecone_index_host
    - braintrust_api_key
    - git_sha

    All are already present except for the typo. Only fix the key name — do not change values or add new vars.
  </action>
  <verify>
    <automated>grep "OTEL_SERVICE_NAME" .env.example && ! grep "OTL_SERVICE_NAME" .env.example && echo "PASS"</automated>
  </verify>
  <done>`.env.example` contains `OTEL_SERVICE_NAME=vici` (not `OTL_SERVICE_NAME`), and grep for the old typo returns nothing.</done>
</task>

<task type="auto">
  <name>Task 2: Add OTEL_SERVICE_NAME to docker-compose app service and render.yaml</name>
  <files>docker-compose.yml, render.yaml</files>
  <action>
    **docker-compose.yml:** In the `app` service environment block, add `OTEL_SERVICE_NAME: vici` alongside the existing `OTEL_EXPORTER_OTLP_ENDPOINT` line. The app service already sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `WEBHOOK_BASE_URL` — add `OTEL_SERVICE_NAME` in the same block.

    **render.yaml:** The production env var list is missing two observability vars. Add both after the existing `GIT_SHA` entry:
    ```yaml
      - key: OTEL_EXPORTER_OTLP_ENDPOINT
        sync: false
      - key: OTEL_SERVICE_NAME
        value: "vici"
    ```
    `OTEL_EXPORTER_OTLP_ENDPOINT` uses `sync: false` because the production collector endpoint must be set by the operator (it depends on deployment topology). `OTEL_SERVICE_NAME` can be hardcoded to `"vici"` as it never changes.

    Do not modify any other existing env var entries in either file.
  </action>
  <verify>
    <automated>grep "OTEL_SERVICE_NAME" docker-compose.yml && grep "OTEL_SERVICE_NAME" render.yaml && grep "OTEL_EXPORTER_OTLP_ENDPOINT" render.yaml && echo "PASS"</automated>
  </verify>
  <done>docker-compose.yml app service includes `OTEL_SERVICE_NAME: vici`. render.yaml includes both `OTEL_EXPORTER_OTLP_ENDPOINT` (sync: false) and `OTEL_SERVICE_NAME` (value: "vici").</done>
</task>

</tasks>

<verification>
All three files updated. Run the automated verify commands from each task. Then do a final cross-check:

```bash
# Every flat Settings field name should appear in .env.example (case-insensitive)
python3 -c "
import re
with open('src/config.py') as f: cfg = f.read()
fields = re.findall(r'^\s{4}(\w+): (?:str|bool|int)', cfg, re.MULTILINE)
with open('.env.example') as f: env = f.read().upper()
missing = [f for f in fields if f.upper() not in env]
print('Missing from .env.example:', missing or 'none')
"
```
</verification>

<success_criteria>
- `OTEL_SERVICE_NAME` (not `OTL_SERVICE_NAME`) is the key in .env.example
- `docker-compose.yml` app service env block contains `OTEL_SERVICE_NAME: vici`
- `render.yaml` env list contains `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME`
- No other changes to these files
- All existing tests pass: `uv run pytest -x -q`
</success_criteria>

<output>
After completion, create `.planning/quick/1-ensure-all-env-variables-or-values-assoc/1-SUMMARY.md` with what was changed and why.
</output>
