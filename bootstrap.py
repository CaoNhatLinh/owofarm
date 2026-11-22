"""First-run files for the Windows launcher; uses only Python's standard library."""

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def prepare(root=ROOT):
    """Copy public templates once. Never overwrite local credentials/settings."""
    for template in sorted((root / "config" / "examples").iterdir()):
        target = root / "config" / template.name
        if target.exists():
            continue
        shutil.copyfile(template, target)
    tokens = root / "tokens.txt"
    if not tokens.exists():
        tokens.touch(exist_ok=False)
    return tokens


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check account input before starting")
    args = parser.parse_args()
    if not (3, 12) <= sys.version_info[:2] < (3, 14):
        print("Use Python 3.12 or 3.13 (64-bit).")
        return 1
    tokens = prepare()
    if args.check:
        rows = [line.split() for line in tokens.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        if not rows or any(len(row) != 2 or not row[1].isascii() or not row[1].isdigit()
                           or not 17 <= len(row[1]) <= 20 for row in rows):
            print("Edit tokens.txt: one TOKEN CHANNEL_ID pair per line. Do not share this file.")
            print("See HUONG_DAN_WINDOWS.md for setup instructions.")
            return 1
    print("Local configuration ready. Existing settings and tokens were preserved.")
    print("Dashboard: http://127.0.0.1:1200")
    print("Local dashboard opens without a password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
