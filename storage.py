# -*- coding: utf-8 -*-
"""Shared JSON datastore: atomic writes + per-file async locks.

The bot cogs and the FastAPI dashboard run in the SAME process and the SAME
asyncio event loop, so a process-wide lock registry keyed by absolute file
path lets both sides serialize read-modify-write cycles on the same ``json/``
files. Without this, a dashboard edit that lands during a cog's ``await``
(or vice versa) silently overwrites the other side's change.

Every write goes through a temp file + ``os.replace``, which is atomic on the
same filesystem: a crash mid-write can never leave a truncated/empty JSON
file (which ``read_json`` would otherwise swallow as ``{}`` — silently wiping
points/queues/etc.).

Usage::

    import storage

    async with storage.lock_for(POINTS_JSON):
        data = storage.read_json(POINTS_JSON)
        data[...] = ...
        storage.write_json_atomic(POINTS_JSON, data)
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile

__all__ = ["read_json", "write_json_atomic", "lock_for"]

_locks: dict[str, asyncio.Lock] = {}


def lock_for(path) -> asyncio.Lock:
    """Return the process-wide :class:`asyncio.Lock` guarding ``path``.

    Keyed by absolute path so a cog using ``"json/points.json"`` and a
    dashboard route using ``Path("json/points.json")`` share the exact same
    lock object. Safe to call at import / cog-init time: an ``asyncio.Lock``
    binds to the running loop lazily on first ``await`` (Python 3.10+). The
    registry mutation is only ever touched from the single event-loop thread,
    so no extra synchronisation is needed.
    """
    key = os.path.abspath(os.fspath(path))
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def read_json(path, default=None):
    """Load JSON from ``path``.

    Returns ``default`` (or ``{}`` when ``default`` is ``None``) if the file
    is missing, empty, corrupt, or unreadable — callers never see an
    exception.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {} if default is None else default


def write_json_atomic(path, data, *, ensure_ascii: bool = False, indent=None) -> None:
    """Atomically write ``data`` as JSON to ``path``.

    Writes to a temp file in the same directory, fsyncs it, then
    ``os.replace`` onto the target (atomic on the same filesystem). The temp
    file is cleaned up if anything fails before the rename.
    """
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
