# ADR 0064: The number of backups to keep is a setting

Status: accepted (2026-10-16). Changes the retention rule of FR-SY-06; asked for by the owner.

## Context
Backups were pruned by a fixed rule: the 14 newest plus the newest of each of the 8 previous weeks. The owner wants to choose how many are kept.

## Decision
- New setting `backups_keep` in the Retention section: a whole number from 1 to 365, default 5.
- Pruning keeps the newest `backups_keep` regular backups and deletes the rest. The weekly tier is gone, so the setting means what it says.
- The prune runs whenever a backup is made: the nightly job, "Back up now" and `folio backup`, all with the saved number. The pre-migration and pre-restore safety copies are limited separately to 5 each, as before; files that are not backups are never touched.
- The setting is edited in the Backups panel on the System page (and appears in Settings, Retention).

## Consequences
Existing installs go from up to 22 kept backups to 5 at the next backup; raise the number first to keep more. A restore always takes a safety copy first, so lowering the number never removes that.
