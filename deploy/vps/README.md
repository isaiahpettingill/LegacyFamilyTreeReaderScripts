# VPS deployment

This stack runs the application as UID/GID `10001`, mounts the family database read-only, gives
the application no persistent write path, and publishes no VPS ports. A dedicated Cloudflare
Tunnel connects the FastAPI service to its hostname and Cloudflare terminates HTTPS.

## Install

Use a supported Linux VPS, then install Docker Engine and the Compose plugin from Docker's
official repository: <https://docs.docker.com/engine/install/>. Install `cloudflared` on the
administration workstation or VPS and authenticate it to the Cloudflare account that manages the
hostname. Add the deploy user to the `docker` group only if that user may effectively have root
access. Verify installation:

```sh
docker version
docker compose version
```

Clone the repository on the VPS and work from `deploy/vps`.

## Initial deploy

1. Create a dedicated tunnel and route the deployment hostname to it. Use the tunnel UUID
   explicitly when creating the DNS route:

```sh
cloudflared tunnel create family-history-archive
cloudflared tunnel route dns --overwrite-dns TUNNEL_UUID family.example.com
cloudflared tunnel token TUNNEL_UUID
```

   Store the final command's token only in `.env`; never commit or paste it into Compose. The DNS
   command creates the required proxied CNAME automatically.
2. Create the configuration and database location:

```sh
cp .env.example .env
chmod 600 .env
install -d -m 700 data backups
install -m 444 /path/to/family-tree.sqlite data/family-tree.sqlite
```

3. Edit `.env`. Use a long unique family password, generate the session secret with
   `openssl rand -hex 32`, and set `CLOUDFLARE_TUNNEL_TOKEN`. Do not quote values or use trailing
   comments.
4. Check and start the stack:

```sh
docker compose config --quiet
docker compose build --pull
docker compose up --detach
docker compose ps
docker compose logs --no-log-prefix cloudflared app
```

The application and tunnel containers have no published host ports. Confirm the public HTTPS
hostname reaches `/login` before sharing it.

## Updates

Review upstream changes before deployment, then rebuild without deleting volumes:

```sh
git pull --ff-only
docker compose build --pull
docker compose up --detach --remove-orphans
docker compose ps
```

Keep the previous Git revision available for rollback.

## Backups

The mounted SQLite file is the authoritative data. The app cannot modify it. Take a consistent
backup before application or database updates and store encrypted copies off the VPS:

```sh
backup="backups/family-tree-$(date +%F-%H%M%S).sqlite"
sudo sqlite3 data/family-tree.sqlite ".backup '$backup'"
sudo sqlite3 "$backup" "PRAGMA quick_check;"
```

Test restores periodically. Stop the stack before replacing the mounted database, retain the old
file, set its mode to `444`, then start the stack and check its health. The `data` directory stays
mode `700` and the container mount is read-only; using a world-readable file mode only inside that
private directory avoids UID remapping failures in rootless or user-namespaced Docker. `.env`,
`data/`, and `backups/` are ignored by Git and the Docker build context.

## Firewall

Cloudflare Tunnel makes outbound connections, so the VPS needs no inbound HTTP or HTTPS rules.
Allow SSH before enabling a default-deny firewall. With UFW, adjust the SSH rule if it uses a
nonstandard port:

```sh
sudo ufw allow OpenSSH
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

Restrict SSH to keys or Tailscale, disable direct root login, apply unattended security updates,
and keep Docker and the base OS patched. Do not publish port 8000, 80, or 443 in Compose or a
cloud firewall.

## Threat model

`FAMILY_PASSWORD` and `SESSION_SECRET` are passed only to the application; Cloudflare terminates
public TLS and the tunnel forwards to FastAPI on an isolated Docker network. The deployment sets
`SESSION_COOKIE_SECURE=1`, so FastAPI marks its session cookie `Secure`. The server enforces the
family password on every HTML and API route other than `/healthz`, `/robots.txt`, `/login`, and
`/logout`. Verify that unauthenticated API requests are rejected before sharing the hostname.

Authentication protects against casual unauthorised access, not a compromised VPS, Cloudflare
account, Docker/root access, stolen `.env` or backups, password sharing, or an authenticated user
retaining returned family data. Cloudflare can observe traffic passing through the tunnel. Use a
random password, rotate both secrets after suspected disclosure, protect backups, monitor logs,
and avoid placing other untrusted workloads on the host. Add Cloudflare Access or rate limiting
if internet password guessing is a material risk.
