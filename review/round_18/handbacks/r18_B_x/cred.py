"""Read-only: credibility.build on a copy of q18 against its stored credibility.json; print what differs (the page is page(_render(c)))."""
import json
import pathlib
import sys

from cafe.pm import credibility as cr

run = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("runs/q18copy")
new = json.loads(json.dumps(cr._clean(cr.build(run)), default=str))
old = json.loads((run / "report" / "credibility.json").read_text())


def walk(a, b, path=""):
    if type(a) is not type(b):
        yield path, "type", None, None
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                yield f"{path}/{k}", "missing in " + ("old" if k not in a else "new"), None, None
            else:
                yield from walk(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            yield path, f"len {len(a)} -> {len(b)}", None, None
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk(x, y, f"{path}[{i}]")
    elif a != b:
        yield path, "changed", a, b


diffs = list(walk(old, new))
print("differences:", len(diffs))
for p, what, a, b in diffs:
    print(p, what)
    if a is not None:
        print("   old:", str(a)[:600])
        print("   new:", str(b)[:900])
html = cr.page("Credibility report", cr._render(cr._clean(cr.build(run))))
oldhtml = (run / "report" / "credibility.html").read_text()
print("html bytes old/new", len(oldhtml), len(html), "contains 'not affected':", "not affected" in oldhtml, "->", "not affected" in html, "'never too high':", "never too high" in html)
