interface Env {
  GITHUB_TOKEN: string;
  GITHUB_OWNER: string;
  GITHUB_REPO: string;
  GITHUB_BASE_BRANCH: string;
  RATE_LIMIT?: KVNamespace;
}

type JsonObject = Record<string, unknown>;

const MAX_BODY_BYTES = 96 * 1024;
const REPORT_PATH = /^CUSA\d{5}$/;
const REPORT_ID = /^[A-Za-z0-9._-]{8,160}$/;
const SOC_ID = /^[a-z0-9._-]{2,80}$/;
const PRIVATE_PATTERN = /(content:\/\/|file:\/\/|\/storage\/emulated\/|\/data\/user\/|\/sdcard\/|ro\.serialno|android[_ -]?id|adb[_ -]?serial|mac[_ -]?address|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,})/i;
const STATUS = new Set(["playable", "ingame", "menus", "boots", "nothing"]);
const CAPTURE = new Set(["app-captured", "structured-manual", "maintainer-verified", "legacy-imported"]);
const DRIVER_TYPE = new Set(["system", "turnip", "custom"]);

function json(data: unknown, status = 200, extra: HeadersInit = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {"content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra},
  });
}

function isObject(value: unknown): value is JsonObject {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown, max: number, required = false): string {
  if (value == null && !required) return "";
  if (typeof value !== "string") throw new Error("Expected text field");
  const cleaned = value.trim();
  if (required && !cleaned) throw new Error("Required text field is empty");
  if (cleaned.length > max) throw new Error(`Text field exceeds ${max} characters`);
  if (PRIVATE_PATTERN.test(cleaned)) throw new Error("Submission contains a private identifier or local path");
  return cleaned;
}

function safeScalarMap(value: unknown): Record<string, boolean | number | string> {
  if (!isObject(value)) return {};
  if (Object.keys(value).length > 128) throw new Error("Too many configuration fields");
  const result: Record<string, boolean | number | string> = {};
  for (const [key, raw] of Object.entries(value)) {
    if (!/^[A-Za-z0-9._-]{2,120}$/.test(key)) throw new Error(`Unsafe setting id: ${key}`);
    if (typeof raw !== "boolean" && typeof raw !== "number" && typeof raw !== "string") {
      throw new Error(`Unsupported public setting value: ${key}`);
    }
    if (typeof raw === "string" && PRIVATE_PATTERN.test(raw)) throw new Error(`Private value rejected: ${key}`);
    result[key] = raw;
  }
  return result;
}

function scanUnknown(value: unknown, depth = 0): void {
  if (depth > 8) throw new Error("Submission is too deeply nested");
  if (typeof value === "string") {
    if (PRIVATE_PATTERN.test(value)) throw new Error("Submission contains a private identifier or local path");
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > 64) throw new Error("Submission array is too large");
    value.forEach(v => scanUnknown(v, depth + 1));
    return;
  }
  if (isObject(value)) Object.values(value).forEach(v => scanUnknown(v, depth + 1));
}

function normalizeReport(input: unknown): JsonObject {
  if (!isObject(input)) throw new Error("report must be an object");
  scanUnknown(input);
  if (input.schemaVersion !== 2) throw new Error("schemaVersion must be 2");
  const cusaId = text(input.cusaId, 10, true).toUpperCase();
  if (!REPORT_PATH.test(cusaId)) throw new Error("Invalid CUSA id");
  const status = text(input.status, 20, true).toLowerCase();
  if (!STATUS.has(status)) throw new Error("Invalid compatibility status");

  const release = isObject(input.release) ? input.release : {};
  const device = isObject(input.device) ? input.device : {};
  const driver = isObject(input.driver) ? input.driver : {};
  const config = isObject(input.config) ? input.config : {};
  const result = isObject(input.result) ? input.result : {};
  const contributor = isObject(input.contributor) ? input.contributor : {};
  const provenance = isObject(input.provenance) ? input.provenance : {};

  const captureType = text(provenance.captureType, 40, true);
  if (!CAPTURE.has(captureType)) throw new Error("Invalid provenance captureType");
  const driverType = text(driver.type, 20, true);
  if (!DRIVER_TYPE.has(driverType)) throw new Error("Invalid driver type");
  const socId = text(device.socId, 80, true).toLowerCase();
  if (!SOC_ID.test(socId)) throw new Error("Invalid canonical SoC id");

  const ram = Number(device.ramBucketGb);
  if (!Number.isInteger(ram) || ram < 1 || ram > 64) throw new Error("Invalid RAM bucket");
  const testedAt = text(input.testedAt, 40, true);
  if (Number.isNaN(Date.parse(testedAt))) throw new Error("Invalid testedAt timestamp");
  const commit = text(release.commit, 40, true);
  if (!/^[0-9a-fA-F]{7,40}$/.test(commit)) throw new Error("Invalid release commit");
  const publicId = text(contributor.publicId, 80, true);
  if (!/^[A-Za-z0-9._-]{4,80}$/.test(publicId)) throw new Error("Invalid contributor public id");

  const issues = Array.isArray(result.issues)
    ? result.issues.slice(0, 32).map(v => text(v, 80, true).toLowerCase()).filter(v => /^[a-z0-9._-]{2,80}$/.test(v))
    : [];
  const performance = isObject(input.performance) ? input.performance : undefined;
  const normalizedPerformance = performance ? {
    ...(typeof performance.nativeAverageFps === "number" ? {nativeAverageFps: Math.max(0, Math.min(240, performance.nativeAverageFps))} : {}),
    ...(typeof performance.nativeOnePercentLowFps === "number" ? {nativeOnePercentLowFps: Math.max(0, Math.min(240, performance.nativeOnePercentLowFps))} : {}),
    ...(typeof performance.outputAverageFps === "number" ? {outputAverageFps: Math.max(0, Math.min(480, performance.outputAverageFps))} : {}),
    ...(Number.isInteger(performance.testDurationSeconds) ? {testDurationSeconds: Math.max(1, Math.min(86400, Number(performance.testDurationSeconds)))} : {}),
    ...(typeof performance.framePacing === "string" ? {framePacing: text(performance.framePacing, 40)} : {}),
  } : undefined;

  // Evidence is intentionally not accepted from arbitrary client URLs. The v2 schema permits
  // evidence, but the public ingestion endpoint only publishes structured reports until a
  // separately sanitized object-storage upload path is enabled.
  if (input.evidence != null) throw new Error("Direct evidence submission is not enabled; submit structured compatibility data only");

  return {
    schemaVersion: 2,
    reportId: text(input.reportId, 160, false),
    cusaId,
    testedAt,
    status,
    ...(isObject(input.game) ? {game: {version: text(input.game.version, 40), region: text(input.game.region, 40)}} : {}),
    release: {tag: text(release.tag, 40, true), commit, ...(release.runtimeRevision ? {runtimeRevision: text(release.runtimeRevision, 120)} : {})},
    device: {
      manufacturer: text(device.manufacturer, 80, true), model: text(device.model, 120, true), socId,
      socName: text(device.socName, 120, true), gpu: text(device.gpu, 120, true),
      androidVersion: text(device.androidVersion, 32, true), ramBucketGb: ram,
    },
    driver: {
      ...(driver.id ? {id: text(driver.id, 160)} : {}), type: driverType,
      name: text(driver.name, 160, true), version: text(driver.version, 120, true),
      ...(driver.build ? {build: text(driver.build, 160)} : {}),
    },
    config: {
      settings: safeScalarMap(config.settings),
      requiredOverrides: safeScalarMap(config.requiredOverrides),
      driverId: text(config.driverId, 160, true),
      guestBackend: "FEX",
      frameGenerationMode: text(config.frameGenerationMode, 40, true),
      fexPreset: text(config.fexPreset, 80, true),
      ...(typeof config.adrenoTurboMode === "boolean" ? {adrenoTurboMode: config.adrenoTurboMode} : {}),
      ...(typeof config.bigCoreAffinity === "boolean" ? {bigCoreAffinity: config.bigCoreAffinity} : {}),
      ...(typeof config.maliGpuOptimizations === "boolean" ? {maliGpuOptimizations: config.maliGpuOptimizations} : {}),
    },
    ...(Array.isArray(input.patches) ? {patches: input.patches.slice(0, 32).filter(isObject).map(p => ({id: text(p.id, 160, true), ...(p.preset ? {preset: text(p.preset, 160)} : {}), ...(p.revision ? {revision: text(p.revision, 120)} : {})}))} : {}),
    ...(normalizedPerformance ? {performance: normalizedPerformance} : {}),
    result: {summary: text(result.summary, 1000, true), notes: text(result.notes, 6000), issues},
    contributor: {publicId, ...(contributor.displayName ? {displayName: text(contributor.displayName, 80)} : {})},
    provenance: {captureType, ...(provenance.appBuild ? {appBuild: text(provenance.appBuild, 120)} : {})},
  };
}

async function github(env: Env, path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${env.GITHUB_TOKEN}`);
  headers.set("accept", "application/vnd.github+json");
  headers.set("x-github-api-version", "2022-11-28");
  headers.set("user-agent", "bachata-compatibility-submit-worker");
  if (init.body) headers.set("content-type", "application/json");
  return fetch(`https://api.github.com${path}`, {...init, headers});
}

async function rateLimit(request: Request, env: Env): Promise<void> {
  if (!env.RATE_LIMIT) return;
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const day = new Date().toISOString().slice(0, 10);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${day}:${ip}`));
  const key = `submit:${day}:${Array.from(new Uint8Array(digest)).slice(0, 12).map(v => v.toString(16).padStart(2, "0")).join("")}`;
  const count = Number(await env.RATE_LIMIT.get(key) || "0");
  if (count >= 12) throw new Error("Daily submission limit reached");
  await env.RATE_LIMIT.put(key, String(count + 1), {expirationTtl: 172800});
}

async function ensureCanonicalIssue(env: Env, cusaId: string, title: string): Promise<number> {
  const issueRepo = "Bachata-S4";
  const search = await github(env, `/search/issues?q=${encodeURIComponent(`repo:${env.GITHUB_OWNER}/${issueRepo} is:issue in:title \"${cusaId}\"`)}`);
  if (search.ok) {
    const data = await search.json() as {items?: Array<{number:number; title:string}>};
    const exact = data.items?.find(item => item.title.startsWith(`[${cusaId}]`));
    if (exact) return exact.number;
  }
  const created = await github(env, `/repos/${env.GITHUB_OWNER}/${issueRepo}/issues`, {
    method: "POST",
    body: JSON.stringify({
      title: `[${cusaId}] ${title}`,
      body: `Canonical community compatibility discussion for **${title}** (${cusaId}). Individual device/release results are reviewed as immutable compatibility reports.`,
      labels: ["type:compatibility", "triage:new"],
    }),
  });
  if (!created.ok) throw new Error(`Could not create canonical issue (${created.status})`);
  return ((await created.json()) as {number:number}).number;
}

async function submit(request: Request, env: Env): Promise<Response> {
  const length = Number(request.headers.get("content-length") || "0");
  if (length > MAX_BODY_BYTES) return json({error: "payload_too_large"}, 413);
  await rateLimit(request, env);
  const bodyText = await request.text();
  if (bodyText.length > MAX_BODY_BYTES) return json({error: "payload_too_large"}, 413);
  const envelope = JSON.parse(bodyText) as JsonObject;
  const report = normalizeReport(envelope.report);
  const gameMetadata = isObject(envelope.game) ? envelope.game : {};
  const cusaId = String(report.cusaId);
  const now = new Date();
  const random = crypto.randomUUID().replace(/-/g, "").slice(0, 10);
  const reportId = `${now.toISOString().replace(/[-:.]/g, "").replace("Z", "Z")}-${cusaId.toLowerCase()}-${random}`;
  report.reportId = reportId;

  const repoBase = `/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}`;
  const baseRef = await github(env, `${repoBase}/git/ref/heads/${encodeURIComponent(env.GITHUB_BASE_BRANCH)}`);
  if (!baseRef.ok) throw new Error(`Could not resolve base branch (${baseRef.status})`);
  const baseData = await baseRef.json() as {object:{sha:string}};
  const branch = `community/${cusaId.toLowerCase()}/${reportId}`;
  const createRef = await github(env, `${repoBase}/git/refs`, {
    method: "POST",
    body: JSON.stringify({ref: `refs/heads/${branch}`, sha: baseData.object.sha}),
  });
  if (!createRef.ok) throw new Error(`Could not create moderation branch (${createRef.status})`);

  // Ensure game metadata exists. New CUSAs also get one canonical public issue.
  const gamePath = `games/${cusaId}/game.json`;
  const existingGame = await github(env, `${repoBase}/contents/${gamePath}?ref=${encodeURIComponent(env.GITHUB_BASE_BRANCH)}`);
  if (existingGame.status === 404) {
    const title = text(gameMetadata.title, 200, true);
    const region = text(gameMetadata.region, 60, true);
    const publisher = text(gameMetadata.publisher, 200, true);
    const issueNumber = await ensureCanonicalIssue(env, cusaId, title);
    const game = {
      schemaVersion: 2, cusaId, title, region, publisher,
      canonicalIssue: {repository: `${env.GITHUB_OWNER}/Bachata-S4`, number: issueNumber},
      legacyIssues: [],
    };
    const createGame = await github(env, `${repoBase}/contents/${gamePath}`, {
      method: "PUT",
      body: JSON.stringify({message: `compat(${cusaId}): add game metadata`, branch, content: btoa(unescape(encodeURIComponent(JSON.stringify(game, null, 2) + "\n")))}),
    });
    if (!createGame.ok) throw new Error(`Could not create game metadata (${createGame.status})`);
  } else if (!existingGame.ok) {
    throw new Error(`Could not verify game metadata (${existingGame.status})`);
  }

  const reportPath = `games/${cusaId}/reports/${reportId}.json`;
  const createReport = await github(env, `${repoBase}/contents/${reportPath}`, {
    method: "PUT",
    body: JSON.stringify({
      message: `compat(${cusaId}): submit community report`, branch,
      content: btoa(unescape(encodeURIComponent(JSON.stringify(report, null, 2) + "\n"))),
    }),
  });
  if (!createReport.ok) throw new Error(`Could not stage report (${createReport.status})`);

  const pr = await github(env, `${repoBase}/pulls`, {
    method: "POST",
    body: JSON.stringify({
      title: `compat(${cusaId}): community report ${reportId}`,
      head: branch,
      base: env.GITHUB_BASE_BRANCH,
      draft: true,
      body: `Community compatibility report submitted through the Bachata S4 app.\n\n- CUSA: ${cusaId}\n- Status: ${report.status}\n- Release: ${(report.release as JsonObject).tag}\n- SoC: ${(report.device as JsonObject).socName}\n- Contributor: ${(report.contributor as JsonObject).publicId}\n\nStructured report only; no game files, firmware, keys, licenses, local paths, or raw logs are accepted by this endpoint.`,
    }),
  });
  if (!pr.ok) throw new Error(`Could not open moderation PR (${pr.status})`);
  const prData = await pr.json() as {number:number; html_url:string};
  return json({ok: true, submissionId: reportId, pullRequest: prData.number, moderationUrl: prData.html_url}, 202);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return json({ok: true, service: "bachata-compatibility-submit-v2"});
    if (request.method !== "POST" || url.pathname !== "/v2/reports") return json({error: "not_found"}, 404);
    if (!request.headers.get("content-type")?.toLowerCase().includes("application/json")) return json({error: "content_type_must_be_json"}, 415);
    try {
      return await submit(request, env);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Submission failed";
      const clientError = /Invalid|Expected|Required|private|Unsafe|Too many|Unsupported|not enabled|limit/i.test(message);
      return json({error: clientError ? "invalid_submission" : "submission_failed", message}, clientError ? 400 : 502);
    }
  },
};
