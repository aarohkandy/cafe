"""A probe for `remote.store_lock`: whether the lock file is held right now, asked through a descriptor of its own (a `flock` belongs to the open file, so a
second `open` of the file in this process conflicts with the first)."""
import fcntl
import os


def held(lockfile) -> bool:
    """True when somebody holds an exclusive `flock` on `lockfile`; False when it is free (or the file is not there)."""
    try:
        fd = os.open(lockfile, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)                                                       # (closing drops the lock if the probe got it)
    return False
