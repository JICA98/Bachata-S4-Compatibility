# Bachata S4 Compatibility Data

This repository is the append-only source of truth for the
[Bachata S4 compatibility website](https://jica98.github.io/Bachata-S4/).
The emulator repository owns the frontend; this repository owns game metadata,
individual test reports, screenshots, compressed logs, schemas, and generated indexes.

## Layout

```text
games/CUSAxxxxx/game.json
 games/CUSAxxxxx/reports/<report-id>.json
assets/CUSAxxxxx/<report-id>/screenshots/*.webp
assets/CUSAxxxxx/<report-id>/logs/*.log.gz
data/releases.json
```

Each CUSA has one canonical GitHub issue. Every confirmed test is a new immutable report
file. Generated files are never edited by hand.

## Validate and build

```bash
python3 scripts/validate.py
python3 scripts/build_site_data.py --output generated
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the issue, evidence, and pull-request flow.
