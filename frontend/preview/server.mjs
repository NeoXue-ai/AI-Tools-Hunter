/**
 * Design preview server — NOT part of the shipped console.
 *
 * Serves the built bundle from `src/ai_tools_hunter/static` and answers the four
 * read endpoints with fixed fixtures, so the interface can be reviewed without
 * running the Python daemon or a real CT scan. Mutations are accepted and
 * acknowledged but never persisted.
 *
 *   node preview/server.mjs        →  http://127.0.0.1:4173
 *   DH_EMPTY=1 node preview/server.mjs   →  first-run (empty) state
 */

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = normalize(join(fileURLToPath(new URL(".", import.meta.url)), ".."));
// Vite writes the bundle to the package's static dir, one level above `frontend/`.
const STATIC = normalize(join(FRONTEND, "..", "src", "ai_tools_hunter", "static"));
const PORT = Number(process.env.PORT ?? 4173);
/** Rehearse the first-run state: no candidates, no cursor, empty queue. */
const EMPTY = process.env.DH_EMPTY === "1";

const now = Date.now();
const iso = (msAgo) => new Date(now - msAgo).toISOString();
const DAY = 86_400_000;
const HOUR = 3_600_000;

const WEIGHTS = {
  product: 0.35,
  early: 0.3,
  lowExposure: 0.2,
  completeness: 0.15,
};

/** Mirrors `calculate_review_priority`: the score IS the sum of contributions. */
const priorityOf = ([product, early, lowExposure, completeness]) => {
  const parts = {
    product_evidence_contribution: round(product * WEIGHTS.product),
    early_presence_contribution: round(early * WEIGHTS.early),
    low_exposure_contribution: round(lowExposure * WEIGHTS.lowExposure),
    data_completeness_contribution: round(completeness * WEIGHTS.completeness),
  };
  return {
    score: round(Object.values(parts).reduce((sum, value) => sum + value, 0)),
    formula_version: "review-priority-v1",
    ...parts,
  };
};

const candidate = (spec) => ({
  candidate_id: `c_${spec.domain.replace(/[^a-z0-9]/g, "")}`,
  domain: spec.domain,
  version: spec.version ?? 1,
  author_kind: spec.author ?? "llm",
  primary_outcome: spec.outcome ?? "publishable_ai_saas",
  classification_confidence: spec.confidence ?? 0.78,
  name_suggestion: spec.name ?? null,
  description_suggestion: spec.description ?? null,
  evidence: (spec.quotes ?? []).map((quote, index) => ({
    type: spec.quoteTypes?.[index] ?? "visible_text",
    quote,
    url: `https://${spec.domain}/`,
  })),
  canonical_url: `https://${spec.domain}/`,
  internal_links: spec.links ?? [],
  priority: priorityOf(spec.inputs),
  review_state: "pending",
  newness: {
    status: spec.age === null ? "unknown" : "passed",
    checked_at: iso(2 * HOUR),
    ct_first_seen_at: spec.seenHours === null ? null : iso(spec.seenHours * HOUR),
    rdap_tier: spec.age === null ? "unknown" : spec.age <= 30 ? "tier1" : "tier2",
    rdap_age_days: spec.age,
    rdap_registration_at: spec.age === null ? null : iso(spec.age * DAY),
  },
  reachability: {
    status: spec.http === null ? "unknown" : spec.http < 400 ? "passed" : "failed",
    http_status_code: spec.http,
    final_url: spec.http === null ? null : `https://${spec.domain}/`,
    canonical_url: spec.http === null ? null : `https://${spec.domain}/`,
    same_root: spec.http === null ? null : spec.sameRoot ?? true,
  },
});

const round = (value) => Math.round(value * 10000) / 10000;

const QUEUE = [
  candidate({
    domain: "lumenstack.dev",
    name: "Lumenstack",
    description:
      "面向数据团队的 AI 语义层，把数仓表结构自动编译成可查询的指标接口。",
    quotes: [
      "Lumenstack compiles your warehouse schema into a governed semantic layer — ask questions in plain English, get audited SQL back.",
      "Start free with 3 seats. Usage-based pricing after that.",
      "Trusted by data teams at 40+ Series A companies",
    ],
    quoteTypes: ["title", "pricing", "visible_text"],
    links: ["https://lumenstack.dev/docs", "https://lumenstack.dev/pricing"],
    age: 2,
    seenHours: 3,
    http: 200,
    inputs: [0.95, 0.9, 0.85, 0.9],
    confidence: 0.88,
  }),
  candidate({
    domain: "orbitrag.ai",
    name: "OrbitRAG",
    description: "为法律团队做的检索增强问答引擎，支持合同条款级引用。",
    quotes: [
      "OrbitRAG answers contract questions with clause-level citations you can verify in one click.",
      "SOC 2 Type II in progress",
    ],
    quoteTypes: ["meta_description", "visible_text"],
    links: ["https://orbitrag.ai/security"],
    age: 6,
    seenHours: 11,
    http: 200,
    inputs: [0.9, 0.85, 0.7, 0.85],
    confidence: 0.81,
  }),
  candidate({
    domain: "fernwork.io",
    name: "Fernwork",
    description: "把 Figma 设计稿转成可维护的 React 组件库，带视觉回归测试。",
    quotes: [
      "Turn Figma frames into production React components — with visual regression tests wired in from the first commit.",
      "Ship design changes without a handoff meeting",
    ],
    quoteTypes: ["h1", "cta"],
    links: ["https://fernwork.io/changelog"],
    age: 14,
    seenHours: 26,
    http: 200,
    inputs: [0.8, 0.75, 0.55, 0.7],
    confidence: 0.69,
  }),
  candidate({
    domain: "quillpay.co",
    name: "Quillpay",
    description: "面向独立开发者的订阅计费 API，两行代码接入。",
    quotes: [
      "Subscriptions, invoicing, and tax handled behind a two-line API.",
      "No monthly minimum. 0.9% per transaction.",
    ],
    quoteTypes: ["title", "pricing"],
    age: 23,
    seenHours: 40,
    http: 200,
    inputs: [0.7, 0.7, 0.5, 0.65],
    confidence: 0.74,
  }),
  candidate({
    domain: "terravault.cloud",
    name: "Terravault",
    description: null,
    quotes: [
      "Terravault — encrypted object storage with per-tenant keys",
      "Beta access by request",
    ],
    quoteTypes: ["title", "cta"],
    age: 41,
    seenHours: 62,
    http: 403,
    inputs: [0.55, 0.45, 0.4, 0.45],
    confidence: 0.52,
    author: "rule",
  }),
  candidate({
    domain: "nimbusnotes.app",
    name: null,
    description: null,
    quotes: [],
    age: 55,
    seenHours: 80,
    http: 200,
    sameRoot: false,
    inputs: [0.35, 0.3, 0.25, 0.3],
    confidence: 0.35,
    author: "rule",
  }),
  candidate({
    domain: "promptbasin.xyz",
    name: "Prompt Basin",
    description: "提示词分享目录，按模型和任务分类。",
    quotes: ["A community directory of prompts, sorted by model and task."],
    quoteTypes: ["title"],
    age: 12,
    seenHours: 30,
    http: 200,
    inputs: [0.2, 0.3, 0.2, 0.3],
    confidence: 0.61,
    outcome: "not_target",
  }),
  candidate({
    domain: "verdigris-labs.net",
    name: "Verdigris Labs",
    description: null,
    quotes: [],
    age: null,
    seenHours: 6,
    http: null,
    inputs: [0.2, 0.18, 0.15, 0.2],
    confidence: 0.4,
    author: "rule",
    outcome: "valid_but_not_ready",
  }),
  candidate({
    domain: "atlasrune.com",
    name: "Atlas Rune",
    description: "地理空间数据可视化平台，面向城市规划团队。",
    quotes: [
      "Atlas Rune turns parcel, transit, and zoning layers into shareable planning maps.",
      "Pilot programs available for municipal teams",
    ],
    quoteTypes: ["meta_description", "cta"],
    age: 87,
    seenHours: 120,
    http: 200,
    inputs: [0.15, 0.08, 0.25, 0.2],
    confidence: 0.66,
  }),
];

const DOMAIN_SNAPSHOTS = [
  ...QUEUE.map((item) => ({
    domain: item.domain,
    first_seen_at: item.newness.ct_first_seen_at,
    observed_at: item.newness.checked_at,
    outcome_code: item.reachability.http_status_code ? "success" : "dns_timeout",
    attempt_number: 1,
    status_code: item.reachability.http_status_code,
    final_url: item.reachability.final_url,
    detail: null,
  })),
  { domain: "quietloop.dev", first_seen_at: iso(9 * HOUR), observed_at: iso(9 * HOUR), outcome_code: "content_insufficient", attempt_number: 1, status_code: 200, final_url: "https://quietloop.dev/", detail: null },
  { domain: "zz-9042.biz", first_seen_at: iso(20 * HOUR), observed_at: iso(20 * HOUR), outcome_code: "dns_not_found", attempt_number: 2, status_code: null, final_url: null, detail: null },
  { domain: "marblerow.co", first_seen_at: iso(31 * HOUR), observed_at: iso(31 * HOUR), outcome_code: "tls_error", attempt_number: 1, status_code: null, final_url: null, detail: null },
];

const COUNTS = {
  source_events: 184_932,
  domains: 12_408,
  observations: 9_731,
  candidates: 214,
  candidate_versions: 260,
  review_queue: QUEUE.length,
};

const LOG_LINES = [
  "2026-10-14 10:41:02 INFO ai_tools_hunter.ingest.runner sweep start cursor=8412993144",
  "2026-10-14 10:41:03 INFO ai_tools_hunter.ingest.ct_log_adapter page entries=500 log=nimbus2026",
  "2026-10-14 10:41:07 INFO ai_tools_hunter.filter.pipeline strict reject=418 tier=stale",
  "2026-10-14 10:41:07 INFO ai_tools_hunter.filter.pipeline dns pass=31 fail=12",
  "2026-10-14 10:41:12 INFO ai_tools_hunter.crawler.http_probe probe=16 ok=9 status_4xx=3 timeout=4",
  "2026-10-14 10:41:14 INFO ai_tools_hunter.pipeline candidates_created=2",
  "2026-10-14 10:41:15 INFO ai_tools_hunter.ingest.runner sweep done next_cursor=8412993871 idle=15s",
];

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json; charset=utf-8",
  ".woff2": "font/woff2",
  ".ico": "image/x-icon",
};

const json = (response, body, status = 200) => {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "Content-Length": Buffer.byteLength(payload),
  });
  response.end(payload);
};

const server = createServer(async (request, response) => {
  const url = new URL(request.url, `http://${request.headers.host}`);

  if (request.method === "POST") {
    // Mutations are acknowledged so the console's flows stay exercisable.
    const match = url.pathname.match(/^\/v1\/candidates\/([^/]+)\/versions\/(\d+)\/decisions/);
    if (match) return json(response, { created: true, decision_id: "preview" }, 201);
    if (url.pathname === "/v1/run/discovery") {
      return json(response, {
        status: "completed",
        next_cursor: "8412993871",
        certificates_seen: 500,
        events_added: 412,
        roots_observed: 318,
        strict_rejections: 418,
        probes_run: 16,
        candidates_created: 2,
        source_errors: [],
        pending_work: 0,
      });
    }
  }

  // `DH_EMPTY=1` rehearses the first-run state — a fresh database has no
  // candidates yet, and that empty queue is the very first screen an operator
  // sees, so it needs to be reviewable without seeding anything.
  if (url.pathname === "/v1/review-queue") {
    return json(response, { items: EMPTY ? [] : QUEUE });
  }

  const contextMatch = url.pathname.match(/^\/v1\/candidates\/([^/]+)\/review-context$/);
  if (contextMatch) {
    const found = QUEUE.find((item) => item.candidate_id === contextMatch[1]);
    if (!found) return json(response, { detail: "candidate not found" }, 404);
    return json(response, {
      ...found,
      audit: {
        decisions:
          found.domain === "fernwork.io"
            ? [
                {
                  decision_id: "d_preview",
                  action: "defer",
                  actor_id: "lin",
                  decided_at: iso(5 * HOUR),
                  reason_tags: ["insufficient_evidence"],
                  revoked: false,
                },
              ]
            : [],
      },
    });
  }

  if (url.pathname === "/v1/discovery/overview") {
    return json(response, {
      cursor: EMPTY ? null : "8412993871",
      domains: EMPTY ? [] : DOMAIN_SNAPSHOTS,
      counts: EMPTY ? { ...COUNTS, candidates: 0, candidate_versions: 0, review_queue: 0 } : COUNTS,
    });
  }

  if (url.pathname === "/v1/discovery/log") {
    return json(response, { exists: true, lines: LOG_LINES });
  }

  if (url.pathname === "/healthz") return json(response, { ok: true });

  // Static bundle, with SPA fallback so /review/{id} survives a reload.
  const relative = url.pathname === "/" ? "/index.html" : url.pathname;
  const target = normalize(join(STATIC, relative));
  if (!target.startsWith(STATIC)) {
    response.writeHead(403).end("Forbidden");
    return;
  }

  try {
    const info = await stat(target);
    if (info.isDirectory()) throw new Error("directory");
    const body = await readFile(target);
    response.writeHead(200, {
      "Content-Type": MIME[extname(target)] ?? "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(body);
  } catch {
    try {
      const body = await readFile(join(STATIC, "index.html"));
      response.writeHead(200, { "Content-Type": MIME[".html"], "Cache-Control": "no-store" });
      response.end(body);
    } catch {
      response.writeHead(404).end("Not found");
    }
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`AI-Tools-Hunter design preview → http://127.0.0.1:${PORT}`);
});
