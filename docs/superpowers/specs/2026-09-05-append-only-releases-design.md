# Append-only release index design

Date: 2026-09-05  
Status: Approved for planning  
Approach: Merge-in-place sync (Approach A)

## Problem

`scripts/sync_releases.py` fully rewrites `data/releases.json` from the GitHub Releases API and always refreshes `generatedAt`. When GitHub stops exposing older releases, the index loses those tags. The six-hour sync workflow can also create empty commits when only `generatedAt` changes.

Compatibility reports are immutable and may reference release tags that are not (yet) published on GitHub. Validation currently rejects those reports.

## Goals

1. Make the release index append-only: never delete an existing entry.
2. Upsert currently published GitHub releases into the index.
3. Mark releases no longer returned by GitHub as `archived: true` with `latest: false`.
4. Update `generatedAt` only when release metadata actually changes; skip pointless writes.
5. Allow reports whose `release.tag` is missing from `data/releases.json`.

## Non-goals

- Restoring historical tags `v0.1.0-alpha` through `v0.1.7` into the index (deferred).
- Site UI treatment of `archived`.
- Adding a JSON Schema for the release index.
- Auto-inserting tags from `add_report.py`.
- Unrelated stashed WIP on this machine.

## Data model

`data/releases.json` remains the single release index:

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-09-05T10:44:16Z",
  "repository": "JICA98/Bachata-S4",
  "releases": [
    {
      "tag": "v0.1.9",
      "name": "BachataS4 v0.1.9",
      "url": "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.9",
      "publishedAt": "2026-08-29T07:42:43Z",
      "prerelease": false,
      "latest": true
    },
    {
      "tag": "v0.1.8",
      "name": "BachataS4 v0.1.8",
      "url": "https://github.com/JICA98/Bachata-S4/releases/tag/v0.1.8",
      "publishedAt": "2026-08-29T07:43:02Z",
      "prerelease": false,
      "latest": false,
      "archived": true
    }
  ]
}
```

New optional field on each release entry:

- `archived` (boolean): `true` when the tag is not present in the current non-draft GitHub Releases response; omit or `false` when live.

Existing fields (`tag`, `name`, `url`, `publishedAt`, `prerelease`, `latest`) are unchanged in meaning.

Current committed index keeps `v0.1.8` and `v0.1.9` only; no historical backfill in this change.

## Sync algorithm (`scripts/sync_releases.py`)

1. Load existing `data/releases.json` if present and valid; otherwise start from an empty releases list.
2. Fetch GitHub Releases for `JICA98/Bachata-S4`; ignore drafts.
3. Compute `latest` as the first non-prerelease tag among currently published releases (same selection rule as today).
4. For each published GitHub release, upsert by `tag`:
   - set `name`, `url`, `publishedAt`, `prerelease`
   - set `latest` from step 3
   - set `archived` to `false` (or omit)
5. For each existing index entry whose `tag` is absent from the published set:
   - keep the entry
   - set `latest` to `false`
   - set `archived` to `true`
   - leave other last-known fields unchanged
6. Never delete an existing entry.
7. Sort stably for readable diffs: non-archived first by `publishedAt` descending, then archived by `publishedAt` descending (missing dates last).
8. Compare the new `releases` array (and other non-`generatedAt` top-level fields) to the previous file:
   - if unchanged: do not write the file (preserve previous `generatedAt`)
   - if changed: set `generatedAt` to now (UTC, second precision, `Z` suffix) and write

### Error handling

- GitHub API failure: exit non-zero; leave `data/releases.json` untouched.
- Corrupt existing file: treat as empty index and rebuild from GitHub for this run; subsequent runs remain append-only.

## Validation (`scripts/validate.py`)

- Remove the hard failure: `release tag is not in data/releases.json`.
- Keep other release checks (for example `release.commit` SHA shape).
- Keep the requirement that `data/releases.json` exists and contains at least one release.
- Optional non-failing note for missing tags is allowed but not required for the first implementation.

## Consumers

- `scripts/build_site_data.py` continues to copy `data/releases.json` through unchanged; `archived` is transparent extra metadata.
- `.github/workflows/sync-releases.yml` already commits only when `git diff` detects changes to `data/releases.json`; conditional `generatedAt` makes that guard effective.

## Testing

Fixture-based tests (mock GitHub payload + existing index):

1. New published tag is added.
2. Existing published tag metadata is updated.
3. Tag missing from GitHub is retained with `archived: true` and `latest: false`.
4. No metadata change results in no file write / unchanged `generatedAt`.
5. `validate.py` accepts a report whose `release.tag` is absent from the index.

## Success criteria

1. Re-running sync against an unchanged GitHub set does not modify `data/releases.json`.
2. If GitHub drops a previously indexed tag, the entry remains with `archived: true` and `latest: false`.
3. New GitHub releases are upserted and `latest` is recomputed from live non-prerelease tags.
4. Validation accepts reports that reference tags not present in the index.

## Files expected to change

- `scripts/sync_releases.py`
- `scripts/validate.py`
- Tests under `tests/` (new or extended)
- This design doc under `docs/superpowers/specs/`
