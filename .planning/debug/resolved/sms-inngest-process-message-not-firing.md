---
status: resolved
trigger: "sms-inngest-process-message-not-firing"
created: 2026-03-07T00:00:00Z
updated: 2026-03-07T00:01:00Z
---

## Current Focus

hypothesis: CONFIRMED — Inngest client created without event_api_base_url; inside Docker it defaults to localhost:8288 (the app container itself), so client.send() events go nowhere
test: read inngest_client.py and docker-compose.yml
expecting: fix by passing event_api_base_url=settings.inngest_base_url to inngest.Inngest()
next_action: apply fix to src/inngest_client.py

## Symptoms

expected: SMS arrives at /webhook/sms → process-message Inngest function fires and appears in dashboard
actual: /webhook/sms returns 200 OK but no Inngest job ever appears in dashboard
errors: No error on webhook. Separate 500 on POST /api/inngest?fnId=vici-sync-pinecone-queue&stepId=step (unrelated)
reproduction: Send real SMS to Twilio number
started: Never worked — freshly implemented feature

## Eliminated

(none yet)

## Evidence

- timestamp: 2026-03-07T00:00:30Z
  checked: src/inngest_client.py — inngest.Inngest() constructor call
  found: Inngest client is created with only app_id and is_production; event_api_base_url is NOT passed
  implication: SDK defaults event_api_base_url to http://localhost:8288; inside Docker "localhost" is the app container, not the inngest container — events are sent nowhere

- timestamp: 2026-03-07T00:00:40Z
  checked: docker-compose.yml
  found: INNGEST_BASE_URL=http://inngest:8288 is set as an env var for the app container
  implication: The correct URL is already in the environment via settings.inngest_base_url, but is never passed to the Inngest client

- timestamp: 2026-03-07T00:00:50Z
  checked: src/config.py
  found: inngest_base_url field exists in Settings (default "http://localhost:8288"), env var INNGEST_BASE_URL populates it
  implication: The plumbing for the correct URL exists end-to-end; only the wire-up in inngest.Inngest() is missing

- timestamp: 2026-03-07T00:01:00Z
  checked: Inngest Python SDK docs (official)
  found: inngest.Inngest() accepts event_api_base_url parameter; INNGEST_EVENT_API_BASE_URL env var is the alternative
  implication: Passing event_api_base_url=settings.inngest_base_url to the client constructor will direct events to the correct Docker container

## Resolution

root_cause: inngest.Inngest() in src/inngest_client.py is constructed without event_api_base_url. Inside Docker, the SDK defaults to http://localhost:8288 which resolves to the app container itself (not the inngest container). Events sent via client.send() never reach the Inngest dev server.
fix: Pass event_api_base_url=settings.inngest_base_url to inngest.Inngest()
verification: confirmed by user — SMS webhook now triggers process-message Inngest job visible in dashboard
files_changed:
  - src/inngest_client.py
