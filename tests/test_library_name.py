"""caracole/library_name.py: which library a page shows, by its name, and a badge for one that isn't your usual one."""

from pathlib import Path

import pytest

from caracole.config import Config, ConfigError, load_config
from caracole.library_name import SCRATCH, LibraryName, scratch_badge


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "caracole.toml"
    p.write_text(text, encoding="utf-8")
    return p


def at(library: str, state: str) -> Config:
    """A config whose library and state are these folders (none need exist)."""
    lib = Path(library)
    return Config(library_dir=lib, music_dir=lib.parent / "music", state_dir=Path(state),
                  cache_dir=Path(state).parent / "cache", overrides_file=lib / "overrides.toml",
                  wanted_file=lib / "wanted.txt")


# --- the name -----------------------------------------------------------------------------------------------------


def test_a_library_is_named_by_its_folder_unless_caracole_toml_names_it(tmp_path):
    cfg = load_config(None, env={"HOME": str(tmp_path)})
    assert cfg.name is None and cfg.library_name == "Tabs"  # ~/Tabs
    cfg = load_config(write(tmp_path, f'library_dir = "{tmp_path / "Chord sheets"}"\n'), env={"HOME": str(tmp_path)})
    assert cfg.library_name == "Chord sheets"
    cfg = load_config(write(tmp_path, 'name = "  Dani\'s songs "\n'), env={"HOME": str(tmp_path)})
    assert cfg.name == "Dani's songs" and cfg.library_name == "Dani's songs"
    cfg = load_config(write(tmp_path, 'name = ""\n'), env={"HOME": str(tmp_path)})
    assert cfg.name is None and cfg.library_name == "Tabs"  # an empty name: the folder's


@pytest.mark.parametrize("toml,said", [
    ("name = 5\n", "name must be a string"),
    (f'name = "{"x" * 81}"\n', "name must be 80 characters at most"),
    ('name = "two\\nlines"\n', "name must be one line"),
])
def test_a_name_is_one_short_line(tmp_path, toml, said):
    with pytest.raises(ConfigError, match=said):
        load_config(write(tmp_path, toml), env={"HOME": str(tmp_path)})


def test_a_library_at_the_root_still_has_a_name():
    assert at("/", "/var/lib/caracole/state").library_name == "library"


# --- the badge ----------------------------------------------------------------------------------------------------

NIX_DEVELOP = {"HOME": "/home/dani", "TMPDIR": "/tmp/nix-shell.tlvFkV"}


@pytest.mark.parametrize("library,state,config,env", [
    ("/tmp/test-lib/library", "/tmp/test-lib/state", None, {"HOME": "/home/dani"}),
    ("/var/tmp/demo/Tabs", "/var/tmp/demo/state", None, {"HOME": "/home/dani"}),
    ("/dev/shm/pytest-of-dani/lib", "/dev/shm/pytest-of-dani/state", None, {"HOME": "/home/dani"}),
    # An agent's scratchpad in nix develop's TMPDIR, and a TMPDIR of one's own
    ("/tmp/nix-shell.tlvFkV/claude-1000/scratch/library", "/tmp/nix-shell.tlvFkV/claude-1000/scratch/state", None,
     NIX_DEVELOP),
    ("/home/dani/scratch/tmp/lib", "/home/dani/scratch/tmp/state", None,
     {"HOME": "/home/dani", "TMPDIR": "/home/dani/scratch/tmp"}),
    # The real library, served with a state of its own in a temporary folder: not the usual server
    ("/home/dani/Tabs", "/tmp/try/state", None, {"HOME": "/home/dani"}),
    # A config file in a temporary folder
    ("/home/dani/Tabs", "/home/dani/.local/state/caracole", "/tmp/try/caracole.toml", {"HOME": "/home/dani"}),
], ids=["tmp", "var-tmp", "dev-shm", "nix-develop-tmpdir", "own-tmpdir", "temporary-state", "temporary-config"])
def test_a_library_kept_in_a_temporary_folder_is_a_scratch_library(library, state, config, env):
    assert scratch_badge(at(library, state), config_path=Path(config) if config else None, env=env) == SCRATCH
    assert SCRATCH == "Scratch library"


@pytest.mark.parametrize("library,state,config", [
    # NixOS (services.caracole: dataDir /var/lib/caracole, its caracole.toml in the store)
    ("/var/lib/caracole/library", "/var/lib/caracole/state", "/nix/store/0123abcd-caracole.toml"),
    # Ubuntu without Nix (docs/deploy.md)
    ("/var/lib/caracole/library", "/var/lib/caracole/state", "/etc/caracole/caracole.toml"),
    # A library run by hand at home, with its XDG defaults
    ("/home/dani/Tabs", "/home/dani/.local/state/caracole", "/home/dani/.config/caracole/caracole.toml"),
    ("/home/dani/Tabs", "/home/dani/.local/state/caracole", None),
], ids=["nixos", "ubuntu", "home", "home-no-config"])
@pytest.mark.parametrize("env", [
    {"HOME": "/home/dani"}, NIX_DEVELOP, {"HOME": "/var/empty"},
    # A TMPDIR that holds the home folder, or is the root, marks nothing
    {"HOME": "/home/dani", "TMPDIR": "/home"}, {"HOME": "/home/dani", "TMP": "/"},
], ids=["home", "nix-develop", "service", "tmpdir-holds-home", "tmp-root"])
def test_the_owners_usual_libraries_are_never_badged(library, state, config, env):
    assert scratch_badge(at(library, state), config_path=Path(config) if config else None, env=env) is None


def test_a_label_says_what_the_library_is_wherever_it_lives():
    service = at("/var/lib/caracole/library", "/var/lib/caracole/state")
    scratch = at("/tmp/demo/library", "/tmp/demo/state")
    assert scratch_badge(scratch, label="Demo", env={}) == "Demo"
    assert scratch_badge(service, label="  Test  ", env={}) == "Test"
    assert scratch_badge(scratch, label="", env={}) is None  # --label "": no badge at all
    assert scratch_badge(scratch, label="   ", env={}) is None


def test_a_link_into_a_temporary_folder_counts_as_one(tmp_path):
    # /tmp may be reached by a link (macOS's /tmp is /private/tmp): folders are compared as the system resolves them.
    real = tmp_path / "real-tmp"
    (real / "lib").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "link").symlink_to(real)
    cfg = at(str(tmp_path / "home" / "link" / "lib"), str(tmp_path / "home" / ".local" / "state"))
    assert scratch_badge(cfg, env={"HOME": str(tmp_path / "home"), "TMPDIR": str(real)}) == SCRATCH


# --- what a page says -----------------------------------------------------------------------------------------------


def test_a_pages_title_names_caracole_and_the_library_and_a_badge_first():
    assert LibraryName("Tabs").title() == "caracole · Tabs"
    assert LibraryName("Tabs").title("Look up") == "Look up · caracole · Tabs"
    assert LibraryName("test-lib", SCRATCH).title() == "Scratch library · caracole · test-lib"
    assert LibraryName("Tabs", "Demo").title("Pick the match") == "Demo · Pick the match · caracole · Tabs"


def test_the_name_and_the_badge_are_escaped_markup():
    plain = LibraryName("Tabs & <b>chords</b>").markup()
    assert plain == '<span class="libname"><span class="name">Tabs &amp; &lt;b&gt;chords&lt;/b&gt;</span></span>'
    badged = LibraryName("lib", '"Demo"').markup("p")
    assert badged == ('<p class="libname"><span class="name">lib</span> '
                      '<span class="scratch" title="Not your usual library">&quot;Demo&quot;</span></p>')


def test_a_badged_library_has_its_own_icon():
    from caracole.page_icon import LINK

    assert LibraryName("Tabs").icon() == LINK
    other = LibraryName("lib", SCRATCH).icon()
    assert other != LINK and other.startswith('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,')
