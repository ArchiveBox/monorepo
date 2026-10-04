# Scheduled documentation and galleries

The five core repositories run their documentation suites twice daily. ArchiveBox,
Android, Electron, Apple, and browser-extension galleries use separate twice-daily
slots. Each workflow first checks this action; unchanged inputs skip the expensive
jobs. Existing manual entry points remain available. Android and Electron manual
runs opt into galleries with `capture_gallery`.

The comparison key contains the workflow's source commit and, where applicable,
the resolved ArchiveBox backend commit or published Docker version. Capture jobs
must use the returned backend value so a moving ref cannot change mid-run.

A final job named `Scheduled inputs: KEY` records successful completion. The action
finds the latest successful scheduled or manual run of the same workflow and
branch with this checkpoint. A skipped checkpoint on an unchanged run retains the
same baseline. Ordinary app build runs have no valid checkpoint key. Failed or
cancelled workflows never advance the baseline and are tried again at the next
slot. With no prior checkpoint, the first run executes all scheduled work.

The small change-check job still runs at each scheduled slot. GitHub may delay cron
execution. Source changes are compared by commit, including dependency-lock and
workflow changes; these checks do not depend on time-based caches or mutable tags.

Publish this shared action to `ArchiveBox/monorepo` on `main` before publishing the
dependent workflows. Screenshot artifact consumers must accept `schedule` events
while retaining their existing repository, branch, provenance, and checksum checks.
