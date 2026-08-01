# Contributing compatibility reports

Compatibility reports must be reproducible, evidence-backed, and tied to one published
Bachata S4 release, one physical Android device, and one selected Vulkan driver.

1. Search Issues for the CUSA ID. Reuse the existing canonical issue or create one with
   the `game:CUSAxxxxx`, `game-report`, and `status:testing` labels.
2. Create a branch and a Git worktree from this repository's `main` branch.
3. Capture screenshots and unmodified logs using the skill in
   `JICA98/Bachata-S4/.agents/skills/bachata-compatibility/SKILL.md`.
4. Add one new report using `scripts/add_report.py` from inside the worktree.
5. Run `python3 scripts/validate.py` and `python3 scripts/build_site_data.py`.
6. Show the report and evidence to the tester. Do not publish before explicit confirmation.
7. After confirmation, push the branch, open a pull request, comment on the canonical
   issue, and update its single `status:*` label to the best confirmed status.

## Status meanings

- `playable`: full completion verified without major game-breaking issues.
- `ingame`: controllable gameplay reached, but major issues or incomplete verification remain.
- `menus`: functional menus reached, but gameplay cannot be entered.
- `boots`: useful visual/audio output before menus.
- `nothing`: crash, hang, or black screen before useful output.

## Immutable evidence

Existing files under `games/*/reports/` and `assets/` may not be modified or deleted.
Submit a new superseding report instead. Do not commit games, firmware, keys, licenses,
account data, ADB serials, or other private information.
