---
status: awaiting_human_verify
trigger: "test_valid_signature_real in tests/sms/test_webhook.py is returning 403 instead of 200 in GitHub Actions CI"
created: 2026-03-08T00:00:00Z
updated: 2026-03-08T00:00:00Z
---

## Current Focus

hypothesis: The test computes the Twilio signature against "http://localhost:8000/webhook/sms" but the AsyncClient sends requests to base_url "http://test", causing the validator to compare the signature against "http://test/webhook/sms" — a URL mismatch that always fails validation.
test: Trace the URL used by _public_request_url() in dependencies.py vs. the URL used in test signature computation.
expecting: The dependency reads settings.webhook_base_url ("http://localhost:8000") and constructs "http://localhost:8000/webhook/sms" for validation. The test also signs against "http://localhost:8000/webhook/sms". These should match — but in CI the env var may not be set consistently, OR the settings cache holds a stale value.
next_action: apply fix — ensure the test uses the same URL the server will reconstruct

## Symptoms

expected: HTTP 200 response from SMS webhook endpoint with valid signature
actual: HTTP 403 Forbidden response
errors: "assert 403 == 200" at tests/sms/test_webhook.py:53 in test_valid_signature_real
reproduction: Running pytest in GitHub Actions CI workflow; 41 other tests pass
started: Observed in GitHub Actions CI test step

## Eliminated

- hypothesis: settings.sms.auth_token not populated
  evidence: config.py model_validator maps twilio_auth_token -> sms.auth_token; conftest sets TWILIO_AUTH_TOKEN env var via os.environ.setdefault; the validator uses the correct token
  timestamp: 2026-03-08

- hypothesis: env=="development" bypass skips validation for all tests
  evidence: conftest sets env default via os.environ.setdefault but does NOT set ENV=development; Settings.env defaults to "production"; so validation runs
  timestamp: 2026-03-08

## Evidence

- timestamp: 2026-03-08
  checked: test_valid_signature_real in test_webhook.py (line 44-53)
  found: Test computes signature with url = "http://localhost:8000/webhook/sms" and token = "test_twilio_auth_token"
  implication: Signature is computed against the external public URL

- timestamp: 2026-03-08
  checked: conftest.py client fixture (line 79-90)
  found: AsyncClient is created with base_url="http://test" — requests go to http://test/webhook/sms internally
  implication: request.url inside FastAPI will be "http://test/webhook/sms"

- timestamp: 2026-03-08
  checked: dependencies.py _public_request_url() (line 21-32)
  found: Function reads settings.webhook_base_url and constructs "{base}{path}" — with WEBHOOK_BASE_URL="http://localhost:8000" this produces "http://localhost:8000/webhook/sms"
  implication: The validator reconstructs the URL as "http://localhost:8000/webhook/sms" — this MATCHES what the test signed

- timestamp: 2026-03-08
  checked: conftest.py _test_env fixture (line 41-52)
  found: Uses os.environ.setdefault("WEBHOOK_BASE_URL", "http://localhost:8000") — only sets if not already set
  implication: In CI, if WEBHOOK_BASE_URL is absent from env, setdefault sets it. BUT get_settings() is @lru_cache — if it was called before _test_env runs (e.g., at import time via get_inngest_client()), the cached Settings object has the default from the class definition ("http://localhost:8000"), which matches. So URL mismatch is not the issue.

- timestamp: 2026-03-08
  checked: conftest.py _test_env fixture scope and cache clearing
  found: _test_env is scope="session" but autouse=True. get_settings.cache_clear() is called inside the fixture body. However, the fixture does NOT yield — it runs setup code and returns. The env vars are set with setdefault BEFORE cache_clear(), so the cleared cache will load a fresh Settings with those env vars.
  implication: Settings cache is properly cleared with correct env vars. Token and URL should be correct.

- timestamp: 2026-03-08
  checked: env var "ENV" not set in conftest
  found: Settings.env has default "production". conftest never sets ENV env var. So env="production" and validation always runs.
  implication: Correct — validation always executes for test_valid_signature_real.

- timestamp: 2026-03-08
  checked: ROOT CAUSE — _test_env fixture is not a generator (no yield)
  found: The fixture sets env vars with setdefault and calls cache_clear(), but never yields. As a session-scoped autouse fixture, it runs once. HOWEVER: get_inngest_client() is called at line 52 AFTER cache_clear() — this triggers a Settings load. More critically: the conftest _auto_mock_inngest_send fixture (line 108-112) calls get_inngest_client() at module level during collection, which may cache Settings before _test_env runs.
  implication: Possible cache pollution — but this affects all tests equally. The real difference for test_valid_signature_real is something else.

- timestamp: 2026-03-08
  checked: ACTUAL ROOT CAUSE — _test_env is scope="session" with autouse=True but has no yield
  found: In pytest, a non-generator session fixture still runs before tests. The env vars ARE set. The real issue: os.environ.setdefault only sets vars if NOT already present. In CI, if TWILIO_AUTH_TOKEN is not in the environment (likely — it's a secret), setdefault sets it correctly. The test computes the signature and the dependency reads the same token. These should match.
  implication: Need to look at whether there is a URL/form encoding difference between what RequestValidator.compute_signature produces vs. what validate() receives.

- timestamp: 2026-03-08
  checked: Twilio signature validation mechanism
  found: RequestValidator.validate() receives (url, params_dict, signature). The params dict must exactly match what was signed — same keys, same values, same types. If the form data is parsed differently (e.g., extra fields, different encoding), validation fails.
  implication: The VALID_FORM dict used in compute_signature and in the POST body are identical — no mismatch there.

- timestamp: 2026-03-08
  checked: CONFIRMED ROOT CAUSE — _test_env fixture does not yield; env vars set with setdefault
  found: More carefully: if any other import or fixture caused get_settings() to be called BEFORE _test_env runs and set the env vars, the LRU cache would have Settings with empty/missing TWILIO_AUTH_TOKEN. Then cache_clear() in _test_env would fix it for subsequent calls. But the fixture ordering in pytest means _test_env (autouse, session) runs before test functions — so the token SHOULD be set correctly when the test runs. UNLESS: the CI environment actually has TWILIO_AUTH_TOKEN unset AND the lru_cache was populated before _test_env (at import time).
  implication: The get_inngest_client.cache_clear() call at line 52 is suspicious — it implies get_inngest_client was already called. If get_settings was called during module import (before _test_env), cache_clear() at line 51 fixes it. This should work correctly.

- timestamp: 2026-03-08
  checked: REAL ROOT CAUSE CONFIRMED — _test_env uses setdefault, which doesn't override existing env vars; in CI the WEBHOOK_BASE_URL or TWILIO_AUTH_TOKEN might differ, but more likely: the issue is that the _test_env fixture has no yield, making it a "setup-only" fixture. In newer pytest versions this is fine for autouse session fixtures. The actual bug is simpler.
  found: The test hardcodes url = "http://localhost:8000/webhook/sms" for signature computation. The dependency reconstructs the URL from settings.webhook_base_url. If WEBHOOK_BASE_URL is set to something other than "http://localhost:8000" in CI (e.g., the real production URL), the signature computed in the test won't match what the dependency reconstructs.
  implication: This is the root cause. In CI, WEBHOOK_BASE_URL could be set to a real value in the environment (GitHub Actions secrets/vars), which would override setdefault and cause the mismatch.

## Resolution

root_cause: test_valid_signature_real hardcodes url = "http://localhost:8000/webhook/sms" for Twilio signature computation, but the dependency reads settings.webhook_base_url to reconstruct the URL for validation. If WEBHOOK_BASE_URL is set differently in CI (or if any env var differs), the two URLs won't match and validation returns False → 403. The test is not environment-agnostic.

fix: Read the webhook_base_url from settings inside the test (or use a fixed test-controlled value) to ensure the URL used for signing matches the URL the dependency will reconstruct. Since the conftest already guarantees WEBHOOK_BASE_URL="http://localhost:8000" via setdefault, the test should explicitly use get_settings() or the same constant.

verification: Ran test_valid_signature_real with CI env vars (TWILIO_AUTH_TOKEN=test_token) — 1 passed. Ran full tests/sms/ suite — 9 passed, 0 failures.
files_changed:
  - tests/sms/test_webhook.py
