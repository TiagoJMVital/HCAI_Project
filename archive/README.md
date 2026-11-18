# Historical archive and safety snapshots

The expanded `legacy_v1/` and `pre_cleanup_v2_2026-11-18/` directories are local, SHA-256-verified backups and are excluded from Git to avoid adding hundreds of duplicate files to a commit. They are not part of the active benchmark or Python import path.

`legacy_v1/` preserves 41 old scenarios, independent scenario-annotation files (including six completed forms), the old proposal and A/B results, relevant source code/tests, and the pre-cleanup documentation snapshot. `pre_cleanup_v2_2026-11-18/` preserves the original v2 scenario, proposal, author draft, manifest and B run before their path migration. Each snapshot has `BACKUP_SHA256.json`; the documentation snapshot has a separate checksum file.

The old data and source files also remain recoverable from the repository's Git history after a future commit. The ignored local backups should be retained until the team has verified its own archival/storage policy. Do not treat their labels or outputs as part of the current schema-2 benchmark.
