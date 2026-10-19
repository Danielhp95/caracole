"""tabarr.toml: settings, directories and secrets.

Directories resolve in this order: an explicit key in the TOML file, then the
systemd-provided ``$STATE_DIRECTORY`` / ``$CACHE_DIRECTORY``, then the XDG base
directories, then ``~``. Secrets come from ``$CREDENTIALS_DIRECTORY`` (systemd
``LoadCredential``), then a ``*_file`` key, then an environment variable.
Unknown keys are errors, so a typo never silently falls back to a default.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

DEFAULT_USER_AGENT = "tabarr/0.1 (personal tab library)"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class ProviderPolicy:
    budget: int
    delay: tuple[float, float]


DEFAULT_PROVIDERS: dict[str, ProviderPolicy] = {
    "ug": ProviderPolicy(budget=60, delay=(10.0, 20.0)),
    "lrclib": ProviderPolicy(budget=200, delay=(1.0, 2.0)),
    "lacuerda": ProviderPolicy(budget=30, delay=(10.0, 20.0)),
}


@dataclass(frozen=True)
class SpotifyConfig:
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str = "http://127.0.0.1:8888/callback"
    liked_songs: bool = True
    playlists: tuple[str, ...] = ()
    suggest_top_tracks: bool = True

    @property
    def enabled(self) -> bool:
        """Spotify is optional: without a client id the source is skipped."""
        return bool(self.client_id)


@dataclass(frozen=True)
class MatchPolicy:
    accept: float = 90
    margin: float = 8
    review: float = 75
    artist_gate: float = 90


@dataclass(frozen=True)
class RankPolicy:
    coverage_threshold: float = 0.8
    line_match: int = 85
    prior_votes: int = 10
    scored_sheets: int = 3
    label_penalty: float = 0.5
    variant_bonus: float = 0.25
    keep_sheet: int = 1
    keep_guitar_pro: int = 2
    keep_tab: int = 1


@dataclass(frozen=True)
class NtfyConfig:
    url: str | None = None
    token: str | None = None


@dataclass(frozen=True)
class AutochordsConfig:
    btc_weights: Path | None = None
    btc_config: Path | None = None
    beat_checkpoint: Path | None = None
    device: str = "cpu"


@dataclass(frozen=True)
class Config:
    library_dir: Path
    music_dir: Path
    state_dir: Path
    cache_dir: Path
    overrides_file: Path
    wanted_file: Path
    user_agent: str = DEFAULT_USER_AGENT
    guitar_pro_mode: str = "assisted"
    chordpro_bin: str = "chordpro"
    cjk_font: Path | None = None
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    providers: Mapping[str, ProviderPolicy] = field(default_factory=lambda: dict(DEFAULT_PROVIDERS))
    match: MatchPolicy = field(default_factory=MatchPolicy)
    rank: RankPolicy = field(default_factory=RankPolicy)
    ntfy: NtfyConfig = field(default_factory=NtfyConfig)
    autochords: AutochordsConfig = field(default_factory=AutochordsConfig)

    @property
    def db_path(self) -> Path:
        return self.state_dir / "tabarr.sqlite"

    def provider(self, name: str) -> ProviderPolicy:
        return self.providers[name]


_TOP_KEYS = {
    "library_dir", "music_dir", "state_dir", "cache_dir", "overrides_file", "wanted_file",
    "user_agent", "guitar_pro_mode", "chordpro_bin", "cjk_font",
    "spotify", "providers", "match", "rank", "ntfy", "autochords",
}
_SPOTIFY_KEYS = {
    "client_id", "client_secret_file", "redirect_uri", "liked_songs", "playlists",
    "suggest_top_tracks",
}
_PROVIDER_KEYS = {"budget", "delay"}
_NTFY_KEYS = {"url", "token_file"}
_AUTOCHORDS_KEYS = {"btc_weights", "btc_config", "beat_checkpoint", "device"}


def _check_keys(table: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")


def _table(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"[{key}] must be a table")
    return value


class _Paths:
    def __init__(self, env: Mapping[str, str], base: Path | None):
        self.env = env
        self.base = base

    @property
    def home(self) -> Path:
        home = self.env.get("HOME")
        return Path(home) if home else Path.home()

    def resolve(self, value: str) -> Path:
        if value == "~" or value.startswith("~/"):
            return self.home / value[2:] if value != "~" else self.home
        p = Path(value)
        if not p.is_absolute() and self.base is not None:
            p = self.base / p
        return p

    def xdg(self, systemd_var: str, xdg_var: str, fallback: str) -> Path:
        systemd = self.env.get(systemd_var)
        if systemd:
            return Path(systemd.split(":")[0])
        xdg = self.env.get(xdg_var)
        if xdg:
            return Path(xdg) / "tabarr"
        return self.home / fallback / "tabarr"


def _read_secret(
    env: Mapping[str, str], paths: _Paths, credential: str, file_value: str | None, env_var: str
) -> str | None:
    creds = env.get("CREDENTIALS_DIRECTORY")
    if creds:
        p = Path(creds) / credential
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    if file_value:
        p = paths.resolve(file_value)
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ConfigError(f"cannot read secret file {p}: {e}") from e
    value = env.get(env_var)
    return value.strip() if value else None


def _delay(value: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(v, (int, float)) for v in value)
        or value[0] < 0
        or value[1] < value[0]
    ):
        raise ConfigError(f"{where}.delay must be [min, max] seconds")
    return (float(value[0]), float(value[1]))


def _default_config_path(paths: _Paths) -> Path | None:
    xdg = paths.env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else paths.home / ".config"
    candidate = base / "tabarr" / "tabarr.toml"
    return candidate if candidate.is_file() else None


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    """Load ``tabarr.toml``; with no path, use ``~/.config/tabarr/tabarr.toml`` if present."""
    env = dict(os.environ) if env is None else dict(env)
    probe = _Paths(env, None)
    if path is None:
        path = _default_config_path(probe)
    data: Mapping[str, Any] = {}
    if path is not None:
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e
    paths = _Paths(env, path.parent if path is not None else None)
    _check_keys(data, _TOP_KEYS, "tabarr.toml")

    def dir_value(key: str, default: Path) -> Path:
        value = data.get(key)
        return paths.resolve(value) if value else default

    library_dir = dir_value("library_dir", paths.home / "Tabs")
    music_dir = dir_value("music_dir", paths.home / "Music")
    state_dir = dir_value("state_dir", paths.xdg("STATE_DIRECTORY", "XDG_STATE_HOME", ".local/state"))
    cache_dir = dir_value("cache_dir", paths.xdg("CACHE_DIRECTORY", "XDG_CACHE_HOME", ".cache"))
    overrides_file = dir_value("overrides_file", library_dir / "overrides.toml")
    wanted_file = dir_value("wanted_file", library_dir / "wanted.txt")

    mode = data.get("guitar_pro_mode", "assisted")
    if mode != "assisted":
        raise ConfigError(
            f"guitar_pro_mode = {mode!r} is not supported; only 'assisted' is implemented "
            "(UG's robots.txt disallows /tab/download for bots)"
        )

    sp = _table(data, "spotify")
    _check_keys(sp, _SPOTIFY_KEYS, "[spotify]")
    playlists = sp.get("playlists", [])
    if not isinstance(playlists, list) or not all(isinstance(x, str) for x in playlists):
        raise ConfigError("[spotify].playlists must be a list of strings")
    spotify = SpotifyConfig(
        client_id=sp.get("client_id") or None,
        client_secret=_read_secret(
            env, paths, "spotify_client_secret", sp.get("client_secret_file"),
            "TABARR_SPOTIFY_CLIENT_SECRET",
        ),
        redirect_uri=sp.get("redirect_uri", SpotifyConfig.redirect_uri),
        liked_songs=bool(sp.get("liked_songs", True)),
        playlists=tuple(playlists),
        suggest_top_tracks=bool(sp.get("suggest_top_tracks", True)),
    )

    providers = dict(DEFAULT_PROVIDERS)
    for name, table in _table(data, "providers").items():
        if not isinstance(table, Mapping):
            raise ConfigError(f"[providers.{name}] must be a table")
        _check_keys(table, _PROVIDER_KEYS, f"[providers.{name}]")
        base = providers.get(name, ProviderPolicy(budget=30, delay=(10.0, 20.0)))
        budget = table.get("budget", base.budget)
        if not isinstance(budget, int) or budget < 0:
            raise ConfigError(f"[providers.{name}].budget must be a non-negative integer")
        delay = _delay(table["delay"], f"[providers.{name}]") if "delay" in table else base.delay
        providers[name] = ProviderPolicy(budget=budget, delay=delay)

    match_t = _table(data, "match")
    _check_keys(match_t, set(MatchPolicy.__dataclass_fields__), "[match]")
    rank_t = _table(data, "rank")
    _check_keys(rank_t, set(RankPolicy.__dataclass_fields__), "[rank]")

    ntfy_t = _table(data, "ntfy")
    _check_keys(ntfy_t, _NTFY_KEYS, "[ntfy]")
    ntfy = NtfyConfig(
        url=ntfy_t.get("url") or None,
        token=_read_secret(env, paths, "ntfy_token", ntfy_t.get("token_file"), "TABARR_NTFY_TOKEN"),
    )

    ac_t = _table(data, "autochords")
    _check_keys(ac_t, _AUTOCHORDS_KEYS, "[autochords]")

    def ac_path(key: str, env_var: str) -> Path | None:
        value = ac_t.get(key) or env.get(env_var)
        return paths.resolve(value) if value else None

    autochords = AutochordsConfig(
        btc_weights=ac_path("btc_weights", "TABARR_BTC_WEIGHTS"),
        btc_config=ac_path("btc_config", "TABARR_BTC_CONFIG"),
        beat_checkpoint=ac_path("beat_checkpoint", "TABARR_BEAT_CHECKPOINT"),
        device=ac_t.get("device", "cpu"),
    )

    cjk_font_value = data.get("cjk_font") or env.get("TABARR_CJK_FONT")

    return Config(
        library_dir=library_dir,
        music_dir=music_dir,
        state_dir=state_dir,
        cache_dir=cache_dir,
        overrides_file=overrides_file,
        wanted_file=wanted_file,
        user_agent=data.get("user_agent", DEFAULT_USER_AGENT),
        guitar_pro_mode=mode,
        chordpro_bin=data.get("chordpro_bin", "chordpro"),
        cjk_font=paths.resolve(cjk_font_value) if cjk_font_value else None,
        spotify=spotify,
        providers=providers,
        match=MatchPolicy(**match_t),
        rank=RankPolicy(**rank_t),
        ntfy=ntfy,
        autochords=autochords,
    )
