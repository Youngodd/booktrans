"""PyInstaller entry point for the desktop shell."""
import multiprocessing

from booktrans.desktop.shell import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
