# Community Evidence Git Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make in-app community submits produce draft PRs with sanitized screenshots, redacted session logs, honest release identity, and FPS parsed from `application.log`.

**Architecture:** Android captures framebuffer shots and redacts logs, then multipart-POSTs to the Worker. The Worker re-encodes images via Cloudflare Images, scans/re-gzips logs, overwrites `performance` from log lines, and creates one Git Data API commit plus a draft PR on `feat/community-compatibility-v2`.

**Tech Stack:** Kotlin/Compose (Dev worktree), Cloudflare Worker TypeScript, GitHub Git Data API, Cloudflare Images binding, Python `validate_v2.py`, vitest for Worker unit tests.

**Worktrees:**
- Compat: `/home/jica/repo/.worktrees/community-compatibility-v2` branch `feat/community-compatibility-v2`
- Dev: `/home/jica/repo/Bachata-S4-Dev/.worktrees/community-compatibility-v2` branch `feat/community-compatibility-v2`

**Spec:** `docs/superpowers/specs/2026-09-15-community-evidence-git-design.md`

## Global Constraints

- App never holds GitHub credentials.
- Client must not send `report.evidence`; Worker stamps `path` + sha256 after git blobs exist.
- Screenshots are PixelCopy of the game `SurfaceView` only (no gallery, MediaProjection, or trophy shots).
- Git bytes for images are always Cloudflare Images WebP output (`fit: scale-down`, 1920, quality 80, `anim: false`).
- Logs: client redacts with `DiagnosticRedactor`, Worker gunzips, scans `PRIVATE_PATTERN`, re-gzips; never commit raw `.log`.
- Worker overwrites `performance` from uploaded `application.log`; client-supplied FPS is ignored.
- `release.tag` is a published tag only when HEAD is that tag; otherwise `unreleased`.
- `GITHUB_BASE_BRANCH` is `feat/community-compatibility-v2` until v2 validation is on `main`.
- Caps: envelope ≤ 96 KiB, multipart ≤ 8 MiB, each image ≤ 1.5 MiB, each gzip ≤ 1.5 MiB / 4 MiB uncompressed, 1–3 screenshots, 1–3 logs.
- Rate limit 12 accepted submits per hashed IP per UTC day.
- Do not merge draft PR #19; do not rewrite historical v1 reports.

## File structure

**Compat**
- `schemas/report-v2.schema.json` — `path` XOR `url` evidence; optional `driver.source`
- `scripts/validate_v2.py` — enforce evidence for `app-captured`
- `tests/test_community_v2.py` — schema/validator cases
- `worker/src/performance.ts` — parse Performance lines
- `worker/src/evidence.ts` — log gunzip/scan/gzip + Images re-encode
- `worker/src/github-git.ts` — Git Data API one-commit helper
- `worker/src/index.ts` — multipart submit
- `worker/src/duplicate.ts` — fingerprint includes evidence hashes
- `worker/wrangler.toml` — `[images]` + base branch
- `worker/README.md` — evidence now enabled under this contract
- `worker/package.json` — add vitest
- `worker/src/*.test.ts` — unit tests

**Dev**
- `core/runtime/.../FrameTelemetryReporter.kt` — `sourceFps`/`outputFps`/`fg` log line
- `core/compatibility/.../SessionPerformanceParser.kt` — same parse rules as Worker
- `core/compatibility/.../CompatibilityCaptureStore.kt` — FIFO 3 WebPs per CUSA
- `core/compatibility/.../CommunityReportBuilder.kt` — SFO, allowlist, patches, unreleased, driver source
- `core/compatibility/.../CompatibilitySubmission.kt` — multipart client
- `feature/session/.../SessionDrawer.kt` + `SessionScreen.kt` — save screenshot
- `feature/dashboard/.../CompatibilityViewModel.kt` + `CompatibilityScreen.kt` — evidence UI
- `feature/dashboard/build.gradle.kts` — `BACHATA_GIT_EXACT_TAG`

---

### Task 1: v2 schema and validator evidence paths

**Files:**
- Modify: `schemas/report-v2.schema.json` (driver + evidence)
- Modify: `scripts/validate_v2.py` (driver allowed keys; evidence path XOR url; app-captured required)
- Modify: `tests/test_community_v2.py`

**Interfaces:**
- Produces: `validate_report_v2` rejects `app-captured` without 1–3 screenshots and ≥1 application log; accepts `path` under `assets/<CUSA>/<reportId>/(screenshots|logs)/`

- [ ] **Step 1: Write the failing tests**

In `tests/test_community_v2.py`, add (keep existing `report()` helper; it stays valid for scoring tests that are not `app-captured` evidence checks):

```python
from validate_v2 import validate_report_v2

class EvidencePathTests(unittest.TestCase):
    def _app(self, **overrides) -> dict:
        value = report("20260915T053801455Z-cusa00900-6a87bfd509", capture="app-captured")
        value["evidence"] = {
            "screenshots": [{
                "path": "assets/CUSA00900/20260915T053801455Z-cusa00900-6a87bfd509/screenshots/01.webp",
                "sha256": "a" * 64,
                "caption": "Hunter's Dream",
            }],
            "diagnostics": [{
                "path": "assets/CUSA00900/20260915T053801455Z-cusa00900-6a87bfd509/logs/01-application.log.gz",
                "sha256": "b" * 64,
                "label": "Bachata application log",
            }],
        }
        value.update(overrides)
        return value

    def test_app_captured_path_evidence_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260915T053801455Z-cusa00900-6a87bfd509.json"
            path.write_text(json.dumps(self._app()), encoding="utf-8")
            self.assertEqual(validate_report_v2(path, json.loads(path.read_text()), "CUSA00900"), [])

    def test_app_captured_without_screenshots_fails(self) -> None:
        payload = self._app()
        payload["evidence"]["screenshots"] = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260915T053801455Z-cusa00900-6a87bfd509.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            errors = validate_report_v2(path, json.loads(path.read_text()), "CUSA00900")
            self.assertTrue(any("screenshot" in e for e in errors))

    def test_path_outside_assets_prefix_fails(self) -> None:
        payload = self._app()
        payload["evidence"]["screenshots"][0]["path"] = "games/CUSA00900/evil.webp"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260915T053801455Z-cusa00900-6a87bfd509.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            errors = validate_report_v2(path, json.loads(path.read_text()), "CUSA00900")
            self.assertTrue(any("path" in e for e in errors))

    def test_path_and_url_together_fail(self) -> None:
        payload = self._app()
        payload["evidence"]["screenshots"][0]["url"] = "https://example.com/x.webp"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20260915T053801455Z-cusa00900-6a87bfd509.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            errors = validate_report_v2(path, json.loads(path.read_text()), "CUSA00900")
            self.assertTrue(any("path" in e and "url" in e for e in errors))
```

Change `test_schema_is_closed_and_evidence_is_optional` name/body to still assert `evidence` is not in top-level `required` (withdrawn/legacy reports), and that screenshot items allow `path`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/jica/repo/.worktrees/community-compatibility-v2
python3 -m unittest tests.test_community_v2.EvidencePathTests -v
```

Expected: FAIL (`validate_report_v2` still requires `url`, does not require screenshots for `app-captured`).

- [ ] **Step 3: Update schema**

In `schemas/report-v2.schema.json`:

- Add `"source": {"type": "string", "maxLength": 160}` to `driver.properties`.
- Replace `evidence.properties.screenshots.items` and `diagnostics.items` with `oneOf` of path-form and url-form. Path pattern for screenshots: `^assets/CUSA[0-9]{5}/[A-Za-z0-9._-]+/screenshots/[A-Za-z0-9._-]+\\.webp$`. Diagnostics: `^assets/CUSA[0-9]{5}/[A-Za-z0-9._-]+/logs/[A-Za-z0-9._-]+\\.log\\.gz$`. Each form has `additionalProperties: false`. Path form required `["path","sha256"]`; url form required `["url","sha256"]`. Caption on screenshots, label on diagnostics, both optional max lengths as today.

- [ ] **Step 4: Update `validate_v2.py`**

In `closed_object` for driver, add `"source"` to allowed keys and `bounded_text(..., 160)`.

Replace the evidence block (current lines 237–257) with:

```python
ASSET_SHOT_RE = re.compile(r"^assets/(CUSA[0-9]{5})/([A-Za-z0-9._-]+)/screenshots/[A-Za-z0-9._-]+\.webp$")
ASSET_LOG_RE = re.compile(r"^assets/(CUSA[0-9]{5})/([A-Za-z0-9._-]+)/logs/[A-Za-z0-9._-]+\.log\.gz$")

def validate_evidence_entry(errors, report_path, label, item, kind, cusa, report_id):
    if not isinstance(item, dict):
        fail(errors, report_path, f"{label} must be an object")
        return
    has_path = "path" in item
    has_url = "url" in item
    extra = {"caption"} if kind == "screenshots" else {"label"}
    allowed = {"path", "url", "sha256"} | extra
    unknown = set(item) - allowed
    if unknown:
        fail(errors, report_path, f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    if has_path == has_url:
        fail(errors, report_path, f"{label} must contain exactly one of path or url")
        return
    digest = bounded_text(errors, report_path, f"{label}.sha256", item.get("sha256"), 64, True)
    if digest and not SHA256_RE.fullmatch(digest):
        fail(errors, report_path, f"{label}.sha256 must be lowercase SHA-256")
    if has_path:
        path = bounded_text(errors, report_path, f"{label}.path", item.get("path"), 300, True)
        regex = ASSET_SHOT_RE if kind == "screenshots" else ASSET_LOG_RE
        match = regex.fullmatch(path or "")
        if not match or match.group(1) != cusa or match.group(2) != report_id:
            fail(errors, report_path, f"{label}.path must be under assets/{cusa}/{report_id}/")
    else:
        url = bounded_text(errors, report_path, f"{label}.url", item.get("url"), 2048, True)
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            fail(errors, report_path, f"{label}.url must be HTTPS")
    if kind == "screenshots":
        bounded_text(errors, report_path, f"{label}.caption", item.get("caption"), 300)
    else:
        bounded_text(errors, report_path, f"{label}.label", item.get("label"), 120)
```

After parsing provenance, if `captureType == "app-captured"`:

- `evidence` object required
- 1–3 screenshots
- ≥1 diagnostics entry whose `label` is `Bachata application log`

Call `validate_evidence_entry` for each item.

- [ ] **Step 5: Run tests**

```bash
python3 -m unittest tests.test_community_v2 -v
python3 scripts/validate.py --root .
```

Expected: new tests PASS; historical v1 `validate.py` still passes (it does not walk v2-only files as v2 unless already mixed — current `validate.py` on this branch still exists; do not change v1 reports).

If `validate.py` is run on the whole repo and v2 reports without evidence exist, only fail new `app-captured` fixtures you add; do not rewrite old v1 JSON.

- [ ] **Step 6: Commit**

```bash
cd /home/jica/repo/.worktrees/community-compatibility-v2
git add schemas/report-v2.schema.json scripts/validate_v2.py tests/test_community_v2.py
git commit -m "feat(compat): require git-path evidence on app-captured v2 reports"
```

---

### Task 2: Worker performance parser

**Files:**
- Create: `worker/src/performance.ts`
- Create: `worker/src/performance.test.ts`
- Modify: `worker/package.json` (add vitest, `"test": "vitest run"`)

**Interfaces:**
- Produces: `parsePerformanceFromLog(text: string): PerformanceStats | undefined`
- `PerformanceStats = { nativeAverageFps: number; nativeOnePercentLowFps?: number; outputAverageFps?: number; testDurationSeconds: number; framePacing: "smooth"|"minor-stutter"|"stuttery"|"severe-stutter" }`

- [ ] **Step 1: Add vitest**

In `worker/`:

```bash
npm install --save-dev vitest --ignore-scripts
```

Set `"test": "vitest run"` in `package.json`.

- [ ] **Step 2: Write failing tests** in `worker/src/performance.test.ts`

```ts
import {describe, expect, it} from "vitest";
import {parsePerformanceFromLog} from "./performance";

const line = (elapsed: number, source: number, output: number, ft: number, fg: "on"|"off") =>
  `[2026-09-15T05:00:00Z] [App.Performance] <Info> elapsedMs=${elapsed} sourceFps=${source.toFixed(2)} outputFps=${output.toFixed(2)} frameTimeMs=${ft.toFixed(2)} fg=${fg}`;

describe("parsePerformanceFromLog", () => {
  it("ignores boot window and zero fps, then averages native fps", () => {
    const text = [
      line(0, 5, 5, 200, "off"),
      line(2000, 0, 0, 0, "off"),
      line(12000, 30, 30, 33.3, "off"),
      line(14000, 32, 32, 31.2, "off"),
      line(16000, 28, 28, 35.7, "off"),
      line(18000, 30, 30, 33.3, "off"),
      line(20000, 31, 31, 32.2, "off"),
    ].join("\n");
    const stats = parsePerformanceFromLog(text);
    expect(stats?.nativeAverageFps).toBeCloseTo(30.2, 1);
    expect(stats?.testDurationSeconds).toBe(20);
    expect(stats?.outputAverageFps).toBeUndefined();
    expect(stats?.nativeOnePercentLowFps).toBeUndefined();
  });

  it("accepts legacy fps= lines", () => {
    const text = Array.from({length: 6}, (_, i) =>
      `[t] [App.Performance] <Info> elapsedMs=${12000 + i * 2000} fps=20.00 frameTimeMs=50.00`,
    ).join("\n");
    expect(parsePerformanceFromLog(text)?.nativeAverageFps).toBe(20);
  });

  it("omits stats when fewer than 5 post-boot samples", () => {
    const text = line(12000, 30, 30, 33, "off");
    expect(parsePerformanceFromLog(text)).toBeUndefined();
  });

  it("sets outputAverageFps only when fg=on and output differs", () => {
    const text = Array.from({length: 6}, (_, i) => line(12000 + i * 2000, 30, 58, 33.3, "on")).join("\n");
    const stats = parsePerformanceFromLog(text);
    expect(stats?.nativeAverageFps).toBe(30);
    expect(stats?.outputAverageFps).toBe(58);
  });
});
```

- [ ] **Step 3: Run to verify fail**

```bash
cd worker && npx vitest run src/performance.test.ts
```

Expected: FAIL cannot find module `./performance`.

- [ ] **Step 4: Implement `worker/src/performance.ts`**

```ts
export type FramePacing = "smooth" | "minor-stutter" | "stuttery" | "severe-stutter";

export interface PerformanceStats {
  nativeAverageFps: number;
  nativeOnePercentLowFps?: number;
  outputAverageFps?: number;
  testDurationSeconds: number;
  framePacing: FramePacing;
}

const NEW_RE = /elapsedMs=(\d+)\s+sourceFps=([\d.]+)\s+outputFps=([\d.]+)\s+frameTimeMs=([\d.]+)\s+fg=(on|off)/;
const OLD_RE = /elapsedMs=(\d+)\s+fps=([\d.]+)\s+frameTimeMs=([\d.]+)/;

interface Sample { elapsedMs: number; sourceFps: number; outputFps: number; frameTimeMs: number; fgOn: boolean }

function parseLine(line: string): Sample | undefined {
  const newer = line.match(NEW_RE);
  if (newer) {
    return {elapsedMs: Number(newer[1]), sourceFps: Number(newer[2]), outputFps: Number(newer[3]), frameTimeMs: Number(newer[4]), fgOn: newer[5] === "on"};
  }
  const older = line.match(OLD_RE);
  if (older) {
    const fps = Number(older[2]);
    return {elapsedMs: Number(older[1]), sourceFps: fps, outputFps: fps, frameTimeMs: Number(older[3]), fgOn: false};
  }
  return undefined;
}

function mean(values: number[]): number {
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function percentile(values: number[], p: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((p / 100) * (sorted.length - 1))));
  return sorted[index];
}

function pacing(frameTimes: number[]): FramePacing {
  const avg = mean(frameTimes);
  if (avg <= 0) return "severe-stutter";
  const variance = mean(frameTimes.map(v => (v - avg) ** 2));
  const cv = Math.sqrt(variance) / avg;
  if (cv < 0.08) return "smooth";
  if (cv < 0.18) return "minor-stutter";
  if (cv < 0.35) return "stuttery";
  return "severe-stutter";
}

export function parsePerformanceFromLog(text: string): PerformanceStats | undefined {
  const samples = text.split(/\r?\n/).map(parseLine).filter((s): s is Sample => !!s)
    .filter(s => s.elapsedMs >= 10000 && s.sourceFps > 0);
  if (samples.length < 5) return undefined;
  const span = samples[samples.length - 1].elapsedMs - samples[0].elapsedMs;
  if (span < 10000) return undefined;
  const native = samples.map(s => s.sourceFps);
  const nativeAverageFps = Math.round(mean(native) * 100) / 100;
  const stats: PerformanceStats = {
    nativeAverageFps,
    testDurationSeconds: Math.max(1, Math.round(samples[samples.length - 1].elapsedMs / 1000)),
    framePacing: pacing(samples.map(s => s.frameTimeMs)),
  };
  if (samples.length >= 20) stats.nativeOnePercentLowFps = Math.round(percentile(native, 1) * 100) / 100;
  const fgOn = samples.some(s => s.fgOn);
  const outputMean = mean(samples.map(s => s.outputFps));
  if (fgOn && Math.abs(outputMean - nativeAverageFps) > 0.5) {
    stats.outputAverageFps = Math.round(outputMean * 100) / 100;
  }
  return stats;
}
```

- [ ] **Step 5: Run tests**

```bash
npx vitest run src/performance.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add worker/package.json worker/package-lock.json worker/src/performance.ts worker/src/performance.test.ts
git commit -m "feat(worker): parse native FPS from application.log Performance lines"
```

---

### Task 3: Worker evidence sanitize (logs + Images)

**Files:**
- Create: `worker/src/evidence.ts`
- Create: `worker/src/evidence.test.ts`

**Interfaces:**
- Consumes: `env.IMAGES` with `info(bytes)` and `input(bytes).transform({width,height,fit}).output({format,quality,anim})`
- Produces:
  - `sanitizeLogGzip(bytes: Uint8Array): Promise<Uint8Array>`
  - `reencodeScreenshot(images: ImagesBinding, bytes: Uint8Array): Promise<Uint8Array>`
  - `sha256Hex(bytes: Uint8Array): Promise<string>`

- [ ] **Step 1: Write failing tests** in `worker/src/evidence.test.ts`

Use `CompressionStream` / `DecompressionStream` available in vitest/node 20+. Include a tiny valid gzip of `hello /data/user/0/secret\n` that must throw, and a gzip of `elapsedMs=1 fps=1.00 frameTimeMs=1.00\n` that must round-trip without the original gzip filename.

Mock Images:

```ts
const WEBP = new Uint8Array([0x52,0x49,0x46,0x46,0,0,0,0,0x57,0x45,0x42,0x50]);
const images = {
  async info(bytes: ArrayBuffer) {
    const u8 = new Uint8Array(bytes as ArrayBuffer);
    if (u8[0] === 0x3c) throw new Error("unsupported");
    return {width: 1920, height: 1080, format: "image/jpeg"};
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
```

Cases: JPEG-like bytes → WebP magic; SVG `<` → throw; oversize 1.5 MiB+1 → throw; 4_000_001 pixels via info width/height → throw.

- [ ] **Step 2: Run to verify fail**

```bash
npx vitest run src/evidence.test.ts
```

Expected: FAIL missing module.

- [ ] **Step 3: Implement `worker/src/evidence.ts`**

Constants: `MAX_IMAGE_BYTES = 1.5 * 1024 * 1024`, `MAX_PIXELS = 4_000_000`, `MAX_GZIP = 1.5 * 1024 * 1024`, `MAX_UNCOMPRESSED = 4 * 1024 * 1024`.

Reuse the same `PRIVATE_PATTERN` regex as `index.ts` (export it from a tiny `worker/src/privacy.ts` if that avoids a cycle; otherwise duplicate the regex once in `evidence.ts` and import it from `index.ts`).

`sanitizeLogGzip`:
1. if `bytes.byteLength` > MAX_GZIP throw `Log exceeds size limit`
2. gunzip via `DecompressionStream("gzip")`
3. if uncompressed > MAX_UNCOMPRESSED throw
4. decode UTF-8, if `PRIVATE_PATTERN.test(text)` throw `Submission contains a private identifier or local path`
5. gzip the UTF-8 bytes again via `CompressionStream("gzip")`

`reencodeScreenshot`:
1. size check
2. `await images.info(bytes)` — throw `Invalid screenshot` on failure
3. if `info.width * info.height > MAX_PIXELS` throw
4. `const out = await images.input(bytes).transform({width:1920,height:1920,fit:"scale-down"}).output({format:"image/webp",quality:80,anim:false})`
5. `new Uint8Array(await out.response().arrayBuffer())`

`sha256Hex`: `crypto.subtle.digest` → hex.

- [ ] **Step 4: Run tests** — expected PASS.

- [ ] **Step 5: Commit**

```bash
git add worker/src/evidence.ts worker/src/evidence.test.ts worker/src/privacy.ts
git commit -m "feat(worker): re-encode screenshots and rescan gzipped logs"
```

---

### Task 4: Multipart submit + Git Data API

**Files:**
- Create: `worker/src/github-git.ts`
- Create: `worker/src/submit.test.ts`
- Modify: `worker/src/index.ts`
- Modify: `worker/src/duplicate.ts`
- Modify: `worker/wrangler.toml`
- Modify: `worker/README.md`

**Interfaces:**
- Consumes: `parsePerformanceFromLog`, `sanitizeLogGzip`, `reencodeScreenshot`, `sha256Hex`
- Produces: `submit(request, env)` accepts `multipart/form-data`, requires `screenshot` × 1–3 and `log-application`, writes one git commit, draft PR, stamps `evidence.path`

- [ ] **Step 1: Write failing submit tests**

`worker/src/submit.test.ts` should export `fetch` handler tests by importing default from `./index.ts` and stubbing `globalThis.fetch` for `api.github.com`. Stub `env.IMAGES` as in Task 3. Stub `env.GITHUB_TOKEN` / `GITHUB_ISSUE_TOKEN` / `GITHUB_OWNER=JICA98` / `GITHUB_REPO=Bachata-S4-Compatibility` / `GITHUB_BASE_BRANCH=feat/community-compatibility-v2`.

Helper `multipart(parts)` builds a `Request` to `https://example.com/api/compat/v2/reports`.

Cases:
1. JSON body still 415 (content type must be multipart now for POST reports). Wait — health/feed stay JSON GET. Only POST reports change. If content-type is JSON, return `415` with message to use multipart. Existing Android JSON clients will break until Task 7; that is intended.
2. Happy path: 1 JPEG screenshot + gzip application log with 6 Performance lines + envelope without evidence → 202, GitHub `POST /git/blobs` called for webp + gz + json, `POST /git/trees` once, `POST /pulls` with `draft: true` and `base: feat/community-compatibility-v2`. Report JSON blob contains `"path": "assets/CUSA00900/.../screenshots/01.webp"` and Worker-stamped performance, no client fps.
3. Envelope with `evidence` → 400.
4. No screenshot part → 400 `evidence_required`.
5. Log text contains `/data/user/` → 400, no `POST /git/refs`.
6. SVG screenshot → 400, no git refs.

- [ ] **Step 2: Run to verify fail** — current handler requires JSON and rejects evidence; tests FAIL.

- [ ] **Step 3: Implement `github-git.ts`**

```ts
export async function commitFiles(
  github: (path: string, init?: RequestInit) => Promise<Response>,
  args: {
    owner: string; repo: string; branch: string; baseCommitSha: string; baseTreeSha: string;
    message: string;
    files: Array<{path: string; content: Uint8Array}>;
  },
): Promise<string> {
  const blobs = [];
  for (const file of args.files) {
    const response = await github(`/repos/${args.owner}/${args.repo}/git/blobs`, {
      method: "POST",
      body: JSON.stringify({content: uint8ToBase64(file.content), encoding: "base64"}),
    });
    if (!response.ok) throw new Error(`Could not create blob (${response.status})`);
    const data = await response.json() as {sha: string};
    blobs.push({path: file.path, mode: "100644", type: "blob", sha: data.sha});
  }
  const tree = await github(`/repos/${args.owner}/${args.repo}/git/trees`, {
    method: "POST",
    body: JSON.stringify({base_tree: args.baseTreeSha, tree: blobs}),
  });
  if (!tree.ok) throw new Error(`Could not create tree (${tree.status})`);
  const treeSha = ((await tree.json()) as {sha: string}).sha;
  const commit = await github(`/repos/${args.owner}/${args.repo}/git/commits`, {
    method: "POST",
    body: JSON.stringify({message: args.message, tree: treeSha, parents: [args.baseCommitSha]}),
  });
  if (!commit.ok) throw new Error(`Could not create commit (${commit.status})`);
  const commitSha = ((await commit.json()) as {sha: string}).sha;
  const update = await github(`/repos/${args.owner}/${args.repo}/git/refs/heads/${encodeURIComponent(args.branch)}`, {
    method: "PATCH",
    body: JSON.stringify({sha: commitSha}),
  });
  if (!update.ok) throw new Error(`Could not update branch (${update.status})`);
  return commitSha;
}
```

Implement `uint8ToBase64` without `btoa` on large arrays (`String.fromCharCode` in chunks or `Buffer` is not in Workers — use chunked `btoa`).

- [ ] **Step 4: Change `duplicate.ts` `stable()`** so it does not strip nested `sha256` fields. Fingerprint input is `{report, evidenceSha256s: string[]}` computed in submit after sanitize. Change `duplicateFingerprint` to accept `JsonObject` that already includes `evidenceSha256s` at the top level of the object you pass in (do not put it in the committed report).

```ts
export async function duplicateFingerprint(report: JsonObject, evidenceSha256s: string[]): Promise<string> {
  return fingerprint({report: stable(report), evidenceSha256s: [...evidenceSha256s].sort()});
}
```

Keep ignoring `reportId` / `testedAt` / `summary` / `notes` inside `stable(report)`.

- [ ] **Step 5: Rewrite `submit()` in `index.ts`**

- `MAX_MULTIPART_BYTES = 8 * 1024 * 1024`. Reject if `content-length` exceeds it.
- Require `content-type` contains `multipart/form-data`.
- `const form = await request.formData()`.
- `envelope` part → JSON parse; `normalizeReport` still throws if `input.evidence != null`.
- Delete `normalizedPerformance` from what gets committed until log parse runs.
- Collect `form.getAll("screenshot")` as `Blob`s (1–3). Captions `screenshot-caption-0` etc.
- `log-application` required Blob; optional `log-shadps4`, `log-shadps4-internal`.
- If `!env.IMAGES` throw `Images binding is not configured`.
- Re-encode each screenshot; sanitize each log.
- `parsePerformanceFromLog` on the **pre-gzip scanned UTF-8** of application.log (sanitize can return `{gzip, text}` or parse before gzip). Overwrite `report.performance` or delete it.
- Create branch from `GITHUB_BASE_BRANCH` as today.
- Resolve base commit + tree: `GET /git/commits/{sha}`.
- Files:
  - `assets/${cusa}/${reportId}/screenshots/01.webp` …
  - `assets/${cusa}/${reportId}/logs/01-application.log.gz`
  - `02-shadps4.log.gz` / `03-shadps4-internal.log.gz` if present
  - `games/${cusa}/game.json` only if 404 on base
  - `games/${cusa}/reports/${reportId}.json` with

```ts
evidence: {
  screenshots: shots.map((shot, i) => ({
    path: `assets/${cusaId}/${reportId}/screenshots/${String(i + 1).padStart(2, "0")}.webp`,
    sha256: shot.sha,
    caption: captions[i],
  })),
  diagnostics: logs.map((log, i) => ({
    path: `assets/${cusaId}/${reportId}/logs/${String(i + 1).padStart(2, "0")}-${log.slug}.log.gz`,
    sha256: log.sha,
    label: log.label, // "Bachata application log" | "shadPS4 session log" | "shadPS4 internal log"
  })),
}
```

- `commitFiles` once, then open draft PR. PR body must mention screenshots/logs attached (no longer “structured report only”).
- On GitHub failure after branch create: 502, do not `markAccepted`.

Catch `evidence_required` as 400 with `error: "evidence_required"`.

- [ ] **Step 6: wrangler.toml**

```toml
GITHUB_BASE_BRANCH = "feat/community-compatibility-v2"

[images]
binding = "IMAGES"
```

- [ ] **Step 7: README** — replace “binary evidence disabled” with this contract: Images re-encode, log rescan, git paths, draft PR, no client evidence field.

- [ ] **Step 8: Run tests**

```bash
cd worker && npx vitest run && npx tsc --noEmit
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add worker
git commit -m "feat(worker): accept multipart evidence and commit git assets"
```

Do not `wrangler deploy` in this task.

---

### Task 5: Android Performance log line + parser

**Files:**
- Modify: `android/BachataS4/core/runtime/src/main/kotlin/com/bachatas4/android/runtime/session/FrameTelemetryReporter.kt`
- Modify: `android/BachataS4/core/runtime/src/test/kotlin/com/bachatas4/android/runtime/session/FrameTelemetryReporterTest.kt`
- Modify: `android/BachataS4/app/src/main/kotlin/com/bachatas4/android/service/EmulationService.kt` (`sample.logLine()` call site — pass full `FrameTelemetry`)
- Create: `android/BachataS4/core/compatibility/src/main/kotlin/com/bachatas4/android/compatibility/submission/SessionPerformanceParser.kt`
- Create: `android/BachataS4/core/compatibility/src/test/kotlin/com/bachatas4/android/compatibility/submission/SessionPerformanceParserTest.kt`

**Interfaces:**
- Produces: log line `elapsedMs=%d sourceFps=%.2f outputFps=%.2f frameTimeMs=%.2f fg=%s`
- Produces: `SessionPerformanceParser.parse(text: String): CommunityPerformance?` matching Worker rules

- [ ] **Step 1: Fail `logLineUsesLocaleIndependentDecimals`**

Change `FrameTelemetrySample` to hold `sourceFps`, `outputFps`, `frameGenerationActive`. Update `logLine()` and the test expected string to `elapsedMs=2000 sourceFps=30.50 outputFps=58.00 frameTimeMs=32.79 fg=on`. Update `record()` to copy those fields from `FrameTelemetry`.

- [ ] **Step 2: Run**

```bash
cd /home/jica/repo/Bachata-S4-Dev/.worktrees/community-compatibility-v2
# use the repo's Android test entry from the building-bachata-android skill if the worktree gradle wrapper needs Podman;
# unit tests for these modules:
./gradlew :core:runtime:testDebugUnitTest --tests com.bachatas4.android.runtime.session.FrameTelemetryReporterTest
```

If Gradle must run in Podman, use `./gradlew` from the worktree root as the skill documents. Expected: FAIL until implementation.

- [ ] **Step 3: Implement reporter + EmulationService remains `sample.logLine()`** (no extra args if sample holds the fields).

- [ ] **Step 4: Port Worker rules to Kotlin `SessionPerformanceParser`** with the same regexes and thresholds. Tests copy the vitest fixtures (legacy `fps=`, boot skip, fg on).

- [ ] **Step 5: Run both test classes** — PASS.

- [ ] **Step 6: Commit (Dev)**

```bash
git add android/BachataS4/core/runtime android/BachataS4/app/src/main/kotlin/com/bachatas4/android/service/EmulationService.kt android/BachataS4/core/compatibility
git commit -m "feat(compat): log source/output FPS and parse session performance"
```

---

### Task 6: Capture store + session drawer

**Files:**
- Create: `android/BachataS4/core/compatibility/src/main/kotlin/com/bachatas4/android/compatibility/capture/CompatibilityCaptureStore.kt`
- Create: `android/BachataS4/core/compatibility/src/test/kotlin/com/bachatas4/android/compatibility/capture/CompatibilityCaptureStoreTest.kt`
- Modify: `feature/session/.../SessionDrawer.kt` — `onSaveCompatibilityScreenshot: () -> Unit`
- Modify: `feature/session/.../SessionScreen.kt` — PixelCopy + encode + toast

**Interfaces:**
- Produces: `CompatibilityCaptureStore.save(cusaId, webpBytes): List<File>` FIFO 3; `list(cusaId): List<File>`; `clear(cusaId)`
- Root: `context.filesDir.resolve("compatibility-captures")`

- [ ] **Step 1: Failing tests** — save 4 bytes arrays named by incrementing instants; assert 3 files remain, oldest gone; `clear` empties; reject cusa that is not `CUSA\\d{5}`.

- [ ] **Step 2: Run** — FAIL class missing.

- [ ] **Step 3: Implement store.** Filenames `${utc}-${n}.webp`. Max 1.5 MiB per file.

- [ ] **Step 4: Session drawer** — in the existing column with Resume/Stop, add a row `Save compatibility screenshot` calling `onSaveCompatibilityScreenshot`.

- [ ] **Step 5: SessionScreen PixelCopy** — keep a `var runtimeSurfaceView: SurfaceView?`. On save: `PixelCopy.request(view, bitmap, ...)` on the main handler. On SUCCESS, scale so long edge ≤ 1920, `bitmap.compress(WEBP, 80, out)`, `store.save(gameId, bytes)`, toast `Screenshot N of 3 saved`. Do not copy the Compose overlay.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(session): save framebuffer shots for compatibility reports"
```

---

### Task 7: Builder fields + multipart client

**Files:**
- Modify: `CommunityReportBuilder.kt`, `CompatibilitySubmission.kt`, `CompatibilityViewModel.kt`
- Modify: `feature/dashboard/build.gradle.kts`
- Create: `core/compatibility/src/test/.../CommunityReportBuilderTest.kt` (if Android unit tests can construct the builder with fakes; otherwise test pure helpers `releaseTag()`, `reportableOverrides` already exists)
- Create: `CompatibilityPatchSource` fun interface in compatibility module

**Interfaces:**
- Produces: envelope with `game.version`/`region`, full allowlist, patches, `driver.source`, `release.tag` `unreleased` or exact tag; **no** `performance` (Worker overwrites; preview is UI-only)
- Produces: `CompatibilitySubmissionClient.submit(envelope, screenshots: List<ScreenshotPart>, logs: List<LogPart>)`
- `data class ScreenshotPart(val bytes: ByteArray, val caption: String)`
- `data class LogPart(val fieldName: String, val bytes: ByteArray)` where fieldName is `log-application` / `log-shadps4` / `log-shadps4-internal`

- [ ] **Step 1: `BACHATA_GIT_EXACT_TAG`**

```kotlin
val bachataGitExactTag = providers.exec {
    commandLine("git", "describe", "--tags", "--exact-match", "HEAD")
}.standardOutput.asText.map { it.trim() }.orElse("")
buildConfigField("String", "BACHATA_GIT_EXACT_TAG", "\"${bachataGitExactTag.get()}\"")
```

Helper:

```kotlin
fun releaseTag(exactTag: String, versionName: String): String {
    val tag = exactTag.trim()
    if (tag.isNotEmpty()) return if (tag.startsWith("v")) tag else "v$tag"
    return "unreleased"
}
```

Unit-test: empty exact tag → `unreleased`; `v0.2.1` → `v0.2.1`. Never use `v${versionName}` unless exact tag matches.

- [ ] **Step 2: Builder**

- Parse `filesDir/games/${cusaId}/sce_sys/param.sfo` via `ParamSfoReader.parse`. `game.version = appVer ?: "Unknown"`, `game.region = "Unknown"` (SFO has no region key today). Title/publisher from SFO title when non-null else arguments.
- Settings: encode public profile as today, then for each `CompatibilityReportableSettings.ids` missing from the map, if the catalog spec has a scalar `defaultValue`, insert it. That is how resolution scale always appears.
- Patches: `patchSource.enabledPatches(cusaId)` — implement in dashboard by reading `PatchManagerService.getGamePatches` enabled ids (bind in the app/dashboard Hilt module). Tests use a fake that returns `listOf(CommunityPatch("bloodborne-30fps", preset = "mobile-performance"))`.
- Driver source: `listOfNotNull(metadata.sourceRepository, metadata.releaseTag).joinToString(" ").takeIf { it.isNotBlank() }`.
- Add optional `source` on `CommunityDriver`.
- Add `game: CommunityGameVersion?` on `CommunityReport` (`version`, `region`).
- Do not set `performance` on the envelope.

- [ ] **Step 3: Multipart client**

Replace JSON `outputStream.write(payload)` with `multipart/form-data; boundary=...`.

Parts: `envelope` (JSON bytes), `screenshot-caption-i`, `screenshot` (filename `01.webp`), logs.

Keep 96 KiB envelope check, 8 MiB total check, private-marker scan on envelope JSON only (logs already redacted).

`connectTimeout = 12_000`, `readTimeout = 60_000`.

Map HTTP 400 `evidence_required` to a clear message.

- [ ] **Step 4: Tests** for `releaseTag`, allowlist fill, multipart body contains `log-application` and does not contain `"evidence"`.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(compat): multipart submit with SFO, settings allowlist, unreleased tags"
```

---

### Task 8: Submit UI evidence block

**Files:**
- Modify: `CompatibilityScreen.kt` `CommunityReportDialog`
- Modify: `CompatibilityViewModel.kt` `submitCommunityReport`

**Interfaces:**
- Consumes: `CompatibilityCaptureStore.list`, latest session dir matching `-$cusaId-` under `filesDir/logs`, `SessionPerformanceParser`, `DiagnosticRedactor`

- [ ] **Step 1: ViewModel**

Replace FPS parameters with no performance args.

`submitCommunityReport(status, summary, notes, issues, captions: List<String>)`:

1. Load shots from store; if empty error `Pause the game → Save compatibility screenshot`
2. Find latest `filesDir/logs/*-$cusaId-*` with `application.log`; else error `Play this game once so session logs exist`
3. Redact application.log (and shadps4 / internal if present) through `DiagnosticRedactor`, gzip to temp bytes
4. Build envelope (no performance)
5. `submissionClient.submit(...)`
6. On success `captureStore.clear(cusaId)`

Add `evidencePreview: StateFlow` with shot files, log names/sizes, parsed performance, sfo version — loaded in `load()`.

- [ ] **Step 2: Dialog**

Remove FPS/duration/pacing fields.

Add Evidence: thumbnails (`AsyncImage` or `BitmapFactory.decodeFile`), caption fields, log lines, read-only performance and game version.

Disable Submit unless shots ≥ 1, application.log present, summary non-empty, both consents, every kept shot has a non-blank caption.

- [ ] **Step 3: Manual compile**

```bash
./gradlew :feature:dashboard:testDebugUnitTest --tests com.bachatas4.android.feature.dashboard.viewmodels.CompatibilityViewModelTest
```

Add a ViewModel test if a fake store/client exists; otherwise test preview mapping in a small pure function `canSubmit(shots, hasAppLog, summary, consents, captions)`.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(compat): require screenshots and session logs in submit UI"
```

---

### Task 9: Deploy Worker, close PR 19, device smoke

**Files:** none in git except maybe progress doc.

- [ ] **Step 1: Confirm Images** on the Cloudflare account for `bachata-compatibility-submit`. If `IMAGES.info` would fail closed, enable Image Transformations before deploy.

- [ ] **Step 2: Deploy**

```bash
cd /home/jica/repo/.worktrees/community-compatibility-v2/worker
npx wrangler deploy
curl -sS https://bachata-compatibility-submit.bachatas4.workers.dev/api/compat/v2/health
```

Expected: `{"ok":true,...}`. POST JSON to `/api/compat/v2/reports` now 415.

- [ ] **Step 3: Close PR 19** (do not merge)

```bash
gh pr close 19 -R JICA98/Bachata-S4-Compatibility --comment "Superseded: structured-only v2 submit without screenshots/logs. Next in-app reports use multipart evidence on feat/community-compatibility-v2."
```

- [ ] **Step 4: Build and install APK** from the Dev worktree using `building-bachata-android` (`./gradlew buildBachataApk`). Install the reported playstoreDebug APK to the Pad 2 (`OPD2403` / `7d6afed8`).

- [ ] **Step 5: Smoke**

1. Launch Bloodborne (or any owned game).
2. Pause → Save compatibility screenshot at least once (gameplay frame, not the drawer).
3. Stop session. Open Compatibility → Submit.
4. Confirm preview shows shot + application.log + parsed FPS (or omitted if <5 samples).
5. Submit. Expect 202 and a **new** draft PR whose files include `assets/CUSA…/screenshots/01.webp` and `logs/01-application.log.gz`, `release.tag` `unreleased` for this feature APK, CI on `feat/community-compatibility-v2` green.

- [ ] **Step 6: Commit progress** only if you update `docs/community-compatibility-v2-progress.md` checkboxes. No code commit required if nothing changed.

---

## Self-review

| Spec section | Task |
|---|---|
| Git assets on draft PR | 4 |
| PixelCopy drawer capture | 6 |
| Submit UI evidence / no typed FPS | 8 |
| Multipart contract / HTTP codes | 4, 7 |
| Images re-encode | 3, 4 |
| Log redact + rescan | 3, 8 |
| FPS from Performance lines | 2, 5, 4 |
| SFO / allowlist / patches / unreleased | 7 |
| Schema path XOR url / app-captured required | 1 |
| Base branch feat/community-compatibility-v2 | 4 |
| Close PR #19 / device smoke | 9 |
| Out of scope R2, main merge, gallery | not scheduled |
)
