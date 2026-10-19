# tabarr

tabarr builds a folder of chord sheets for the songs you want to learn on
guitar. You give it a list of songs. Every night it finds a chord sheet with
the lyrics, saves the lyrics, and makes a PDF.

    ~/Tabs/
    ├── wanted.txt              your songs, one "Artist - Title" per line
    ├── _todo.md                what tabarr needs you to do
    ├── index.html              browse and search everything
    └── Oasis/Wonderwall/
        ├── sheet.pdf           chords over lyrics
        ├── lyrics.txt
        └── tab.txt             a guitar tab, when there is one

Sheets come from Ultimate Guitar and, for Spanish songs, LaCuerda. Lyrics come
from LRCLIB. A Spotify playlist works as a song list too, but you don't need
one. For a song nobody has charted, you can buy the track and let tabarr work
out the chords from the audio.

## Install

See [docs/install.md](docs/install.md) for NixOS, Ubuntu and installing from
source. [docs/deploy.md](docs/deploy.md) covers running it nightly on a NixOS
server.

## Use

    tabarr add "Oasis" "Wonderwall"   # or add a line to ~/Tabs/wanted.txt
    tabarr index build                # once, takes about 10 minutes
    tabarr run                        # what the nightly timer runs

Then open `~/Tabs/_todo.md`. Settings go in `~/.config/tabarr/tabarr.toml`,
and none are needed to start. Commands, settings and overrides are explained
in [docs/usage.md](docs/usage.md).

## Requests

tabarr is gentle with the sites it reads. It makes about 60 requests a night
to Ultimate Guitar, one at a time and 10 to 20 seconds apart. It follows
robots.txt, never uses a site's search, never downloads Guitar Pro files for
you, and stops for at least a day when a site pushes back.

## Development

    nix develop
    pytest

## License

MIT. The sheets and lyrics tabarr downloads belong to their authors, so keep
your library to yourself.
