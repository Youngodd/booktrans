"""PyInstaller entry point of the installed app: BookTranslator.exe.

`BookTranslator.exe`            opens the window (the shell)
`BookTranslator.exe --sidecar`  runs the local server; the shell starts this copy of itself
"""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()  # needed if anything ever starts worker processes
    if "--sidecar" in sys.argv:
        if sys.stdout is None:  # a windowed program has no console: log to a file, uvicorn needs a stream
            from booktrans.desktop.__main__ import data_dir
            data_dir().mkdir(parents=True, exist_ok=True)
            sys.stdout = sys.stderr = open(data_dir() / "sidecar.log", "a", encoding="utf-8")
        from booktrans.desktop.__main__ import main
    else:
        from booktrans.desktop.shell import main
    main()
