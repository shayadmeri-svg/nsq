// UI smoke test — signs in and opens every screen of a running app, failing on anything a person would see as broken:
// an uncaught JavaScript error, an API call answering 5xx, an error box on the page, "Invalid Date" / "NaN" in the
// text, or a page that never renders its heading. Read-only: it never clicks Run, Save or Delete.
//
//   E2E_EMAIL=… E2E_PASSWORD=… node smoke.mjs                 # against http://localhost:5173 (just run-web)
//   BASE_URL=http://<server> E2E_EMAIL=… E2E_PASSWORD=… node smoke.mjs --shots   # + a screenshot per page in shots/
//
// Credentials come only from the environment. Use a super admin to cover the admin screens.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = (process.env.BASE_URL || "http://localhost:5173").replace(/\/$/, "");
const EMAIL = process.env.E2E_EMAIL, PASSWORD = process.env.E2E_PASSWORD;
const SHOTS = process.argv.includes("--shots");
const ONLY = (process.argv.find((a) => a.startsWith("--only=")) || "").slice(7);
if (!EMAIL || !PASSWORD) {
  console.error("Set E2E_EMAIL and E2E_PASSWORD (a super admin covers every screen).");
  process.exit(2);
}

const PLAYGROUND = ["explore", "ledger", "insights", "forensics", "forensics?view=portfolio", "forensics?view=needed", "investigate",
  "world", "molecule", "plants", "wc", "health", "medicines", "process", "reactions"].map((t) => `/playground/${t}`);
const ADMIN = ["/admin", "/admin/orgs", "/admin/users", "/admin/data/update", "/admin/data/schedules", "/admin/molecules", "/admin/sites",
  "/admin/audit", "/admin/data/map", "/admin/explorer"];
const ORG = ["", "/quality", "/infrastructure", "/opportunities", "/eu", "/team"];
const IGNORE_CONSOLE = [/ERR_TUNNEL/, /favicon/, /status of 401/, /Download the React DevTools/];
const BAD_TEXT = [/Invalid Date/, /\bNaN\b/, /\[object Object\]/];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage();
let problems = [];
page.on("pageerror", (e) => problems.push(`JS error: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !IGNORE_CONSOLE.some((r) => r.test(m.text()))) problems.push(`console: ${m.text().slice(0, 200)}`); });
page.on("response", (r) => { if (r.url().includes("/api/") && r.status() >= 500) problems.push(`API ${r.status()} ${new URL(r.url()).pathname}`); });

try { await page.goto(`${BASE}/login`); } catch (e) {
  console.error(`Cannot reach ${BASE} — start the app (just run-api + just run-web) or set BASE_URL.`); await browser.close(); process.exit(2);
}
await page.fill("input[type=email]", EMAIL);
await page.fill("input[type=password]", PASSWORD);
await page.click("button[type=submit]");
await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15000 }).catch(() => {});
if (page.url().includes("/login")) { console.error("Sign-in failed — check E2E_EMAIL / E2E_PASSWORD."); await browser.close(); process.exit(2); }

const me = await page.evaluate(async () => (await fetch("/api/auth/me")).json()).catch(() => ({}));
const isPlatform = me?.user?.is_platform ?? ["super_admin", "admin"].includes(me?.user?.role);
const orgs = await page.evaluate(async () => { try { return (await (await fetch("/api/orgs")).json()).orgs || []; } catch { return []; } });
let routes = ["/", ...PLAYGROUND, ...(isPlatform ? ADMIN : []), ...(orgs[0] ? ORG.map((s) => `/o/${orgs[0].slug}${s}`) : [])];
if (ONLY) routes = routes.filter((r) => r.includes(ONLY));
if (SHOTS) mkdirSync("shots", { recursive: true });

let failed = 0;
for (const route of routes) {
  problems = [];
  const t0 = Date.now();
  await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => problems.push("still loading after 20 s"));
  await page.waitForTimeout(600);
  const heading = await page.locator("h1").first().textContent({ timeout: 5000 }).catch(() => null);
  if (!heading) problems.push("no page heading rendered");
  const notes = await page.locator("[data-testid=error-note]").allTextContents();
  notes.forEach((n) => problems.push(`error box: ${n.slice(0, 160)}`));
  const text = await page.locator("main, body").first().innerText().catch(() => "");
  BAD_TEXT.forEach((rx) => { const m = text.match(rx); if (m) problems.push(`shows "${m[0]}"`); });
  if (SHOTS) await page.screenshot({ path: `shots/${route.replace(/[/?=]+/g, "_").replace(/^_/, "") || "home"}.png`, fullPage: true });
  const ok = problems.length === 0;
  if (!ok) failed++;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${route.padEnd(40)} ${(Date.now() - t0) / 1000}s ${heading ? `· ${heading.trim().slice(0, 40)}` : ""}`);
  [...new Set(problems)].forEach((p) => console.log(`         - ${p}`));
}
await browser.close();
console.log(`\n${routes.length - failed}/${routes.length} screens clean${failed ? ` · ${failed} with problems` : ""}`);
process.exit(failed ? 1 : 0);
