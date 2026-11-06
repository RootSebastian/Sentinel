"""Sentinel - automatic backups and a friendly system monitor for Linux.

Package layout:
    config.py          settings (~/.config/sentinel/config.json)
    history.py         backup run log (~/.config/sentinel/history.json)
    backup_engine.py   rsync wrapper + worker thread
    restore_engine.py  reverse rsync (bring files back) + worker thread
    theme.py           design system: 8 color themes, QSS, icons, fonts
    widgets.py         reusable cards, usage bars, option cards
    graphs.py          scrolling history graphs + sparklines
    ui/                screens and the main window
    main.py            entry point (GUI + `--backup-now` headless mode)
"""

__version__ = "1.2.0"
APP_NAME = "Sentinel"
