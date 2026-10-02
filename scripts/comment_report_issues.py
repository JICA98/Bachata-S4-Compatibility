#!/usr/bin/env python3
"""Post each merged compatibility report to its game's canonical GitHub issue.

The comment shows the first screenshot and links every log, all pinned to the
commit that added the report, so a game's issue collects its whole history.
Comments carry a hidden marker, so re-running never posts the same report twice.

  --before SHA --after SHA   reports added between two commits (push events)
  --all                      every report (backfill)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPOSITORY = "JICA98/Bachata-S4-Compatibility"
SITE = "https://bachatas4.games"
API = "https://api.github.com"
STATUS_EMOJI = {"playable": "🟢", "ingame": "🔵", "menus": "🟡", "boots": "🟠", "nothing": "🔴"}


def marker(report_id: str) -> str:
    return f"<!-- bachata-report:{report_id} -->"


def report_id(report: dict, path: str) -> str:
    return str(report.get("reportId") or Path(path).stem)


def raw_url(sha: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{REPOSITORY}/{sha}/{path}"


def blob_url(sha: str, path: str) -> str:
    return f"https://github.com/{REPOSITORY}/blob/{sha}/{path}"


def md(value) -> str:
    """Single-line text safe inside a markdown table cell."""
    return " ".join(str(value).split()).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def device_label(report: dict) -> str:
    device = report.get("device") or {}
    if device.get("label"):
        return device["label"]
    name = " ".join(v for v in (device.get("manufacturer"), device.get("model")) if v)
    soc = device.get("socName") or device.get("soc")
    return " · ".join(v for v in (name, soc) if v) or "Unknown device"


def driver_label(report: dict) -> str:
    driver = report.get("driver") or {}
    return " ".join(str(v) for v in (driver.get("name") or driver.get("type"), driver.get("version")) if v) or "Unknown driver"


def fps_label(report: dict) -> str | None:
    perf = report.get("performance") or {}
    avg = perf.get("nativeAverageFps", perf.get("averageFps"))
    if not isinstance(avg, (int, float)):
        return None
    low = perf.get("nativeOnePercentLowFps", perf.get("minimumFps"))
    text = f"{avg:.1f} avg"
    if isinstance(low, (int, float)):
        text += f" · {low:.1f} low"
    if perf.get("framePacing"):
        text += f" · {perf['framePacing']} pacing"
    return text


def emulator_version(report: dict) -> str:
    release = report.get("release") or {}
    tag = release.get("tag")
    if tag and tag != "unreleased":
        return tag
    # Builds before the release-tag fix reported "unreleased"; the app build still names the version.
    build = report.get("emulatorVersion") or (report.get("provenance") or {}).get("appBuild")
    if not build:
        return "unreleased"
    version = build if str(build).startswith("v") else f"v{build}"
    return f"{version} ({release['commit'][:7]})" if release.get("commit") else version


def build_comment(report: dict, path: str, sha: str) -> str:
    status = str(report.get("status") or "unknown").lower()
    release = emulator_version(report)
    evidence = report.get("evidence") or {}
    shots = [s for s in evidence.get("screenshots") or [] if isinstance(s, dict) and s.get("path")]
    logs = [l for l in [*(evidence.get("logs") or []), *(evidence.get("diagnostics") or [])] if isinstance(l, dict) and l.get("path")]
    cusa = report.get("cusaId", "")

    rows = [
        ("Device", device_label(report)),
        ("GPU", (report.get("device") or {}).get("gpu")),
        ("Driver", driver_label(report)),
        ("Game version", (report.get("game") or {}).get("version") or report.get("gameVersion")),
        ("FPS", fps_label(report)),
        ("Tested", str(report.get("testedAt") or "")[:10]),
        ("Tester", (report.get("contributor") or {}).get("publicId") or report.get("tester")),
    ]
    # The emulator version leads, so the issue reads as a per-release history of the game.
    lines = [marker(report_id(report, path)), f"### Bachata S4 {md(release)} · {STATUS_EMOJI.get(status, '⚪')} {status.capitalize()} on {md(device_label(report))}", ""]
    lines += ["| | |", "|---|---|"] + [f"| {k} | {md(v)} |" for k, v in rows if v] + [""]
    summary = (report.get("result") or {}).get("summary") or report.get("summary")
    notes = (report.get("result") or {}).get("notes") or report.get("notes")
    if summary:
        lines += [f"> {md(summary)}", ""]
    if notes:
        lines += ["<details><summary>Tester notes</summary>", "", md(notes), "", "</details>", ""]
    if shots:
        first = shots[0]
        alt = md(first.get("caption") or f"{cusa} screenshot").replace("[", "(").replace("]", ")")
        lines += [f"[![{alt}]({raw_url(sha, first['path'])})]({blob_url(sha, first['path'])})", ""]
        if len(shots) > 1:
            lines += [f"{len(shots) - 1} more screenshot{'s' if len(shots) > 2 else ''} on the [game page]({SITE}/games/{cusa}/).", ""]
    if logs:
        lines += ["**Logs**"] + [f"- [{md(l.get('label') or Path(l['path']).name)}]({blob_url(sha, l['path'])})" for l in logs] + [""]
    lines += [f"[Report JSON]({blob_url(sha, path)}) · [Game page]({SITE}/games/{cusa}/) · commit `{sha[:7]}`"]
    return "\n".join(lines) + "\n"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def added_reports(before: str, after: str) -> list[tuple[str, str]]:
    out = git("diff", "--diff-filter=A", "--name-only", f"{before}..{after}", "--", "games/*/reports/*.json")
    return [(path, after) for path in out.split()]


def all_reports() -> list[tuple[str, str]]:
    found = []
    for path in sorted(str(p) for p in Path("games").glob("CUSA*/reports/*.json")):
        sha = git("log", "--diff-filter=A", "--format=%H", "-1", "--", path).strip() or git("rev-parse", "HEAD").strip()
        found.append((path, sha))
    return found


def canonical_issue(cusa_dir: Path) -> int | None:
    try:
        game = json.loads((cusa_dir / "game.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ref = game.get("canonicalIssue") or {}
    return ref.get("number") if ref.get("repository") == REPOSITORY and isinstance(ref.get("number"), int) else None


def github(method: str, path: str, token: str, body: dict | None = None):
    request = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "bachata-report-comments",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def posted_markers(issue: int, token: str) -> set[str]:
    seen, page = set(), 1
    while True:
        comments = github("GET", f"/repos/{REPOSITORY}/issues/{issue}/comments?per_page=100&page={page}", token)
        for comment in comments:
            body = comment.get("body") or ""
            if "<!-- bachata-report:" in body:
                seen.add(body.split("<!-- bachata-report:", 1)[1].split(" -->", 1)[0])
        if len(comments) < 100:
            return seen
        page += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print comments instead of posting")
    args = parser.parse_args()
    if args.all:
        reports = all_reports()
    elif args.before and args.after and set(args.before) != {"0"}:
        reports = added_reports(args.before, args.after)
    else:
        print("Nothing to compare; pass --all or --before/--after.")
        return 0
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token and not args.dry_run:
        print("GITHUB_TOKEN is required to post comments", file=sys.stderr)
        return 1

    seen: dict[int, set[str]] = {}
    posted = skipped = 0
    for path, sha in sorted(reports, key=lambda item: item[0]):
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        issue = canonical_issue(Path(path).parent.parent)
        if issue is None:
            print(f"skip {path}: no canonical issue in {REPOSITORY}")
            skipped += 1
            continue
        rid = report_id(report, path)
        body = build_comment(report, path, sha)
        if args.dry_run:
            print(f"--- #{issue} {path}\n{body}")
            continue
        if issue not in seen:
            seen[issue] = posted_markers(issue, token)
        if rid in seen[issue]:
            skipped += 1
            continue
        github("POST", f"/repos/{REPOSITORY}/issues/{issue}/comments", token, {"body": body})
        seen[issue].add(rid)
        posted += 1
        print(f"posted {path} -> #{issue}")
    print(f"{posted} posted, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
