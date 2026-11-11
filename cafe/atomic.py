"""The one writer of a file that is read back, standard library only: the live app image (Dockerfile, requirements.txt) has no pyyaml, so the app's own
files (job status and results, the CFD cache) could not use `cafe.pm.config`, which imports it. `cafe.pm.config.write_text` calls this function, so there is
one implementation of the temporary-and-replace (round 15, P-R14L0-1)."""
import contextlib, json, os, pathlib, shutil, uuid
from typing import Any


def write_text(p: Any, text: str) -> None:
    """`text` in `p` through a sibling temporary and os.replace: a run killed mid-write, or a disk that fills, leaves the old file, never half of a new one,
    and no temporary behind. The temporary has a name of its own (two writers of one file, or two threads, never share one). A symlink is followed, so the
    file it points to is the one replaced and the link stays a link. An existing file keeps its permission bits (a new file gets the default ones); a hard
    link to it does not survive, because a replace gives the name a new inode and the other name keeps the old content."""
    p = pathlib.Path(os.path.realpath(p))
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")           # not mkstemp: its 0600 would lock other users out
    try:
        tmp.write_text(text)
        with contextlib.suppress(OSError):                                  # the mode of the file being replaced; a new file has none to keep
            shutil.copymode(p, tmp)
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(p: Any, obj: Any, end: str = "", **kw: Any) -> None:
    """`obj` as JSON (`kw` go to json.dumps) followed by `end` in `p`, by `write_text`."""
    write_text(p, json.dumps(obj, **kw) + end)
