"""HTTP for every provider: errors, responses and the polite client.

Rules this module enforces (plan §6, "Politeness"):

- every raw response worth keeping (200, 404) is cached forever, and a cached
  URL never costs a request again;
- a per-run request budget, with a random pause before every network request;
- one request at a time;
- a 403, a 429 or a challenge page raises ``ProviderBlocked``. Errors are never
  misses: callers must not turn any ``ProviderError`` into "not found".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Collection, Mapping, Protocol, runtime_checkable


class ProviderError(Exception):
    """A provider failed: an HTTP error, a timeout or an unparseable page. Never a miss."""

    def __init__(
        self,
        provider: str,
        url: str | None = None,
        status: int | None = None,
        message: str | None = None,
    ):
        self.provider = provider
        self.url = url
        self.status = status
        self.message = message
        parts = [provider]
        if status is not None:
            parts.append(str(status))
        if url:
            parts.append(url)
        if message:
            parts.append(message)
        super().__init__(": ".join(parts))


class ProviderBlocked(ProviderError):
    """A 403, a 429 or a challenge page: stop using the provider and back off."""


class ProviderUnavailable(ProviderError):
    """Too many consecutive errors this run; the provider is skipped until the next run."""


class BudgetExhausted(Exception):
    """This run's request budget for the provider is spent. Not an error and not a miss."""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"{provider}: request budget for this run is spent")


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    content: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)


@dataclass(frozen=True)
class Event:
    """One network request, for the ``events`` table."""

    provider: str
    url: str
    status: int | None
    decision: str  # ok | not_modified | blocked | error | budget | unavailable
    message: str | None = None


@runtime_checkable
class Client(Protocol):
    """What provider code needs from an HTTP client; tests pass fakes with this shape."""

    requests_made: int

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        cache: bool = True,
        conditional: bool = False,
        accept: Collection[int] = (200,),
    ) -> Response: ...
