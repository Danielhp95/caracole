from caracole.ug.lookup import IndexTab, artist_known, learned_artist_url, remember_artist_url, song_tabs


def index(conn, rows):
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, '1', 'x', ?)",
        [(*r, f"{r[1]}/{r[2]}-{r[3]}-{r[0]}") for r in rows],
    )


def test_song_tabs_includes_variant_slugs_only(conn):
    index(conn, [
        (1, "oasis", "wonderwall", "chords"),
        (2, "oasis", "wonderwall-acoustic", "chords"),
        (3, "oasis", "wonderwall-intro", "tabs"),
        (4, "oasis", "wonderwall-ii", "chords"),
        (5, "other", "wonderwall", "chords"),
    ])
    assert song_tabs(conn, "oasis", "wonderwall") == [
        IndexTab(1, "chords", "wonderwall", None, "oasis/wonderwall-chords-1"),
        IndexTab(2, "chords", "wonderwall-acoustic", "acoustic", "oasis/wonderwall-acoustic-chords-2"),
        IndexTab(3, "tabs", "wonderwall-intro", "intro", "oasis/wonderwall-intro-tabs-3"),
    ]


def test_index_tab_url_is_the_slugged_page(conn):
    index(conn, [(1081462, "soda-stereo", "persiana-americana", "tabs")])
    t = song_tabs(conn, "soda-stereo", "persiana-americana")[0]
    assert t.url == "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-tabs-1081462"


def test_artist_helpers(conn):
    index(conn, [(10, "soda-stereo", "persiana-americana", "tabs"), (7, "soda-stereo", "signos", "chords")])
    assert artist_known(conn, "soda-stereo") and not artist_known(conn, "joaquin-sabina")
    assert learned_artist_url(conn, "soda-stereo") is None
    remember_artist_url(conn, "soda-stereo", "https://www.ultimate-guitar.com/artist/soda_stereo_2946")
    assert learned_artist_url(conn, "soda-stereo").endswith("soda_stereo_2946")
