import assert from "node:assert/strict";

import worker from "../deploy/cloudflare/worker.mjs";


const env = {
  SITE_PASSWORD: "test-password",
  SESSION_SECRET: "test-session-secret",
  ASSETS: {
    fetch: async () => new Response("private-site", { headers: { "Content-Type": "text/plain" } }),
  },
};

const anonymous = await worker.fetch(new Request("https://example.pages.dev/ledger.html"), env);
assert.equal(anonymous.status, 401);
assert.match(await anonymous.text(), /站点密码/);

const badForm = new FormData();
badForm.set("password", "wrong");
badForm.set("next", "/ledger.html");
const badLogin = await worker.fetch(
  new Request("https://example.pages.dev/__auth/login", { method: "POST", body: badForm }),
  env,
);
assert.equal(badLogin.status, 401);

const goodForm = new FormData();
goodForm.set("password", "test-password");
goodForm.set("next", "/ledger.html");
const goodLogin = await worker.fetch(
  new Request("https://example.pages.dev/__auth/login", { method: "POST", body: goodForm }),
  env,
);
assert.equal(goodLogin.status, 303);
assert.equal(goodLogin.headers.get("Location"), "/ledger.html");
assert.match(goodLogin.headers.get("Set-Cookie"), /HttpOnly; Secure; SameSite=Strict/);

const cookie = goodLogin.headers.get("Set-Cookie").split(";", 1)[0];
const authenticated = await worker.fetch(
  new Request("https://example.pages.dev/ledger.html", { headers: { Cookie: cookie } }),
  env,
);
assert.equal(authenticated.status, 200);
assert.equal(await authenticated.text(), "private-site");
assert.equal(authenticated.headers.get("Cache-Control"), "private, no-store");

const tampered = await worker.fetch(
  new Request("https://example.pages.dev/ledger.html", { headers: { Cookie: `${cookie}x` } }),
  env,
);
assert.equal(tampered.status, 401);

console.log("cloudflare auth worker tests passed");
