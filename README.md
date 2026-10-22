# NGX Trading Bot

An asynchronous trading-bot prototype with a mock broker, SQLite persistence, a command-line runner, and a Streamlit simulation dashboard. The included live broker adapters have not been verified against official broker documentation or a sandbox and must not be assumed production-ready.

## Requirements

- Python 3.11 or newer
- Docker Desktop with Docker Compose (optional, for container deployment)

## Run locally on Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py --broker mock
```

The CLI defaults to the mock broker. The dashboard also uses only the mock broker:

```powershell
streamlit run ui_app.py
```

## Run with Docker Compose

```powershell
docker compose up --build -d
docker compose logs -f dashboard
```

Open `http://localhost:8501`. The dashboard is bound to loopback and the SQLite database is stored in a named Docker volume. Stop it with:

```powershell
docker compose down
```

The database volume is retained by that command. Do not use `docker compose down -v` unless you intend to delete the database. For remote access, put the service behind an authenticated HTTPS reverse proxy; do not expose port 8501 directly to the internet.

## Live broker adapters

Live broker selection is disabled unless the explicit `--enable-live-trading` flag is supplied. Credentials are read from environment variables rather than stored in source:

```powershell
$env:NGX_API_KEY = "..."
$env:NGX_API_SECRET = "..."
$env:NGX_ACCOUNT = "..."
python main.py --broker cardinalstone --enable-live-trading
```

This flag is only a guard against accidental selection. It does **not** mean a broker integration is verified or safe for live orders. Before live use, validate endpoint paths, authentication/signing rules, order-status mappings, fees, partial fills, cancellation behavior, and account permissions against the broker's current official documentation and sandbox. Use a dedicated account with strict limits. The Docker Compose service intentionally runs the mock dashboard only.

## Operational limitations

- If saved state contains an open/pending order or held shares, startup stops and requires reconciliation with the broker. This is deliberate; the app does not automatically adopt or cancel broker-side orders.
- SQLite is intended for a single application instance on local/persistent storage, not multiple replicas or a network filesystem.
- The configured price-limit setting is not currently an implemented circuit breaker.
- Configure and verify database backups, monitoring, access control, and recovery procedures for your deployment environment.