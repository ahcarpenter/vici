---
phase: quick-2
plan: 2
type: execute
wave: 1
depends_on: []
files_modified:
  - docker-compose.yml
  - .env.example
autonomous: true
requirements: []
must_haves:
  truths:
    - "No URL string in docker-compose.yml is hardcoded where the value could differ between environments"
    - "The inngest service command uses a variable for the app's internal URL"
    - ".env.example documents the INNGEST_APP_URL variable so operators know it exists"
  artifacts:
    - path: "docker-compose.yml"
      provides: "All env-sensitive URLs use ${VAR:-default} substitution syntax"
    - path: ".env.example"
      provides: "INNGEST_APP_URL documented under Inngest section"
  key_links:
    - from: "docker-compose.yml inngest service command"
      to: "INNGEST_APP_URL env var"
      via: "${INNGEST_APP_URL:-http://app:8000} shell substitution"
      pattern: "INNGEST_APP_URL"
---

<objective>
Extract hardcoded URL strings in docker-compose.yml that could vary by environment into variable substitution references, and document them in .env.example.

Purpose: Any URL that could change (app host, port, service name) should be overridable without editing docker-compose.yml directly. This matches the pattern already used for GIT_SHA on line 77.
Output: docker-compose.yml with ${VAR:-default} substitution for env-sensitive URLs; .env.example updated with new variable.
</objective>

<execution_context>
@/Users/ahcarpenter/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ahcarpenter/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@src/config.py
@docker-compose.yml
@.env.example
</context>

<tasks>

<task type="auto">
  <name>Task 1: Parameterise hardcoded URLs in docker-compose.yml</name>
  <files>docker-compose.yml</files>
  <action>
    Two URLs in docker-compose.yml are hardcoded strings that should use shell variable substitution:

    1. Line 76 — app service `WEBHOOK_BASE_URL`:
       Change `http://localhost:8000` to `${WEBHOOK_BASE_URL:-http://localhost:8000}`
       Rationale: If running behind a reverse proxy or on a different port, operator can override without editing the file. Matches pattern of GIT_SHA on line 77.

    2. Line 87 — inngest service command:
       Change `inngest dev -u http://app:8000/api/inngest`
       to     `inngest dev -u ${INNGEST_APP_URL:-http://app:8000}/api/inngest`
       Rationale: The Docker Compose service name `app` and port `8000` are the only URL components that could change if the service is renamed or the port mapping changes. Extracting it allows override without touching docker-compose.yml.

    No other URLs in docker-compose.yml need extraction:
    - `DATABASE_URL` on line 71 uses Docker service name `postgres` — already a Compose-internal concern, port and credentials are also Compose-internal. Leave as-is; it correctly overrides the .env DATABASE_URL for container networking.
    - `INNGEST_BASE_URL` on line 73 and `OTEL_EXPORTER_OTLP_ENDPOINT` on line 74 use Docker service names (`inngest`, `jaeger-collector`) — these are Compose-internal and do not change across prod/staging (production does not use docker-compose). Leave as-is.
    - Health check `curl` URLs (lines 23, 42) use `localhost` inside the container — not env-specific, leave as-is.
    - `http://localhost:9090`, `http://localhost:3000` in health checks are internal container checks — leave as-is.
  </action>
  <verify>
    grep "WEBHOOK_BASE_URL:-" docker-compose.yml
    grep "INNGEST_APP_URL:-" docker-compose.yml
  </verify>
  <done>Both grep commands return a match. docker-compose.yml has no remaining hardcoded env-sensitive URL strings.</done>
</task>

<task type="auto">
  <name>Task 2: Document INNGEST_APP_URL in .env.example</name>
  <files>.env.example</files>
  <action>
    Add `INNGEST_APP_URL` to the Inngest section of .env.example, after `INNGEST_BASE_URL`.

    Insert this block after the `INNGEST_BASE_URL=http://localhost:8288` line:

    ```
    # Internal URL docker-compose uses to register the app with Inngest Dev Server.
    # Change if you rename the 'app' service or use a different port.
    INNGEST_APP_URL=http://app:8000
    ```

    Note: this variable is only used by docker-compose.yml (inngest service command). It is NOT read by src/config.py — do not add it to Settings.
  </action>
  <verify>
    grep "INNGEST_APP_URL" .env.example
  </verify>
  <done>grep returns the INNGEST_APP_URL line in .env.example under the Inngest section.</done>
</task>

</tasks>

<verification>
After both tasks:
  grep "WEBHOOK_BASE_URL:-" docker-compose.yml && echo "WEBHOOK_BASE_URL OK"
  grep "INNGEST_APP_URL:-" docker-compose.yml && echo "INNGEST_APP_URL in compose OK"
  grep "INNGEST_APP_URL" .env.example && echo "INNGEST_APP_URL documented OK"
</verification>

<success_criteria>
- docker-compose.yml uses ${WEBHOOK_BASE_URL:-http://localhost:8000} on the app service WEBHOOK_BASE_URL line
- docker-compose.yml uses ${INNGEST_APP_URL:-http://app:8000}/api/inngest in the inngest service command
- .env.example documents INNGEST_APP_URL with a comment explaining its purpose
- No new variables added to src/config.py (these are Compose-only concerns)
- All existing tests still pass: uv run pytest tests/ -x -q
</success_criteria>

<output>
After completion, create `.planning/quick/2-make-sure-any-strings-with-url-s-that-co/2-SUMMARY.md` using the summary template.
</output>
