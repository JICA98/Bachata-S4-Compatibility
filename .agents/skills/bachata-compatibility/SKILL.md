---
name: bachata-compatibility
description: Prepare, verify, and submit an evidence-backed Bachata S4 compatibility report for one intended Bachata version/source commit, one physical Android device, and one selected Vulkan driver. Reuse one canonical JICA98/Bachata-S4 issue per CUSA, store immutable report/evidence only in JICA98/Bachata-S4-Compatibility, and publish only after explicit user confirmation. The tested version may be released on GitHub later; never query GitHub Releases to choose or verify the latest release.
---

# Bachata S4 compatibility report workflow

## Repository model

Use the repositories according to their current roles:

- `JICA98/Bachata-S4` `main`: release/community metadata and canonical compatibility issues. It is **not** the maintained emulator-core source checkout.
- `JICA98/Bachata-S4` `gh-pages`: compatibility website/frontend and site/capture helper scripts. Its current Pages build reads `JICA98/Bachata-S4-Compatibility` directly and generates a real static page at `/games/CUSAxxxxx/` for each game.
- `JICA98/Bachata-S4-Compatibility`: append-only compatibility metadata, immutable per-test JSON reports, screenshots, and logs.
- The emulator source/build being tested comes from the development checkout supplied to the agent. Do not assume that checkout is `JICA98/Bachata-S4`, and do not clone the public release repository as a substitute for the tested source tree.

The website is derived directly from compatibility data. Agents do **not** hand-create game pages, permalink files, archived-discussion pages, or site-specific compatibility records. A game report belongs in the compatibility repository; the Pages build generates the public per-game page. The website builder does not require agents to maintain `generated/` indexes.

## Absolute rules

1. Test only content the tester legally owns. Never publish game files, firmware, keys, licenses, accounts, private device identifiers, or the ADB serial.
2. The user/maintainer supplies the intended Bachata version/tag. **Never call GitHub Releases to discover, select, or verify the latest release.** The GitHub release may be published later.
3. Every report must identify the exact source commit used by the tested build. The report's `release.tag` is the intended Bachata version; its `release.commit` is the exact tested source/build commit.
4. Do not fabricate or modify `data/releases.json` merely to make a pre-release report validate. Do not run release-sync logic on the user's behalf unless explicitly asked.
5. Create the compatibility Git worktree **before** creating or changing report files.
6. Search for or create exactly one canonical GitHub issue in `JICA98/Bachata-S4` per CUSA. The issue is for coordination; the website's generated game page is the public game page.
7. Existing report JSON and evidence are immutable. Never rewrite or delete an old test to represent a new run; add a new superseding report.
8. Do not commit, push, open a pull request, change the final issue status, or comment the result until the user explicitly confirms the prepared report.
9. Status is the furthest state actually observed: `playable`, `ingame`, `menus`, `boots`, or `nothing`. When uncertain, choose the lower status.
10. The canonical issue has exactly one final `status:*` label representing the best confirmed result across all reports. A regression must not erase the historically best confirmed status; use `severity:regression` when appropriate.
11. Every confirmed issue update must display at least one safe, representative gameplay screenshot inline. Use screenshots committed with the report and immutable commit URLs.
12. Do not publish local paths, ADB serials, notification content, account names, or other private information.
13. Do not add site-only "permanent link", "archived discussion", `legacyIssues`, or migration logic to a report. Do not manually edit `game.json` unless the compatibility tooling explicitly requires a metadata correction; normally use `scripts/add_report.py`.

## 1. Resolve the tested source checkout and compatibility repository

The current working repository is the source/build checkout being tested unless the caller provides another one.

```bash
SOURCE_ROOT="${BACHATA_SOURCE_ROOT:-$(git rev-parse --show-toplevel)}"
COMPAT_REPO="${BACHATA_COMPAT_REPO:-$(dirname "$SOURCE_ROOT")/Bachata-S4-Compatibility}"
COMPAT_REMOTE="https://github.com/JICA98/Bachata-S4-Compatibility.git"
SITE_REPO="${BACHATA_SITE_REPO:-$(dirname "$SOURCE_ROOT")/Bachata-S4-site}"
SITE_REMOTE="https://github.com/JICA98/Bachata-S4.git"

command -v gh adb git python3 >/dev/null
gh auth status

if [[ ! -d "$COMPAT_REPO/.git" ]]; then
  git clone "$COMPAT_REMOTE" "$COMPAT_REPO"
fi

git -C "$COMPAT_REPO" remote set-url origin "$COMPAT_REMOTE"
git -C "$COMPAT_REPO" fetch origin main --prune
```

Set the concrete test identity. CUSA must be uppercase.

```bash
export CUSA=CUSAxxxxx
export GAME_TITLE="Exact game title"
export BACHATA_RELEASE=v0.x.y          # intended version/tag supplied by maintainer
export DEVICE_LABEL="OnePlus 13 · Snapdragon 8 Elite"
```

Resolve the **tested source commit locally**, not from a GitHub release/tag lookup:

```bash
export TEST_COMMIT="${BACHATA_TEST_COMMIT:-$(git -C "$SOURCE_ROOT" rev-parse HEAD)}"

git -C "$SOURCE_ROOT" cat-file -e "$TEST_COMMIT^{commit}"
printf 'Tested version: %s\nTested commit: %s\n' "$BACHATA_RELEASE" "$TEST_COMMIT"
```

Do not infer `BACHATA_RELEASE` from the newest GitHub Release. Do not run `gh release view`, `gh release list`, release APIs, or a "latest release" lookup.

The exact commit must describe the installed/tested build. If the working tree is dirty and the installed APK includes uncommitted changes, stop and get a reproducible commit identity before creating a public report. A commit SHA that omits local changes is not valid provenance.

## 2. Create the compatibility worktree first

Use a unique branch and sibling worktree. Never stage reports directly in the main compatibility clone.

```bash
STAMP="$(date -u +%Y%m%d-%H%M%S)"
REPORT_BRANCH="compat/${CUSA,,}-$STAMP"
WORKTREE_ROOT="${BACHATA_WORKTREE_ROOT:-$(dirname "$COMPAT_REPO")/.worktrees}"
COMPAT_WORKTREE="$WORKTREE_ROOT/bachata-compat-${CUSA,,}-$STAMP"
mkdir -p "$WORKTREE_ROOT"

git -C "$COMPAT_REPO" worktree add -b "$REPORT_BRANCH" \
  "$COMPAT_WORKTREE" origin/main
```

All compatibility-repository scripts after this point run from `$COMPAT_WORKTREE`.

## 3. Find or create the canonical issue

Ensure the shared label taxonomy exists:

```bash
"$COMPAT_WORKTREE/scripts/setup_labels.sh" JICA98/Bachata-S4
```

Search open and closed issues by exact CUSA. Match the `[CUSAxxxxx]` title prefix exactly; never accept a substring match or create a second issue for the same CUSA.

```bash
ISSUE_NUMBER="$(gh issue list --repo JICA98/Bachata-S4 \
  --state all --search "\"$CUSA\" in:title" --json number,title \
  --jq ".[] | select(.title | test(\"^\\\\[$CUSA\\\\]( |$)\")) | .number" | head -n1)"
```

Create an issue only when no exact match exists:

```bash
if [[ -z "$ISSUE_NUMBER" ]]; then
  ISSUE_URL="$(gh issue create --repo JICA98/Bachata-S4 \
    --title "[$CUSA] $GAME_TITLE" \
    --label "type:compatibility,triage:new,status:testing" \
    --body "Compatibility tracking for **$GAME_TITLE** ($CUSA). Confirmed device/driver/version tests are stored as immutable reports in JICA98/Bachata-S4-Compatibility.")"
  ISSUE_NUMBER="${ISSUE_URL##*/}"
else
  # Keep the existing best confirmed status label while a new run is in progress.
  gh issue edit "$ISSUE_NUMBER" --repo JICA98/Bachata-S4 \
    --add-label "type:compatibility"
fi
```

Read the issue and existing reports before testing so the new run addresses known blockers:

```bash
gh issue view "$ISSUE_NUMBER" --repo JICA98/Bachata-S4 --comments
find "$COMPAT_WORKTREE/games/$CUSA/reports" -maxdepth 1 -name '*.json' -print 2>/dev/null | sort
```

Do not create or manipulate old "archived discussion" records. Do not add another issue reference merely because a game had older discussions elsewhere.

## 4. Select the physical device and exact Vulkan driver

```bash
adb devices -l
export SERIAL=<exact-adb-serial>
```

When multiple devices exist, `$SERIAL` is mandatory. It may appear in temporary private capture metadata, but never in report JSON or public comments.

In Bachata S4, select the driver and record what is actually displayed or logged:

- Turnip: type, name, exact Mesa/Turnip version, and when available build/revision/source.
- System: driver name and observed version.
- Custom: exact name and version.

Do not confuse Android version, Vulkan API version, GPU model, or a driver bundle filename with the Turnip version.

## 5. Capture the test

Prefer the capture helper shipped with the current website branch. Resolve it without treating the public release repository as the emulator source checkout:

```bash
if [[ -x "$SOURCE_ROOT/scripts/compatibility/capture_android_report.sh" ]]; then
  CAPTURE_HELPER="$SOURCE_ROOT/scripts/compatibility/capture_android_report.sh"
else
  if [[ ! -d "$SITE_REPO/.git" ]]; then
    git clone --single-branch --branch gh-pages "$SITE_REMOTE" "$SITE_REPO"
  else
    git -C "$SITE_REPO" fetch origin gh-pages --prune
    git -C "$SITE_REPO" checkout gh-pages
    git -C "$SITE_REPO" reset --hard origin/gh-pages
  fi
  CAPTURE_HELPER="$SITE_REPO/scripts/compatibility/capture_android_report.sh"
fi

[[ -x "$CAPTURE_HELPER" ]]
"$CAPTURE_HELPER" --help || true
```

Example Turnip capture, using the intended release label without any GitHub Release lookup:

```bash
cd "$SOURCE_ROOT"
"$CAPTURE_HELPER" "$CUSA" \
  --release-tag "$BACHATA_RELEASE" \
  --device-label "$DEVICE_LABEL" \
  --driver-type turnip \
  --driver-name "Mesa Turnip" \
  --turnip-version "26.3.0-devel" \
  --turnip-build "git-exactrevision" \
  --turnip-source "bundled/imported source label" \
  --delay 60 --count 2 --interval 30
```

If the helper cannot launch the installed build, inspect `--help` and use its supported manual/no-launch mode rather than changing the report identity.

Assign the printed evidence directory to `CAPTURE` and inspect it:

```bash
export CAPTURE="<absolute evidence directory>"
cat "$CAPTURE/device.json"
cat "$CAPTURE/capture.json"   # private; never publish
find "$CAPTURE/session-logs" -type f -maxdepth 3 -print
find "$CAPTURE/screenshots" -type f -maxdepth 1 -print
```

Inspect the screenshots and relevant log lines. Do not infer gameplay from launch success or a single log line. Discard blank, private, or misleading screenshots. Keep collected logs byte-for-byte; the report importer handles public evidence storage, compression, and hashing.

## 6. Stage one immutable report

Use the canonical issue number, intended Bachata version, and the exact tested commit. Add one `--screenshot` and one `--log` argument per selected evidence file. `path::caption` and `path::label` are supported.

```bash
cd "$COMPAT_WORKTREE"

python3 scripts/add_report.py \
  --title "$GAME_TITLE" \
  --cusa "$CUSA" \
  --region US \
  --publisher "Publisher" \
  --issue-number "$ISSUE_NUMBER" \
  --issue-repository JICA98/Bachata-S4 \
  --status ingame \
  --game-version "01.00" \
  --release-tag "$BACHATA_RELEASE" \
  --commit "$TEST_COMMIT" \
  --emulator-version "${BACHATA_RELEASE#v}" \
  --guest-backend fex \
  --summary "Exact one-sentence observed result." \
  --notes "What was tested, how far it progressed, settings, and the blocker." \
  --issue "Major reproducible problem, when present" \
  --device-json "$CAPTURE/device.json" \
  --driver-type turnip \
  --driver-name "Mesa Turnip" \
  --driver-version "26.3.0-devel" \
  --driver-build "git-exactrevision" \
  --driver-source "bundled/imported source label" \
  --resolution-scale 1.0 \
  --average-fps 30 --min-fps 24 --max-fps 35 \
  --frame-pacing stuttery \
  --test-duration-seconds 300 \
  --screenshot "$CAPTURE/screenshots/first.png::What this proves" \
  --screenshot "$CAPTURE/screenshots/second.png::What this proves" \
  --log "$CAPTURE/session-logs/<session>/application.log::Bachata application log" \
  --log "$CAPTURE/session-logs/<session>/shadps4.log::shadPS4 session log" \
  --tester "$(gh api user --jq .login)"
```

FPS fields are optional unless measured by a real counter or trace. Never invent performance values.

`add_report.py` owns the current report/game schema. Do not hand-add site permalink fields, archived discussions, or migration metadata.

### Pre-release validation rule

The current compatibility validator still requires every report's release tag to exist in local `data/releases.json`. Because the maintainer may publish the GitHub Release later, a brand-new intended tag can be absent during testing.

Check the **local compatibility index only**; do not query GitHub Releases:

```bash
if python3 - "$BACHATA_RELEASE" <<'PY'
import json, pathlib, sys
wanted = sys.argv[1]
p = pathlib.Path('data/releases.json')
if not p.exists():
    raise SystemExit(1)
data = json.loads(p.read_text(encoding='utf-8'))
raise SystemExit(0 if any(x.get('tag') == wanted for x in data.get('releases', [])) else 1)
PY
then
  python3 scripts/validate.py
  rm -rf generated
  python3 scripts/build_site_data.py --output generated
  VALIDATION_STATE="full validation passed"
else
  echo "Intended release $BACHATA_RELEASE is not yet in local data/releases.json."
  echo "Do not fabricate release metadata and do not query GitHub Releases."
  VALIDATION_STATE="pre-release: local release index pending"
fi
```

When the intended release is not yet indexed, perform integrity checks on the newly staged report/evidence rather than pretending the repository-wide validator passed:

```bash
python3 - "$COMPAT_WORKTREE" "$CUSA" "$BACHATA_RELEASE" "$TEST_COMMIT" "$ISSUE_NUMBER" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
cusa, tag, commit, issue = sys.argv[2:]
reports = sorted((root / 'games' / cusa / 'reports').glob('*.json'), key=lambda p: p.stat().st_mtime)
assert reports, 'no report created'
p = reports[-1]
r = json.loads(p.read_text(encoding='utf-8'))
assert r['cusaId'] == cusa
assert r['release']['tag'] == tag
assert r['release']['commit'].lower() == commit.lower()
assert str(r['issueNumber']) == str(issue)
assert r.get('issueRepository', 'JICA98/Bachata-S4') == 'JICA98/Bachata-S4'
shots = r['evidence']['screenshots']
logs = r['evidence']['logs']
assert 1 <= len(shots) <= 3
assert len(logs) >= 1
for entry in [*shots, *logs]:
    rel = entry['path']
    f = root / rel
    assert f.is_file(), f'missing evidence: {rel}'
    if entry.get('sha256'):
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        assert got == entry['sha256'], f'hash mismatch: {rel}'
print(f'Pre-release integrity checks passed: {p.relative_to(root)}')
PY
```

A missing future tag in `data/releases.json` is a **known temporary release-index condition**, not permission to weaken evidence requirements. The website itself can build directly from report data, but the compatibility repository's current PR validation still rejects a report whose tag is absent from `data/releases.json`. The maintainer will publish/update release metadata later. The agent must not invent it.

## 7. Review the prepared report and request explicit confirmation

Before publication, show the user:

- CUSA and exact game title;
- canonical issue number;
- observed status and why it meets that boundary;
- **intended** Bachata version/tag (do not call it a published GitHub release unless the user says it is published);
- exact tested source commit;
- selected public device identity;
- selected driver and exact Turnip version/build when applicable;
- measured performance only when actually measured;
- screenshot thumbnails/paths and log names/hashes;
- the exact one to three screenshots that will be embedded in the canonical issue comment;
- `git -C "$COMPAT_WORKTREE" diff --stat`;
- validation state: either `full validation passed` or `pre-release: local release index pending; integrity checks passed`.

Ask for explicit confirmation to publish **this exact report**. Stop here until confirmation. Silence, previous general permission, or successful validation is not confirmation.

Do not create a website page manually for the preview. The current Pages workflow generates the per-game page from compatibility data after deployment.

### If the intended release is not indexed yet

The default is **do not push a deliberately red compatibility PR**. `JICA98/Bachata-S4-Compatibility` currently runs `scripts/validate.py` on every pull request, and that validator still requires the report tag in `data/releases.json`.

After the user confirms the report, keep the prepared worktree/branch intact and report:

- the local report path/report ID;
- the intended version and tested commit;
- the evidence files/hashes;
- that report integrity checks passed;
- that publication is blocked only by maintainer-owned release indexing.

Do **not** query GitHub Releases, create a GitHub Release, invoke release-sync workflows, edit `data/releases.json`, change the report to an older tag, or push a PR expected to fail. Resume publication when the maintainer explicitly says release/indexing is ready (or explicitly instructs you to push despite the expected validation failure).

When resuming, refresh only the compatibility repository and re-check its **local** release index:

```bash
git -C "$COMPAT_REPO" fetch origin main --prune
git -C "$COMPAT_WORKTREE" rebase origin/main
cd "$COMPAT_WORKTREE"
python3 scripts/validate.py
rm -rf generated
python3 scripts/build_site_data.py --output generated
```

No GitHub Releases lookup is needed at any point.

## 8. Publish only after explicit confirmation and release-index readiness

Determine the best confirmed status across the existing reports plus the newly confirmed report:

```text
playable > ingame > menus > boots > nothing
```

Do not downgrade the issue's historically best confirmed status because a newer build/device/driver regresses. Retain the best `status:*` label and add `severity:regression` when the new report demonstrates a regression.

Stage only compatibility data/evidence:

```bash
cd "$COMPAT_WORKTREE"
git add games assets

mapfile -t ISSUE_SCREENSHOTS < <(
  git diff --cached --name-only --diff-filter=A -- assets \
    | grep -Ei '/screenshots/.*\.(png|jpe?g|webp)$' \
    | head -n 3
)

if (( ${#ISSUE_SCREENSHOTS[@]} == 0 )); then
  echo "No safe staged screenshot found; refusing to publish an issue update without visual evidence." >&2
  exit 1
fi
```

Commit and push the report branch:

```bash
git commit -m "compat($CUSA): add $BACHATA_RELEASE report"
REPORT_COMMIT="$(git rev-parse HEAD)"
git push -u origin "$REPORT_BRANCH"
```

Open the PR only after the local compatibility index contains the intended tag and full validation/build has passed, unless the user explicitly overrides this rule:

```bash
PR_URL="$(gh pr create --repo JICA98/Bachata-S4-Compatibility \
  --base main --head "$REPORT_BRANCH" \
  --title "compat($CUSA): $GAME_TITLE on $BACHATA_RELEASE" \
  --body "Canonical issue: https://github.com/JICA98/Bachata-S4/issues/$ISSUE_NUMBER

- Status: <status>
- Device: $DEVICE_LABEL
- Driver: <exact driver/version>
- Bachata version: $BACHATA_RELEASE
- Tested source commit: $TEST_COMMIT
")"
```

If validation is blocked only because the future tag is absent from `data/releases.json`, return to the release-index-pending state above. Do **not** query GitHub for another release, change the tested tag, add fake release entries, or rewrite the report. The maintainer controls release publication/indexing.

### Update the canonical issue

After confirmation, update the issue to exactly one best final `status:*` label. Remove `status:testing` when it is the current status. Do not remove a better historical status because of a regression.

Then post one concise comment with the report summary and one to three screenshots rendered inline. Build image URLs from the **pushed report commit SHA**, not a local path or mutable branch name:

```bash
ISSUE_COMMENT="$(mktemp)"
cat > "$ISSUE_COMMENT" <<EOF2
Confirmed compatibility report submitted: $PR_URL

- **Status:** <status>
- **Intended Bachata version:** $BACHATA_RELEASE
- **Tested source commit:** \`$TEST_COMMIT\`
- **Device:** $DEVICE_LABEL
- **Driver:** <exact driver/version>
- **Evidence commit:** \`$REPORT_COMMIT\`

### Screenshots
EOF2

for screenshot_path in "${ISSUE_SCREENSHOTS[@]}"; do
  encoded_path="${screenshot_path// /%20}"
  printf '\n![%s — %s — %s](https://raw.githubusercontent.com/JICA98/Bachata-S4-Compatibility/%s/%s)\n' \
    "$GAME_TITLE" "$BACHATA_RELEASE" "<status>" \
    "$REPORT_COMMIT" "$encoded_path" >> "$ISSUE_COMMENT"
done

gh issue comment "$ISSUE_NUMBER" --repo JICA98/Bachata-S4 \
  --body-file "$ISSUE_COMMENT"
rm -f "$ISSUE_COMMENT"
```

Open the issue after commenting and verify every selected image renders correctly. If an image is broken, private, blank, or misleading, edit/delete the comment and replace it with safe evidence from the same report.

The agent does **not** create or update a site permalink. After the compatibility report reaches the data branch consumed by Pages and the site deploys, the website build generates the game's permanent static page at `https://bachatas4.games/games/$CUSA/` from the CUSA data and screenshots.

## 9. Cleanup

After the PR is merged or abandoned:

```bash
git -C "$COMPAT_REPO" worktree remove "$COMPAT_WORKTREE"
git -C "$COMPAT_REPO" worktree prune
```

On user rejection, do not push. Remove the temporary worktree and local branch. If the agent created a brand-new issue whose only state is `status:testing`, remove that temporary status or close the issue only when the user asks; do not disturb an existing game's confirmed status/history.
