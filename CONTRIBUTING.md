<!-- generated-by: gsd-doc-writer -->
# Contributing to Vici

Thank you for your interest in contributing to Vici — an SMS-driven platform for the gig economy. This document outlines how to get involved, the coding conventions we follow, and the process for submitting changes.

For an overview of what Vici does and how it is structured, see the project [README.md](README.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Code of Conduct

This project does not yet have a formal `CODE_OF_CONDUCT.md`. In the meantime, we ask contributors to be respectful, constructive, and welcoming in all interactions (issues, pull requests, reviews, and discussions). Harassment or discriminatory behavior will not be tolerated.

## Getting Help

If you get stuck or have questions:

- Open a [GitHub issue](https://github.com/ahcarpenter/vici/issues) with the `question` label. <!-- VERIFY: public repository URL github.com/ahcarpenter/vici -->
- Check the existing documentation in the `docs/` directory:
  - [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md) — prerequisites and first-run instructions
  - [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — local development commands and workflows
  - [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture and component overview
  - [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — environment variables and configuration
  - [docs/TESTING.md](docs/TESTING.md) — how to write and run tests
  - [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — how the project is deployed and rolled back
- Review closed issues and pull requests — your question may already be answered.

## Reporting Bugs

Before filing a bug report, please search [existing issues](https://github.com/ahcarpenter/vici/issues) to avoid duplicates. <!-- VERIFY: public repository URL github.com/ahcarpenter/vici -->

When opening a bug report, include:

1. **Summary** — A one-line description of the problem.
2. **Steps to reproduce** — Exact commands, API requests, or SMS flows that trigger the bug.
3. **Expected behavior** — What you expected to happen.
4. **Actual behavior** — What actually happened, including full error messages and stack traces.
5. **Environment** — Python version (Vici requires `>=3.12`), operating system, whether you're running via Docker Compose or directly, and any relevant environment variable overrides.
6. **Logs** — Relevant application logs, Temporal worker output, or container logs if applicable.

## Suggesting Features

Feature requests are welcome. Open a GitHub issue with the `enhancement` label and include:

- **Problem statement** — What gap or pain point does this address?
- **Proposed solution** — What should the behavior look like?
- **Alternatives considered** — Other approaches you thought about and why you prefer this one.
- **Scope and impact** — Which domain(s) under `src/` would be affected. Current domains include `src/sms/`, `src/extraction/`, `src/matches/`, `src/pipeline/`, `src/temporal/`, `src/jobs/`, `src/work_goals/`, and `src/users/`.

For substantial features, please open an issue for discussion before starting work — this avoids wasted effort if the direction needs adjustment.

## Local Development Setup

Detailed setup instructions live in the docs directory to avoid duplication:

- See [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md) for prerequisites (Docker, Python 3.12+, `uv`, required third-party API keys) and first-run instructions.
- See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for day-to-day commands (running the API, Temporal worker, migrations, linting, and tests).
- See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full list of environment variables and the `.env.*.example` files you'll need to copy.

At a high level, the flow is: clone the repo, install dependencies with `uv sync`, copy the example env files, and run `docker compose up` to start the full stack.

## Coding Standards

This project follows the FastAPI conventions documented in [AGENTS.md](AGENTS.md) at the repository root. All contributors (human and AI) are expected to adhere to these standards. Highlights:

### Project Structure — Organize by Domain

Code is organized by domain under `src/`, not by file type. Each domain directory (e.g., `src/sms/`, `src/matches/`, `src/extraction/`, `src/pipeline/`) contains its own `router.py`, `schemas.py`, `models.py`, `service.py`, `dependencies.py`, `constants.py`, `exceptions.py`, and `utils.py` as needed. Global application wiring lives in `src/main.py`, `src/config.py`, `src/database.py`, and `src/models.py`.

When importing across domains, use explicit module names:

```python
from src.matches import service as matches_service
from src.sms import constants as sms_constants
```

### Async Rules

- Use `async def` routes **only** for non-blocking I/O (`await` calls).
- Use `def` routes (sync) for blocking I/O — FastAPI runs them in a threadpool automatically.
- Never call blocking functions (e.g., `time.sleep`, synchronous `requests`) inside `async def` — it blocks the event loop.
- To use a sync library from an async route, wrap it with `fastapi.concurrency.run_in_threadpool`.
- Offload CPU-intensive work to Temporal workflows or a dedicated worker rather than running it inside a request handler.

### Pydantic and SQLModel

- Prefer built-in validators (`Field`, `EmailStr`, regex patterns) over custom validators.
- Split `BaseSettings` by domain where practical — global settings live in `src/config.py` and are remapped into nested sub-models; see [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for details.
- Constantize magic numbers in `constants.py` within the owning domain.

### Dependencies

- Use FastAPI dependencies for validation, not just dependency injection (e.g., a `valid_post_id` dependency resolves the ID and raises a domain exception if missing).
- Chain dependencies to share validation logic (e.g., `valid_owned_post` depends on `valid_post_id` and `parse_jwt_data`).
- Prefer `async` dependencies to avoid threadpool overhead.
- Use consistent path variable names across endpoints to enable dependency reuse.

### Database and Migrations

- Use `lower_case_snake` naming with singular table names (`user`, `job`, `match`).
- Use `_at` suffix for timestamps (`created_at`), `_date` for dates (`birth_date`).
- Ensure schemas are in third normal form (3NF).
- Keep Alembic migrations static and reversible; descriptive filenames are enforced via `alembic.ini`'s `file_template`.
- Prefer SQL-level operations (joins, aggregation, JSON building) for complex queries.

### Design Principles

- Apply SOLID principles relentlessly.
- Prefer canonical Gang of Four patterns when a design pattern is warranted.
- Apply DRY relentlessly.
- Use canonical domain language throughout the codebase — if a term is more conventional in the domain, use it consistently everywhere.

### Linting and Formatting

We use [ruff](https://docs.astral.sh/ruff/) for both linting and formatting. The configuration lives in `pyproject.toml` under `[tool.ruff]`:

- Target Python version: `py312`
- Enabled lint rules: `E` (pycodestyle errors), `F` (pyflakes), `I` (isort)
- Per-file ignores: `src/extraction/prompts.py` ignores `E501` (long lines are intentional in LLM prompt strings)

Before committing, run:

```bash
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
```

CI enforces `uv run ruff check src/ tests/` on every push to `main` and every pull request targeting `main` via `.github/workflows/ci.yml` — a pull request with lint violations will not merge.

## Commit Message Conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/). The format is:

```
<type>(<scope>): <short description>
```

**Common types:** `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`.

**Scope** is optional but encouraged. It typically refers to a domain under `src/` or a phase/feature identifier. Examples drawn from recent history:

```
fix(ci): grant id-token:write permission to CD caller workflows
docs(06): create phase plan for infra best-practice audit and hardening
fix(infra): re-encrypt Pulumi stack configs for passphrase-based secrets
fix(tests): add start_cron_if_needed coverage and fix ruff violations
```

Keep the subject line under ~72 characters. Use the body (separated by a blank line) for extended explanation when the "why" isn't obvious from the diff.

## Branching

- The default branch is `main`. All pull requests target `main`.
- Create a feature branch off the latest `main` for each change. Suggested naming:
  - `feat/<short-description>` — new features
  - `fix/<short-description>` — bug fixes
  - `docs/<short-description>` — documentation changes
  - `chore/<short-description>` — tooling, config, or maintenance
- Keep branches focused on a single logical change. If a branch grows too large, split it.
- Rebase onto the latest `main` before opening a pull request to keep history clean.

## Pull Request Process

1. **Fork and branch** — Fork the repository (if you're an external contributor), then create a feature branch from `main`.
2. **Make your changes** — Follow the coding standards above. Keep commits logical and well-scoped.
3. **Add or update tests** — Any behavior change must be covered by tests. See the Testing Requirements section below.
4. **Run the quality checks locally** — Before pushing, run:

   ```bash
   uv run ruff check src/ tests/
   uv run ruff format src/ tests/
   uv run pytest tests/ -x --tb=short -q
   ```

5. **Update documentation** — If your change affects user-facing behavior, configuration, or architecture, update the relevant file(s) under `docs/` (for example [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) or [docs/CONFIGURATION.md](docs/CONFIGURATION.md)) or the root [README.md](README.md).
6. **Open the pull request** — Push your branch and open a PR against `main`. This repository does not currently ship a pull request template, so please include the following in your PR description:
   - What the change does and why
   - Any issues it closes (e.g., `Closes #123`)
   - Testing notes — how you verified the change locally
   - Screenshots or log excerpts if relevant
7. **Pass CI** — The `CI` workflow defined in `.github/workflows/ci.yml` runs on every push to `main` and every pull request targeting `main`. It installs dependencies with `uv sync --frozen`, runs `uv run ruff check src/ tests/`, and runs `uv run pytest tests/ -x --tb=short -q` against an aiosqlite-backed test database. Your PR must be green before review.
8. **Respond to review feedback** — Address reviewer comments with follow-up commits (don't force-push during review unless asked). Once approved, a maintainer will merge.

## Testing Requirements

See [docs/TESTING.md](docs/TESTING.md) for the full testing guide. Key expectations for contributors:

- **New features require new tests.** Unit and/or integration tests that exercise the new code paths.
- **Bug fixes require a regression test.** Add a test that fails on the old code and passes on the new code.
- **Tests use pytest in async mode.** Configured via `pyproject.toml` (`asyncio_mode = "auto"`).
- **Use the async test client.** Tests that hit the FastAPI app should use `httpx.AsyncClient` with `ASGITransport`.
- **Tests live under `tests/`** and are discovered automatically (`testpaths = ["tests"]`).
- **CI runs** `uv run pytest tests/ -x --tb=short -q` on every push and pull request. The `-x` flag means the suite stops at the first failure — make sure your branch is green locally before pushing.

## License

By contributing to Vici, you agree that your contributions will be licensed under the [GNU General Public License v3.0](LICENSE), the same license that covers the rest of the project.

---

Thank you for helping make Vici better!
