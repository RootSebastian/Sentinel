# Contributing to Sentinel

Thanks for considering a contribution!

## Getting set up

```bash
git clone https://github.com/RootSebastian/sentinel.git
cd sentinel

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"        # installs the package + pytest

sentinel                       # run the app
```

`rsync` must be installed (on almost every distribution it already is):
`sudo apt install rsync`.

## Running the tests

The test suite runs headless (no display needed):

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

CI runs the same command on every push and pull request.

## Project layout

```
sentinel/            the Python package
    config.py        settings persistence (~/.config/sentinel/)
    history.py       backup run log
    backup_engine.py rsync wrapper + worker thread
    restore_engine.py reverse rsync (bring files back)
    theme.py         design system: themes, QSS, icons, fonts
    widgets.py       reusable styled widgets
    graphs.py        scrolling graphs + sparklines
    ui/              main window + one module per screen
    main.py          entry point (GUI + --backup-now)
tests/               pytest suite (offscreen Qt + real rsync)
tools/               developer utilities (screenshots, icon)
data/                .desktop file, systemd units, app icon
docs/                screenshots and extra documentation
```

## Guidelines

- **Match the design system.** Colors come from `sentinel/theme.py` -
  never hard-code hex values in screens. Use the widget factories
  (`label`, `Card`, `OptionCard`, …) so new UI fits every theme
  automatically.
- **Keep the UI thread free.** Anything slow (rsync, filesystem walks)
  belongs on a `QThread` worker - see `BackupWorker` / `RestoreWorker`
  for the pattern.
- **Backwards compatibility for config.** `~/.config/sentinel/config.json`
  must keep loading after any change; add keys with sensible defaults.
- **Tests for new features.** Engine logic gets real rsync tests
  (`tests/test_engines.py` shows how); UI changes get at least a smoke
  test.
- Small, focused pull requests are easiest to review.

## Reporting bugs

Open an issue with: your distribution, Python version, how you installed,
what you did, what you expected, and any output on the terminal. For
crashes, run from a terminal (`sentinel`) and include the traceback.
