# caracole

caracole builds a private library of sing-along chord sheets, chords over the full
lyrics, for the songs you list. Every night it finds each new song's sheet (Ultimate
Guitar, LaCuerda), its lyrics (LRCLIB) and a Guitar Pro file where gtptabs.com has
one, and makes a PDF and a phone-friendly page of the sheet; for a song nobody has
charted, the optional auto-chords package works the chords out from the audio.
`caracole serve` puts the library, its search and your songbooks on your network.

![The library page searching for "traditional": four songs of the library and three that Ultimate Guitar has, under one artist, each with Open or Get it](docs/screenshots/library.png)

*Search your songs and the sites' indexes as you type; a song you haven't got is a Get it away.*

![Greensleeves on a laptop: chords over the lyrics, the rail of chord necks on the left, the transpose, capo, mode and chord-name settings on the right](docs/screenshots/sheet.png)

*Each sheet: the chords over the lyrics, their shapes on the neck, transpose, capo and mode.*

![Danny Boy with a Roman numeral beside each chord, and the Harmony panel listing each section's progression and the progressions it contains](docs/screenshots/harmony.png)

*The Harmony panel reads each section in its key: numerals, named progressions, and a ▶ that strums them.*

<p>
  <img src="docs/screenshots/phone-chord.png" width="300" alt="Scarborough Fair on a phone, the card of its G chord docked at the foot: its shape, other chords to play instead, its notes and the scale to solo in">
  <img src="docs/screenshots/phone-pinyin.png" width="300" alt="The Chinese folk song 茉莉花 on a phone, with the pinyin of each character between it and its chord">
</p>

*On a phone: tap a chord for its shapes, its notes and a scale to solo in; pinyin over Chinese lyrics.*

![The Songbooks tab: the Campfire songbook's set list, each song with the key it is played in, Amazing Grace's key, mode and capo open, and a guitar beside Greensleeves](docs/screenshots/songbooks.png)

*Songbooks: a set list with each song in the key you play it in, as a PDF, a phone page and a ChordPro file. The guitar marks a song with a Guitar Pro file.*

<img src="docs/screenshots/songbook-pdf.png" width="440" alt="A page of the songbook's PDF: Greensleeves, its chord diagrams, then its verses and chorus with the chords over the words">

*Every sheet and songbook is a PDF too, with its chord diagrams.*

![The Guitar Pro page: Greensleeves' melody drawn as a score and a tab, with Play, the tempo and a button for each track](docs/screenshots/guitar-pro.png)

*A song's Guitar Pro file, drawn and played in the browser.*

The pictures show a demo library of public-domain songs, which
[docs/screenshots/make.py](docs/screenshots/make.py) builds and photographs.

## Quick start

```sh
nix shell github:Danielhp95/caracole            # x86_64-linux; or see docs/install.md
caracole add "Traditional - Scarborough Fair"   # a line of ~/Tabs/wanted.txt
caracole index build                            # once: Ultimate Guitar's sitemaps, about 10 minutes
caracole run                                    # what the nightly run does, now
caracole serve                                  # the library at http://127.0.0.1:8737/
```

The library is the folder `~/Tabs`. No settings are needed to start; they go in
`~/.config/caracole/caracole.toml`, and `caracole serve --address` with
`--token-file` serves your network.

- [docs/install.md](docs/install.md): NixOS, Ubuntu with or without Nix, and from source.
- [docs/usage.md](docs/usage.md): every command, setting and file.
- [docs/deploy.md](docs/deploy.md): running it on a server.

caracole is gentle with the sites it reads: one request at a time, 10 to 20
seconds apart at night, within a small budget, never a page robots.txt closes,
and a day's rest when a site pushes back ([how](docs/usage.md#caracole-run)). The one exception is
YouTube, which only the auto-chords package uses, for the audio of songs nobody
has charted ([why](docs/usage.md#audio-from-youtube)). Keep your library private:
the sheets and lyrics are other people's work.

## Development

`nix develop`, then `pytest -q`. [AGENTS.md](AGENTS.md) says how the code is laid
out and the rules a change keeps.

## License

MIT.
