"""Zip files with the same bytes on every call.

``ZipFile.writestr`` dates an entry with the clock, so two calls a second apart make different
bytes. A test parametrized with such a file then has a different id in each pytest-xdist worker,
and xdist refuses to run a suite whose workers collected different tests.
"""

from __future__ import annotations

import zipfile

DATE = (2026, 10, 18, 0, 0, 0)


def dated_entry(z: zipfile.ZipFile, name: str) -> zipfile.ZipInfo:
    """An entry for ``z.writestr`` as ``writestr(name, ...)`` makes one, but dated ``DATE``."""
    info = zipfile.ZipInfo(name, date_time=DATE)
    info.compress_type = z.compression
    info.external_attr = 0o600 << 16
    return info
