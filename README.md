# caracole

caracole builds a folder of chord sheets for the songs you want to learn on
guitar. You give it a list of songs. Every night it finds a chord sheet with
the lyrics, saves the lyrics, and makes a PDF and a page for your phone. Each
song gets its key, and where the key came from.

    ~/Tabs/
    ├── wanted.txt              your songs, one "Artist - Title" per line
    ├── _todo.md                what caracole needs you to do
    ├── index.html              browse and search everything
    └── Oasis/Wonderwall/
        ├── sheet.pdf           chords over lyrics
        ├── sheet.html          the same on a phone: tap a chord for its shapes,
        │                       transpose, capo, other chords and modes in the key
        ├── lyrics.txt
        ├── tab.txt             a guitar tab, when there is one
        └── guitar-1.gp5        a Guitar Pro file, when there is one

Sheets come from Ultimate Guitar and, for Spanish songs, LaCuerda. Lyrics come
from LRCLIB. Guitar Pro files come from gtptabs.com, downloaded for you, and
from the Ultimate Guitar pages the to-do page lists for you to click. A Spotify
playlist works as a song list too, but you don't need one. For a song nobody
has charted, you can buy the track and let caracole work out the chords from
the audio.

## Install

See [docs/install.md](docs/install.md) for NixOS, Ubuntu and installing from
source. [docs/deploy.md](docs/deploy.md) covers running it nightly on a NixOS
server.

## Use

    caracole add "Oasis" "Wonderwall"   # or add a line to ~/Tabs/wanted.txt
    caracole index build                # once, takes about 10 minutes
    caracole run                        # what the nightly timer runs

Then open `~/Tabs/_todo.md`, or `~/Tabs/index.html` to browse. `caracole serve`
serves that page at `http://127.0.0.1:8737/`, with a form to request a song and
fetch it now. Settings go in `~/.config/caracole/caracole.toml`, and none are
needed to start. Commands, settings and overrides are explained in
[docs/usage.md](docs/usage.md).

## Requests

caracole is gentle with the sites it reads. It makes about 60 requests a night
to Ultimate Guitar, one at a time and 10 to 20 seconds apart. It follows
robots.txt, never uses a site's search, never logs in, and stops for at least a
day when a site pushes back. It downloads Guitar Pro files only where
robots.txt allows it: from gtptabs.com, with at most 20 requests a night, one
file for each song that has none. Ultimate Guitar's robots.txt closes its
downloads to bots, so its Guitar Pro pages are yours to click. From MuseScore it
reads only the song sitemaps its robots.txt lists, for links to its pages, and
downloads nothing: a download there needs a login. A Cloudflare challenge, which
is what MuseScore answered caracole with in October 2026, counts as a block.

## Development

    nix develop
    pytest

## License

MIT. The sheets and lyrics caracole downloads belong to their authors, so keep
your library to yourself.
