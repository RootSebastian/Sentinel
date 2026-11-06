"""Allow `python -m sentinel` (from the repository root)."""

from sentinel.main import main

if __name__ == "__main__":
    raise SystemExit(main())
