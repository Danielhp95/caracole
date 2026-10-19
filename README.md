# tabarr

Turns the songs you want to learn into a private library of sing-along chord
sheets, lyrics and guitar parts.

You list the songs in `wanted.txt`, or in a Spotify playlist if you like.
Each night tabarr matches them against a local index of Ultimate Guitar's
sitemaps and keeps each song's best chord sheet, preferring one with all the
lyrics, from Ultimate Guitar or, for Spanish songs, LaCuerda. It saves the
lyrics from LRCLIB, picks the best guitar parts, and renders a PDF in your
key. A to-do page lists the few things only you can do, such as a match to
confirm or a Guitar Pro file to download. For a song nobody has charted, buy
the track and a local model writes the chords.

It is polite by design: it never uses Ultimate Guitar's search or any other
page its robots.txt closes to bots, keeps to a small nightly budget of
requests, one at a time, never downloads Guitar Pro files itself, and backs
off when a site pushes back.

## Quick start

    nix shell .                   # tabarr on PATH; or nix build, then ./result/bin/tabarr
    tabarr add 宋冬野 斑马斑马 --album 安和桥北 --duration 4:13
    tabarr index build            # once: about 10 minutes, 10-20 s between requests
    tabarr match --dry-run        # how each song matches, saving nothing
    tabarr run                    # what the nightly timer runs

Then open `~/Tabs/_todo.md`, and `~/Tabs/index.html` to browse the library.
No configuration is needed to start; settings go in
`~/.config/tabarr/tabarr.toml`.

## Documentation

- [docs/usage.md](docs/usage.md): configuration, sources, the first run,
  every command, the to-do page, overrides.toml and the library folder, with a
  worked example.
- [docs/deploy.md](docs/deploy.md): running it nightly on a NixOS host, with
  agenix secrets, Syncthing, restic and the offline auto-chords unit.
- [plan.md](plan.md): the design, and why. The step 0 findings are in
  [docs/spike-2026-10-18.md](docs/spike-2026-10-18.md).

## Development

    nix develop
    pytest

    nix build                     # the package; its build runs the test suite
    nix build .#autochords        # with torch, beat-this and librosa
    nix flake check               # also evaluates the NixOS module's units

## License

MIT, see [LICENSE](LICENSE). The license covers tabarr's code. The sheets,
lyrics and tabs it downloads belong to their authors, so keep your library
private.
