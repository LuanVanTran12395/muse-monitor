"""Extension management CLI.

    python -m musemonitor.plugins new "My Extension" [--category EEG] [--dir PATH]
    python -m musemonitor.plugins list
"""
import argparse
import sys

from .loader import default_dir, search_dirs
from .api import CATEGORIES
from .scaffold import create_extension, placement, suggest_category


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m musemonitor.plugins")
    sub = ap.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="create a new extension from the template")
    new.add_argument("name")
    new.add_argument("--dir", default=None, help=f"destination folder (default: {default_dir()})")
    new.add_argument("--category", choices=list(CATEGORIES), default=None,
                     help="menu placement of its panel (default: suggested from the name)")
    sub.add_parser("list", help="list discovered extensions")
    a = ap.parse_args(argv)

    if a.cmd == "new":
        category = a.category or suggest_category(a.name)
        folder = create_extension(a.name, a.dir or default_dir(), category)
        print(f"Created {folder}/__init__.py")
        if a.category is None:
            print(f"Suggested category from the name: {category}" if category != "Other"
                  else "No category suggested from the name: using Other")
        print(*placement(a.name, category), sep="\n")
        print(f'Change `category = "{category}"` in {folder}/__init__.py to move it. '
              "Restart Muse Monitor (or Extensions ▸ Manage ▸ Update) to load it.")
    elif a.cmd == "list":
        from .loader import discover
        print("Search folders:", *([str(d) for d in search_dirs()] or ["(none)"]), sep="\n  ")
        for d in discover():
            state = "error" if d.error else f"{d.cls.name or d.id} {d.cls.version}"
            print(f"- {d.id:20s} {state:30s} {d.source}")
            if d.error: print("    " + d.error.strip().splitlines()[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
