# Deploying the demo instance

How the dev/demo instance runs: one small VM with Docker Compose, and Postgres on Supabase's free plan. The decision
and the options considered are in #121. This is a demo setup with no backups; it isn't the public service.

## What runs

| Service | What it is | Network |
|---|---|---|
| `caddy` | TLS (Let's Encrypt) and reverse proxy to the API | public ports 80 and 443 |
| `api` | FastAPI, serving the JSON API and the built frontend | internal only |
| `worker` | procrastinate worker running analyses | internal only |
| `migrate` | `alembic upgrade head`, run once before `api` and `worker` start | internal only |
| `egress` | Squid, HTTPS CONNECT to `pypi.org`, `files.pythonhosted.org`, `github.com` and `codeload.github.com` only | internal and outbound |
| `dbproxy` | HAProxy, a TCP pass-through to the Supabase session pooler | internal and outbound |

`api`, `worker` and `migrate` sit on a Docker network with no route out. Their HTTP requests go through `egress`
(`HTTPS_PROXY`), and their database connection goes through `dbproxy`. Anything else, including DNS lookups for outside
names, fails. TLS to Supabase stays end to end: `dbproxy` only forwards bytes.

All three run from one image (`Dockerfile` at the repository root), as uid 10001, with a read-only root filesystem and
no capabilities. The worker writes to the `data` volume (blobs, download cache, analysis temp files); the API mounts it
read-only to serve file diffs.

The files are in `deploy/`: `compose.yaml`, `Caddyfile`, `squid.conf`, `haproxy.cfg` and `env.example`.

## Supabase

1. Create a project on the free plan, in the US region nearest the VM. Save the database password.
2. Open **Connect** and copy the **Session pooler** connection string (port 5432). Don't use the transaction pooler
   (port 6543): the job queue needs LISTEN/NOTIFY and session-level locks.
3. Split it into `deploy/.env` (next section): `postgresql://<user>:<password>@<host>:5432/<name>`. The user looks like
   `postgres.<project-ref>`.

Free plan limits: a 500 MB database, and projects pause after a week without activity. The worker's open connection
should keep it active; if it pauses anyway, restore it from the dashboard.

## The VM

A DigitalOcean Basic droplet with 2 vCPU and 4 GB (Ubuntu 24.04), in a US region near the Supabase project.

1. Create it with an SSH key. Add a cloud firewall allowing 22 (from your address), 80 and 443 inbound.
2. Add swap, for building the image and for large archives:
   ```bash
   fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
   echo '/swapfile none swap sw 0 0' >> /etc/fstab
   ```
3. Install Docker Engine and the Compose plugin from Docker's apt repository
   ([instructions](https://docs.docker.com/engine/install/ubuntu/)).
4. Point the domain's DNS A record at the droplet.

## First deploy

```bash
git clone https://github.com/aesir-oss/sightglass.git && cd sightglass/deploy
cp env.example .env       # then fill in the domain and the Supabase values
docker compose up -d --build
```

The first build takes several minutes: it installs the pixi environment, compiles the Rust extension and builds the
frontend. Then:

```bash
docker compose ps                       # migrate exited 0; api healthy; the rest running
curl https://<domain>/api/health        # {"status":"ok",...}
docker compose logs -f worker egress    # analyses, and every outbound request with its verdict
```

## Updates

```bash
git pull && docker compose up -d --build
```

`migrate` runs again before `api` and `worker` restart, so schema changes apply on the way up.

## Operating it

- **A shell in the app's environment:** `docker compose exec worker bash /shell-hook.sh python`. The shell hook
  activates the pixi environment; `exec` doesn't run the image's entrypoint.
- **Allowing another host:** add it to `allowed_hosts` in `squid.conf` and `docker compose restart egress`. Only add a
  host the code fetches from (see `PYPI_HOSTS` and `GITHUB_HOSTS` in `sightglass.ecosystems`).
- **Testers only:** uncomment the `basic_auth` block in `Caddyfile` and `docker compose restart caddy`.
- **Disk:** container logs rotate at 3 × 10 MB per service. The `data` volume grows with every analysis; remove it
  with `docker compose down -v` to start over. The analyses stay in the database, but their file diffs need the stored
  contents.

## Not covered yet

- Backups. Supabase's free plan has none; Pro adds daily backups.
- A prebuilt image. The VM builds its own. Publishing one from CI would make updates quicker.
- Image size. The image carries the whole pixi environment, including build tools (Rust, Node) and test dependencies,
  because `pixi.toml` has a single environment. A runtime-only environment would shrink it.
- Per-client rate limits on analysis requests (see "Security of the service" in `design.md`).
- S3-compatible blob storage, for when the app runs on more than one machine.
