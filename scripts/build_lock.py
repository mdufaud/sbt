#!/usr/bin/env python3
"""Serialize sbt runs on one build variant.

Concurrent make/scons runs on the same build path share .sconsign.dblite and
vcpkg/, so two of them (typically two agents) corrupt each other.
The lock is an flock held by a detached process for as long as the owning
make is alive: a killed make never leaves a stale lock behind.

usage: build_lock.py acquire LOCK_PATH TIMEOUT_SECONDS OWNER_PID
exit 0: lock held until OWNER_PID exits; exit 1: timed out
"""

import contextlib
import os
import sys
import time

try:
    import fcntl
except ImportError:
    fcntl = None

POLL_SECONDS = 0.2
REPORT_SECONDS = 30


def _process_cmdline(pid):
    try:
        with open("/proc/{}/cmdline".format(pid), "rb") as f:
            cmdline = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmdline = ""
    return cmdline or "pid {}".format(pid)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        # an exited owner its parent has not reaped yet still answers kill(pid, 0)
        with open("/proc/{}/stat".format(pid)) as f:
            return f.read().rpartition(")")[2].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _holder_info(fd):
    try:
        return os.pread(fd, 4096, 0).decode(errors="replace").strip() or "unknown holder"
    except OSError:
        return "unknown holder"


def _hold_until_owner_exits(owner_pid):
    """Fork a detached child inheriting the locked fd; it outlives this process."""
    if os.fork():
        return
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for std_fd in (0, 1, 2):
        os.dup2(devnull, std_fd)
    while _pid_alive(owner_pid):
        time.sleep(POLL_SECONDS)
    os._exit(0)


def _wait_lock(lock_path, timeout):
    """Return the fd holding the flock on lock_path, or None once timeout expires."""
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    start = time.monotonic()
    next_report = 0.0
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            pass
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            sys.stderr.write("sbt: timed out after {:.0f}s waiting for build lock {} held by: {}\n".format(
                elapsed, lock_path, _holder_info(fd)))
            os.close(fd)
            return None
        if elapsed >= next_report:
            sys.stderr.write("sbt: waiting for build lock {} held by: {} (timeout {:.0f}s)\n".format(
                lock_path, _holder_info(fd), timeout))
            sys.stderr.flush()
            next_report = elapsed + REPORT_SECONDS
        time.sleep(POLL_SECONDS)


def _write_holder(fd, pid):
    info = "{} (pid {}, since {})".format(_process_cmdline(pid), pid, time.strftime("%F %T"))
    os.ftruncate(fd, 0)
    os.pwrite(fd, info.encode(), 0)


def acquire(lock_path, timeout, owner_pid):
    if fcntl is None:
        sys.stderr.write("sbt: no flock on this host, build lock skipped\n")
        return 0
    fd = _wait_lock(lock_path, timeout)
    if fd is None:
        return 1
    _write_holder(fd, owner_pid)
    _hold_until_owner_exits(owner_pid)
    return 0


@contextlib.contextmanager
def held(lock_path, timeout):
    """Hold the lock for the with-block in this process; timeout 0 disables it."""
    if fcntl is None or timeout == 0:
        if fcntl is None:
            sys.stderr.write("sbt: no flock on this host, build lock skipped\n")
        yield
        return
    fd = _wait_lock(lock_path, timeout)
    if fd is None:
        raise TimeoutError("build lock {} not acquired within {:.0f}s".format(lock_path, timeout))
    _write_holder(fd, os.getpid())
    try:
        yield
    finally:
        os.close(fd)


def main(argv):
    if len(argv) != 5 or argv[1] != "acquire":
        sys.stderr.write(__doc__)
        return 2
    return acquire(argv[2], float(argv[3]), int(argv[4]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
