"""A fake ntfy topic, for the alerts a command sends: ``FakeNtfy`` keeps each message it was sent.

A test puts ``URL`` under ``[ntfy]`` in its caracole.toml and hands ``FakeNtfy.handler`` out as
the transport for provider "ntfy" (``caracole.commands._common.transport_for``, patched); ``titles``
are the messages' titles, in order.
"""

from __future__ import annotations

import httpx

URL = "https://ntfy.example/caracole-test"
CONFIG = f'[ntfy]\nurl = "{URL}"\n'


class FakeNtfy:
    def __init__(self):
        self.posts: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})

    @property
    def titles(self) -> list[str]:
        return [p.headers["title"] for p in self.posts]
