"""The one writer of a file that is read back, standard library only: the live app image (Dockerfile, requirements.txt) has no pyyaml, so the app's own
files (job status and results, the CFD cache) could not use `cafe.pm.config`, which imports it. `cafe.pm.config.write_text` calls this function, so there is
one implementation of the temporary-and-replace (round 15, P-R14L0-1)."""
import json, os, pathlib, stat, uuid
from typing import Any, Callable


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


def _target(p: Any, follow_symlinks: bool) -> tuple[pathlib.Path, int | None]:
    """Where a replace of `p` lands and the mode the new file takes: the one place of the link and mode rules (`_replace_through` and `replace_from` share it).
    A symbolic link at `p` is refused (`OSError`, ELOOP) unless `follow_symlinks`: then the file it points to is the target (a loop of links is ELOOP too: no
    file is there to replace; a dangling link is not a loop, its target is made). The mode is that of an existing regular file, the nine bits of owner, group and
    other and never setuid, setgid or sticky (round 17); None when there is none (a new name, or something that is not a regular file)."""
    p = pathlib.Path(p)
    if follow_symlinks:
        p = pathlib.Path(os.path.realpath(p))
        if p.is_symlink():                                                               # `realpath` of a loop is a name that is itself a link (round 17, M-15)
            raise OSError(40, "symbolic link loop", str(p))                              # ELOOP, as below; a dangling link is no loop (its target is no link)
    elif p.is_symlink():
        raise OSError(40, "refusing to write through a symbolic link", str(p))           # 40 = ELOOP
    try:
        st = os.stat(p)
    except OSError:
        return p, None
    return p, (stat.S_IMODE(st.st_mode) & 0o777 if stat.S_ISREG(st.st_mode) else None)


def _replace_through(p: Any, fill: Callable[[pathlib.Path, int], None], follow_symlinks: bool) -> None:
    """The one temporary-and-replace of this module (`write_text` and `write_with` call it, so the two never differ again: round 16, S1). `fill(tmp, fd)` writes
    the new content through `fd`, the descriptor `os.open(..., O_EXCL)` returned (`tmp` is its name, for a `Path` that stands in for it). The temporary is
    made with the mode `0o600` when `p` exists and the creation mode `0o666` (the process's umask applies) when it does not, so it is never readable more
    widely than the file it becomes; an existing file's permission bits (owner, group and other: never setuid, setgid or sticky, round 17) are set on it after
    the write (a new file gets the default ones); a hard link to the file does not survive, because a replace gives the name a new inode and the other name
    keeps the old content. A symbolic link at `p` is refused (`OSError`, ELOOP) unless `follow_symlinks`: then the file it points to is the one replaced and
    the link stays a link (`_target`). A failed write leaves `p` as it was and no temporary."""
    p, mode = _target(p, follow_symlinks)
    tmp = tmp_name(p)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else 0o600)       # ours alone: O_EXCL fails on any existing name
    try:
        try:
            fill(tmp, fd)                                                                # through fd, never by name again (round 15, security review)
            if mode is not None:
                os.fchmod(fd, mode)
        finally:
            os.close(fd)
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_text(p: Any, text: str, follow_symlinks: bool = False) -> None:
    """`text` in `p` through a sibling temporary and os.replace (`_replace_through`): a run killed mid-write, or a disk that fills, leaves the old file, never
    half of a new one, and no temporary behind. A symbolic link at `p` is refused unless `follow_symlinks` (the writers of a path a person names:
    `cafe.pm.config.write_text`). The app's job files never follow one."""
    def fill(tmp: pathlib.Path, fd: int) -> None:
        made = _Created(tmp)
        made.fd = fd
        made.write_text(text)

    _replace_through(p, fill, follow_symlinks)


def write_json(p: Any, obj: Any, end: str = "", **kw: Any) -> None:
    """`obj` as JSON (`kw` go to json.dumps) followed by `end` in `p`, by `write_text` (a symbolic link at `p` is refused)."""
    write_text(p, json.dumps(obj, **kw) + end)


def write_with(p: Any, writer: Callable[[Any], None], follow_symlinks: bool = False) -> None:
    """A binary file that is read back (an `.npz`) written by `writer(file_object)` into a sibling temporary and os.replace'd onto `p`: a kill or a full
    disk leaves the old `p` or none, never half of a new zip (a half one is `BadZipFile` at the next read, not the refetch that follows an absent file), and no
    temporary behind. It is `write_text`'s implementation (`_replace_through`: the temporary has `tmp_name`'s name and is made with `O_EXCL`, an existing
    file keeps its mode, a symbolic link at `p` is refused unless `follow_symlinks`); `writer` gets a file object on the descriptor of the temporary, never a
    second open by name, so a numpy `savez` adds no `.npz` to its name (P-R15A-3). The standard library only, like `write_text`."""
    def fill(tmp: pathlib.Path, fd: int) -> None:
        with open(fd, "wb", closefd=False) as f:
            writer(f)

    _replace_through(p, fill, follow_symlinks)


def replace_from(src: Any, p: Any, follow_symlinks: bool = False) -> None:
    """The finished file `src` renamed onto `p`: no copy, so no second file on the disk and no second pass over the bytes (a download's `.part`, a fetched NetCDF
    part: large, and the disks are nearly full). The rules are `_replace_through`'s, taken from the same `_target`: a symbolic link at `p` is refused (ELOOP)
    unless `follow_symlinks`, and an existing regular file's nine permission bits (never setuid, setgid or sticky) are put on `src` first, so a part made with
    the umask no longer changes the mode of the file it replaces (round 17, M-13 sibling). `src` is a file this process made under a name of its own or under
    a held lock: it is opened with `O_NOFOLLOW` (a link at `src` is ELOOP) and the mode goes on that descriptor. `src` is gone afterwards, and `p` has its
    inode; a failed call leaves `src` where it was."""
    p, mode = _target(p, follow_symlinks)
    if mode is not None:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    os.replace(src, p)
