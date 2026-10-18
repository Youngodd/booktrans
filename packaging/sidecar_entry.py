"""PyInstaller entry point for the desktop sidecar (a script, so no relative imports)."""
import multiprocessing

from booktrans.desktop.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed if anything ever starts worker processes
    main()
