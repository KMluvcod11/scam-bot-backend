"""One-time backfill for existing LINE groups with unknown member counts."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detection_history import sync_missing_group_members


if __name__ == "__main__":
    result = sync_missing_group_members()
    print(f"Missing groups: {result['missing']}; updated: {result['updated']}")
