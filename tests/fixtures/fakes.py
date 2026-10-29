"""Small stand-ins shared by the orchestration tests."""
import importlib
import sys
import types


def fake_module(monkeypatch, dotted, **attrs):
    """Install a stand-in for a module that the code under test imports inside a function.

    Both `sys.modules` and the parent package attribute are replaced: `from pkg import name` reads the attribute first, so a real
    module that another test already imported would otherwise win. `monkeypatch` may be a `pytest.MonkeyPatch` or the fixture."""
    mod = types.ModuleType(dotted)
    mod.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, dotted, mod)
    parent, _, name = dotted.rpartition(".")
    monkeypatch.setattr(importlib.import_module(parent), name, mod, raising=False)
    return mod
