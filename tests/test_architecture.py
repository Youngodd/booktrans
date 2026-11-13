"""The import structure of booktrans: no cycles, and nothing below the entry points imports them.

Imports are read with `ast`, including those inside functions (a deferred import is how a cycle
was once hidden), so a new dependency that loops back is caught here, not at run time.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent / "booktrans"
ENTRY = ("cli", "web", "desktop", "__main__")     # packages that start the program
ABOVE_THE_CORE = ("pipeline", "cli", "web", "desktop")


def modules():
    """{dotted name relative to booktrans: path} for every module and package."""
    out = {}
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out[".".join(parts)] = p
    return out


def imports_of(name, path, known):
    """The booktrans modules that `path` imports, whether at the top or inside a function."""
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").startswith("booktrans")):
            base = package.split(".") if package else []
            if node.level:
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module.removeprefix("booktrans").lstrip(".")
            if target in known:
                found.add(target)
            for alias in node.names:  # `from . import glossary` names a module
                sub = f"{target}.{alias.name}" if target else alias.name
                if sub in known:
                    found.add(sub)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("booktrans."):
                    target = alias.name.removeprefix("booktrans.")
                    if target in known:
                        found.add(target)
    found.discard(name)
    return found


def graph():
    known = modules()
    return {n: imports_of(n, p, known) for n, p in known.items()}


def find_cycle(g):
    state, stack = {}, []

    def visit(n):
        state[n] = 1
        stack.append(n)
        for m in sorted(g[n]):
            if state.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if m not in state and (c := visit(m)):
                return c
        stack.pop()
        state[n] = 2
        return None
    for n in sorted(g):
        if n not in state and (c := visit(n)):
            return c
    return None


def test_the_reader_finds_imports_in_all_their_forms():
    g = graph()
    assert "glossary" in g["translate"]                 # `from . import glossary as gloss`
    assert "backends.base" in g["glossary"]             # `from .backends.base import ...`
    assert "web.jobs" in g["web.app"] and "pipeline" in g["web.jobs"]   # inside a function too (jobs.run_job)
    assert "web.app" in g["desktop.__main__"]


def test_there_is_no_import_cycle():
    cycle = find_cycle(graph())
    assert cycle is None, " -> ".join(cycle)


def test_a_cycle_would_be_caught():
    assert find_cycle({"a": {"b"}, "b": {"c"}, "c": {"a"}}) == ["a", "b", "c", "a"]
    assert find_cycle({"a": {"b"}, "b": set()}) is None


def test_the_translating_core_does_not_import_the_entry_points():
    g = graph()
    bad = [(n, m) for n, deps in g.items() if n.split(".")[0] not in ENTRY
           for m in deps if m.split(".")[0] in ABOVE_THE_CORE and not (n == "pipeline" and m == "pipeline")]
    # pipeline is the core's top: it may not import the entry points either
    assert not [b for b in bad if b[0] != "pipeline" or b[1] != "pipeline"], bad


def test_the_lowest_layer_imports_nothing_from_the_ones_above():
    g = graph()
    base = {"backends.base", "languages", "fsutil", "usage", "textclean", "prompts"}
    above = {"pipeline", "translate", "glossary", "layout", "writer", "ocr", "readers", "spend"}
    for n in base:
        assert not (g[n] & above), (n, g[n] & above)
