# Community Compatibility v2 submission Worker

This Cloudflare Worker is the only public write gateway for in-app compatibility reports. The Android application must never contain GitHub write credentials.

## Responsibilities

- Accept multipart compatibility report schema v2 payloads (`envelope` JSON + screenshots + gzipped logs).
- Reject local filesystem/content URIs, device identifiers, credentials, and unsupported nested configuration values.
- Re-encode screenshots through the Cloudflare Images binding to WebP; rescan and re-gzip logs.
- Overwrite `performance` from `application.log` Performance lines. Ignore client-supplied FPS.
- Keep native FPS separate from frame-generated output FPS.
- Rate-limit public submission traffic when the `RATE_LIMIT` KV binding is configured.
- Create a moderation branch and **draft pull request** in `JICA98/Bachata-S4-Compatibility` against `feat/community-compatibility-v2`.
- Create/reuse canonical CUSA discussion identity through the configured GitHub repositories.
- Do not accept game files, firmware, keys, licenses, passcodes, save archives, PKGs, raw unsanitized logs, or client-supplied `evidence` fields.

## Required environment

`wrangler.toml` contains non-secret defaults only. Configure these bindings/secrets in Cloudflare before production deployment:

- `GITHUB_TOKEN` — secret. Prefer a GitHub App installation token or narrowly scoped fine-grained token. Required permissions: contents write + pull requests write on `Bachata-S4-Compatibility`, and issues write on the canonical public Bachata repository if automatic issue creation remains enabled.
- `GITHUB_OWNER` — normally `JICA98`.
- `GITHUB_REPO` — normally `Bachata-S4-Compatibility`.
- `GITHUB_BASE_BRANCH` — `feat/community-compatibility-v2` until v2 validation is on `main`.
- `IMAGES` — Cloudflare Images binding. Image transformations must be enabled on the same account.
- `RATE_LIMIT` — KV namespace used only for hashed/day-scoped rate-limit counters. Raw IP addresses are not stored.

Never commit production tokens, KV IDs, account IDs, or private Cloudflare credentials.

## Deployment

From `worker/`:

```bash
npm install --ignore-scripts
npm run typecheck
npx wrangler secret put GITHUB_TOKEN
npx wrangler deploy
```

Production routing should expose only the compatibility API path intended by the app (for example `api.bachatas4.games/compat/v2/*`). Keep development `workers.dev` URLs out of release builds.

## Evidence upload security contract

`POST /api/compat/v2/reports` is `multipart/form-data`. The client must not send `report.evidence`. The Worker:

1. accepts PNG/JPEG/WebP screenshot parts and rejects anything `IMAGES.info` cannot decode (SVG, archives, executables);
2. caps multipart size at 8 MiB, each image at 1.5 MiB and 4 megapixels;
3. fully decodes and re-encodes screenshots with `env.IMAGES` to WebP (quality 80, long edge 1920, `anim: false`), which strips EXIF/XMP/ICC;
4. names committed files `01.webp` / `01-application.log.gz` under `assets/<CUSA>/<reportId>/`;
5. gunzips logs, scans them with the same private-path/token regex as JSON, and re-gzips — raw `.log` files are never committed;
6. stamps repo-relative `path` + sha256 onto the report JSON in the same git commit;
7. opens a **draft** pull request. Evidence is not public until merge.

Legal/privacy takedowns still use the tombstone mechanism after merge; this iteration stores sanitized bytes in git like v1 maintainer reports.

## Moderation and takedowns

An accepted submission is not public compatibility evidence until its draft PR is reviewed and merged. Moderators must reject reports that contain piracy links, private data, fabricated hardware identity, abusive content, or misleading performance claims.

Legal/privacy/security removal must override normal append-only report immutability. Use the project tombstone mechanism once implemented; do not rewrite an ordinary historical report merely to change its result.
