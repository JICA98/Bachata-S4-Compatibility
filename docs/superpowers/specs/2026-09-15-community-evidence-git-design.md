# Community compatibility evidence on draft-PR git assets

Date: 2026-09-15
Repos: `JICA98/Bachata-S4-Dev` (`feat/community-compatibility-v2`) and
`JICA98/Bachata-S4-Compatibility` (`feat/community-compatibility-v2`)
Status: approved design; not implemented

## Goal

The next in-app community submit must produce a moderation-ready v2 report with the
same class of proof as a maintainer v1 report: 1–3 gameplay screenshots, redacted
session logs, honest release identity, public runtime settings, and FPS taken from
the play session rather than typed into the form.

## Why the Pad 2 submit was incomplete

Draft PR https://github.com/JICA98/Bachata-S4-Compatibility/pull/19 (`CUSA00900`,
OnePlus OPD2403) was accepted by the Worker (HTTP 202) as structured JSON only.

Missing versus v1 (`games/CUSA00900/reports/20260801T163245Z-…` and later v0.2.1
reports):

- screenshots under `assets/<CUSA>/<reportId>/screenshots/*.webp` plus captions
- `application.log.gz` and `shadps4.log.gz` (optional `shadps4-internal.log.gz`)
- `game.version` / region from `param.sfo`
- full public settings allowlist including resolution scale
- patches, driver source, release URL
- measured FPS / duration / min-max (v1 overlay); this submit had a typed 15 FPS
- canonical issue fields live on v2 `game.json`, not on the report; Worker did
  not fail that, but `main` CI still validates v1 shape and is red

This is by construction: `CommunityReportBuilder` never attaches evidence, the
submit dialog never captures screenshots, and `worker/src/index.ts` throws if
`evidence` is present. `worker/README.md` forbids enabling binary evidence until
decode/re-encode, format caps, metadata strip, and log redaction exist.

## Decision

Store sanitized evidence as git assets on the draft PR (v1 layout). Do not use
R2 or a hand-attached diagnostic ZIP for this iteration.

The Android app never holds GitHub credentials. One Worker request creates the
branch, writes assets + JSON, and opens a draft PR.

## Architecture

```
Play session
  framebuffer screenshots → app-private compatibility-captures/<CUSA>/  (FIFO max 3)
  session logs            → files/logs/<session>/{application,shadps4,shadps4-internal}.log
  FPS samples             → application.log Performance lines every ~2s

Submit dialog
  captions + consents
  client re-encodes images (WebP, long edge ≤ 1920) so the upload fits the cap
  client redacts logs with DiagnosticRedactor, then gzip
  multipart POST /api/compat/v2/reports

Worker
  validate envelope JSON (reject client-supplied evidence)
  Cloudflare Images: decode, scale-down, output WebP (canonical bytes)
  gunzip logs, scan private markers, re-gzip
  parse Performance lines; overwrite report.performance
  Git Data API: one commit on community/<cusa>/<reportId>
  draft PR against feat/community-compatibility-v2
```

Repo layout (unchanged from v1):

```
games/CUSA00900/reports/<reportId>.json
assets/CUSA00900/<reportId>/screenshots/01.webp
assets/CUSA00900/<reportId>/logs/01-application.log.gz
assets/CUSA00900/<reportId>/logs/02-shadps4.log.gz
assets/CUSA00900/<reportId>/logs/03-shadps4-internal.log.gz   # only if present
```

## Android capture

Screenshots come only from the game `SurfaceView` via PixelCopy. Gallery picks,
system screenshots, and trophy screenshots are rejected sources.

During play, the existing session drawer (`SessionDrawerOverlay`) gains
**Save compatibility screenshot**. That copies the surface under the Compose
overlay, writes app-private
`files/compatibility-captures/<CUSA>/<utc>-<n>.webp`, and toasts
`Screenshot N of 3 saved`. Oldest file is deleted when a fourth is saved.

No extra on-screen overlay button and no MediaProjection.

## Android submit UI

Keep status, summary, notes, issue tags, and the two consents.

Remove native/output FPS, 1% low, duration, and frame-pacing inputs.

Add an Evidence block:

- thumbnails of the 1–3 captures; each caption is required, ≤ 300 characters;
  user may drop a shot; user may not add files from elsewhere
- auto-attached logs from the latest session directory whose name contains this
  CUSA: `application.log` is always attached when present (submit blocked if
  missing); `shadps4.log` and `shadps4-internal.log` attached when those files
  exist. The Worker requires `log-application` only; extra logs are optional.
- show log name + size and “redacted before upload”
- read-only game version / region from `ParamSfoReader`
- read-only performance preview parsed from the same session `application.log`

Submit is disabled until: ≥ 1 screenshot, `application.log` present, non-empty
summary, both consents. Helper copy if blocked:

- no shots: `Pause the game → Save compatibility screenshot`
- no logs: `Play this game once so session logs exist`

Successful submit clears `compatibility-captures/<CUSA>/`. Failed submit leaves
files in place. Success copy remains “queued for moderation”.

## Multipart contract

`POST https://bachata-compatibility-submit.bachatas4.workers.dev/api/compat/v2/reports`
(`CompatibilityApi.SUBMIT_URL` unchanged).

| Part | Required | Notes |
|---|---|---|
| `envelope` | yes | JSON `CommunitySubmissionEnvelope`. `report.evidence` must be absent |
| `screenshot-caption-0..2` | yes per shot | text, ≤ 300 chars |
| `screenshot` | 1–3 | image bytes; PNG/JPEG/WebP accepted as input |
| `log-application` | yes | gzip of redacted application.log |
| `log-shadps4` | if session had the file | gzip of redacted shadps4.log |
| `log-shadps4-internal` | no | gzip of redacted internal log |

Caps: envelope ≤ 96 KiB; whole multipart ≤ 8 MiB; each image ≤ 1.5 MiB; each
gzip ≤ 1.5 MiB compressed / 4 MiB uncompressed.

Client timeout: connect 12 s, read 60 s.

HTTP:

- `400 evidence_required` — missing screenshot or application log
- `400 invalid_submission` — bad image, private log content, bad JSON
- `413 payload_too_large`
- `409 duplicate_submission` — fingerprint includes evidence sha256s
- `202` — `{ ok, submissionId, pullRequest, moderationUrl }`
- `502 submission_failed` — GitHub error after validation; do not mark duplicate

## Worker image pipeline

Bind Cloudflare Images in `worker/wrangler.toml`. Image transformations must
already be enabled on the same Cloudflare account as the Worker; deploy fails
closed if `env.IMAGES` is missing.

```toml
[images]
binding = "IMAGES"
```

For each screenshot part:

1. Reject if empty or larger than 1.5 MiB.
2. `await env.IMAGES.info(bytes)` — if this throws or reports animation, reject.
3. Reject if `width * height > 4_000_000`.
4. Re-encode:

```ts
const out = await env.IMAGES
  .input(bytes)
  .transform({ width: 1920, height: 1920, fit: "scale-down" })
  .output({ format: "image/webp", quality: 80, anim: false });
```

5. Commit only those output bytes. Hash sha256 of the committed WebP.

Client re-encode is upload-size defense only. Git bytes are always Worker output.
SVG, archives, executables, and EXIF/XMP/ICC do not survive `info()` + re-encode.

## Worker log pipeline

For each log part: gunzip → `PRIVATE_PATTERN` scan (same regex as JSON, plus
`android id` / `adb serial` already covered) → reject on match → gzip again with
no original filename/mtime. Never commit a raw `.log`.

## Performance from logs (Worker is authoritative)

`EmulationService` already writes a Performance line every ~2 s via
`FrameTelemetryReporter`. Change `FrameTelemetrySample.logLine()` to:

```
elapsedMs=%d sourceFps=%.2f outputFps=%.2f frameTimeMs=%.2f fg=%s
```

`fg` is `on` or `off` from `FrameTelemetry.frameGenerationActive`.

Parser also accepts the current line `elapsedMs=%d fps=%.2f frameTimeMs=%.2f`
and treats `fps` as `sourceFps` with `fg=off`.

After the uploaded application.log is gunzipped and scanned, the Worker
**overwrites** `report.performance`:

- drop samples with `elapsedMs < 10000` or `sourceFps == 0`
- if fewer than 5 remaining samples or span < 10 s: omit `performance`
- `nativeAverageFps` = mean `sourceFps`
- `nativeOnePercentLowFps` = 1st percentile of those 2 s samples, only if
  sample count ≥ 20. This is not a per-frame 1% low; the log does not store
  per-frame times
- `outputAverageFps` only when `fg=on` and mean output differs from mean source
  by more than 0.5 FPS
- `testDurationSeconds` = last `elapsedMs / 1000` (integer, min 1)
- `framePacing` from coefficient of variation of `frameTimeMs`:
  `< 0.08` smooth; `< 0.18` minor-stutter; `< 0.35` stuttery; else severe-stutter

The Android dialog preview uses the same rules so the user sees what will be
stamped. Client-supplied `performance` in the envelope is ignored.

## Structured fields

`CommunityReportBuilder` always fills:

- `game.version`, `game.region`, title, publisher from `param.sfo`
  (`ParamSfoReader`). Use `"Unknown"` only when SFO is missing
- every id in `CompatibilityReportableSettings` that exists on the resolved
  profile, including catalog defaults (`gpu.resolution_scale`,
  `video.resolution_scale`, `gpu.vblank_divider`, `gpu.readbacks_mode`,
  `gpu.crash_diagnostics`, …)
- `requiredOverrides` = public values that differ from catalog defaults
- `patches` = enabled patches for this CUSA (`id`, optional `preset`/`revision`)
- driver `source` when installed Turnip metadata has a repo/tag; otherwise omit
- `release.tag` = published tag only if `BuildConfig.BACHATA_GIT_COMMIT` equals
  that tag’s commit; otherwise `unreleased` plus the real commit. A feature APK
  must not claim `v0.2.1`

Still user-typed: status, summary, notes, issue tags. Empty notes allowed.
Empty summary not allowed.

v2 reports do not include v1 `issueNumber` / `tester` / `device.label`. Canonical
issue identity stays on `game.json`. Worker keeps `ensureCanonicalIssue` when
creating `game.json`.

## Evidence in JSON

Client must not send `evidence`. Worker writes it after git blobs exist.

v2 schema today requires `https://` URLs. The commit SHA is not known until after
the commit, so this iteration extends the schema:

Each screenshot item is either:

- `{ "path", "sha256", "caption" }` with
  `path` matching `^assets/CUSA[0-9]{5}/[A-Za-z0-9._-]+/screenshots/[A-Za-z0-9._-]+\.webp$`
- or `{ "url", "sha256", "caption" }` with `url` starting `https://`

Each diagnostic/log item is the same with `/logs/` and `.log.gz`, plus `label`.

`additionalProperties` remains false. `path` and `url` are mutually exclusive.
Worker writes `path` only.

`captureType: app-captured` requires 1–3 screenshots and ≥ 1 application log
entry labeled `Bachata application log`.

## Git staging

Replace per-file Contents API writes for this submit path with Git Data API:

1. Read ref `heads/${GITHUB_BASE_BRANCH}`
2. Create `refs/heads/community/<cusa>/<reportId>`
3. Create blobs for WebPs, gzips, report JSON, and `game.json` if missing
4. Create tree from the base tree plus those blobs
5. Create commit, update the branch ref, open a **draft** PR

`GITHUB_BASE_BRANCH` is `feat/community-compatibility-v2` until that validator
is on `main`. Community PRs must not target `main` in this iteration (`main`
`validate.py` still requires v1 `device.label`, top-level `summary`, and git
screenshots in the v1 JSON shape).

If GitHub fails after the branch exists: HTTP 502, do not call `markAccepted`,
leave the branch for cleanup.

Draft PR #19 is structured-only. Do not merge it. Close or supersede it after
the evidence Worker is live.

Rate limit remains 12 accepted submits per hashed IP per UTC day.

Duplicate fingerprint continues to ignore `reportId` / `testedAt` / `summary` /
`notes`, and now includes sorted evidence sha256s.

## Privacy

Unchanged bans: game files, firmware, keys, licenses, Android/ADB serial,
Android ID, MAC, `content://` / `file://` / `/storage/emulated/` / `/data/user/`
paths, GitHub tokens.

Logs are redacted on device, scanned again on the Worker, and stored gzipped.
Screenshots are framebuffer-only and re-encoded server-side.

Contributor identity remains the existing `tester-<12 hex>` public id.

## Tests

Worker (miniflare, mock GitHub + mock `IMAGES`):

- 1 screenshot + application + shadps4 logs → one git commit, draft PR, `path`
  evidence, overwritten performance
- client `evidence` field → 400
- JPEG input → committed object is WebP from `IMAGES.output`
- SVG / EXIF-only garbage / `IMAGES.info` throw → 400, no git write
- log containing `/data/user/` → 400
- 0 screenshots → 400 `evidence_required`
- duplicate identical envelope + same evidence hashes → 409
- feature-branch APK envelope with tag `v0.2.1` and non-tag commit is accepted
  only if the builder already sent `unreleased`; Worker does not rewrite tag

Android:

- builder emits SFO version, full allowlist, `unreleased` when commit ≠ tag
- submit blocked without captures or application.log
- PixelCopy store FIFO max 3
- WebP client encode long-edge cap
- redactor output has no private markers
- performance preview matches Worker rules on a fixture log

Compat repo:

- fixture v2 report with `path` evidence passes `validate_v2.py`
- `app-captured` report missing screenshots fails
- `path` outside `assets/<CUSA>/<reportId>/` fails
- historical v1 reports remain valid and unmodified

## Out of scope

- R2 / object-store URLs as the primary store
- merging `feat/community-compatibility-v2` to `main`
- rewriting historical v1 reports
- auto HUD FPS overlay as the measurement source (logs are the source)
- per-frame 1% low
- gallery picker, MediaProjection, trophy screenshots
- attaching a diagnostic ZIP instead of git assets
- commenting the canonical Bachata-S4 issue from the Worker (moderator still
  does that after merge, using the report commit SHA for image URLs)
- changing Play Store / F-Droid release tagging

## Implementation split

1. Compat: schema + `validate_v2.py` + tests for required `path` evidence
2. Compat: Worker multipart, Images binding, log scan, performance parse, git
   Data API, base branch, tests
3. Dev: `FrameTelemetryReporter` log line, capture store, session drawer
   action, submit UI, builder SFO/settings/tag honesty, multipart client, tests
4. Deploy Worker, close PR #19, smoke on device
)
