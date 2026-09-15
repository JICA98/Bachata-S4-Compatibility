import {duplicateFingerprint, isDuplicate, markAccepted} from "./duplicate";
import {reencodeScreenshot, sanitizeLogGzip, sha256Hex, type ImagesBinding} from "./evidence";
import {commitFiles} from "./github-git";
import {parsePerformanceFromLog} from "./performance";
import {PRIVATE_PATTERN} from "./privacy";

interface Env {
  GITHUB_TOKEN: string;
  GITHUB_ISSUE_TOKEN: string;
  GITHUB_OWNER: string;
  GITHUB_REPO: string;
  GITHUB_BASE_BRANCH: string;
  RATE_LIMIT?: KVNamespace;
  IMAGES?: ImagesBinding;
}

type JsonObject = Record<string, unknown>;

const MAX_ENVELOPE_BYTES = 96 * 1024;
const MAX_MULTIPART_BYTES = 8 * 1024 * 1024;
const REPORT_PATH = /^CUSA\d{5}$/;
const SOC_ID = /^[a-z0-9._-]{2,80}$/;
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
      ...(driver.source ? {source: text(driver.source, 160)} : {}),
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
    result: {summary: text(result.summary, 1000, true), notes: text(result.notes, 6000), issues},
    contributor: {publicId, ...(contributor.displayName ? {displayName: text(contributor.displayName, 80)} : {})},
    provenance: {captureType, ...(provenance.appBuild ? {appBuild: text(provenance.appBuild, 120)} : {})},
  };
}

async function github(env: Env, path: string, init: RequestInit = {}, token = env.GITHUB_TOKEN): Promise<Response> {
  if (!token) throw new Error("GitHub token is not configured");
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
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
  const search = await github(
    env,
    `/search/issues?q=${encodeURIComponent(`repo:${env.GITHUB_OWNER}/${issueRepo} is:issue in:title \"${cusaId}\"`)}`,
    {},
    env.GITHUB_ISSUE_TOKEN,
  );
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
  }, env.GITHUB_ISSUE_TOKEN);
  if (!created.ok) throw new Error(`Could not create canonical issue (${created.status})`);
  return ((await created.json()) as {number:number}).number;
}

async function readPart(value: unknown): Promise<Uint8Array | undefined> {
  if (value == null || typeof value === "string") return undefined;
  if (typeof value === "object" && "arrayBuffer" in value && typeof value.arrayBuffer === "function") {
    return new Uint8Array(await value.arrayBuffer());
  }
  return undefined;
}

async function gunzipText(bytes: Uint8Array): Promise<string> {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}

async function submit(request: Request, env: Env): Promise<Response> {
  if (!env.GITHUB_TOKEN || !env.GITHUB_ISSUE_TOKEN) {
    throw new Error("GitHub tokens are not configured");
  }
  if (!env.IMAGES) throw new Error("Images binding is not configured");
  const length = Number(request.headers.get("content-length") || "0");
  if (length > MAX_MULTIPART_BYTES) return json({error: "payload_too_large"}, 413);
  await rateLimit(request, env);
  const form = await request.formData();
  const envelopePart = form.get("envelope");
  if (typeof envelopePart !== "string") throw new Error("Required text field is empty");
  if (envelopePart.length > MAX_ENVELOPE_BYTES) return json({error: "payload_too_large"}, 413);
  const envelope = JSON.parse(envelopePart) as JsonObject;
  const report = normalizeReport(envelope.report);
  const screenshots = form.getAll("screenshot").filter(value => typeof value !== "string");
  const applicationLog = await readPart(form.get("log-application"));
  if (screenshots.length < 1 || screenshots.length > 3 || !applicationLog) {
    const error = new Error("A screenshot and application log are required");
    (error as Error & {code?: string}).code = "evidence_required";
    throw error;
  }
  const captions = screenshots.map((_, index) => text(form.get(`screenshot-caption-${index}`), 300, true));
  const shotBytes: Array<{bytes: Uint8Array; sha: string; caption: string}> = [];
  for (const [index, file] of screenshots.entries()) {
    const encoded = await reencodeScreenshot(env.IMAGES, new Uint8Array(await file.arrayBuffer()));
    shotBytes.push({bytes: encoded, sha: await sha256Hex(encoded), caption: captions[index]});
  }
  const logs: Array<{slug: string; label: string; bytes: Uint8Array; sha: string; text?: string}> = [];
  const appGzip = await sanitizeLogGzip(applicationLog);
  logs.push({
    slug: "application",
    label: "Bachata application log",
    bytes: appGzip,
    sha: await sha256Hex(appGzip),
    text: await gunzipText(appGzip),
  });
  const shad = await readPart(form.get("log-shadps4"));
  if (shad) {
    const gzipped = await sanitizeLogGzip(shad);
    logs.push({slug: "shadps4", label: "shadPS4 session log", bytes: gzipped, sha: await sha256Hex(gzipped)});
  }
  const internal = await readPart(form.get("log-shadps4-internal"));
  if (internal) {
    const gzipped = await sanitizeLogGzip(internal);
    logs.push({slug: "shadps4-internal", label: "shadPS4 internal log", bytes: gzipped, sha: await sha256Hex(gzipped)});
  }
  const parsed = parsePerformanceFromLog(logs[0].text || "");
  if (parsed) report.performance = parsed;
  else delete report.performance;

  const evidenceHashes = [...shotBytes.map(item => item.sha), ...logs.map(item => item.sha)];
  const fingerprint = await duplicateFingerprint(report, evidenceHashes);
  if (await isDuplicate(env.RATE_LIMIT, fingerprint)) {
    return json({error: "duplicate_submission", message: "An identical compatibility result was already accepted recently."}, 409);
  }
  const gameMetadata = isObject(envelope.game) ? envelope.game : {};
  const cusaId = String(report.cusaId);
  const now = new Date();
  const random = crypto.randomUUID().replace(/-/g, "").slice(0, 10);
  const reportId = `${now.toISOString().replace(/[-:.]/g, "").replace("Z", "Z")}-${cusaId.toLowerCase()}-${random}`;
  report.reportId = reportId;
  report.evidence = {
    screenshots: shotBytes.map((shot, index) => ({
      path: `assets/${cusaId}/${reportId}/screenshots/${String(index + 1).padStart(2, "0")}.webp`,
      sha256: shot.sha,
      caption: shot.caption,
    })),
    diagnostics: logs.map((log, index) => ({
      path: `assets/${cusaId}/${reportId}/logs/${String(index + 1).padStart(2, "0")}-${log.slug}.log.gz`,
      sha256: log.sha,
      label: log.label,
    })),
  };

  const repoBase = `/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}`;
  const baseRef = await github(env, `${repoBase}/git/ref/heads/${encodeURIComponent(env.GITHUB_BASE_BRANCH)}`);
  if (!baseRef.ok) throw new Error(`Could not resolve base branch (${baseRef.status})`);
  const baseData = await baseRef.json() as {object:{sha:string}};
  const commitInfo = await github(env, `${repoBase}/git/commits/${baseData.object.sha}`);
  if (!commitInfo.ok) throw new Error(`Could not resolve base commit (${commitInfo.status})`);
  const baseCommit = await commitInfo.json() as {sha: string; tree: {sha: string}};
  const branch = `community/${cusaId.toLowerCase()}/${reportId}`;
  const createRef = await github(env, `${repoBase}/git/refs`, {
    method: "POST",
    body: JSON.stringify({ref: `refs/heads/${branch}`, sha: baseData.object.sha}),
  });
  if (!createRef.ok) throw new Error(`Could not create moderation branch (${createRef.status})`);

  const files: Array<{path: string; content: Uint8Array}> = [];
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
    files.push({path: gamePath, content: new TextEncoder().encode(JSON.stringify(game, null, 2) + "\n")});
  } else if (!existingGame.ok) {
    throw new Error(`Could not verify game metadata (${existingGame.status})`);
  }

  for (const [index, shot] of shotBytes.entries()) {
    files.push({
      path: `assets/${cusaId}/${reportId}/screenshots/${String(index + 1).padStart(2, "0")}.webp`,
      content: shot.bytes,
    });
  }
  for (const [index, log] of logs.entries()) {
    files.push({
      path: `assets/${cusaId}/${reportId}/logs/${String(index + 1).padStart(2, "0")}-${log.slug}.log.gz`,
      content: log.bytes,
    });
  }
  files.push({
    path: `games/${cusaId}/reports/${reportId}.json`,
    content: new TextEncoder().encode(JSON.stringify(report, null, 2) + "\n"),
  });

  await commitFiles((path, init) => github(env, path, init), {
    owner: env.GITHUB_OWNER,
    repo: env.GITHUB_REPO,
    branch,
    baseCommitSha: baseCommit.sha,
    baseTreeSha: baseCommit.tree.sha,
    message: `compat(${cusaId}): submit community report`,
    files,
  });

  const pr = await github(env, `${repoBase}/pulls`, {
    method: "POST",
    body: JSON.stringify({
      title: `compat(${cusaId}): community report ${reportId}`,
      head: branch,
      base: env.GITHUB_BASE_BRANCH,
      draft: true,
      body: `Community compatibility report submitted through the Bachata S4 app.\n\n- CUSA: ${cusaId}\n- Status: ${report.status}\n- Release: ${(report.release as JsonObject).tag}\n- SoC: ${(report.device as JsonObject).socName}\n- Contributor: ${(report.contributor as JsonObject).publicId}\n- Screenshots: ${shotBytes.length}\n- Logs: ${logs.map(item => item.label).join(", ")}\n`,
    }),
  });
  if (!pr.ok) throw new Error(`Could not open moderation PR (${pr.status})`);
  const prData = await pr.json() as {number:number; html_url:string};
  await markAccepted(env.RATE_LIMIT, fingerprint);
  return json({ok: true, submissionId: reportId, pullRequest: prData.number, moderationUrl: prData.html_url}, 202);
}

const REPORT_PATHS = new Set([
  "/v2/reports",
  "/compat/v2/reports",
  "/api/compat/v2/reports",
]);

const HEALTH_PATHS = new Set([
  "/health",
  "/v2/health",
  "/compat/v2/health",
  "/api/compat/v2/health",
]);

const STUB_SOCS: Record<string, {name: string; vendor: string; gpu: string; family: string; aliases: string[]}> = {
  sm7475: {name: "Snapdragon 7+ Gen 2", vendor: "Qualcomm", gpu: "Adreno 725", family: "adreno-7xx", aliases: ["SM7475", "Snapdragon 7+ Gen 2"]},
  sm8550: {name: "Snapdragon 8 Gen 2", vendor: "Qualcomm", gpu: "Adreno 740", family: "adreno-7xx", aliases: ["SM8550", "Snapdragon 8 Gen 2"]},
  sm8650: {name: "Snapdragon 8 Gen 3", vendor: "Qualcomm", gpu: "Adreno 750", family: "adreno-8xx", aliases: ["SM8650", "Snapdragon 8 Gen 3"]},
  sm8750: {name: "Snapdragon 8 Elite", vendor: "Qualcomm", gpu: "Adreno 830", family: "adreno-8xx", aliases: ["SM8750", "Snapdragon 8 Elite"]},
  sm8850: {name: "Snapdragon 8 Elite Gen 5", vendor: "Qualcomm", gpu: "Adreno 840", family: "adreno-8xx", aliases: ["SM8850", "Snapdragon 8 Elite Gen 5"]},
};

function stubFeed(pathname: string): Response | null {
  if (pathname === "/data/compat/v2/socs.json") {
    return json({schemaVersion: 1, socs: STUB_SOCS});
  }
  if (pathname === "/data/compat/v2/index.json") {
    return json({schemaVersion: 2, generatedForRelease: "worker-stub", games: []});
  }
  const game = pathname.match(/^\/data\/compat\/v2\/games\/(CUSA\d{5})\.json$/);
  if (!game) return null;
  const cusaId = game[1];
  return json({
    schemaVersion: 2,
    generatedForRelease: "worker-stub",
    game: {cusaId, title: cusaId, region: "", publisher: ""},
    general: {status: "unknown", confidence: "none", reportCount: 0, hasCurrentReports: false},
    socs: {},
    families: {},
    reports: [],
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && HEALTH_PATHS.has(url.pathname)) {
      return json({ok: true, service: "bachata-compatibility-submit-v2"});
    }
    if (request.method === "GET") {
      const feed = stubFeed(url.pathname);
      if (feed) return feed;
    }
    if (request.method !== "POST" || !REPORT_PATHS.has(url.pathname)) return json({error: "not_found"}, 404);
    if (!request.headers.get("content-type")?.toLowerCase().includes("multipart/form-data")) {
      return json({error: "content_type_must_be_multipart"}, 415);
    }
    try {
      return await submit(request, env);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Submission failed";
      const coded = (error as Error & {code?: string}).code;
      if (coded === "evidence_required") return json({error: "evidence_required", message}, 400);
      const clientError = /Invalid|Expected|Required|private|Unsafe|Too many|Unsupported|not enabled|limit|screenshot|Images binding/i.test(message);
      return json({error: clientError ? "invalid_submission" : "submission_failed", message}, clientError ? 400 : 502);
    }
  },
};
