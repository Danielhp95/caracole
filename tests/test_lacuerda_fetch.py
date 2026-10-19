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
from tabarr.http import PoliteClient, ProviderBlocked
from tabarr.lacuerda_fetch import LaCuerdaStats, lacuerda_sheets
from tabarr.library import keep_file, kept_files
from tabarr.lyrics import Lyrics
from tabarr.overrides import Overrides
from tabarr.songs import get_song, refresh_status, update_song
from tabarr.ug.page import strip_markup
from tabarr.versions import set_coverage, set_picks, song_versions, upsert_version

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


def artist_page(name: str, slug: str, *songs: tuple[str, str, str]) -> str:
    """The captured artist page, made over for another artist: ``(slug, title, lcd)`` per song."""
    page = fixture("artist.html").replace("Soda Stereo", name).replace("soda_stereo", slug)
    start = page.index("<ul id=b_main")
    head, end = page.index(">", start) + 1, page.index("</ul>", start)
    items = "\n".join(
        f"<li id='r{i:03}' lcd='{lcd}'><a href=\"{song}\">{title} <em>acordes</em></A></li>"
        for i, (song, title, lcd) in enumerate(songs)
    )
    return f"{page[:head]}\n{items}\n{page[end:]}"


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
        html = {"Content-Type": "text/html; charset=UTF-8"}
        if url in self.pages:
            status, body = self.pages[url]
            return httpx.Response(status, text=body, headers=html)
        slug = request.url.path.strip("/")
        if request.url.path.endswith("/") and "/" not in slug:
            return httpx.Response(200, text=soft_404(slug), headers=html)
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


def test_coverage_is_scored_with_the_rank_policy(conn, tmp_path):
    # Demanding exact lines, "y cuento las luces…" misses the sheet's "cuento las luces,".
    song = spanish_song(conn)
    run(FakeLaCuerda(), conn, tmp_path, rank=RankPolicy(line_match=100))
    (v,) = lacuerda_versions(conn, song)
    assert v.coverage == 7 / 8


def test_completeness_follows_the_rank_policy(conn, tmp_path):
    # At a threshold of 0.5, a sheet covering 0.6 is complete: nothing to look for.
    song = spanish_song(conn)
    keep_ug_sheet(conn, tmp_path, song, 0.6)
    site = FakeLaCuerda()
    assert run(site, conn, tmp_path, rank=RankPolicy(coverage_threshold=0.5)) == LaCuerdaStats()
    assert site.requests == []


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


# --- finding the artist, and misses ---------------------------------------------

FITO = f"{BASE}/fito__fitipaldis/"
FITO_PEZ = f"{BASE}/fito__fitipaldis/por_la_boca_vive_el_pez.shtml"


def fito_site() -> FakeLaCuerda:
    pez = ("por_la_boca_vive_el_pez", "Por la boca vive el pez", "R-1")
    page = artist_page("Fito & Fitipaldis", "fito__fitipaldis", pez)
    return FakeLaCuerda({FITO: (200, page), FITO_PEZ: (200, fixture("version.html"))})


def assert_missed(conn, song, tmp_path):
    assert get_song(conn, song.id).lacuerda_checked_at == STAMP
    assert lacuerda_versions(conn, song) == []
    assert not (tmp_path / "lib").exists()


def test_a_soft_404_moves_on_to_the_next_artist_slug(conn, tmp_path):
    # Spotify writes "Fito y Fitipaldis"; LaCuerda's slug comes from "Fito & Fitipaldis".
    site = fito_site()
    song = spanish_song(conn, "Fito y Fitipaldis", "Por la boca vive el pez")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    assert site.requests == [f"{BASE}/fito_y_fitipaldis/", FITO, FITO_PEZ]
    (v,) = lacuerda_versions(conn, song)
    assert (v.tab_id, v.url) == ("fito__fitipaldis/por_la_boca_vive_el_pez-1", FITO_PEZ)


def test_an_http_404_for_an_artist_page_moves_on_too(conn, tmp_path):
    # A full error page, too big to pass for the soft 404's short body.
    site = fito_site()
    site.pages[f"{BASE}/fito_y_fitipaldis/"] = (404, fixture("song.html"))
    spanish_song(conn, "Fito y Fitipaldis", "Por la boca vive el pez")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)


def test_an_artist_lacuerda_does_not_have_is_a_miss(conn, tmp_path):
    site = FakeLaCuerda()
    song = spanish_song(conn, "Artista Desconocido", "Canción de Prueba")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, missing=1)
    assert site.requests == [f"{BASE}/artista_desconocido/"]
    assert_missed(conn, song, tmp_path)


def test_a_title_the_artist_page_lacks_is_a_miss(conn, tmp_path):
    site = FakeLaCuerda()
    song = spanish_song(conn, title="Canción Inexistente")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, missing=1)
    assert site.requests == [SODA]
    assert_missed(conn, song, tmp_path)


def test_a_song_without_an_acordes_version_is_a_miss(conn, tmp_path):
    # "Telarañas" is listed with two tablatures ("TT") and no Letra y Acordes.
    site = FakeLaCuerda()
    song = spanish_song(conn, title="Telarañas")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, missing=1)
    assert site.requests == [SODA]
    assert_missed(conn, song, tmp_path)


def test_a_version_page_that_is_gone_is_a_miss(conn, tmp_path):
    # The artist page, cached for up to 30 days, can list a version LaCuerda has removed.
    persiana_2 = f"{BASE}/soda_stereo/persiana_americana-2.shtml"
    site = FakeLaCuerda()
    site.pages[persiana_2] = (404, "<html><body>No existe</body></html>")
    song = spanish_song(conn, title="Persiana Americana")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, missing=1)
    assert site.requests == [SODA, persiana_2]
    assert_missed(conn, song, tmp_path)


# --- which songs are tried --------------------------------------------------------

ENGLISH_LYRICS = """\
I walk the line where the river ends
and all the lights are out tonight
you know I never called you back
so here I am, it's late again
"""
# 斑马斑马's lyrics are plain and in Traditional characters on LRCLIB (invented here).
BANMA_LYRICS = "範例歌詞 第一行\n範例歌詞 第二行\n你是一匹斑馬 我是一匹斑馬\n"


def keep_ug_sheet(conn, tmp_path, song, value):
    """A UG sheet kept by the fetch step (sheet.txt and sheet.json), covering ``value``."""
    url = "https://tabs.ultimate-guitar.com/tab/85053"
    raw = {"id": 85053, "type": "Chords"}
    vid = upsert_version(
        conn, provider="ug", tab_id="85053", song_id=song.id, slot="sheet", kind="chords",
        rating=4.5, votes=20, version=2, label=None, url=url, raw=raw, now="2026-10-10T03:30:00Z",
    )
    set_coverage(conn, vid, value)
    content = "[ch]Am[/ch]             [ch]F[/ch]\nCruzo la plaza,    con el café frío\n"
    doc = {"version": raw, "content": content, "url": url}
    files = {"sheet.txt": strip_markup(content), "sheet.json": json.dumps(doc)}
    for name, text in files.items():
        keep_file(conn, tmp_path / "lib", song=song, version_id=vid, name=name, data=text.encode(),
                  rank=1)
    set_picks(conn, song.id, ("chords",), [vid])
    refresh_status(conn, song.id, ignored=False)
    return vid


def assert_not_tried(site, conn, tmp_path, song):
    assert run(site, conn, tmp_path) == LaCuerdaStats()
    assert site.requests == []
    assert get_song(conn, song.id).lacuerda_checked_at is None


def test_an_english_song_is_not_tried(conn, tmp_path):
    song = with_lyrics(conn, add_song(conn, "Radiohead", "Creep"), ENGLISH_LYRICS)
    assert_not_tried(FakeLaCuerda(), conn, tmp_path, song)


def test_english_lyrics_outweigh_a_spanish_looking_title(conn, tmp_path):
    song = with_lyrics(conn, add_song(conn, "Shawn Mendes", "Señorita"), ENGLISH_LYRICS)
    assert_not_tried(FakeLaCuerda(), conn, tmp_path, song)


def test_banma_banma_is_not_tried(conn, tmp_path):
    song = with_lyrics(conn, add_song(conn, "宋冬野", "斑马斑马", duration_ms=253000), BANMA_LYRICS)
    assert_not_tried(FakeLaCuerda(), conn, tmp_path, song)


def test_a_spanish_song_by_an_artist_without_a_latin_name_is_skipped(conn, tmp_path):
    # No slug can be built from the name, so LaCuerda can't be asked.
    song = spanish_song(conn, artist="宋冬野", title="Canción de Prueba")
    assert_not_tried(FakeLaCuerda(), conn, tmp_path, song)


def test_ignored_songs_are_not_tried(conn, tmp_path):
    song = spanish_song(conn)
    update_song(conn, song.id, status="ignored")
    assert_not_tried(FakeLaCuerda(), conn, tmp_path, song)


def test_a_song_with_a_complete_sheet_is_not_tried(conn, tmp_path):
    song = spanish_song(conn)
    keep_ug_sheet(conn, tmp_path, song, 0.8)
    assert_not_tried(FakeLaCuerda(), conn, tmp_path, song)


def test_a_song_checked_in_the_last_30_days_is_not_tried(conn, tmp_path):
    song = spanish_song(conn)
    update_song(conn, song.id, lacuerda_checked_at="2026-09-19T03:30:00Z")  # 29 days before NOW
    site = FakeLaCuerda()
    assert run(site, conn, tmp_path) == LaCuerdaStats()
    assert site.requests == []


def test_spanish_lyrics_decide_whatever_the_title(conn, tmp_path):
    # "Persiana Americana" alone has no Spanish spelling or function words.
    site = FakeLaCuerda()
    site.pages[f"{BASE}/soda_stereo/persiana_americana-2.shtml"] = (200, fixture("version.html"))
    spanish_song(conn, title="Persiana Americana")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)


def test_a_title_is_judged_without_spotifys_suffixes(conn, tmp_path):
    # "(with Juanes)" alone would tip "Corazón" to English.
    site = FakeLaCuerda()
    add_song(conn, "Fonseca", "Corazón (with Juanes)")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, missing=1)
    assert site.requests == [f"{BASE}/fonseca/"]


def test_without_lyrics_a_spanish_title_decides(conn, tmp_path):
    # The lyrics may still be pending; the sheet is kept, with its coverage unknown.
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    (v,) = lacuerda_versions(conn, song)
    assert v.coverage is None
    assert get_song(conn, song.id).status == "found"


# --- replacing a kept sheet -------------------------------------------------------


def keep_auto_sheet(conn, tmp_path, song):
    """An auto-chords sheet, kept as "sheet (auto).txt" and picked for the slot."""
    vid = upsert_version(
        conn, provider="auto", tab_id="auto", song_id=song.id, slot="sheet", kind="auto",
        rating=0, votes=0, version=1, label=None, url="", raw={}, now="2026-10-10T03:30:00Z",
    )
    text = "# auto-generated, unverified\nAm F C G\nCruzo la plaza con el café frío\n"
    keep_file(conn, tmp_path / "lib", song=song, version_id=vid, name="sheet (auto).txt",
              data=text.encode(), rank=1)
    set_picks(conn, song.id, ("auto",), [vid])
    refresh_status(conn, song.id, ignored=False)
    return vid


def picked(conn, song) -> dict[str, int | None]:
    return {v.provider: v.pick_rank for v in song_versions(conn, song.id, slot="sheet")}


def assert_lacuerda_kept(conn, tmp_path, song):
    (v,) = lacuerda_versions(conn, song)
    assert files_of(conn, song)["sheet.txt"] == v.id
    assert files_of(conn, song)["sheet.json"] == v.id
    here = song_folder(tmp_path)
    assert (here / "sheet.txt").read_text(encoding="utf-8").startswith("Intro:\n")
    assert json.loads((here / "sheet.json").read_text(encoding="utf-8"))["provider"] == "lacuerda"
    info = json.loads((here / "info.json").read_text(encoding="utf-8"))
    providers = {f["name"]: f["provider"] for f in info["files"]}
    assert providers["sheet.txt"] == providers["sheet.json"] == "lacuerda"


def assert_ug_kept(conn, tmp_path, song, ug_vid):
    assert files_of(conn, song) == {"sheet.txt": ug_vid, "sheet.json": ug_vid}
    text = (song_folder(tmp_path) / "sheet.txt").read_text(encoding="utf-8")
    assert text == "Am             F\nCruzo la plaza,    con el café frío\n"
    assert picked(conn, song) == {"ug": 1, "lacuerda": None}
    assert get_song(conn, song.id).lacuerda_checked_at == STAMP


def test_a_complete_lacuerda_sheet_replaces_a_partial_ug_sheet(conn, tmp_path):
    song = spanish_song(conn)
    keep_ug_sheet(conn, tmp_path, song, 0.5)
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    assert_lacuerda_kept(conn, tmp_path, song)
    assert picked(conn, song) == {"ug": None, "lacuerda": 1}


def test_a_partial_lacuerda_sheet_that_covers_more_replaces_a_partial_one(conn, tmp_path):
    song = spanish_song(conn, plain=HALF_LYRICS)
    keep_ug_sheet(conn, tmp_path, song, 0.25)
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    assert_lacuerda_kept(conn, tmp_path, song)
    (v,) = lacuerda_versions(conn, song)
    assert v.coverage == 0.5


@pytest.mark.parametrize("ug_coverage", [0.6, 0.5])
def test_a_partial_sheet_that_covers_no_more_leaves_the_kept_one(conn, tmp_path, ug_coverage):
    song = spanish_song(conn, plain=HALF_LYRICS)
    ug_vid = keep_ug_sheet(conn, tmp_path, song, ug_coverage)
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1)
    assert_ug_kept(conn, tmp_path, song, ug_vid)
    # LaCuerda's version is remembered with its coverage, for the record.
    (v,) = lacuerda_versions(conn, song)
    assert (v.coverage, v.pick_rank) == (0.5, None)


def test_a_complete_lacuerda_sheet_replaces_a_sheet_of_unknown_coverage(conn, tmp_path):
    # A kept sheet scored before the song had lyrics has no coverage: it isn't complete.
    song = spanish_song(conn)
    keep_ug_sheet(conn, tmp_path, song, None)
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    assert_lacuerda_kept(conn, tmp_path, song)


def test_a_partial_lacuerda_sheet_never_replaces_a_sheet_of_unknown_coverage(conn, tmp_path):
    # It may cover more than the partial one, or all of the lyrics: no grounds to swap.
    song = spanish_song(conn, plain=HALF_LYRICS)
    ug_vid = keep_ug_sheet(conn, tmp_path, song, None)
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1)
    assert_ug_kept(conn, tmp_path, song, ug_vid)


def test_without_lyrics_a_kept_sheet_is_never_replaced(conn, tmp_path):
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    ug_vid = keep_ug_sheet(conn, tmp_path, song, None)
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1)
    assert_ug_kept(conn, tmp_path, song, ug_vid)


def test_a_complete_sheet_replaces_the_auto_sheet(conn, tmp_path):
    song = spanish_song(conn)
    keep_auto_sheet(conn, tmp_path, song)
    auto = song_folder(tmp_path) / "sheet (auto).txt"
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    assert_lacuerda_kept(conn, tmp_path, song)
    assert "sheet (auto).txt" not in files_of(conn, song)
    assert not auto.exists()
    assert picked(conn, song) == {"auto": None, "lacuerda": 1}


def test_a_partial_sheet_is_kept_beside_the_auto_sheet(conn, tmp_path):
    # The auto sheet goes only once a complete human sheet replaces it.
    song = spanish_song(conn, plain=HALF_LYRICS)
    auto_vid = keep_auto_sheet(conn, tmp_path, song)
    assert run(FakeLaCuerda(), conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    assert files_of(conn, song)["sheet (auto).txt"] == auto_vid
    assert (song_folder(tmp_path) / "sheet (auto).txt").is_file()
    assert_lacuerda_kept(conn, tmp_path, song)
    assert picked(conn, song) == {"auto": None, "lacuerda": 1}


def test_the_sheet_already_kept_is_rescored_not_written_again(conn, tmp_path):
    # Kept while the lyrics were pending; 31 days later the lyrics are in.
    site = FakeLaCuerda()
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    run(site, conn, tmp_path)
    sheet = song_folder(tmp_path) / "sheet.txt"
    inode = sheet.stat().st_ino
    with_lyrics(conn, song, SHEET_LYRICS)
    later = NOW + timedelta(days=31)
    assert run(site, conn, tmp_path, later) == LaCuerdaStats(tried=1)
    assert sheet.stat().st_ino == inode
    (v,) = lacuerda_versions(conn, song)
    assert (v.coverage, v.pick_rank) == (1.0, 1)
    info = json.loads((song_folder(tmp_path) / "info.json").read_text(encoding="utf-8"))
    assert {f["coverage"] for f in info["files"]} == {1.0}
    assert get_song(conn, song.id).lacuerda_checked_at == "2026-11-18T03:30:00Z"


# --- errors are never misses ------------------------------------------------------


def assert_untouched(conn, song, tmp_path):
    """Neither checked nor recorded: the next run asks LaCuerda about the song again."""
    assert get_song(conn, song.id).lacuerda_checked_at is None
    assert lacuerda_versions(conn, song) == []
    assert not (tmp_path / "lib").exists()


def test_an_error_on_a_version_page_leaves_the_song_for_the_next_run(conn, tmp_path):
    site = FakeLaCuerda()
    site.pages[DML_3] = (500, "Internal Server Error")
    song = spanish_song(conn)
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, errors=1)
    assert_untouched(conn, song, tmp_path)

    site.pages[DML_3] = (200, fixture("version.html"))
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    # The artist page came from the cache the second time.
    assert site.requests == [SODA, DML_3, DML_3]


def test_an_artist_page_without_its_song_list_is_an_error(conn, tmp_path):
    # A full page that lost ul#b_main is a changed site, not "LaCuerda doesn't have it".
    site = FakeLaCuerda({SODA: (200, fixture("song.html"))})
    song = spanish_song(conn)
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, errors=1)
    assert_untouched(conn, song, tmp_path)


def test_a_version_page_without_a_sheet_is_an_error(conn, tmp_path):
    site = FakeLaCuerda()
    site.pages[DML_3] = (200, fixture("song.html"))
    song = spanish_song(conn)
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, errors=1)
    assert_untouched(conn, song, tmp_path)


def test_an_error_does_not_end_the_pass(conn, tmp_path):
    site = FakeLaCuerda()
    persiana_2 = f"{BASE}/soda_stereo/persiana_americana-2.shtml"
    site.pages[persiana_2] = (502, "Bad Gateway")
    spanish_song(conn, title="Persiana Americana", added_at="2026-10-02T00:00:00Z")
    spanish_song(conn, title="De Música Ligera", added_at="2026-10-01T00:00:00Z")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=2, kept=1, errors=1)


def test_a_block_propagates_and_marks_nothing(conn, tmp_path):
    site = FakeLaCuerda({SODA: (403, "Forbidden")})
    song = spanish_song(conn)
    with pytest.raises(ProviderBlocked):
        run(site, conn, tmp_path)
    assert_untouched(conn, song, tmp_path)


def test_an_exhausted_budget_ends_the_pass_and_the_next_run_resumes(conn, tmp_path):
    site = FakeLaCuerda()
    song = spanish_song(conn)
    assert run(site, conn, tmp_path, budget=1) == LaCuerdaStats(budget_exhausted=True)
    assert_untouched(conn, song, tmp_path)
    assert site.requests == [SODA]

    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, kept=1)
    assert site.requests == [SODA, DML_3]


def test_three_errors_in_a_row_end_the_pass(conn, tmp_path):
    # PoliteClient stops asking a provider after three errors in a row in one run.
    names = ["Uno", "Dos", "Tres", "Cuatro", "Cinco"]
    site = FakeLaCuerda({f"{BASE}/{name.lower()}/": (500, "Server Error") for name in names})
    songs = [
        spanish_song(conn, name, "Canción de Prueba", added_at=f"2026-10-0{i + 1}T00:00:00Z")
        for i, name in enumerate(names)
    ]
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=3, errors=3)
    assert len(site.requests) == 3
    assert {get_song(conn, s.id).lacuerda_checked_at for s in songs} == {None}


def test_a_stale_artist_page_is_no_answer_once_the_budget_is_spent(conn, tmp_path):
    # The client serves a cached artist page past its 30 days only when the budget
    # is spent. A miss read from it is old news: the song keeps its old check time.
    site = FakeLaCuerda()
    site.pages.update(fito_site().pages)
    before = NOW - timedelta(days=31)
    old = spanish_song(conn, title="Canción Inexistente", added_at="2026-09-01T00:00:00Z")
    assert run(site, conn, tmp_path, before) == LaCuerdaStats(tried=1, missing=1)
    newer = "2026-10-10T00:00:00Z"
    spanish_song(conn, "Fito y Fitipaldis", "Por la boca vive el pez", added_at=newer)

    # Fito's three requests spend the budget; Soda Stereo's page is 31 days old.
    stats = run(site, conn, tmp_path, budget=3)
    assert stats == LaCuerdaStats(tried=1, kept=1, budget_exhausted=True)
    assert site.requests == [SODA, f"{BASE}/fito_y_fitipaldis/", FITO, FITO_PEZ]
    assert get_song(conn, old.id).lacuerda_checked_at == "2026-09-17T03:30:00Z"


# --- asking again after 30 days ------------------------------------------------------


def test_a_miss_is_asked_again_after_30_days_with_a_fresh_artist_page(conn, tmp_path):
    persiana_2 = f"{BASE}/soda_stereo/persiana_americana-2.shtml"
    site = FakeLaCuerda({SODA: (200, artist_page("Soda Stereo", "soda_stereo"))})
    song = spanish_song(conn, title="Persiana Americana")
    assert run(site, conn, tmp_path) == LaCuerdaStats(tried=1, missing=1)

    # LaCuerda adds the song; within 30 days nobody asks.
    site.pages[SODA] = (200, fixture("artist.html"))
    site.pages[persiana_2] = (200, fixture("version.html"))
    assert run(site, conn, tmp_path, NOW + timedelta(days=29)) == LaCuerdaStats()
    assert site.requests == [SODA]

    later = NOW + timedelta(days=31)
    assert run(site, conn, tmp_path, later) == LaCuerdaStats(tried=1, kept=1)
    assert site.requests == [SODA, SODA, persiana_2]
    assert get_song(conn, song.id).lacuerda_checked_at == "2026-11-18T03:30:00Z"


# --- your decisions in overrides.toml ---------------------------------------------------


def run_with(site, conn, tmp_path, overrides) -> LaCuerdaStats:
    client = site.client(tmp_path / "cache")
    return lacuerda_sheets(conn, client, tmp_path / "lib", RANK, NOW, overrides=overrides)


def test_a_sheet_you_pinned_is_never_replaced(conn, tmp_path):
    song = spanish_song(conn)
    ug_vid = keep_ug_sheet(conn, tmp_path, song, 0.5)
    site = FakeLaCuerda()
    assert run_with(site, conn, tmp_path, Overrides(pin={song.key: (85053,)})) == LaCuerdaStats()
    assert site.requests == []
    assert files_of(conn, song) == {"sheet.txt": ug_vid, "sheet.json": ug_vid}


def test_a_pin_of_another_tab_leaves_the_sheet_open_to_lacuerda(conn, tmp_path):
    # A pinned Guitar Pro tab, say: the sheet slot isn't pinned.
    song = spanish_song(conn)
    keep_ug_sheet(conn, tmp_path, song, 0.5)
    stats = run_with(FakeLaCuerda(), conn, tmp_path, Overrides(pin={song.key: (6571406,)}))
    assert stats == LaCuerdaStats(tried=1, kept=1)
    assert_lacuerda_kept(conn, tmp_path, song)


def test_songs_ignored_in_overrides_are_not_tried(conn, tmp_path):
    # Ignored in overrides.toml since the last match: the status still says "wanted".
    song = spanish_song(conn)
    site = FakeLaCuerda()
    overrides = Overrides(ignore=frozenset({song.key}))
    assert run_with(site, conn, tmp_path, overrides) == LaCuerdaStats()
    assert site.requests == []


# --- in the nightly run -----------------------------------------------------------------


def test_the_nightly_lacuerda_step_reports_the_counts(conn, cfg, tmp_path):
    from tabarr.notify import Notifier
    from tabarr.pipeline import Services, default_steps, run_pipeline

    spanish_song(conn)
    spanish_song(conn, title="Canción Inexistente")
    client = FakeLaCuerda().client(tmp_path / "cache")
    services = Services(clients={"lacuerda": client}, spotify=None, notifier=Notifier(None, None))
    steps = [s for s in default_steps() if s.name == "lacuerda"]
    report = run_pipeline(cfg, conn=conn, services=services, steps=steps, now=NOW)
    assert report.steps == {"lacuerda": "2 tried, 1 sheet kept, 1 not on LaCuerda, 0 errors"}
    assert (cfg.library_dir / "Soda Stereo" / "De Música Ligera" / "sheet.txt").is_file()


def test_tonights_lyrics_score_tonights_lacuerda_sheet(conn, cfg, tmp_path):
    # The lyrics step runs first, so a song added today is judged with its lyrics.
    from tabarr.notify import Notifier
    from tabarr.pipeline import Services, default_steps, run_pipeline

    hit = json.loads((FIXTURES.parent / "lrclib" / "get_hit.json").read_text(encoding="utf-8"))
    record = {**hit, "plainLyrics": SHEET_LYRICS, "syncedLyrics": None}
    answer = httpx.MockTransport(lambda request: httpx.Response(200, json=record))
    lrclib = PoliteClient(
        "lrclib", ProviderPolicy(budget=10, delay=(0.0, 0.0)), tmp_path / "cache",
        user_agent="tabarr-test", transport=answer, sleep=lambda seconds: None,
        wall_clock=lambda: NOW,
    )
    song = add_song(conn, "Soda Stereo", "De Música Ligera")
    clients = {"lrclib": lrclib, "lacuerda": FakeLaCuerda().client(tmp_path / "cache")}
    services = Services(clients=clients, spotify=None, notifier=Notifier(None, None))
    steps = [s for s in default_steps() if s.name in ("lyrics", "lacuerda")]
    report = run_pipeline(cfg, conn=conn, services=services, steps=steps, now=NOW)
    assert report.steps["lacuerda"] == "1 tried, 1 sheet kept, 0 not on LaCuerda, 0 errors"
    (v,) = lacuerda_versions(conn, song)
    assert v.coverage == 1.0
