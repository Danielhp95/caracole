"""ntfy notifications: a summary per run, and alerts for blocks and expired Spotify auth.

Sending never raises: a notification failure must not fail a run.
"""

from __future__ import annotations

import email.header
import logging
from typing import Sequence

import httpx

log = logging.getLogger(__name__)


def _header_value(s: str) -> str:
    """ASCII as is; anything else RFC 2047-encoded (ntfy decodes it)."""
    try:
        s.encode("ascii")
        return s
    except UnicodeEncodeError:
        return email.header.Header(s, "utf-8").encode()


class Notifier:
    def __init__(self, url: str | None, token: str | None, *, transport: httpx.BaseTransport | None = None,
                 timeout: float = 15.0):
        self.url = url
        self.token = token
        self._transport = transport
        self._timeout = timeout

    def send(self, title: str, message: str, *, priority: str | None = None, tags: Sequence[str] = ()) -> bool:
        """POST one message to the ntfy topic URL; True if ntfy accepted it."""
        if not self.url:
            return False
        headers = {"Title": _header_value(title)}
        if priority:
            headers["Priority"] = priority
        if tags:
            headers["Tags"] = ",".join(tags)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                resp = client.post(self.url, content=message.encode("utf-8"), headers=headers)
            if resp.is_success:
                return True
            log.warning("ntfy answered HTTP %s", resp.status_code)
        except httpx.HTTPError as e:
            log.warning("ntfy failed: %s", e)
        return False
