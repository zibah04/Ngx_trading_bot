# Private simulation deployment

This deployment runs only the mock dashboard. It is a shared operator console: everyone who
has its password can start or stop the same simulation. It is not a multi-tenant service.
Live trading remains a separate release gate; see [LIVE_READINESS.md](LIVE_READINESS.md).

## Prepare a server

Use a Linux server with Docker Engine and Docker Compose v2. Reserve at least 2 GB RAM and
persistent local disk. Run one dashboard replica. Point a DNS hostname to the server and allow
inbound TCP 80 and 443 for Caddy's automatic HTTPS. Do not publish port 8501 or the Docker socket.
Keep SSH access restricted and keep the host patched.

From the repository checkout:

```sh
cp .env.example .env
chmod 600 .env
docker run --rm -it caddy:2.10.2-alpine caddy hash-password
```

Enter the password interactively. Put the resulting bcrypt hash in `NGX_AUTH_HASH` in `.env`,
using single quotes so Compose preserves the dollar signs. Set `NGX_AUTH_USER` and `NGX_DOMAIN`
to your operator username and real DNS hostname. Do not commit `.env`, plaintext passwords,
or broker credentials. Use a password manager to distribute access to the authorized operators.

```sh
docker compose --env-file .env -f compose.private.yaml up --build -d --wait
docker compose --env-file .env -f compose.private.yaml logs --tail=100
```

Caddy terminates HTTPS, requires a password for all routes (including WebSockets), and forwards
to the internal dashboard. The dashboard has no host port in this file. The loopback-only
`compose.yaml` is an alternative for local development; do not run both stacks against one account.
Use the same project name and Compose file for all subsequent operations so the correct volumes
are used. Do not expose a production deployment through an HTTP domain override.

If a corporate proxy is required for the build, pass Docker's standard `HTTPS_PROXY`, `HTTP_PROXY`,
and `NO_PROXY` build arguments. A trusted CA bundle can be supplied as a BuildKit secret named
`pip_ca` (`docker build --secret id=pip_ca,src=/path/to/ca-bundle.pem ...`). The bundle is used only
in the install layer and is not copied into the final image. Keep certificate verification enabled.
Cloud-specific DNS routing may also require a supported builder network or `--add-host` override.

## Acceptance checks

The repository includes an isolated automated check (no public ports, synthetic credentials,
and a local test certificate authority). It verifies certificate trust, password protection,
authenticated WebSockets, non-root execution, and storage across restart:

```sh
docker build -t ngx-trading-bot:test .
python3 scripts/test_private_deployment.py --image ngx-trading-bot:test
```

For the actual deployment:

1. An unauthenticated HTTPS request to the hostname must return **401**.
2. With the configured username and password, `/_stcore/health` must return **200 / ok**.
   `curl --user YOUR_USERNAME https://YOUR_HOST/_stcore/health` prompts for the password.
3. In the authenticated dashboard, verify mock cash is ₦2,000,000.00, Start simulation changes
   status to Running, and Stop simulation completes. No real broker is contacted.
4. A blocked engine must display **Blocked** and its reason. Stop it before creating another run.
5. Restart the stack and verify records remain in `/app/data`, then repeat the dashboard check.

The Streamlit health check establishes web-server availability only. A running container can
have a blocked simulation. Monitor container health, HTTPS availability, disk space, and logs;
review the dashboard's trading status separately. Automated trading alerts are still a live-release
requirement, not provided by this mock deployment. Configure the host to collect the rotated Docker
logs and send operational alerts through your existing monitoring system.

## Simulation records and recovery

The mock broker keeps cash, holdings, and orders in memory. Every new process and every explicit
**New simulation** gets a distinct SQLite filename, so a fresh mock account is never paired with
orders belonging to a previous mock account. Old databases are retained. **New simulation** is
available only after the previous run has stopped; it does not clear old database state.

Known open orders are cancelled and their final status is checked on graceful shutdown. Cancellation
can race with a fill, and partial fills can leave holdings. Pending submission markers and all
unresolved state remain available for investigation. SIGKILL, host loss, and network failures cannot
provide a graceful-shutdown guarantee. The CLI keeps a stable `--db-path` and refuses to resume
unresolved state. Never delete a live database to bypass that check.

Inspect an archived database without modifying it:

```sh
docker compose -f compose.private.yaml exec -T dashboard \
  python scripts/state_tools.py report --db /app/data/ngx_dashboard-RUN_ID.db
```

For an eventual live incident, compare the report with the broker's authoritative order history,
actual fills, holdings, and cash. A `SUBMISSION_PENDING` marker requires broker-side discovery;
an empty local order list does not prove nothing was submitted. There is deliberately no command
that blindly clears markers, adopts holdings, or starts live trading.

## Backup and restore

Back up every run you need to keep. Use SQLite's online backup API rather than copying a database
file that might be changing. The helper refuses to overwrite an existing backup and checks integrity.
For example, choose a unique output filename:

```sh
docker compose -f compose.private.yaml exec -T dashboard \
  python scripts/state_tools.py backup --db /app/data/ngx_dashboard-RUN_ID.db \
  --output /app/data/backup-RUN_ID-YYYYMMDD.db
```

Copy backups off the host using your backup system, restrict access, encrypt storage, and define
retention. Test restoration regularly. To check a restore, copy a backup into an isolated directory,
run `python scripts/state_tools.py report --db RESTORED_FILE`, verify integrity and compare records.
Do not connect restored live state to an active account before reconciliation. Restored mock databases
are historical records; they do not restore the in-memory mock broker. Never run the restore drill
against the production database. Prune archived simulations only after backup and an operator retention decision.

## Stop and update

```sh
docker compose -f compose.private.yaml down
git pull --ff-only
docker compose --env-file .env -f compose.private.yaml up --build -d --wait
```

`down` preserves named volumes. Do not use `down -v` unless you intend to destroy the data. Stop the
simulation before updating, back up records, and repeat the acceptance checks. Keep the previous
Git commit/image available for rollback; reconcile any trading state before restarting an old version.
