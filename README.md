<img src="docs/logo/caracole_icon-256.png" alt="caracole's logo" width="128" align="right">

# caracole

**Your own songbook, built while you sleep.**

List the songs you want to play. Each night caracole finds their chords, lyrics and tabs and
saves them in a folder on your computer. Read them in the browser, on your phone, or on paper.

![The library page searching for "traditional": four songs you have and three you can get, under one artist](docs/screenshots/library.png)

## What it does

- Finds chord sheets, lyrics, Guitar Pro files, harmonica tabs and jazz charts on [several sites](docs/sources.md).
- Shows each sheet with transpose, capo, and chord shapes for guitar, ukulele, piano and more.
- Searches your songs and the sites' catalogues as you type, offline.
- Makes PDFs and songbooks.
- Optional: works out chords from the audio when no site has them.
- Syncs with an Android app.

Everything, in detail: [docs/features.md](docs/features.md).

## Computer and phone

The computer does the nightly work. The phone keeps a copy, works offline, and syncs with it.

| | Computer | Phone |
|---|:-:|:-:|
| Nightly run over your song list | Yes | No |
| Build the sites' catalogues | Yes | No, gets them by sync |
| Search, offline | Yes | Yes |
| Fetch one song now | Yes | Yes |
| Read sheets, songbooks, Guitar Pro | Yes | Yes |
| PDFs | Yes | Print only |
| Chords from audio, YouTube | Yes | No |
| Share a song or file from another app | No | Yes |

## Try it

```sh
nix shell github:Danielhp95/caracole     # other ways: docs/install.md
caracole add "Oasis - Wonderwall"        # a line of ~/Tabs/wanted.txt
caracole index build                     # once, about 4 minutes
caracole run                             # tonight's run, now
caracole serve                           # http://127.0.0.1:8737/
```

`caracole serve` has no sign-in: use it only on a network you trust.

## More

- [Install](docs/install.md) · [Use it](docs/usage.md) · [Run it as a nightly service](docs/deploy.md)
- [Android app](android/README.md): install from F-Droid, sync, what works offline
- [Sites, and being a good guest](docs/sources.md) · [Features](docs/features.md)
- To work on it: [AGENTS.md](AGENTS.md)

MIT licensed. The sheets and lyrics are other people's work, so keep your library private.
