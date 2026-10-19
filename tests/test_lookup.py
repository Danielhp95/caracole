from tabarr.ug.lookup import IndexTab, artist_known, artist_tab_ids, learned_artist_url, remember_artist_url, song_tabs


def index(conn, rows):
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen) VALUES (?, ?, ?, ?, '1', 'x')",
        rows,
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
        IndexTab(1, "chords", "wonderwall", None),
        IndexTab(2, "chords", "wonderwall-acoustic", "acoustic"),
        IndexTab(3, "tabs", "wonderwall-intro", "intro"),
    ]


def test_artist_helpers(conn):
    index(conn, [(10, "soda-stereo", "persiana-americana", "tabs"), (7, "soda-stereo", "signos", "chords")])
    assert artist_known(conn, "soda-stereo") and not artist_known(conn, "joaquin-sabina")
    assert artist_tab_ids(conn, "soda-stereo") == [7, 10]
    assert learned_artist_url(conn, "soda-stereo") is None
    remember_artist_url(conn, "soda-stereo", "https://www.ultimate-guitar.com/artist/soda_stereo_2946")
    assert learned_artist_url(conn, "soda-stereo").endswith("soda_stereo_2946")
