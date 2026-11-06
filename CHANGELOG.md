# Changelog

All notable changes to Sentinel are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-06

### Added
- **History & Restore screen** - every backup run is logged (date, status,
  files, size, duration) and stays visible across restarts. Headless
  `--backup-now` runs (systemd timer / cron) are logged too.
- **Restore** - bring files back from any backup:
  - quick flow: one click per backed-up folder, pick a target, done
  - advanced picker: browse the backup as a checkable file tree and tick
    individual files or folders; unchecking something inside a checked
    folder excludes just that item
  - restores never delete anything and default to a fresh
    `~/Sentinel restored/…` folder
- Sidebar now has six pages (`Ctrl+1` … `Ctrl+6`); the Dashboard's
  "Last backup" card links to the new screen.
- Backups now record how much data moved (files + bytes), shown in history.

### Changed
- **Project structure** - reorganized into an installable Python package
  (`python -m sentinel`, `pip install -e .`, `sentinel` console command)
  with tests, CI, packaging metadata and docs - GitHub-ready.
- `run_rsync` now returns `(ok, message, stats)` with rsync `--stats`
  numbers; internal rsync output handling is shared with the restore
  engine.

## [1.1.0] - 2026-11-03

### Added
- UI/UX redesign: sidebar navigation, dashboard, cards, sparklines.
- Eight color themes (six dark, two light) with live switching from
  Settings or the sidebar; the choice persists.
- First-run setup wizard, system tray with notifications, process
  search/end-task, `Ctrl+1..5` shortcuts.

## [1.0.0] - 2026-11-02

### Added
- Initial release: rsync backups (incremental / mirror / full copy),
  destination and schedule configuration, in-app scheduler, live progress
  and log, task manager and system monitor (CPU, memory, network, disks).
