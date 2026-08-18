const COOKIE_NAME = "__Host-lft_session";
const SESSION_SECONDS = 12 * 60 * 60;
const encoder = new TextEncoder();

const SECURITY_HEADERS = Object.freeze({
  "Content-Security-Policy": "default-src 'none'; script-src 'self' 'sha256-gejFXlVGkHnHkHvZFnQIzXSbpHGolD/d8fGODE3oV0o='; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
  "Referrer-Policy": "same-origin",
  "X-Content-Type-Options": "nosniff",
  "X-Robots-Tag": "noindex,nofollow,noarchive"
});

function hasValue(value) {
  return typeof value === "string" && value.length > 0;
}

function bytesToBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlToBytes(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  try {
    const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/") + padding);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

async function sha256(value) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

export function constantTimeEqual(left, right) {
  if (!(left instanceof Uint8Array) || !(right instanceof Uint8Array)) return false;
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (left[index] || 0) ^ (right[index] || 0);
  }
  return difference === 0;
}

export async function passwordsEqual(submitted, configured) {
  const [submittedDigest, configuredDigest] = await Promise.all([
    sha256(submitted),
    sha256(configured)
  ]);
  return constantTimeEqual(submittedDigest, configuredDigest);
}

async function hmacKey(secret) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

export async function createSession(secret, now = Date.now()) {
  const expires = Math.floor(now / 1000) + SESSION_SECONDS;
  const payload = `v1.${expires}`;
  const signature = await crypto.subtle.sign("HMAC", await hmacKey(secret), encoder.encode(payload));
  return `${payload}.${bytesToBase64Url(new Uint8Array(signature))}`;
}

export async function verifySession(value, secret, now = Date.now()) {
  if (!hasValue(value) || !hasValue(secret)) return false;
  const match = /^(v1)\.(\d+)\.([A-Za-z0-9_-]+)$/.exec(value);
  if (!match) return false;

  const expires = Number(match[2]);
  const currentSeconds = Math.floor(now / 1000);
  if (!Number.isSafeInteger(expires) || expires <= currentSeconds) return false;

  const signature = base64UrlToBytes(match[3]);
  if (!signature || signature.length !== 32) return false;
  const payload = `${match[1]}.${match[2]}`;
  return crypto.subtle.verify(
    "HMAC",
    await hmacKey(secret),
    signature,
    encoder.encode(payload)
  );
}

export function cookieValue(cookieHeader, name = COOKIE_NAME) {
  for (const item of (cookieHeader || "").split(";")) {
    const separator = item.indexOf("=");
    if (separator === -1) continue;
    if (item.slice(0, separator).trim() === name) return item.slice(separator + 1).trim();
  }
  return null;
}

function sessionCookie(value, expires) {
  return `${COOKIE_NAME}=${value}; Path=/; Max-Age=${SESSION_SECONDS}; Expires=${expires.toUTCString()}; HttpOnly; Secure; SameSite=Strict`;
}

function expiredSessionCookie() {
  return `${COOKIE_NAME}=; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Secure; SameSite=Strict`;
}

function htmlEscape(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeDestination(value, requestUrl) {
  if (!value) return "/";
  try {
    const destination = new URL(value, requestUrl);
    const current = new URL(requestUrl);
    if (destination.origin !== current.origin || !value.startsWith("/") || value.startsWith("//")) {
      return "/";
    }
    if (destination.pathname === "/login" || destination.pathname === "/logout") return "/";
    return `${destination.pathname}${destination.search}`;
  } catch {
    return "/";
  }
}

function loginPage(next = "/", message = "") {
  const notice = message ? `<p role="alert">${htmlEscape(message)}</p>` : "";
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in - Legacy Family Archive</title>
</head>
<body>
  <main>
    <h1>Legacy Family Archive</h1>
    ${notice}
    <form method="post" action="/login">
      <input type="hidden" name="next" value="${htmlEscape(next)}">
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>`;
}

function response(body, status, headers = {}) {
  return new Response(body, { status, headers });
}

function redirect(location, headers = {}) {
  return response(null, 303, { Location: location, ...headers });
}

function isNavigation(request) {
  if (request.method !== "GET") return false;
  return request.mode === "navigate" ||
    request.headers.get("Sec-Fetch-Mode") === "navigate" ||
    request.headers.get("Sec-Fetch-Dest") === "document" ||
    (request.headers.get("Accept") || "").includes("text/html");
}

function sameOrigin(request) {
  const origin = request.headers.get("Origin");
  if (origin !== null) return origin === new URL(request.url).origin;
  const referrer = request.headers.get("Referer");
  if (referrer !== null) {
    try {
      return new URL(referrer).origin === new URL(request.url).origin;
    } catch {
      return false;
    }
  }
  return request.headers.get("Sec-Fetch-Site") === "same-origin";
}

function isHashedPart(pathname) {
  return /(?:^|\/)[^/]*[a-f0-9]{16,}[^/]*\.part\d*$/i.test(pathname);
}

function finalize(source, { noStore = false, immutable = false } = {}) {
  const headers = new Headers(source.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value);
  if (noStore) {
    headers.set("Cache-Control", "private, no-store");
    headers.set("CDN-Cache-Control", "no-store");
  } else if (immutable) {
    headers.set("Cache-Control", "public, max-age=31536000, immutable");
  }
  return new Response(source.body, {
    status: source.status,
    statusText: source.statusText,
    headers
  });
}

function plain(body, status = 200, headers = {}) {
  return response(body, status, { "Content-Type": "text/plain; charset=utf-8", ...headers });
}

async function handleLogin(request, env, passwordConfigured) {
  const url = new URL(request.url);
  if (request.method === "GET" || request.method === "HEAD") {
    const next = safeDestination(url.searchParams.get("next"), request.url);
    const body = request.method === "HEAD" ? null : loginPage(next);
    return response(body, 200, { "Content-Type": "text/html; charset=utf-8" });
  }
  if (request.method !== "POST") return plain("Method not allowed\n", 405, { Allow: "GET, HEAD, POST" });
  if (!passwordConfigured) return redirect("/");

  const contentType = (request.headers.get("Content-Type") || "").split(";", 1)[0].trim().toLowerCase();
  const contentLength = Number(request.headers.get("Content-Length") || 0);
  if (contentType !== "application/x-www-form-urlencoded" || contentLength > 8192) {
    return plain("Bad request\n", 400);
  }
  const body = await request.text();
  if (body.length > 8192) return plain("Bad request\n", 400);
  const form = new URLSearchParams(body);
  const next = safeDestination(form.get("next"), request.url);
  if (!(await passwordsEqual(form.get("password") || "", env.FAMILY_PASSWORD))) {
    return response(loginPage(next, "Invalid password."), 401, {
      "Content-Type": "text/html; charset=utf-8"
    });
  }

  const now = Date.now();
  const session = await createSession(env.SESSION_SECRET, now);
  return redirect(next, {
    "Set-Cookie": sessionCookie(session, new Date(now + SESSION_SECONDS * 1000))
  });
}

async function handleRequest(request, env) {
  const url = new URL(request.url);
  const passwordConfigured = hasValue(env.FAMILY_PASSWORD);
  const sessionConfigured = hasValue(env.SESSION_SECRET);

  if (request.method === "GET" && url.pathname === "/robots.txt") {
    return finalize(plain("User-agent: *\nDisallow: /\n"), { noStore: true });
  }

  if (passwordConfigured && !sessionConfigured) {
    return finalize(plain("Service unavailable\n", 503), { noStore: true });
  }

  if (url.pathname === "/login") {
    const result = await handleLogin(request, env, passwordConfigured);
    return finalize(result, { noStore: true });
  }

  if (url.pathname === "/logout" && request.method === "POST") {
    if (!sameOrigin(request)) return finalize(plain("Forbidden\n", 403), { noStore: true });
    const result = redirect(passwordConfigured ? "/login" : "/");
    result.headers.set("Set-Cookie", expiredSessionCookie());
    return finalize(result, { noStore: true });
  }

  if (request.method !== "GET" && request.method !== "HEAD") {
    return finalize(plain("Method not allowed\n", 405, { Allow: "GET, HEAD" }), {
      noStore: passwordConfigured
    });
  }

  if (passwordConfigured) {
    const session = cookieValue(request.headers.get("Cookie"));
    if (!(await verifySession(session, env.SESSION_SECRET))) {
      if (isNavigation(request)) {
        const next = safeDestination(`${url.pathname}${url.search}`, request.url);
        return finalize(redirect(`/login?next=${encodeURIComponent(next)}`), { noStore: true });
      }
      return finalize(plain("Unauthorized\n", 401), { noStore: true });
    }
  }

  if (!env.ASSETS || typeof env.ASSETS.fetch !== "function") {
    return finalize(plain("Service unavailable\n", 503), { noStore: true });
  }
  const asset = await env.ASSETS.fetch(request);
  return finalize(asset, {
    noStore: passwordConfigured,
    immutable: !passwordConfigured && isHashedPart(url.pathname)
  });
}

export default {
  async fetch(request, env) {
    try {
      return await handleRequest(request, env);
    } catch {
      return finalize(plain("Service unavailable\n", 503), { noStore: true });
    }
  }
};
