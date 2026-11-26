"""A nightly run's client that hands caracole's lock to the owner's job in one of its pauses.

``HandingOver(client, when, then)`` runs ``then()`` once, just before the first request ``when(url, params)`` names,
and counts that hand-over in ``handoffs`` as commands/_common.py's clients count theirs, so a pass that reads what it
holds again after one sees what ``then`` changed; everything else is the wrapped client's.

``picked(cfg, conn, song, record, lyrics)`` is what a lyrics pick (lyrics_pick.py) leaves behind it, done in that pause:
``[lyrics]``' record written, the question asked anew, the song's lyrics found. A clear is the real ``clear_pick``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class HandingOver:
    def __init__(self, client: Any, when: Callable[[str, Mapping[str, Any]], bool], then: Callable[[], None]):
        self.client, self.when, self.then, self.handoffs = client, when, then, 0

    def get(self, url: str, **options: Any) -> Any:
        if self.then is not None and self.when(str(url), dict(options.get("params") or {})):
            then, self.then = self.then, None
            then()
            self.handoffs += 1
        return self.client.get(url, **options)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)


def picked(cfg: Any, conn: Any, song: Any, record: str, lyrics: Any) -> None:
    """The owner's pick of ``record`` for ``song``, its ``lyrics`` kept, as ``caracole lyrics --pick`` keeps them."""
    from caracole.lyrics_search import ask_anew
    from caracole.overrides import set_lyrics_record
    from caracole.songs import get_song, update_song

    set_lyrics_record(cfg.overrides_file, song.display, record)
    ask_anew(conn, get_song(conn, song.id))
    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics.to_json(), lyrics_at="2026-10-01T00:00:00Z")


def cleared(cfg: Any, conn: Any, song: Any) -> None:
    """The owner's ``caracole lyrics --clear`` of the song's picked record."""
    from caracole.lyrics_pick import clear_pick
    from caracole.overrides import load_overrides
    from caracole.songs import get_song

    assert clear_pick(cfg, conn, get_song(conn, song.id), load_overrides(cfg.overrides_file)) is not None
