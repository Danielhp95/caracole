from pathlib import Path

import pytest

from tabarr.config import ConfigError, MatchPolicy, ProviderPolicy, RankPolicy, load_config


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "tabarr.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_defaults(tmp_path):
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.library_dir == tmp_path / "Tabs"
    assert cfg.music_dir == tmp_path / "Music"
    assert cfg.state_dir == tmp_path / ".local/state/tabarr"
    assert cfg.cache_dir == tmp_path / ".cache/tabarr"
    assert cfg.overrides_file == tmp_path / "Tabs/overrides.toml"
    assert cfg.wanted_file == tmp_path / "Tabs/wanted.txt"
    assert cfg.db_path == tmp_path / ".local/state/tabarr/tabarr.sqlite"
    assert cfg.user_agent == "tabarr/0.1 (personal tab library)"
    assert cfg.guitar_pro_mode == "assisted"
    assert cfg.chordpro_bin == "chordpro"
    assert cfg.providers["ug"] == ProviderPolicy(budget=60, delay=(10.0, 20.0))
    assert cfg.providers["lrclib"] == ProviderPolicy(budget=200, delay=(1.0, 2.0))
    assert cfg.providers["lacuerda"] == ProviderPolicy(budget=30, delay=(10.0, 20.0))
    assert cfg.match == MatchPolicy(accept=90, margin=8, review=75, artist_gate=90)
    assert cfg.rank == RankPolicy(
        coverage_threshold=0.8, line_match=85, prior_votes=10, scored_sheets=3,
        label_penalty=0.5, variant_bonus=0.25, keep_sheet=1, keep_guitar_pro=2, keep_tab=1,
    )
    assert cfg.spotify.redirect_uri == "http://127.0.0.1:8888/callback"
    assert cfg.spotify.client_id is None and not cfg.spotify.enabled
    assert cfg.spotify.liked_songs is True and cfg.spotify.playlists == ()
    assert cfg.ntfy.url is None and cfg.ntfy.token is None


def test_xdg_directories(tmp_path):
    env = {"HOME": str(tmp_path), "XDG_STATE_HOME": "/x/state", "XDG_CACHE_HOME": "/x/cache"}
    cfg = load_config(None, env=env)
    assert cfg.state_dir == Path("/x/state/tabarr")
    assert cfg.cache_dir == Path("/x/cache/tabarr")


def test_systemd_directories_win_over_xdg(tmp_path):
    env = {
        "HOME": str(tmp_path), "XDG_STATE_HOME": "/x/state",
        "STATE_DIRECTORY": "/var/lib/tabarr", "CACHE_DIRECTORY": "/var/cache/tabarr:/other",
    }
    cfg = load_config(None, env=env)
    assert cfg.state_dir == Path("/var/lib/tabarr")
    assert cfg.cache_dir == Path("/var/cache/tabarr")


def test_toml_values_tilde_and_relative_paths(tmp_path):
    p = write(tmp_path, """
library_dir = "~/Lib"
music_dir = "music"
state_dir = "/srv/state"

[spotify]
client_id = "abc"
playlists = ["Learn", "Campfire"]

[providers.ug]
budget = 20
delay = [12, 18]

[match]
accept = 92

[ntfy]
url = "https://ntfy.sh/tabarr-test"
""")
    cfg = load_config(p, env={"HOME": "/home/u", "STATE_DIRECTORY": "/var/lib/tabarr"})
    assert cfg.library_dir == Path("/home/u/Lib")
    assert cfg.music_dir == tmp_path / "music"
    assert cfg.state_dir == Path("/srv/state")
    assert cfg.overrides_file == Path("/home/u/Lib/overrides.toml")
    assert cfg.spotify.enabled and cfg.spotify.playlists == ("Learn", "Campfire")
    assert cfg.providers["ug"] == ProviderPolicy(budget=20, delay=(12.0, 18.0))
    assert cfg.providers["lrclib"].budget == 200
    assert cfg.match.accept == 92 and cfg.match.margin == 8
    assert cfg.ntfy.url == "https://ntfy.sh/tabarr-test"


def test_credentials_directory_secret_is_stripped(tmp_path):
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "spotify_client_secret").write_text("s3cret\n")
    (creds / "ntfy_token").write_text("tk_123\n")
    cfg = load_config(None, env={"HOME": str(tmp_path), "CREDENTIALS_DIRECTORY": str(creds)})
    assert cfg.spotify.client_secret == "s3cret"
    assert cfg.ntfy.token == "tk_123"


def test_secret_file_key_then_env_fallback(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("from-file\n")
    p = write(tmp_path, f'[spotify]\nclient_secret_file = "{secret}"\n')
    cfg = load_config(p, env={"HOME": str(tmp_path), "TABARR_NTFY_TOKEN": "from-env"})
    assert cfg.spotify.client_secret == "from-file"
    assert cfg.ntfy.token == "from-env"


def test_unknown_key_is_config_error(tmp_path):
    p = write(tmp_path, "[providers.ug]\nbudgte = 5\n")
    with pytest.raises(ConfigError, match="budgte"):
        load_config(p, env={"HOME": str(tmp_path)})


def test_unknown_top_level_key_is_config_error(tmp_path):
    p = write(tmp_path, 'libary_dir = "/x"\n')
    with pytest.raises(ConfigError, match="libary_dir"):
        load_config(p, env={"HOME": str(tmp_path)})


def test_automatic_guitar_pro_mode_is_rejected(tmp_path):
    p = write(tmp_path, 'guitar_pro_mode = "automatic"\n')
    with pytest.raises(ConfigError, match="assisted"):
        load_config(p, env={"HOME": str(tmp_path)})


def test_default_config_file_location(tmp_path):
    cfgdir = tmp_path / ".config/tabarr"
    cfgdir.mkdir(parents=True)
    (cfgdir / "tabarr.toml").write_text('library_dir = "/srv/tabs"\n')
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.library_dir == Path("/srv/tabs")


def test_missing_explicit_config_file_is_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml", env={"HOME": str(tmp_path)})


def test_autochords_settings(tmp_path):
    p = write(tmp_path, '[autochords]\nbtc_weights = "/w/btc.pt"\ndevice = "cpu"\n')
    cfg = load_config(p, env={"HOME": str(tmp_path), "TABARR_BEAT_CHECKPOINT": "/w/beat.ckpt"})
    assert cfg.autochords.btc_weights == Path("/w/btc.pt")
    assert cfg.autochords.beat_checkpoint == Path("/w/beat.ckpt")
    assert cfg.autochords.device == "cpu"
