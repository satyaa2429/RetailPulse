# Deploy RetailPulse

This package runs locally and provides a container deployment path. No public cloud deployment has been made. Use a host that supports Python containers, an HTTPS endpoint and a persistent data volume.

## Container workflow

From the project folder, build the container:

```bash
docker build -t retailpulse .
docker volume create retailpulse-data
docker run --rm -v retailpulse-data:/data retailpulse python -m retailpulse --data-dir /data demo
```

The initialization command is for an empty volume. To use actual store data instead, mount the CSV as input and run `import-sales` with the appropriate coverage date, then `train`; see README. Do not overwrite an existing store with demo data.

Set a project access token as an environment variable. This Python command prints a randomly generated value for you to store in your hosting secret settings:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Linux/macOS example:

```bash
export RETAILPULSE_API_TOKEN='paste-your-generated-token-here'
docker run -d --name retailpulse -p 127.0.0.1:8000:8000 -v retailpulse-data:/data -e RETAILPULSE_API_TOKEN retailpulse
```

PowerShell example:

```powershell
$env:RETAILPULSE_API_TOKEN = "paste-your-generated-token-here"
docker run -d --name retailpulse -p 127.0.0.1:8000:8000 -v retailpulse-data:/data -e RETAILPULSE_API_TOKEN retailpulse
```

Open the app and enter that token. Docker requires a configured token. For a cloud host, configure its normal public ingress and HTTPS rather than the local loopback port mapping. Keep `/data` on a persistent volume and set `RETAILPULSE_API_TOKEN` in its secret environment settings.

## Hosting configuration

| Setting | Value |
|---|---|
| Runtime | Docker / Python 3.12 |
| Container port | 8000 |
| Data directory | `/data` on persistent storage |
| Availability endpoint | `/api/status` |
| Start command | Supplied by Dockerfile: Gunicorn, one worker, four threads |
| Required secret | `RETAILPULSE_API_TOKEN` |
| Authentication enforcement | `RETAILPULSE_REQUIRE_TOKEN=1` |

Choose host sizing from a trial training run on your dataset. The supplied demo tracks eight products; the UCI default tracks twelve. The container and hosting commands are configuration provided for you to run, not a claim that those environments were tested here.

## Refresh after a completed day

The app's **Refresh forecast** button runs training in the background. Alternatively:

```bash
docker exec retailpulse python -m retailpulse --data-dir /data train
```

Schedule this after the business day closes if the host supports scheduled jobs. This project does not create a schedule automatically. A stale forecast cannot create targets when it lacks lead-time coverage.

Use one application process so the background job lock is coherent. Do not run a scheduled train at the same time as a dashboard refresh. SQLite commits each stock movement atomically. Multiple replicas require a shared database and external job coordination, which are beyond this initial version.

## Keep a recoverable copy of data

Use SQLite's backup API or the host's consistent volume snapshot feature for a running database. Do not copy only a live `.sqlite3` file while its WAL contains uncheckpointed writes. Preserve `forecast.json` alongside the database if you want the current forecasts as well.


## 0.4 operational additions

The application creates consistent SQLite ZIP backups on server start and hourly, keeping 48 automatic backups. The local serve command adds a backup on normal shutdown. Store the data directory and its backups on persistent storage, and download a copy outside that storage for recovery. Manual backups are retained. A restore is performed with restore-backup --file ... into a new empty --data-dir; it refuses existing contents. There is no scheduled cloud transfer or restore over a running shop.

Tables for product actions, stock counts and bill returns are added on opening an older database. Product columns active, revision and introduced_on are added; PRAGMA user_version becomes 4. An older database is backed up through SQLite before migration. Do not deploy a database from a newer schema into an older application.
