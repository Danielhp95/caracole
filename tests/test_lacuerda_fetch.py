"""LaCuerda in the nightly run: which songs are tried, and when its sheet is kept.

LaCuerda is played by ``FakeLaCuerda`` behind a real ``PoliteClient`` (through
``httpx.MockTransport``), serving the fixtures in ``tests/fixtures/lacuerda/``
(real markup, invented sheet text). Like the live site, it answers an unknown
artist with HTTP 200 and its 54-byte "aqui llega:" body. The artist page's
30-day cache and the budget are the client's real behaviour.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import add_song

from tabarr.config import ProviderPolicy, RankPolicy
from tabarr.http import PoliteClient
from tabarr.lacuerda_fetch import LaCuerdaStats, lacuerda_sheets
from tabarr.library import kept_files
from tabarr.lyrics import Lyrics
from tabarr.songs import get_song, update_song
from tabarr.versions import song_versions

FIXTURES = Path(__file__).parent / "fixtures" / "lacuerda"
NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
STAMP = "2026-10-18T03:30:00Z"
RANK = RankPolicy()

BASE = "https://acordes.lacuerda.net"
SODA = f"{BASE}/soda_stereo/"
DML_3 = f"{BASE}/soda_stereo/de_musica_ligera-3.shtml"

# Every line of these lyrics is in the version fixture's sheet (all invented).
SHEET_LYRICS = """\
Cruzo la plaza con el café frío
y cuento las luces del tren de las seis
nadie me espera en el andén vacío
guardo tu nombre y no sé qué hacer
Baila la lluvia sobre los tejados
suena la radio de la vecindad
llevo en el bolso tu carta doblada
mañana el puerto se va a despertar
"""
# Eight more lines that no sheet here has: with them the fixture covers half.
OTHER_LINES = """\
Siete caballos corren hacia el norte
el viento canta coplas de cristal
la madrugada quema mis bolsillos
y las campanas tocan sin final
Un perro viejo duerme en la escalera
las golondrinas vuelven a su hogar
mi abuela teje redes de colores
y el río lento aprende a nadar
"""
HALF_LYRICS = SHEET_LYRICS + OTHER_LINES


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def soft_404(slug: str) -> str:
    return f"aqui llega:../tabs/{slug[0]}/{slug}/index.html"


class FakeLaCuerda:
    """acordes.lacuerda.net: pages by URL, every request recorded.

    By default it has Soda Stereo's artist page and the page of "De Música
    Ligera" version 3, the best "acordes" version that page lists.
    """

    def __init__(self, pages=None):
        self.pages = dict(pages if pages is not None else {
            SODA: (200, fixture("artist.html")),
            DML_3: (200, fixture("version.html")),
        })
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url in self.pages:
            status, body = self.pages[url]
            return httpx.Response(status, text=body, headers={"Content-Type": "text/html; charset=UTF-8"})
        slug = request.url.path.strip("/")
        if request.url.path.endswith("/") and "/" not in slug:
            return httpx.Response(200, text=soft_404(slug), headers={"Content-Type": "text/html; charset=UTF-8"})
        raise AssertionError(f"unexpected request: {url}")

    def client(self, cache_dir: Path, *, budget: int = 30, now: datetime = NOW) -> PoliteClient:
        return PoliteClient(
            "lacuerda",
            ProviderPolicy(budget=budget, delay=(0.0, 0.0)),
            cache_dir,
            user_agent="tabarr-test",
            transport=httpx.MockTransport(self.handler),
            sleep=lambda seconds: None,
            wall_clock=lambda: now,
        )


class Recording:
    """A client that notes the options of every ``get`` before passing it on."""

    def __init__(self, client):
        self.client = client
        self.calls: list[tuple[str, dict]] = []

    @property
    def requests_made(self) -> int:
        return self.client.requests_made

    def get(self, url, **options):
        self.calls.append((url, options))
        return self.client.get(url, **options)


def run(site: FakeLaCuerda, conn, tmp_path: Path, now: datetime = NOW, *, budget: int = 30,
        rank: RankPolicy = RANK) -> LaCuerdaStats:
    """One pass, as one nightly run would make it: a fresh client on the shared cache."""
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    return lacuerda_sheets(conn, client, tmp_path / "lib", rank, now)


def with_lyrics(conn, song, plain: str):
    lyrics = Lyrics(plain=plain, synced=None, instrumental=False, duration=None, lrclib_id=None)
    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics.to_json())
    return get_song(conn, song.id)


def spanish_song(conn, artist="Soda Stereo", title="De Música Ligera", plain=SHEET_LYRICS, **kw):
    return with_lyrics(conn, add_song(conn, artist, title, **kw), plain)


def song_folder(tmp_path: Path, artist="Soda Stereo", title="De Música Ligera") -> Path:
    return tmp_path / "lib" / artist / title


def lacuerda_versions(conn, song):
    return [v for v in song_versions(conn, song.id) if v.provider == "lacuerda"]


def files_of(conn, song) -> dict[str, int]:
    return {f.name: f.version_id for f in kept_files(conn, song.id)}


# --- keeping LaCuerda's sheet --------------------------------------------------


def test_a_spanish_song_without_a_sheet_gets_the_best_acordes_version(conn, tmp_path):
    site = FakeLaCuerda()
    song = spanish_song(conn)
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    # The artist page ranks version 3 first among the "Letra y Acordes" versions.
    assert site.requests == [SODA, DML_3]

    (v,) = lacuerda_versions(conn, song)
    assert (v.tab_id, v.slot, v.kind, v.version, v.url) == (
        "soda_stereo/de_musica_ligera-3", "sheet", "acordes", 3, DML_3)
    assert (v.rating, v.votes, v.label, v.coverage, v.pick_rank) == (0, 0, None, 1.0, 1)
    assert v.raw == {"lcd": "RHRTTTDTB-314865972", "title": "De Música Ligera"}

    here = song_folder(tmp_path)
    assert (here / "sheet.txt").read_text(encoding="utf-8").splitlines()[:7] == [
        "Intro:",
        "",
        "Am-F-C-G",
        "Am-F-C-G(2)",
        "",
        "Am             F          C        G",
        "Cruzo la plaza,    con el café frío",
    ]
    sheet = json.loads((here / "sheet.json").read_text(encoding="utf-8"))
    assert {k: sheet[k] for k in ("provider", "url", "version")} == {
        "provider": "lacuerda", "url": DML_3, "version": 3}
    assert sheet["content"].splitlines()[2] == "[ch]Am[/ch]-[ch]F[/ch]-[ch]C[/ch]-[ch]G[/ch]"
    assert files_of(conn, song) == {"sheet.txt": v.id, "sheet.json": v.id}

    stored = get_song(conn, song.id)
    assert (stored.status, stored.lacuerda_checked_at) == ("found", STAMP)
    info = json.loads((here / "info.json").read_text(encoding="utf-8"))
    assert info["status"] == "found"
    assert {(f["name"], f["provider"], f["coverage"]) for f in info["files"]} == {
        ("sheet.txt", "lacuerda", 1.0), ("sheet.json", "lacuerda", 1.0)}


def test_the_artist_page_is_cached_for_30_days_and_a_404_is_an_answer(conn, tmp_path):
    spanish_song(conn)
    client = Recording(FakeLaCuerda().client(tmp_path / "cache"))
    lacuerda_sheets(conn, client, tmp_path / "lib", RANK, NOW)
    (artist_url, artist), (version_url, version) = client.calls
    assert (artist_url, artist["max_age"]) == (SODA, timedelta(days=30))
    assert 404 in artist["accept"] and 404 in version["accept"]
    # A version page is cached forever, like every other page.
    assert (version_url, version.get("max_age")) == (DML_3, None)


def test_one_artist_page_serves_every_song_by_the_artist(conn, tmp_path):
    persiana_2 = f"{BASE}/soda_stereo/persiana_americana-2.shtml"
    site = FakeLaCuerda()
    site.pages[persiana_2] = (200, fixture("version.html"))
    spanish_song(conn, title="De Música Ligera", added_at="2026-10-02T00:00:00Z")
    spanish_song(conn, title="Persiana Americana", added_at="2026-10-01T00:00:00Z")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=2, kept=2)
    assert site.requests == [SODA, DML_3, persiana_2]


def test_sheet_files_stay_group_readable_under_the_service_umask(conn, tmp_path):
    # The service runs with UMask=0007; Syncthing reads the library through the group.
    spanish_song(conn)
    old = os.umask(0o007)
    try:
        run(FakeLaCuerda(), conn, tmp_path)
    finally:
        os.umask(old)
    here = song_folder(tmp_path)
    for name in ("sheet.txt", "sheet.json", "info.json"):
        assert stat.S_IMODE((here / name).stat().st_mode) == 0o660, name
