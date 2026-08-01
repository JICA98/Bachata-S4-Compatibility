# Legacy Sonic Mania migration

The initial Sonic Mania screenshots are already stored here. Before deleting the old
compatibility assets from `Bachata-S4`, fetch the two existing compressed logs into this
repository and verify their original SHA-256 hashes:

```bash
python3 scripts/migrate_legacy_sonic.py --main-root ../Bachata-S4
python3 scripts/validate.py
```

The migration first copies from the supplied local Bachata-S4 clone and falls back to GitHub's public Contents API. It writes the logs below the immutable report
evidence directory, verifies both hashes, and replaces the temporary legacy URLs with local
paths. Future reports always store logs locally from the start.
