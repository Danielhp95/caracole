import logging
from pathlib import Path

import pytest

from caracole.config import ConfigError, MatchPolicy, ProviderPolicy, RankPolicy, load_config


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "caracole.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults(tmp_path):
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.library_dir == tmp_path / "Tabs"
    assert cfg.music_dir == tmp_path / "Music"
    assert cfg.state_dir == tmp_path / ".local/state/caracole"
    assert cfg.cache_dir == tmp_path / ".cache/caracole"
    assert cfg.overrides_file == tmp_path / "Tabs/overrides.toml"
    assert cfg.wanted_file == tmp_path / "Tabs/wanted.txt"
    assert cfg.db_path == tmp_path / ".local/state/caracole/caracole.sqlite"
    assert cfg.user_agent == "caracole/0.1 (personal tab library)"
    assert cfg.chordpro_bin == "chordpro"
    assert cfg.providers["ug"] == ProviderPolicy(budget=60, delay=(10.0, 20.0))
    assert cfg.providers["lrclib"] == ProviderPolicy(budget=200, delay=(1.0, 2.0))
    assert cfg.providers["lacuerda"] == ProviderPolicy(budget=30, delay=(10.0, 20.0))
    assert cfg.match == MatchPolicy(accept=90, margin=8, review=75, artist_gate=90)
    assert cfg.rank == RankPolicy(
        coverage_threshold=0.8, line_match=85, prior_votes=10, scored_sheets=3,
        label_penalty=0.5, variant_bonus=0.25, keep_guitar_pro=2,
    )
    assert cfg.ntfy.url is None and cfg.ntfy.token is None


def test_xdg_directories(tmp_path):
    env = {"HOME": str(tmp_path), "XDG_STATE_HOME": "/x/state", "XDG_CACHE_HOME": "/x/cache"}
    cfg = load_config(None, env=env)
    assert cfg.state_dir == Path("/x/state/caracole")
    assert cfg.cache_dir == Path("/x/cache/caracole")


def test_systemd_directories_win_over_xdg(tmp_path):
    env = {
        "HOME": str(tmp_path), "XDG_STATE_HOME": "/x/state",
        "STATE_DIRECTORY": "/var/lib/caracole", "CACHE_DIRECTORY": "/var/cache/caracole:/other",
    }
    cfg = load_config(None, env=env)
    assert cfg.state_dir == Path("/var/lib/caracole")
    assert cfg.cache_dir == Path("/var/cache/caracole")


def test_toml_values_tilde_and_relative_paths(tmp_path):
    p = write(tmp_path, """
library_dir = "~/Lib"
music_dir = "music"
state_dir = "/srv/state"

[providers.ug]
budget = 20
delay = [12, 18]

[match]
accept = 92

[ntfy]
url = "https://ntfy.sh/caracole-test"
""")
    cfg = load_config(p, env={"HOME": "/home/u", "STATE_DIRECTORY": "/var/lib/caracole"})
    assert cfg.library_dir == Path("/home/u/Lib")
    assert cfg.music_dir == tmp_path / "music"
    assert cfg.state_dir == Path("/srv/state")
    assert cfg.overrides_file == Path("/home/u/Lib/overrides.toml")
    assert cfg.providers["ug"] == ProviderPolicy(budget=20, delay=(12.0, 18.0))
    assert cfg.providers["lrclib"].budget == 200
    assert cfg.match.accept == 92 and cfg.match.margin == 8
    assert cfg.ntfy.url == "https://ntfy.sh/caracole-test"


def test_data_dir_holds_the_library_music_state_and_cache(tmp_path):
    p = write(tmp_path, 'data_dir = "/data/caracole"\n')
    cfg = load_config(p, env={"HOME": str(tmp_path / "home")})
    assert cfg.library_dir == Path("/data/caracole/library")
    assert cfg.music_dir == Path("/data/caracole/music")
    assert cfg.state_dir == Path("/data/caracole/state")
    assert cfg.cache_dir == Path("/data/caracole/cache")
    assert cfg.overrides_file == Path("/data/caracole/library/overrides.toml")
    assert cfg.wanted_file == Path("/data/caracole/library/wanted.txt")
    assert cfg.db_path == Path("/data/caracole/state/caracole.sqlite")


def test_explicit_folders_win_over_data_dir(tmp_path):
    p = write(tmp_path, """
data_dir = "/data/caracole"
library_dir = "/srv/tabs"
cache_dir = "/var/cache/caracole"
""")
    cfg = load_config(p, env={"HOME": str(tmp_path / "home")})
    assert cfg.library_dir == Path("/srv/tabs")
    assert cfg.wanted_file == Path("/srv/tabs/wanted.txt")
    assert cfg.cache_dir == Path("/var/cache/caracole")
    assert cfg.music_dir == Path("/data/caracole/music")
    assert cfg.state_dir == Path("/data/caracole/state")


def test_data_dir_wins_over_the_systemd_and_xdg_directories(tmp_path):
    env = {
        "HOME": str(tmp_path / "home"), "XDG_STATE_HOME": "/x/state", "XDG_CACHE_HOME": "/x/cache",
        "STATE_DIRECTORY": "/var/lib/caracole", "CACHE_DIRECTORY": "/var/cache/caracole",
    }
    cfg = load_config(write(tmp_path, 'data_dir = "/data/caracole"\n'), env=env)
    assert cfg.state_dir == Path("/data/caracole/state")
    assert cfg.cache_dir == Path("/data/caracole/cache")


def test_data_dir_tilde_and_relative_paths(tmp_path):
    home = tmp_path / "home"
    cfg = load_config(write(tmp_path, 'data_dir = "~/caracole"\n'), env={"HOME": str(home)})
    assert cfg.library_dir == home / "caracole/library"
    assert cfg.state_dir == home / "caracole/state"
    cfg = load_config(write(tmp_path, 'data_dir = "data"\n'), env={"HOME": str(home)})
    assert cfg.music_dir == tmp_path / "data/music"
    assert cfg.cache_dir == tmp_path / "data/cache"


def test_an_empty_data_dir_leaves_the_defaults(tmp_path):
    home = tmp_path / "home"
    cfg = load_config(write(tmp_path, 'data_dir = ""\n'), env={"HOME": str(home)})
    assert cfg.library_dir == home / "Tabs"
    assert cfg.music_dir == home / "Music"
    assert cfg.state_dir == home / ".local/state/caracole"
    assert cfg.cache_dir == home / ".cache/caracole"


def test_credentials_directory_secret_is_stripped(tmp_path):
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "ntfy_token").write_text("tk_123\n")
    cfg = load_config(None, env={"HOME": str(tmp_path), "CREDENTIALS_DIRECTORY": str(creds),
                                 "CARACOLE_NTFY_TOKEN": "from-env"})
    assert cfg.ntfy.token == "tk_123"


def test_secret_file_key_then_env_fallback(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("from-file\n")
    p = write(tmp_path, f'[ntfy]\ntoken_file = "{secret}"\n')
    assert load_config(p, env={"HOME": str(tmp_path), "CARACOLE_NTFY_TOKEN": "from-env"}).ntfy.token == "from-file"
    cfg = load_config(None, env={"HOME": str(tmp_path), "CARACOLE_NTFY_TOKEN": "from-env"})
    assert cfg.ntfy.token == "from-env"


@pytest.mark.parametrize("table", [
    '[spotify]\nclient_id = "abc"\nplaylists = ["Learn"]\nclient_secret_file = "/run/agenix/gone"\n',
    "[spotify]\n",
    'spotify = "whatever an older file held"\n',
], ids=["its-settings", "empty", "not-a-table"])
def test_a_file_that_still_has_spotify_loads_and_says_once_to_delete_it(tmp_path, caplog, table):
    # An older caracole read Spotify; this one doesn't: an upgrade must not stop the nightly run, so the
    # table is ignored, its secret file unread, and the log says what to delete.
    p = write(tmp_path, f'library_dir = "/srv/tabs"\n{table}[ntfy]\nurl = "https://ntfy.sh/t"\n')
    with caplog.at_level(logging.WARNING, logger="caracole.config"):
        cfg = load_config(p, env={"HOME": str(tmp_path)})
    assert cfg.library_dir == Path("/srv/tabs") and cfg.ntfy.url == "https://ntfy.sh/t"
    assert not hasattr(cfg, "spotify")
    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert str(p) in record.getMessage() and "delete its [spotify] table" in record.getMessage()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="caracole.config"):
        load(tmp_path, "[ntfy]\n")
    assert caplog.records == []  # a file without it says nothing


def test_unknown_key_is_config_error(tmp_path):
    p = write(tmp_path, "[providers.ug]\nbudgte = 5\n")
    with pytest.raises(ConfigError, match="budgte"):
        load_config(p, env={"HOME": str(tmp_path)})


def test_unknown_top_level_key_is_config_error(tmp_path):
    p = write(tmp_path, 'libary_dir = "/x"\n')
    with pytest.raises(ConfigError, match="libary_dir"):
        load_config(p, env={"HOME": str(tmp_path)})


def test_automatic_guitar_pro_mode_is_rejected(tmp_path):
    # Ultimate Guitar stays assisted whatever the file says: its robots.txt closes /tab/download.
    # Automatic downloads are gtptabs.com's, switched in its own table.
    p = write(tmp_path, 'guitar_pro_mode = "automatic"\n')
    with pytest.raises(ConfigError, match=r"only 'assisted'.*\[providers\.gtptabs\]"):
        load_config(p, env={"HOME": str(tmp_path)})


def test_assisted_guitar_pro_mode_still_loads(tmp_path):
    # Older files, and the example in docs/usage.md, set it; it names UG's mode, which is fixed.
    p = write(tmp_path, 'guitar_pro_mode = "assisted"\n')
    cfg = load_config(p, env={"HOME": str(tmp_path)})
    assert cfg.provider("gtptabs").enabled


def test_gtptabs_downloads_are_on_by_default_with_a_small_budget(tmp_path):
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.provider("gtptabs") == ProviderPolicy(budget=20, delay=(10.0, 20.0), enabled=True)


def test_gtptabs_can_be_turned_off_and_keeps_its_other_settings(tmp_path):
    p = write(tmp_path, "[providers.gtptabs]\nenabled = false\ndelay = [12, 18]\n")
    policy = load_config(p, env={"HOME": str(tmp_path)}).provider("gtptabs")
    assert policy == ProviderPolicy(budget=20, delay=(12.0, 18.0), enabled=False)


def test_musescore_is_on_by_default_with_a_small_budget(tmp_path):
    # Its index is about 19 sitemaps: read over two nights, then refreshed monthly.
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.provider("musescore") == ProviderPolicy(budget=10, delay=(10.0, 20.0), enabled=True)


def test_musescore_can_be_turned_off(tmp_path):
    p = write(tmp_path, "[providers.musescore]\nenabled = false\n")
    assert load_config(p, env={"HOME": str(tmp_path)}).provider("musescore") == ProviderPolicy(
        budget=10, delay=(10.0, 20.0), enabled=False)


def test_only_gtptabs_and_musescore_can_be_turned_off(tmp_path):
    # UG, LRCLIB and LaCuerda are what caracole is built on: no switch, so a typo can't pass for one.
    for name in ("ug", "lrclib", "lacuerda"):
        p = write(tmp_path, f"[providers.{name}]\nenabled = false\n")
        with pytest.raises(ConfigError, match=rf"unknown key\(s\) in \[providers\.{name}\]: enabled"):
            load_config(p, env={"HOME": str(tmp_path)})


def test_gtptabs_enabled_must_be_true_or_false(tmp_path):
    p = write(tmp_path, '[providers.gtptabs]\nenabled = "no"\n')
    with pytest.raises(ConfigError, match=r'\[providers\.gtptabs\]\.enabled must be true or false, not "no"'):
        load_config(p, env={"HOME": str(tmp_path)})


def test_default_config_file_location(tmp_path):
    cfgdir = tmp_path / ".config/caracole"
    cfgdir.mkdir(parents=True)
    (cfgdir / "caracole.toml").write_text('library_dir = "/srv/tabs"\n')
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.library_dir == Path("/srv/tabs")


def test_missing_explicit_config_file_is_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml", env={"HOME": str(tmp_path)})


def test_autochords_settings(tmp_path):
    p = write(tmp_path, '[autochords]\nbtc_weights = "/w/btc.pt"\ndevice = "cpu"\n')
    cfg = load_config(p, env={"HOME": str(tmp_path), "CARACOLE_BEAT_CHECKPOINT": "/w/beat.ckpt"})
    assert cfg.autochords.btc_weights == Path("/w/btc.pt")
    assert cfg.autochords.beat_checkpoint == Path("/w/beat.ckpt")
    assert cfg.autochords.device == "cpu"


def test_cjk_font_setting_and_env(tmp_path):
    p = write(tmp_path, 'cjk_font = "/fonts/NotoSansCJK.ttc"\n')
    assert load_config(p, env={"HOME": str(tmp_path)}).cjk_font == Path("/fonts/NotoSansCJK.ttc")
    cfg = load_config(None, env={"HOME": str(tmp_path), "CARACOLE_CJK_FONT": "/env/font.otf"})
    assert cfg.cjk_font == Path("/env/font.otf")
    assert load_config(None, env={"HOME": str(tmp_path)}).cjk_font is None


def test_pdf_fonts_setting_and_env(tmp_path):
    p = write(tmp_path, 'pdf_fonts = "~/fonts/pdf"\n')
    env = {"HOME": str(tmp_path), "CARACOLE_PDF_FONTS": "/env/fonts"}
    assert load_config(p, env=env).pdf_fonts == tmp_path / "fonts/pdf"  # the file's wins
    assert load_config(None, env=env).pdf_fonts == Path("/env/fonts")
    assert load_config(None, env={"HOME": str(tmp_path)}).pdf_fonts is None
    with pytest.raises(ConfigError, match="pdf_fonts"):
        load_config(write(tmp_path, "pdf_fonts = 3\n"), env={"HOME": str(tmp_path)})


def test_youtube_is_a_switchable_provider_of_a_few_yt_dlp_runs_a_night(tmp_path):
    # A run is a search or a download: six are three songs. Its pauses are longer than a site's,
    # since each run sends several requests of its own (which yt-dlp's own pauses space out).
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.provider("youtube") == ProviderPolicy(budget=6, delay=(15.0, 30.0), enabled=True)
    p = write(tmp_path, "[providers.youtube]\nenabled = false\nbudget = 2\n")
    assert load_config(p, env={"HOME": str(tmp_path)}).provider("youtube") == ProviderPolicy(
        budget=2, delay=(15.0, 30.0), enabled=False)


def test_ytdlp_bin_setting_and_env(tmp_path):
    # As chordpro_bin, a program found on PATH by default; CARACOLE_YTDLP_BIN points elsewhere, and
    # the file's own key wins over both.
    assert load_config(None, env={"HOME": str(tmp_path)}).ytdlp_bin == "yt-dlp"
    env = {"HOME": str(tmp_path), "CARACOLE_YTDLP_BIN": "/opt/yt-dlp/bin/yt-dlp"}
    assert load_config(None, env=env).ytdlp_bin == "/opt/yt-dlp/bin/yt-dlp"
    p = write(tmp_path, 'ytdlp_bin = "/srv/yt-dlp"\n')
    assert load_config(p, env=env).ytdlp_bin == "/srv/yt-dlp"


# --- values of the wrong type or out of range -----------------------------------------------
#
# Unknown keys are errors so that a typo never falls back to a default unnoticed (usage.md);
# a value of the wrong type must not either, nor end in a traceback.


def load(tmp_path, text):
    return load_config(write(tmp_path, text), env={"HOME": str(tmp_path)})


@pytest.mark.parametrize(
    "toml,named",
    [
        ('data_dir = ["/data/caracole"]\n', "data_dir"),
        ("library_dir = 5\n", "library_dir"),
        ("music_dir = true\n", "music_dir"),
        ('state_dir = ["/srv/state"]\n', "state_dir"),
        ("cache_dir = 1.5\n", "cache_dir"),
        ("overrides_file = 5\n", "overrides_file"),
        ("wanted_file = 5\n", "wanted_file"),
        ("cjk_font = 5\n", "cjk_font"),
        ("[ntfy]\ntoken_file = 5\n", "token_file"),
        ("[autochords]\nbtc_weights = 5\n", "btc_weights"),
        ("[autochords]\nbeat_checkpoint = 5\n", "beat_checkpoint"),
    ],
)
def test_a_path_that_is_not_a_string_is_a_config_error(tmp_path, toml, named):
    with pytest.raises(ConfigError, match=f"{named} must be a string, not "):
        load(tmp_path, toml)


@pytest.mark.parametrize(
    "toml,named",
    [
        ("user_agent = 5\n", "user_agent"),
        ("chordpro_bin = 5\n", "chordpro_bin"),
        ("ytdlp_bin = 5\n", "ytdlp_bin"),
        ("[ntfy]\nurl = 5\n", "url"),
        ("[autochords]\ndevice = 0\n", "device"),
    ],
)
def test_a_setting_that_is_not_a_string_is_a_config_error(tmp_path, toml, named):
    with pytest.raises(ConfigError, match=f"{named} must be a string, not "):
        load(tmp_path, toml)


@pytest.mark.parametrize(
    "toml",
    [
        "[providers.ug]\nbudget = true\n",
        "[providers.ug]\nbudget = 2.5\n",
        '[providers.ug]\nbudget = "60"\n',
        "[providers.ug]\nbudget = -1\n",
        "[providers.ug]\ndelay = [true, 20]\n",
        "[providers.ug]\ndelay = [10, nan]\n",
    ],
)
def test_a_provider_budget_or_delay_of_the_wrong_kind_is_a_config_error(tmp_path, toml):
    with pytest.raises(ConfigError, match=r"\[providers\.ug\]\.(budget|delay) must be"):
        load(tmp_path, toml)


def test_an_unknown_provider_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="lrclb"):
        load(tmp_path, "[providers.lrclb]\nbudget = 5\n")


@pytest.mark.parametrize(
    "toml,named",
    [
        ('[match]\naccept = "90"\n', "accept"),
        ("[match]\naccept = true\n", "accept"),
        ("[match]\naccept = 120\n", "accept"),
        ("[match]\nmargin = -1\n", "margin"),
        ("[match]\nartist_gate = 101\n", "artist_gate"),
        ("[match]\nreview = nan\n", "review"),
        ("[rank]\ncoverage_threshold = 80\n", "coverage_threshold"),  # a fraction, not a percentage
        ('[rank]\nline_match = "85"\n', "line_match"),
        ("[rank]\nprior_votes = -1\n", "prior_votes"),
        ("[rank]\nprior_votes = inf\n", "prior_votes"),
        ("[rank]\nscored_sheets = 0\n", "scored_sheets"),
        ("[rank]\nscored_sheets = 2.5\n", "scored_sheets"),
        ("[rank]\nlabel_penalty = -0.5\n", "label_penalty"),
        ("[rank]\nvariant_bonus = false\n", "variant_bonus"),
        ("[rank]\nkeep_guitar_pro = 1.5\n", "keep_guitar_pro"),
    ],
)
def test_match_and_rank_values_of_the_wrong_kind_are_config_errors(tmp_path, toml, named):
    table = toml.split("]")[0].lstrip("[")
    with pytest.raises(ConfigError, match=rf"\[{table}\]\.{named} must be a (whole )?number"):
        load(tmp_path, toml)


def test_review_above_accept_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match=r"\[match\]\.review .* above \[match\]\.accept"):
        load(tmp_path, "[match]\naccept = 85\nreview = 88\n")


def test_match_and_rank_numbers_in_range_load(tmp_path):
    cfg = load(tmp_path, (
        "[match]\naccept = 92.5\nreview = 70\nmargin = 0\n"
        "[rank]\ncoverage_threshold = 0.75\nline_match = 80.5\n"
        "scored_sheets = 2\nkeep_guitar_pro = 0\n"
    ))
    assert (cfg.match.accept, cfg.match.review, cfg.match.margin) == (92.5, 70, 0)
    assert (cfg.rank.coverage_threshold, cfg.rank.line_match) == (0.75, 80.5)
    assert (cfg.rank.scored_sheets, cfg.rank.keep_guitar_pro) == (2, 0)


@pytest.mark.parametrize(
    "toml,named",
    [
        ("[rank]\nkeep_sheet = 1\n", "keep_sheet"),
        ("[rank]\nkeep_tab = 1\n", "keep_tab"),
        ('[autochords]\nbtc_config = "/models/btc.yaml"\n', "btc_config"),
    ],
)
def test_settings_caracole_never_reads_are_unknown_keys(tmp_path, toml, named):
    with pytest.raises(ConfigError, match=f"unknown key.*{named}"):
        load(tmp_path, toml)


# --- the interactive pace: one song you asked for just now -----------------------------------------


def test_every_provider_has_an_interactive_pace_by_default(tmp_path):
    # Bulk work keeps 10-20 s between requests; a lookup sends its few requests about a second apart.
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    for name in ("ug", "lrclib", "lacuerda", "gtptabs", "musescore"):
        policy = cfg.provider(name)
        assert policy.lookup_delay == (0.5, 1.5), name
        assert policy.lookup_requests == 6, name
        assert policy.lookup_per_hour == 60, name


def test_the_interactive_pace_is_set_per_provider(tmp_path):
    cfg = load(tmp_path, "[providers.ug]\nlookup_delay = [0, 0]\nlookup_requests = 10\nlookup_per_hour = 100\n")
    ug = cfg.provider("ug")
    assert (ug.budget, ug.delay) == (60, (10.0, 20.0))  # the bulk pace is untouched
    assert (ug.lookup_delay, ug.lookup_requests, ug.lookup_per_hour) == ((0.0, 0.0), 10, 100)
    assert cfg.provider("lacuerda").lookup_requests == 6


@pytest.mark.parametrize(
    "toml,where",
    [
        ("lookup_delay = [2, 1]", "lookup_delay"),
        ("lookup_delay = 1", "lookup_delay"),
        ("lookup_requests = -1", "lookup_requests"),
        ("lookup_requests = 2.5", "lookup_requests"),
        ("lookup_per_hour = true", "lookup_per_hour"),
        ('lookup_per_hour = "60"', "lookup_per_hour"),
    ],
)
def test_an_interactive_pace_of_the_wrong_kind_is_a_config_error(tmp_path, toml, where):
    with pytest.raises(ConfigError, match=rf"\[providers\.ug\]\.{where} must be"):
        load(tmp_path, f"[providers.ug]\n{toml}\n")
