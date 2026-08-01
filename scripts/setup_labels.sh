#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-JICA98/Bachata-S4-Compatibility}"
create() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force; }
create game-report 1d76db "Canonical game compatibility discussion"
create needs-confirmation fbca04 "Waiting for tester confirmation"
create regression d73a4a "A previously working result regressed"
create status:testing 6e7781 "A test is currently being prepared"
create status:playable 2da44e "Full completion verified without major blockers"
create status:ingame 1f883d "Controllable gameplay reached"
create status:menus d4c5f9 "Functional menus reached"
create status:boots fbca04 "Useful output before menus"
create status:nothing da3633 "Crash, hang, or black screen before useful output"
