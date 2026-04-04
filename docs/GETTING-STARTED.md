<!-- generated-by: gsd-doc-writer -->
# Getting Started

## Prerequisites

- **Python >= 3.12** (see `pyproject.toml` `requires-python` and Dockerfile `FROM python:3.12-slim`)
- **[uv](https://docs.astral.sh/uv/)** -- the project uses uv for dependency management and script execution
- **Docker and Docker Compose** -- required to run PostgreSQL, Temporal, OpenSearch, Jaeger, Prometheus, and Grafana locally

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/ahcarpenter/vici.git
   cd vici
   ```

2. Install Python dependencies:

   ```bash
   uv sync
   ```

3. Create your environment files. The application reads from `.env` (via Pydantic Settings) and Docker Compose reads from service-specific env files:

   ```bash
   # App-level env file (loaded by Pydantic Settings and docker-compose .env.app)
   cp .env.app.example .env.app   # if an example exists, otherwise create manually
   ```

   At minimum, the following environment variables must be set (the app will fail at startup if any are empty):

   | Variable | Description |
   |----------|-------------|
   | `DATABASE_URL` | PostgreSQL connection string (e.g., `postgresql+asyncpg://vici:password@localhost:5432/vici`) |
   | `TWILIO_AUTH_TOKEN` | Twilio authentication token |
   | `OPENAI_API_KEY` | OpenAI API key |
   | `PINECONE_API_KEY` | Pinecone vector database API key |
   | `TEMPORAL_ADDRESS` | Temporal server address (e.g., `localhost:7233`) |
   | `WEBHOOK_BASE_URL` | Base URL for webhook callbacks (e.g., `http://localhost:8000`) |
   | `ENV` | Environment name (e.g., `local`, `staging`, `production`) |

   Docker Compose also expects `.env.postgres`, `.env.opensearch`, `.env.temporal`, `.env.temporal-ui`, `.env.jaeger-query`, and `.env.grafana` files for the supporting services.

## First Run

The simplest way to start the full stack is with Docker Compose:

```bash
docker compose up --build
```

This will:

1. Start PostgreSQL (port 5432), OpenSearch (port 9200), and Temporal (port 7233)
2. Run Alembic migrations automatically (`alembic upgrade head`)
3. Start the FastAPI app on **http://localhost:8000** with hot reload
4. Start Temporal UI on port 8080, Jaeger UI on port 16686, Prometheus on port 9090, and Grafana on port 3000

Verify the app is running:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### Running Without Docker

If you prefer to run the app directly (with external services already available):

```bash
# Run migrations
uv run alembic upgrade head

# Start the server
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

## Common Setup Issues

- **Missing environment variables at startup** -- The app validates required credentials on boot via `Settings._validate_required_credentials`. If any of the seven required variables listed above are empty, you will see: `ValueError: Required credentials are missing or empty: ...`. Double-check your `.env` or `.env.app` file.

- **PostgreSQL connection refused** -- If running the app outside Docker while PostgreSQL runs inside Docker Compose, ensure your `DATABASE_URL` points to `localhost:5432` (the mapped port) rather than the Docker internal hostname `postgres`.

- **Temporal not ready** -- The app container depends on Temporal being healthy. If Temporal takes longer than expected to start (especially on first run when it auto-sets-up), the app container may restart a few times. This is normal -- Docker Compose will retry based on the health check.

- **Port conflicts** -- The stack uses ports 3000 (Grafana), 5432 (Postgres), 7233 (Temporal), 8000 (app), 8080 (Temporal UI), 9090 (Prometheus), 9200 (OpenSearch), and 16686 (Jaeger). Ensure these are not already in use.

## Next Steps

- [ARCHITECTURE.md](ARCHITECTURE.md) -- Understand the system design and component relationships
- [CONFIGURATION.md](CONFIGURATION.md) -- Full reference of environment variables and settings
