"""Entry point of the packaged app (PyInstaller): the same main() as `python -m musemonitor`."""
import sys

from musemonitor.app import main

if __name__ == "__main__":
    sys.exit(main())
