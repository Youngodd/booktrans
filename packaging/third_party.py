"""List the licenses of the packages the desktop app bundles, from their installed metadata.

usage: python packaging/third_party.py > table.md     (run in the environment the app is built from)
Walks the dependencies of the packages in requirements-web.txt plus pywebview and keyring. The
"AGPL-3.0 compatible?" column is a rough guide from the license name, not legal advice; "check" means
read the license yourself.
"""
import re
import sys
from importlib import metadata

ROOTS = ["pypdf", "reportlab", "ebooklib", "beautifulsoup4", "pymupdf", "anthropic", "openai",
         "opencv-python-headless", "fonttools", "fastapi", "uvicorn", "python-multipart",
         "pywebview", "keyring", "httpx"]
OK = ("mit", "bsd", "apache", "isc", "psf", "python software foundation", "mpl", "mozilla",
      "lgpl", "lesser general public", "zlib", "hpnd", "unlicense", "public domain", "cc0",
      "gnu affero", "agpl")


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def license_of(dist):
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr
    classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or []
                   if c.startswith("License ::") and "OSI Approved" in c or c.startswith("License :: OSI")]
    classifiers = [c for c in classifiers if c != "OSI Approved"]
    text = (md.get("License") or "").strip()
    if classifiers:
        return "; ".join(dict.fromkeys(classifiers))
    return text.splitlines()[0][:80] if text else "unknown"


def closure():
    seen, todo = {}, [norm(r) for r in ROOTS]
    dists = {norm(d.metadata["Name"]): d for d in metadata.distributions() if d.metadata["Name"]}
    while todo:
        name = todo.pop()
        if name in seen or name not in dists:
            continue
        seen[name] = dists[name]
        for req in dists[name].requires or []:
            if "extra ==" in req:
                continue
            m = re.match(r"[A-Za-z0-9_.-]+", req)
            if m:
                todo.append(norm(m.group()))
    return seen


def main():
    rows = []
    for name, d in sorted(closure().items()):
        lic = license_of(d)
        ok = "yes" if any(k in lic.lower() for k in OK) else "check"
        rows.append((d.metadata["Name"], d.version, lic, ok))
    print("| Package | Version | License (from metadata) | AGPL-3.0 compatible? |")
    print("| --- | --- | --- | --- |")
    for r in rows:
        print("| " + " | ".join(x.replace("|", "/") for x in r) + " |")
    print(f"\n{len(rows)} packages", file=sys.stderr)


if __name__ == "__main__":
    main()
