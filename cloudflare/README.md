# Cloudflare Hosting

This Worker hosts the chunked static archive generated in `cloudflare/public`.
The generated directory is intentionally ignored: do not commit a database,
manifest, or chunk files.

## Prerequisites

- A descriptive SQLite database produced by `legacy-family-tree`
- `legacy-family-tree` installed on `PATH`, or `uv` and this repository checkout
- Node.js with `npx`
- A Cloudflare account authenticated with `npx --yes wrangler@4.31.0 login`
- OpenSSL when using the deployment script's default password setup

No R2 or D1 service is needed. The site builder splits the database into static
assets below Cloudflare's 25 MiB per-asset limit.

## Self-Host Locally

Generate the site and run Wrangler's local server from the repository root:

```console
legacy-family-tree build-site genealogy.sqlite cloudflare/public --force
npx --yes wrangler@4.31.0 dev --config cloudflare/wrangler.jsonc
```

If the command is not installed, use:

```console
uv run legacy-family-tree build-site genealogy.sqlite cloudflare/public --force
```

Local password testing uses an ignored `cloudflare/.dev.vars` file:

```dotenv
FAMILY_PASSWORD=choose-a-password
SESSION_SECRET=replace-with-a-long-random-value
```

Omit both values for an unprotected local site. If `FAMILY_PASSWORD` is set but
`SESSION_SECRET` is missing or empty, the Worker deliberately returns a generic
503 response.

## Deploy

The helper rebuilds the complete site, asks Wrangler for `FAMILY_PASSWORD`,
generates a new random `SESSION_SECRET` without printing it, and deploys with
Wrangler 4.31.0:

```console
scripts/deploy-cloudflare.sh genealogy.sqlite
```

Use alternate paths when needed:

```console
scripts/deploy-cloudflare.sh genealogy.sqlite \
  --site-dir cloudflare/public \
  --config cloudflare/wrangler.jsonc
```

To deploy without setting or changing password secrets:

```console
scripts/deploy-cloudflare.sh genealogy.sqlite --no-password
```

`--no-password` never deletes existing secrets. If `FAMILY_PASSWORD` already
exists, the Worker remains password-protected. Explicitly remove it with:

```console
npx --yes wrangler@4.31.0 secret delete FAMILY_PASSWORD \
  --config cloudflare/wrangler.jsonc
```

Deleting `SESSION_SECRET` is optional once `FAMILY_PASSWORD` is absent. Never
put either secret in `wrangler.jsonc` or a committed file.

## Update The Archive

Run the same deployment command with the current database. `--force` replaces
the generated local site before Wrangler uploads its changed assets:

```console
scripts/deploy-cloudflare.sh genealogy.sqlite
```

The default command also rotates `SESSION_SECRET`, so every existing login is
invalidated. Use `--no-password` for an asset-only update that preserves current
secrets and sessions.

## Passwords And Sessions

Set or replace the password manually:

```console
npx --yes wrangler@4.31.0 secret put FAMILY_PASSWORD \
  --config cloudflare/wrangler.jsonc
```

Changing only `FAMILY_PASSWORD` does not revoke already-issued 12-hour session
cookies. Rotate the signing secret to log out every browser immediately:

```console
openssl rand -hex 32 | npx --yes wrangler@4.31.0 secret put SESSION_SECRET \
  --config cloudflare/wrangler.jsonc
```

The random value is piped directly to Wrangler and is not printed. After a
successful login, the browser receives a 12-hour `HttpOnly`, `Secure`,
`SameSite=Strict` cookie. To log out the current browser, run this on the site's
own origin in its browser developer console:

```js
fetch("/logout", { method: "POST" }).then(() => location.assign("/login"));
```

The logout endpoint accepts only a same-origin POST and clears the cookie.

## Custom Domain

Deploy first, then open the Cloudflare dashboard and select **Workers & Pages >
family-history-hosted-pattengills > Settings > Domains & Routes > Add > Custom
Domain**. Enter a domain in a zone managed by the same account and complete the
DNS prompt. Cloudflare provisions HTTPS; confirm the custom-domain URL reaches
`/login` before sharing it. Keep the generated `workers.dev` address private or
disable that route in the dashboard if the custom domain should be the only
entry point.

## Threat Model

This is static hosting with an optional shared-password gate. It is a speed
bump against casual access, not user-level authorization, encryption, digital
rights management, or a guarantee of security. Cloudflare receives and serves
the archive bytes. Anyone with the shared password can use, retain, or share
them, and changing the password alone does not revoke an existing session.

An authorized browser downloads all database chunks and reconstructs the whole
SQLite database in memory. A user who can view the archive can also save or
extract its contents. Do not publish records that should not be disclosed to
every authorized user, and do not treat the chunking as encryption.

`robots.txt`, `X-Robots-Tag`, and `noindex` directives are advisory. They ask
cooperative crawlers not to index the site but cannot prevent discovery,
scraping, screenshots, browser extensions, compromised devices, leaked
passwords, Cloudflare account compromise, or access through an accidentally
unprotected deployment. Use a strong password, rotate the session secret after
suspected exposure, protect the Cloudflare account with MFA, and remove the
deployment when it is no longer needed.

The CSP allows same-origin bundled JavaScript and CSS plus one exact hashed
inline bootstrap that keeps both hosted deep links and direct `file://` use
working. It does not include `unsafe-eval`; the bundled SQL.js asm runtime does
not require it. If a future generated runtime switches to code generation or
WebAssembly, test that change explicitly rather than weakening the policy
silently.
