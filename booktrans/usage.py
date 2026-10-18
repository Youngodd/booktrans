"""Token usage tracking, shared by all backends."""
import json

FIELDS = ("input_tokens", "output_tokens",
          "cache_creation_input_tokens", "cache_read_input_tokens")


class Usage:
    def __init__(self):
        self.calls = 0
        self.tokens = dict.fromkeys(FIELDS, 0)
        self.cost_usd = 0.0  # only reported by the claude-cli backend

    def record(self, usage, cost=None):
        """Add one call's usage (API object or CLI dict) to the running totals."""
        get = usage.get if isinstance(usage, dict) else lambda k: getattr(usage, k, 0)
        self.calls += 1
        for k in FIELDS:
            self.tokens[k] += get(k) or 0
        self.cost_usd += cost or 0.0

    def as_dict(self):
        return {"calls": self.calls, **self.tokens, "cost_usd": self.cost_usd}

    def report(self, out):
        """Print this run's token usage and save it next to the output."""
        if not self.calls:
            print("Token usage: no API calls this run (everything was cached).")
            return
        t = self.tokens
        print("Token usage (this run): %d calls, %d input, %d output, "
              "%d cache-write, %d cache-read" % (
                  self.calls, t["input_tokens"], t["output_tokens"],
                  t["cache_creation_input_tokens"], t["cache_read_input_tokens"]))
        if self.cost_usd:
            print("Reported cost (this run): $%.4f" % self.cost_usd)
        path = out.with_suffix(".usage.json")
        runs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        runs.append(self.as_dict())
        path.write_text(json.dumps(runs, indent=2), encoding="utf-8")
        print(f"Usage log: {path}")
