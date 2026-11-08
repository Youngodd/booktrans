"""Test sidecar: the real desktop sidecar with a fake backend that can be slowed, failed, or made to
reject a marker key. Only the backend is swapped; app code is untouched. Env: BOOKTRANS_SHIM_DELAY (s per
call), BOOKTRANS_SHIM_FAIL_FILE (calls fail while it exists), BOOKTRANS_SHIM_CALLS (log file, one line per call)."""
import os, sys, time
from pathlib import Path
import booktrans.desktop.__main__ as dm
import booktrans.translate as tr
from booktrans.backends.base import AuthError, BackendError
tr.RETRY_DELAYS = (0.2,)  # test only: do not wait 5/20/60 s between retries

class Shim(dm.FakeBackend):
    def __init__(self, key=""):
        super().__init__(); self.key = key
    def complete(self, system, user, max_tokens=4096):
        if self.key == "sk-test-reject": raise AuthError("rejected")
        if self.key == "sk-test-neterr": raise BackendError("network down")
        ff = os.environ.get("BOOKTRANS_SHIM_FAIL_FILE")
        if ff and Path(ff).exists() and max_tokens != 1: raise BackendError("simulated provider outage")
        if max_tokens != 1:
            log = os.environ.get("BOOKTRANS_SHIM_CALLS")
            if log:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(system.replace("\n", " ")[:4000] + "\n")
            time.sleep(float(os.environ.get("BOOKTRANS_SHIM_DELAY", "0")))
        return super().complete(system, user, max_tokens)

orig = dm.create_app
def create(*a, **kw):
    kw["backend_factory"] = lambda key, provider="api", **c: Shim(key)
    return orig(*a, **kw)
dm.create_app = create
if __name__ == "__main__":
    sys.exit(dm.main())
