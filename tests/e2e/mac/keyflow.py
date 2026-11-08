"""Key flow through the real shell Api. usage: keyflow.py PHASE  (env set by caller)"""
import os, sys, json
from pathlib import Path
os.environ["no_proxy"] = "*"
import keyring
from booktrans.desktop import shell
from booktrans.desktop.__main__ import data_dir
assert type(keyring.get_keyring()).__name__ == "FileKR", keyring.get_keyring()
phase = sys.argv[1]
side = shell.Sidecar().start(); api = shell.Api(side)
side.http = __import__("httpx").Client(base_url=side.base, headers={"X-Booktrans-Token": side.token}, timeout=60, trust_env=False)
out = {}
try:
    if phase == "first":
        out["first_run_has_key"] = api.has_key()["has_key"]
        out["config_has_key_before"] = side.http.get("/api/config").json()["has_key"]
        r = api.save_key("api", "sk-test-reject"); out["reject"] = r; out["after_reject_has_key"] = api.has_key()["has_key"]
        r = api.save_key("api", "sk-test-neterr"); out["neterr"] = r; out["after_neterr_has_key"] = api.has_key()["has_key"]
        out["empty"] = api.save_key("api", "  ")
        out["good"] = api.save_key("api", "sk-test-0000"); out["has"] = api.has_key()
        out["models"] = api.set_models("api", "claude-x", "")
    elif phase == "restart":
        out["has"] = api.has_key(); out["config_before_use"] = side.http.get("/api/config").json()["has_key"]
        out["use"] = api.use_stored_key(); c = side.http.get("/api/config").json()
        out["config_after_use"] = {"has_key": c["has_key"], "provider": c["provider"]}
        out["models"] = api.get_models()
    elif phase == "delete":
        api.use_stored_key(); api.delete_key()
        out["has_after_delete"] = api.has_key()["has_key"]; out["config_has_key"] = side.http.get("/api/config").json()["has_key"]
        out["delete_again_ok"] = api.delete_key()
    d = data_dir()
    hits = [str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and b"sk-test-0000" in p.read_bytes()]
    out["files_containing_key"] = hits; out["data_files"] = sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())
    out["log_tail"] = (d / "sidecar.log").read_text(errors="replace")[-300:]
finally:
    side.stop()
print(json.dumps(out, ensure_ascii=False, indent=1))
