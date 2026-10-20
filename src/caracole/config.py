"""caracole.toml: settings, directories and secrets.

Directories resolve in this order: an explicit key in the TOML file, then the
``library``, ``music``, ``state`` or ``cache`` folder in ``data_dir`` when that
key is set, then the systemd-provided ``$STATE_DIRECTORY`` /
``$CACHE_DIRECTORY``, then the XDG base directories, then ``~``. Secrets come
from ``$CREDENTIALS_DIRECTORY`` (systemd ``LoadCredential``), then a ``*_file``
key, then an environment variable.
Unknown keys are errors, and so are values of the wrong type or out of range,
so a typo never silently falls back to a default or turns into another value.
"""

from __future__ import annotations

import json
import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

DEFAULT_USER_AGENT = "caracole/0.1 (personal tab library)"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class ProviderPolicy:
    budget: int
    delay: tuple[float, float]
    enabled: bool = True  # only a provider in SWITCHABLE can be off


DEFAULT_PROVIDERS: dict[str, ProviderPolicy] = {
    "ug": ProviderPolicy(budget=60, delay=(10.0, 20.0)),
    "lrclib": ProviderPolicy(budget=200, delay=(1.0, 2.0)),
    "lacuerda": ProviderPolicy(budget=30, delay=(10.0, 20.0)),
    # Guitar Pro files, downloaded for you: its robots.txt allows /tabs/download/ (gtptabs.py).
    "gtptabs": ProviderPolicy(budget=20, delay=(10.0, 20.0)),
    # Its song sitemaps, for the to-do page's links: nothing is downloaded (musescore.py).
    "musescore": ProviderPolicy(budget=10, delay=(10.0, 20.0)),
    # yt-dlp, for the audio of a song nobody has charted (youtube.py): a budget of yt-dlp runs,
    # each a search or a download, so six are three songs a night. A run sends several requests,
    # which yt-dlp's own pauses space out; these pauses go between two runs.
    "youtube": ProviderPolicy(budget=6, delay=(15.0, 30.0)),
}
# The providers [providers.<name>] can turn off with `enabled = false`. The others are what
# caracole is built on, so for them `enabled` is an unknown key like any other.
SWITCHABLE = frozenset({"gtptabs", "musescore", "youtube"})


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
    keep_guitar_pro: int = 2


# What each [match] and [rank] value may be: (lowest, highest or None, whole numbers only).
_MATCH_RANGES = {
    "accept": (0, 100, False),
    "margin": (0, 100, False),
    "review": (0, 100, False),
    "artist_gate": (0, 100, False),
}
_RANK_RANGES = {
    "coverage_threshold": (0, 1, False),  # a fraction of the lyric lines
    "line_match": (0, 100, False),
    "prior_votes": (0, None, False),
    "scored_sheets": (1, None, True),
    "label_penalty": (0, None, False),
    "variant_bonus": (0, None, False),
    "keep_guitar_pro": (0, None, True),
}


@dataclass(frozen=True)
class NtfyConfig:
    url: str | None = None
    token: str | None = None


@dataclass(frozen=True)
class AutochordsConfig:
    btc_weights: Path | None = None
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
    ytdlp_bin: str = "yt-dlp"
    cjk_font: Path | None = None
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    providers: Mapping[str, ProviderPolicy] = field(default_factory=lambda: dict(DEFAULT_PROVIDERS))
    match: MatchPolicy = field(default_factory=MatchPolicy)
    rank: RankPolicy = field(default_factory=RankPolicy)
    ntfy: NtfyConfig = field(default_factory=NtfyConfig)
    autochords: AutochordsConfig = field(default_factory=AutochordsConfig)

    @property
    def db_path(self) -> Path:
        return self.state_dir / "caracole.sqlite"

    def provider(self, name: str) -> ProviderPolicy:
        return self.providers[name]


_TOP_KEYS = {
    "data_dir", "library_dir", "music_dir", "state_dir", "cache_dir", "overrides_file",
    "wanted_file",
    "user_agent", "guitar_pro_mode", "chordpro_bin", "ytdlp_bin", "cjk_font",
    "spotify", "providers", "match", "rank", "ntfy", "autochords",
}
_SPOTIFY_KEYS = {
    "client_id", "client_secret_file", "redirect_uri", "liked_songs", "playlists",
    "suggest_top_tracks",
}
_PROVIDER_KEYS = {"budget", "delay"}
_NTFY_KEYS = {"url", "token_file"}
_AUTOCHORDS_KEYS = {"btc_weights", "beat_checkpoint", "device"}


def _check_keys(table: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")


def _table(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"[{key}] must be a table")
    return value


def _shown(value: Any) -> str:
    """A value about as TOML writes it, for an error message: true, "false", 5."""
    if isinstance(value, bool):
        return "true" if value else "false"
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):  # a TOML date, say
        return str(value)


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{where} must be a string, not {_shown(value)}")
    return value


def _optional_string(table: Mapping[str, Any], key: str, where: str) -> str | None:
    """The string at ``key``, or None when it's absent or empty."""
    value = table.get(key)
    if value is None:
        return None
    return _string(value, where) or None


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where} must be true or false, not {_shown(value)}")
    return value


def _number(value: Any, where: str, low: float, high: float | None, whole: bool) -> float:
    """A finite number (never a boolean) from ``low`` up to ``high``; ``whole`` wants an integer."""
    kinds = int if whole else (int, float)
    if (
        isinstance(value, bool)
        or not isinstance(value, kinds)
        or not math.isfinite(value)
        or value < low
        or (high is not None and value > high)
    ):
        kind = "a whole number" if whole else "a number"
        span = f"from {low:g} to {high:g}" if high is not None else f"of {low:g} or more"
        raise ConfigError(f"{where} must be {kind} {span}, not {_shown(value)}")
    return value


def _numbers(table: Mapping[str, Any], ranges: Mapping[str, tuple], where: str) -> dict[str, Any]:
    _check_keys(table, set(ranges), where)
    return {key: _number(value, f"{where}.{key}", *ranges[key]) for key, value in table.items()}


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
            return Path(xdg) / "caracole"
        return self.home / fallback / "caracole"


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
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
        or not all(math.isfinite(v) for v in value)
        or value[0] < 0
        or value[1] < value[0]
    ):
        raise ConfigError(f"{where}.delay must be [min, max] seconds, not {_shown(value)}")
    return (float(value[0]), float(value[1]))


def _default_config_path(paths: _Paths) -> Path | None:
    xdg = paths.env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else paths.home / ".config"
    candidate = base / "caracole" / "caracole.toml"
    return candidate if candidate.is_file() else None


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    """Load ``caracole.toml``; with no path, use ``~/.config/caracole/caracole.toml`` if present."""
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
    _check_keys(data, _TOP_KEYS, "caracole.toml")

    def dir_value(key: str, default: Path) -> Path:
        value = _optional_string(data, key, key)
        return paths.resolve(value) if value else default

    data_value = _optional_string(data, "data_dir", "data_dir")
    data_dir = paths.resolve(data_value) if data_value else None

    def default_dir(name: str, fallback: Path) -> Path:
        """The folder ``name`` in data_dir when that is set, else ``fallback``."""
        return data_dir / name if data_dir is not None else fallback

    xdg_state = paths.xdg("STATE_DIRECTORY", "XDG_STATE_HOME", ".local/state")
    xdg_cache = paths.xdg("CACHE_DIRECTORY", "XDG_CACHE_HOME", ".cache")
    library_dir = dir_value("library_dir", default_dir("library", paths.home / "Tabs"))
    music_dir = dir_value("music_dir", default_dir("music", paths.home / "Music"))
    state_dir = dir_value("state_dir", default_dir("state", xdg_state))
    cache_dir = dir_value("cache_dir", default_dir("cache", xdg_cache))
    overrides_file = dir_value("overrides_file", library_dir / "overrides.toml")
    wanted_file = dir_value("wanted_file", library_dir / "wanted.txt")

    # Ultimate Guitar's mode, which its robots.txt fixes (it disallows /tab/download for bots):
    # the key stays so that older files load. Downloads for you are gtptabs.com's, in its table.
    mode = data.get("guitar_pro_mode", "assisted")
    if mode != "assisted":
        raise ConfigError(
            f"guitar_pro_mode = {_shown(mode)} is not supported; only 'assisted' is: Ultimate Guitar's "
            "robots.txt disallows /tab/download for bots, so its Guitar Pro pages are yours to click. "
            "caracole downloads Guitar Pro files for you from gtptabs.com only, unless "
            "[providers.gtptabs] says enabled = false"
        )

    sp = _table(data, "spotify")
    _check_keys(sp, _SPOTIFY_KEYS, "[spotify]")
    playlists = sp.get("playlists", [])
    if not isinstance(playlists, list) or not all(isinstance(x, str) for x in playlists):
        raise ConfigError("[spotify].playlists must be a list of strings")
    spotify = SpotifyConfig(
        client_id=_optional_string(sp, "client_id", "[spotify].client_id"),
        client_secret=_read_secret(
            env, paths, "spotify_client_secret",
            _optional_string(sp, "client_secret_file", "[spotify].client_secret_file"),
            "CARACOLE_SPOTIFY_CLIENT_SECRET",
        ),
        redirect_uri=_string(
            sp.get("redirect_uri", SpotifyConfig.redirect_uri), "[spotify].redirect_uri"
        ),
        liked_songs=_bool(sp.get("liked_songs", True), "[spotify].liked_songs"),
        playlists=tuple(playlists),
        suggest_top_tracks=_bool(
            sp.get("suggest_top_tracks", True), "[spotify].suggest_top_tracks"
        ),
    )

    providers = dict(DEFAULT_PROVIDERS)
    for name, table in _table(data, "providers").items():
        if name not in DEFAULT_PROVIDERS:
            known = ", ".join(sorted(DEFAULT_PROVIDERS))
            raise ConfigError(
                f"unknown provider [providers.{name}]; caracole's providers are {known}"
            )
        if not isinstance(table, Mapping):
            raise ConfigError(f"[providers.{name}] must be a table")
        keys = _PROVIDER_KEYS | ({"enabled"} if name in SWITCHABLE else set())
        _check_keys(table, keys, f"[providers.{name}]")
        base = providers[name]
        budget = table.get("budget", base.budget)
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
            raise ConfigError(
                f"[providers.{name}].budget must be a non-negative integer, not {_shown(budget)}"
            )
        delay = _delay(table["delay"], f"[providers.{name}]") if "delay" in table else base.delay
        enabled = _bool(table.get("enabled", base.enabled), f"[providers.{name}].enabled")
        providers[name] = ProviderPolicy(budget=budget, delay=delay, enabled=enabled)

    match = MatchPolicy(**_numbers(_table(data, "match"), _MATCH_RANGES, "[match]"))
    if match.review > match.accept:
        raise ConfigError(
            f"[match].review ({match.review:g}) must not be above [match].accept ({match.accept:g})"
        )
    rank = RankPolicy(**_numbers(_table(data, "rank"), _RANK_RANGES, "[rank]"))

    ntfy_t = _table(data, "ntfy")
    _check_keys(ntfy_t, _NTFY_KEYS, "[ntfy]")
    ntfy = NtfyConfig(
        url=_optional_string(ntfy_t, "url", "[ntfy].url"),
        token=_read_secret(
            env, paths, "ntfy_token", _optional_string(ntfy_t, "token_file", "[ntfy].token_file"),
            "CARACOLE_NTFY_TOKEN",
        ),
    )

    ac_t = _table(data, "autochords")
    _check_keys(ac_t, _AUTOCHORDS_KEYS, "[autochords]")

    def ac_path(key: str, env_var: str) -> Path | None:
        value = _optional_string(ac_t, key, f"[autochords].{key}") or env.get(env_var)
        return paths.resolve(value) if value else None

    autochords = AutochordsConfig(
        btc_weights=ac_path("btc_weights", "CARACOLE_BTC_WEIGHTS"),
        beat_checkpoint=ac_path("beat_checkpoint", "CARACOLE_BEAT_CHECKPOINT"),
        device=_string(ac_t.get("device", "cpu"), "[autochords].device"),
    )

    cjk_font_value = _optional_string(data, "cjk_font", "cjk_font") or env.get("CARACOLE_CJK_FONT")
    ytdlp_bin = _optional_string(data, "ytdlp_bin", "ytdlp_bin") or env.get("CARACOLE_YTDLP_BIN") or "yt-dlp"

    return Config(
        library_dir=library_dir,
        music_dir=music_dir,
        state_dir=state_dir,
        cache_dir=cache_dir,
        overrides_file=overrides_file,
        wanted_file=wanted_file,
        user_agent=_string(data.get("user_agent", DEFAULT_USER_AGENT), "user_agent"),
        guitar_pro_mode=mode,
        chordpro_bin=_string(data.get("chordpro_bin", "chordpro"), "chordpro_bin"),
        ytdlp_bin=ytdlp_bin,
        cjk_font=paths.resolve(cjk_font_value) if cjk_font_value else None,
        spotify=spotify,
        providers=providers,
        match=match,
        rank=rank,
        ntfy=ntfy,
        autochords=autochords,
    )
