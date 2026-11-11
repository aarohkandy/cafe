"""The one writer of a file that is read back, standard library only: the live app image (Dockerfile, requirements.txt) has no pyyaml, so the app's own
files (job status and results, the CFD cache) could not use `cafe.pm.config`, which imports it. `cafe.pm.config.write_text` calls this function, so there is
one implementation of the temporary-and-replace (round 15, P-R14L0-1)."""
import json, os, pathlib, stat, uuid
from typing import Any


def tmp_name(p: Any) -> pathlib.Path:
    """A temporary name beside `p`: `.<12 hex>.tmp`, 17 characters whatever `p` is called, so it fits wherever `p` fits (a name built from `p`'s own, with a
    pid and a suffix added, was up to 21 characters longer and failed for final names of about 235 to 255 characters: round 15, M-6). It has a name of its
    own (two writers of one file never share one) and ends in `.tmp`, which `bin/sync_filters` and `pipeline.is_junk` already leave out."""
    p = pathlib.Path(p)
    return p.with_name(f".{uuid.uuid4().hex[:12]}.tmp")


class _Created(type(pathlib.Path())):  # type: ignore[misc]
    """The temporary as a `Path` whose `open` is the descriptor `os.open(O_EXCL)` returned, whatever the name now points to: `Path.write_text` (which the
    tests that cut a write patch) goes through `open`, and opening the name again would follow a link planted at it after the create and write there."""
    fd = -1

    def open(self, mode: str = "r", buffering: int = -1, encoding: Any = None, errors: Any = None, newline: Any = None) -> Any:  # type: ignore[override]
        return open(self.fd, mode, buffering, encoding, errors, newline, closefd=False)


def write_text(p: Any, text: str, follow_symlinks: bool = False) -> None:
    """`text` in `p` through a sibling temporary and os.replace: a run killed mid-write, or a disk that fills, leaves the old file, never half of a new one,
    and no temporary behind. The temporary is made by `os.open(..., O_EXCL)` with the mode `0o600` when `p` exists and the creation mode `0o666` (the
    process's umask applies) when it does not, so it is never readable more widely than the file it becomes; an existing file's permission bits are set on it
    after the write (a new file gets the default ones); a hard link to the file does not survive, because a replace gives the name a new inode and the
    other name keeps the old content. A symbolic link at `p` is refused (`OSError`, ELOOP) unless `follow_symlinks`: then the file it points to is the one
    replaced and the link stays a link (the writers of a path a person names: `cafe.pm.config.write_text`). The app's job files never follow one."""
    p = pathlib.Path(p)
    if follow_symlinks:
        p = pathlib.Path(os.path.realpath(p))
    elif p.is_symlink():
        raise OSError(40, "refusing to write through a symbolic link", str(p))           # 40 = ELOOP
    try:
        mode: int | None = stat.S_IMODE(os.stat(p).st_mode)                              # the mode of the file being replaced; a new file has none to keep
    except OSError:
        mode = None
    tmp = tmp_name(p)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else 0o600)       # ours alone: O_EXCL fails on any existing name
    try:
        try:
            made = _Created(tmp)
            made.fd = fd
            made.write_text(text)                                                        # through fd, never by name again (round 15, security review)
            if mode is not None:
                os.fchmod(fd, mode)
        finally:
            os.close(fd)
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(p: Any, obj: Any, end: str = "", **kw: Any) -> None:
    """`obj` as JSON (`kw` go to json.dumps) followed by `end` in `p`, by `write_text` (a symbolic link at `p` is refused)."""
    write_text(p, json.dumps(obj, **kw) + end)
