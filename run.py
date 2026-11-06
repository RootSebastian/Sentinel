"""Allow `python run.py` from the repository root (same as `python -m sentinel`)."""

from sentinel.main import main

if __name__ == "__main__":
    raise SystemExit(main())
