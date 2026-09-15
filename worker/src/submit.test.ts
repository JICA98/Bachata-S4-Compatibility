import {afterEach, describe, expect, it} from "vitest";
import worker from "./index";

const WEBP = new Uint8Array([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50]);
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);

async function gzip(text: string): Promise<Uint8Array> {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function performanceLog(): string {
  return Array.from({length: 6}, (_, i) =>
    `[t] [App.Performance] <Info> elapsedMs=${12000 + i * 2000} sourceFps=30.00 outputFps=30.00 frameTimeMs=33.33 fg=off`,
  ).join("\n");
}

function envelope(overrides: Record<string, unknown> = {}) {
  return {
    game: {title: "Bloodborne", region: "Unknown", publisher: "FromSoftware"},
    report: {
      schemaVersion: 2,
      reportId: "client-pending",
      cusaId: "CUSA00900",
      testedAt: "2026-09-15T05:38:01.455Z",
      status: "ingame",
      release: {tag: "unreleased", commit: "28d2a1628"},
      device: {
        manufacturer: "OnePlus", model: "OPD2403", socId: "sm8650", socName: "Snapdragon 8 Gen 3",
        gpu: "Adreno 750", androidVersion: "16", ramBucketGb: 12,
      },
      driver: {type: "turnip", name: "Turnip", version: "26.1"},
      config: {
        settings: {"gpu.dump_shaders": false},
        requiredOverrides: {},
        driverId: "turnip-x",
        guestBackend: "FEX",
        frameGenerationMode: "OFF",
        fexPreset: "DEFAULT",
      },
      result: {summary: "Reached Hunter's Dream", notes: "", issues: []},
      contributor: {publicId: "tester-cc929a063ee6"},
      provenance: {captureType: "app-captured", appBuild: "0.2.1"},
      performance: {nativeAverageFps: 99, testDurationSeconds: 1, framePacing: "smooth"},
      ...overrides,
    },
  };
}

const images = {
  async info() {
    return {width: 1280, height: 720, format: "image/jpeg"};
  },
  input() {
    return {
      transform() {
        return {
          async output() {
            return {response: () => new Response(WEBP, {headers: {"content-type": "image/webp"}})};
          },
        };
      },
    };
  },
};

function env() {
  const store = new Map<string, string>();
  return {
    GITHUB_TOKEN: "token",
    GITHUB_ISSUE_TOKEN: "issue-token",
    GITHUB_OWNER: "JICA98",
    GITHUB_REPO: "Bachata-S4-Compatibility",
    GITHUB_BASE_BRANCH: "feat/community-compatibility-v2",
    IMAGES: images,
    RATE_LIMIT: {
      async get(key: string) {
        return store.get(key) ?? null;
      },
      async put(key: string, value: string) {
        store.set(key, value);
      },
    },
  };
}

let blobBodies: string[] = [];
let githubCalls: Array<{url: string; method: string}> = [];

function installGithubMock(options: {gameExists?: boolean} = {}) {
  blobBodies = [];
  githubCalls = [];
  const gameExists = options.gameExists ?? true;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    githubCalls.push({url, method});
    if (url.includes("/git/ref/heads/")) return Response.json({object: {sha: "basecommit"}});
    if (url.includes("/git/commits/basecommit")) return Response.json({sha: "basecommit", tree: {sha: "basetree"}});
    if (url.includes("/contents/games/") && method === "GET") {
      return gameExists ? Response.json({sha: "game"}) : new Response("missing", {status: 404});
    }
    if (url.includes("/git/refs") && method === "POST") return new Response("{}", {status: 201});
    if (url.includes("/git/blobs") && method === "POST") {
      blobBodies.push(String(init?.body || ""));
      return Response.json({sha: `blob${blobBodies.length}`});
    }
    if (url.includes("/git/trees")) return Response.json({sha: "tree1"});
    if (url.includes("/git/commits") && method === "POST") return Response.json({sha: "commit1"});
    if (url.includes("/git/refs/heads/") && method === "PATCH") return Response.json({});
    if (url.endsWith("/pulls") && method === "POST") {
      return Response.json({number: 20, html_url: "https://github.com/JICA98/Bachata-S4-Compatibility/pull/20"});
    }
    return new Response("unhandled " + url, {status: 500});
  }) as typeof fetch;
}

afterEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (globalThis as any).fetch;
});

async function post(form: FormData, testEnv = env()) {
  return worker.fetch(new Request("https://example.com/api/compat/v2/reports", {method: "POST", body: form}), testEnv as never);
}

describe("multipart submit", () => {
  it("rejects JSON bodies", async () => {
    const response = await worker.fetch(new Request("https://example.com/api/compat/v2/reports", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify(envelope()),
    }), env() as never);
    expect(response.status).toBe(415);
  });

  it("commits screenshots, logs, stamped paths, and parsed performance", async () => {
    installGithubMock();
    const form = new FormData();
    form.set("envelope", JSON.stringify(envelope()));
    form.append("screenshot", new Blob([JPEG]), "01.jpg");
    form.set("screenshot-caption-0", "Hunter's Dream");
    form.set("log-application", new Blob([await gzip(performanceLog())]), "01-application.log.gz");
    form.set("log-shadps4", new Blob([await gzip("shadps4 ok\n")]), "02-shadps4.log.gz");
    const response = await post(form);
    expect(response.status).toBe(202);
    const body = await response.json() as {ok: boolean; pullRequest: number};
    expect(body.ok).toBe(true);
    expect(body.pullRequest).toBe(20);
    expect(githubCalls.some(call => call.url.includes("/git/trees"))).toBe(true);
    expect(githubCalls.filter(call => call.url.includes("/pulls")).some(call => call.method === "POST")).toBe(true);
    const reportBlob = blobBodies.map(raw => JSON.parse(raw) as {content: string; encoding: string})
      .map(entry => {
        const decoded = atob(entry.content);
        if (!decoded.startsWith("{")) return undefined;
        return JSON.parse(decoded) as Record<string, unknown>;
      })
      .find(parsed => parsed?.schemaVersion === 2);
    expect(reportBlob).toBeTruthy();
    const evidence = reportBlob!.evidence as {screenshots: Array<{path: string}>; diagnostics: Array<{label: string}>};
    expect(evidence.screenshots[0].path).toMatch(/^assets\/CUSA00900\/.+\/screenshots\/01\.webp$/);
    expect(evidence.diagnostics.some(item => item.label === "Bachata application log")).toBe(true);
    const performance = reportBlob!.performance as {nativeAverageFps: number};
    expect(performance.nativeAverageFps).toBe(30);
    expect(reportBlob!.performance).not.toMatchObject({nativeAverageFps: 99});
    const pr = githubCalls.find(call => call.url.endsWith("/pulls"));
    expect(pr).toBeTruthy();
  });

  it("rejects client-supplied evidence", async () => {
    installGithubMock();
    const form = new FormData();
    form.set("envelope", JSON.stringify(envelope({evidence: {screenshots: []}})));
    form.append("screenshot", new Blob([JPEG]), "01.jpg");
    form.set("screenshot-caption-0", "shot");
    form.set("log-application", new Blob([await gzip(performanceLog())]), "app.log.gz");
    const response = await post(form);
    expect(response.status).toBe(400);
    expect(githubCalls.some(call => call.url.includes("/git/refs"))).toBe(false);
  });

  it("requires a screenshot", async () => {
    installGithubMock();
    const form = new FormData();
    form.set("envelope", JSON.stringify(envelope()));
    form.set("log-application", new Blob([await gzip(performanceLog())]), "app.log.gz");
    const response = await post(form);
    const body = await response.json() as {error: string};
    expect(response.status).toBe(400);
    expect(body.error).toBe("evidence_required");
    expect(githubCalls.some(call => call.url.includes("/git/refs"))).toBe(false);
  });

  it("rejects private paths in logs", async () => {
    installGithubMock();
    const form = new FormData();
    form.set("envelope", JSON.stringify(envelope()));
    form.append("screenshot", new Blob([JPEG]), "01.jpg");
    form.set("screenshot-caption-0", "shot");
    form.set("log-application", new Blob([await gzip("path /data/user/0/com.bachatas4.android\n")]), "app.log.gz");
    const response = await post(form);
    expect(response.status).toBe(400);
    expect(githubCalls.some(call => call.url.includes("/git/refs"))).toBe(false);
  });

  it("rejects SVG screenshots", async () => {
    installGithubMock();
    const svgImages = {
      async info() {
        throw new Error("unsupported");
      },
      input() {
        return images.input();
      },
    };
    const form = new FormData();
    form.set("envelope", JSON.stringify(envelope()));
    form.append("screenshot", new Blob([new Uint8Array([0x3c, 0x73, 0x76, 0x67])]), "x.svg");
    form.set("screenshot-caption-0", "shot");
    form.set("log-application", new Blob([await gzip(performanceLog())]), "app.log.gz");
    const response = await post(form, {...env(), IMAGES: svgImages});
    expect(response.status).toBe(400);
    expect(githubCalls.some(call => call.url.includes("/git/refs"))).toBe(false);
  });
});
