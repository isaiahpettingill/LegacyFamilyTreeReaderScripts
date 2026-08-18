# VPS deployment

This stack runs the application as UID/GID `10001`, mounts the family database read-only, gives
the application no persistent write path, and publishes only Caddy on ports 80 and 443. Caddy
obtains and renews HTTPS certificates automatically.

## Install

Use a supported Linux VPS with a public IP, then install Docker Engine and the Compose plugin
from Docker's official repository: <https://docs.docker.com/engine/install/>. Add the deploy user
to the `docker` group only if that user may effectively have root access. Verify installation:

```sh
docker version
docker compose version
```

Clone the repository on the VPS and work from `deploy/vps`.

## Initial deploy

1. Create DNS `A` and, when IPv6 is configured, `AAAA` records for the deployment hostname.
   Both records must point directly to the VPS. Remove an unusable `AAAA` record.
2. Create the configuration and database location:

```sh
cp .env.example .env
chmod 600 .env
install -d -m 700 data backups
install -m 400 /path/to/family-tree.sqlite data/family-tree.sqlite
sudo chown 10001:10001 data/family-tree.sqlite
```

3. Edit `.env`. Use a long unique family password and generate the session secret with
   `openssl rand -hex 32`. Do not quote values or use trailing comments.
4. Check and start the stack:

```sh
docker compose config --quiet
docker compose build --pull
docker compose up --detach
docker compose ps
docker compose logs --no-log-prefix caddy app
```

Caddy can issue a certificate after DNS resolves and inbound ports 80 and 443 are reachable.
The application container has no published host port.

## Updates

Review upstream changes before deployment, then rebuild without deleting volumes:

```sh
git pull --ff-only
docker compose build --pull
docker compose up --detach --remove-orphans
docker compose ps
```

Keep the previous Git revision available for rollback. Never run `docker compose down --volumes`
unless intentionally deleting certificate state.

## Backups

The mounted SQLite file is the authoritative data. The app cannot modify it. Take a consistent
backup before application or database updates and store encrypted copies off the VPS:

```sh
backup="backups/family-tree-$(date +%F-%H%M%S).sqlite"
sudo sqlite3 data/family-tree.sqlite ".backup '$backup'"
sudo sqlite3 "$backup" "PRAGMA quick_check;"
```

Test restores periodically. Stop the stack before replacing the mounted database, retain the old
file, set restored ownership to `10001:10001` and mode `400`, then start the stack and check its
health. `.env`, `data/`, and `backups/` are ignored by Git and the Docker build context.

## Firewall

Allow SSH before enabling a default-deny firewall. With UFW, adjust the SSH rule if it uses a
nonstandard port:

```sh
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

Restrict SSH to keys, disable direct root login, apply unattended security updates, and keep
Docker and the base OS patched. Do not publish port 8000 in Compose or a cloud firewall.

## Threat model

`FAMILY_PASSWORD` and `SESSION_SECRET` are passed only to the application; Caddy terminates TLS
and does not provide authentication. The deployment sets `SESSION_COOKIE_SECURE=1`, so FastAPI
marks its session cookie `Secure`. The server enforces the family password on every HTML and API
route other than `/healthz`, `/robots.txt`, `/login`, and `/logout`. Verify that unauthenticated
API requests are rejected before publishing DNS.

Authentication protects against casual unauthorised access, not a compromised VPS, Docker/root
access, stolen `.env` or backups, password sharing, or an authenticated user downloading all
family data. Use a random password, rotate both secrets after suspected disclosure, protect
backups, monitor logs, and avoid placing other untrusted workloads on the host. Add upstream rate
limiting or an identity-aware proxy if internet password guessing is a material risk.
