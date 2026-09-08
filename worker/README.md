# Community Compatibility v2 submission Worker

This Cloudflare Worker is the only public write gateway for in-app compatibility reports. The Android application must never contain GitHub write credentials.

## Responsibilities

- Accept only structured compatibility report schema v2 payloads.
- Reject local filesystem/content URIs, device identifiers, credentials, and unsupported nested configuration values.
- Keep native FPS separate from frame-generated output FPS.
- Rate-limit public submission traffic when the `RATE_LIMIT` KV binding is configured.
- Create a moderation branch and **draft pull request** in `JICA98/Bachata-S4-Compatibility` instead of publishing directly to `main`.
- Create/reuse canonical CUSA discussion identity through the configured GitHub repositories.
- Do not accept game files, firmware, keys, licenses, passcodes, save archives, PKGs, raw logs, or arbitrary evidence URLs.

## Required environment

`wrangler.toml` contains non-secret defaults only. Configure these bindings/secrets in Cloudflare before production deployment:

- `GITHUB_TOKEN` — secret. Prefer a GitHub App installation token or narrowly scoped fine-grained token. Required permissions: contents write + pull requests write on `Bachata-S4-Compatibility`, and issues write on the canonical public Bachata repository if automatic issue creation remains enabled.
- `GITHUB_OWNER` — normally `JICA98`.
- `GITHUB_REPO` — normally `Bachata-S4-Compatibility`.
- `GITHUB_BASE_BRANCH` — normally `main`.
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

Binary evidence submission is intentionally **disabled** in the current Worker. A later evidence endpoint must not be enabled until all of the following are implemented and covered by tests:

1. allow only PNG/JPEG/WebP based on decoded file contents, not filename/MIME alone;
2. reject SVG, archives, executable/polyglot payloads and unknown formats;
3. cap request size, decoded dimensions and pixel count before persistent storage;
4. fully decode and re-encode server-side to a fresh WebP/JPEG object;
5. strip EXIF/XMP/ICC and other metadata, including location/device metadata;
6. assign content-addressed server-side object names; never trust client paths;
7. store evidence separately from immutable Git history so legal/privacy takedowns remain possible;
8. never accept raw diagnostic logs through the image endpoint;
9. run privacy scanning/redaction on any future diagnostic extract before upload;
10. require the same contributor consent and report association as the structured submission.

Until every requirement above exists, the Worker must continue returning an error whenever a public submission contains `evidence`.

## Moderation and takedowns

An accepted submission is not public compatibility evidence until its draft PR is reviewed and merged. Moderators must reject reports that contain piracy links, private data, fabricated hardware identity, abusive content, or misleading performance claims.

Legal/privacy/security removal must override normal append-only report immutability. Use the project tombstone mechanism once implemented; do not rewrite an ordinary historical report merely to change its result.
