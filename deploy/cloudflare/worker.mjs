const COOKIE_NAME = "ptc_session";
const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;
const encoder = new TextEncoder();

function hex(bytes) {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function constantTimeEqual(left, right) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

async function sha256(value) {
  return hex(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

async function sign(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return hex(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
}

function cookieValue(request) {
  const header = request.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === COOKIE_NAME) return value.join("=");
  }
  return "";
}

async function validSession(request, secret) {
  const [expiresAt, signature, ...rest] = cookieValue(request).split(".");
  if (rest.length || !/^\d+$/.test(expiresAt || "") || !signature) return false;
  if (Number(expiresAt) <= Math.floor(Date.now() / 1000)) return false;
  return constantTimeEqual(signature, await sign(secret, expiresAt));
}

function safeNext(value) {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//")
    ? value
    : "/";
}

function pageHeaders() {
  return {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "Content-Type": "text/html; charset=utf-8",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow",
  };
}

function loginPage(next = "/", invalid = false) {
  const escapedNext = safeNext(next).replaceAll("&", "&amp;").replaceAll('"', "&quot;");
  const error = invalid ? '<p class="error">密码不正确，请重试。</p>' : "";
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>登录 · Makubex 交易训练</title>
  <style>
    *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101316;color:#eef0ed;font-family:Arial,"PingFang SC",sans-serif;padding:24px}.shell{width:min(420px,100%);border-top:3px solid #d6ff3f;background:#191d20;padding:32px;border-radius:6px;box-shadow:0 18px 60px #0008}.eyebrow{color:#a9b0aa;font:12px/1.4 ui-monospace,monospace;text-transform:uppercase}.title{font-size:26px;margin:10px 0 8px}.copy{color:#a9b0aa;font-size:14px;line-height:1.7;margin:0 0 24px}label{display:block;font-size:13px;margin-bottom:8px}input{width:100%;height:46px;border:1px solid #4b5350;border-radius:4px;background:#101316;color:#fff;padding:0 12px;font-size:16px;outline:none}input:focus{border-color:#d6ff3f}button{width:100%;height:46px;margin-top:14px;border:0;border-radius:4px;background:#d6ff3f;color:#101316;font-weight:700;font-size:15px;cursor:pointer}.error{color:#ff8b7b;font-size:13px;margin:12px 0 0}.foot{margin-top:20px;color:#78807a;font-size:12px}
  </style>
</head>
<body>
  <main class="shell">
    <div class="eyebrow">Private coach desk</div>
    <h1 class="title">Makubex 交易训练</h1>
    <p class="copy">这是受保护的个人交易站。输入站点密码后继续。</p>
    <form method="post" action="/__auth/login">
      <input type="hidden" name="next" value="${escapedNext}">
      <label for="password">站点密码</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
      <button type="submit">进入教练台</button>
    </form>
    ${error}
    <div class="foot">会话保留7天 · 不在页面中保存密码</div>
  </main>
</body>
</html>`;
}

function loginResponse(next, invalid = false) {
  return new Response(loginPage(next, invalid), { status: 401, headers: pageHeaders() });
}

export default {
  async fetch(request, env) {
    if (!env.SITE_PASSWORD || !env.SESSION_SECRET || !env.ASSETS) {
      return new Response("Site authentication is not configured.", { status: 503 });
    }

    const url = new URL(request.url);

    if (url.pathname === "/__auth/logout") {
      return new Response(null, {
        status: 303,
        headers: {
          Location: "/",
          "Set-Cookie": `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`,
        },
      });
    }

    if (url.pathname === "/__auth/login" && request.method === "POST") {
      const form = await request.formData();
      const supplied = String(form.get("password") || "");
      const next = safeNext(String(form.get("next") || "/"));
      const passwordMatches = constantTimeEqual(
        await sha256(supplied),
        await sha256(env.SITE_PASSWORD),
      );
      if (!passwordMatches) return loginResponse(next, true);

      const expiresAt = String(Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS);
      const token = `${expiresAt}.${await sign(env.SESSION_SECRET, expiresAt)}`;
      return new Response(null, {
        status: 303,
        headers: {
          Location: next,
          "Set-Cookie": `${COOKIE_NAME}=${token}; Path=/; Max-Age=${SESSION_TTL_SECONDS}; HttpOnly; Secure; SameSite=Strict`,
        },
      });
    }

    if (!(await validSession(request, env.SESSION_SECRET))) {
      return loginResponse(`${url.pathname}${url.search}`);
    }

    const assetResponse = await env.ASSETS.fetch(request);
    const headers = new Headers(assetResponse.headers);
    headers.set("Cache-Control", "private, no-store");
    headers.set("X-Content-Type-Options", "nosniff");
    headers.set("X-Frame-Options", "DENY");
    headers.set("X-Robots-Tag", "noindex, nofollow");
    return new Response(assetResponse.body, {
      status: assetResponse.status,
      statusText: assetResponse.statusText,
      headers,
    });
  },
};
