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
from LRCLIB. Guitar Pro files come from gtptabs.com, downloaded for you, or
from wherever you get one: drop it into `_inbox/` and caracole files it. For a
song nobody has charted, caracole works out the chords from the audio, with local models:
a track you bought, or, by default, the song's audio, which it takes from
YouTube with yt-dlp, a few songs a night.

## Install

See [docs/install.md](docs/install.md) for NixOS, Ubuntu and installing from
source. [docs/deploy.md](docs/deploy.md) covers running it nightly on a NixOS
server.

## Use

    caracole add "Oasis" "Wonderwall"   # or add a line to ~/Tabs/wanted.txt
    caracole index build                # once, takes about 10 minutes
    caracole run                        # what the nightly timer runs
    caracole get "Radiohead - Creep"    # one song now: its sheet in seconds
    caracole remove "Oasis - Wonderwall"   # gone for good, until you add it again

Then open `~/Tabs/_todo.md`, or `~/Tabs/index.html` to browse. `caracole serve`
serves that page at `http://127.0.0.1:8737/`, where its search box also
lists what Ultimate Guitar, LaCuerda, gtptabs.com and MuseScore have (from
caracole's offline indexes, and LaCuerda's own search) with a Get it on each, a form to request a song by
name, and a button on each song to remove it; the song's card, or the result's
row, says how a request goes, on one line. Settings go in
`~/.config/caracole/caracole.toml`, and none are needed to start. Commands,
settings and overrides are explained in
[docs/usage.md](docs/usage.md).

## Requests

caracole is gentle with the sites it reads. It makes about 60 requests a night
to Ultimate Guitar, one at a time and 10 to 20 seconds apart. A song you look
up now (`caracole get`) costs a few requests, about a second apart, and every
lookup of an hour shares a budget of 60 requests a site. It follows
robots.txt, never logs in, and stops for at least a day when a site pushes
back. It uses no site's search but LaCuerda's, whose robots.txt is empty: one
request for a query you typed and left in the served page's search box, once
in 30 days a query, at most 20 an hour, within that hour's 60. It downloads Guitar Pro files only where
robots.txt allows it: from gtptabs.com, with at most 20 requests a night, one
file for each song that has none. From Ultimate Guitar it takes chords and
text tabs alone, never a Guitar Pro file: its robots.txt closes its downloads
to bots. From MuseScore it
reads only the song sitemaps its robots.txt lists, for links to its pages, and
downloads nothing: a download there needs a login. A Cloudflare challenge, which
is what MuseScore answered caracole with in October 2026, counts as a block.

YouTube is the one exception, made on purpose, for a personal library: caracole
uses its search there, its robots.txt closes that search and the API yt-dlp
uses, and its terms allow no such downloads, so this route is your choice to
keep or turn off. caracole goes there only for the audio of a song no one has
charted, only with auto-chords to make chords of it, and on the same terms as
elsewhere: at most 6 yt-dlp runs a night (three songs), with pauses, no cookies
and no login, and a cooldown when YouTube pushes back. `[providers.youtube]
enabled = false` turns it off; see
[docs/usage.md](docs/usage.md#audio-from-youtube).

## Development

    nix develop
    pytest
    caracole --help    # the checkout's own code, no install or rebuild

## License

MIT. The sheets and lyrics caracole downloads belong to their authors, so keep
your library to yourself.
