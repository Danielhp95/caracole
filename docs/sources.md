# The sites caracole reads

| What | From |
|---|---|
| Chord sheets, text tabs, ukulele chords | Ultimate Guitar |
| Spanish chord sheets | LaCuerda |
| Lyrics | LRCLIB, then Megalobiz, then AZLyrics |
| Guitar Pro files | gtptabs.com |
| Harmonica tabs | harptabs.com |
| Video game music tabs | gametabs.net |
| Jazz chord charts | iReal Pro's forum |
| Scores | MuseScore, as links you open |
| Audio, for [chords from audio](autochords.md) | YouTube, optional |

caracole is slow on purpose. It sends one request at a time, waits between requests, has a small
budget per site each night, and never asks for a page that a site's robots.txt closes. When a
site blocks it, it stops and stays away for a day or more. The numbers are under
[caracole run](usage.md#caracole-run).

## Exceptions

A few things go against a site's rules. You can turn each off with `[providers.NAME] enabled = false`
in caracole.toml.

- **YouTube.** The optional chords-from-audio add-on takes the audio of a few songs a night,
  against YouTube's robots.txt and terms. See [Audio from YouTube](usage.md#audio-from-youtube).
- **harptabs.com, gametabs.net and AZLyrics.** Their terms forbid bots. caracole still keeps a
  tab or a song's lyrics from them, only for songs on your list, and follows their robots.txt.
- **Links shared to the phone.** Spotify, TIDAL and YouTube forbid automated access. When you
  share a link to the app, it asks that service once for the song's name.

## The published catalogues

Once a week the author's computer writes every site's index (Ultimate Guitar, LaCuerda,
gtptabs.com, MuseScore, harptabs.com and gametabs.net) into one file, and uploads it to this
repository's `indexes` release on GitHub. The app's **Download the site catalogues** fetches it
([the phone](phone.md)). It holds only what the sites list: titles, artists and addresses, and the
artist pages caracole has read. It leaves out your library, your searches on LaCuerda and any
path on the computer. To publish your own, see `caracole index publish` in
[usage.md](usage.md#caracole-index-publish).

## The chord models for the phone

For [chords from audio on the phone](autochords.md#on-the-phone), Settings › Chords from audio downloads two models
once, when you tap Download, through GitHub's API with caracole's own user agent. beat_this (MIT), converted for the
phone, comes from this repository's `models` release. BTC comes from its authors' own repository, the file unchanged:
caracole never republishes it. Each file is checked against its SHA-256 before it is kept. If GitHub says the hour's
requests are spent, the app waits until then and asks nothing before. The owner uploads beat_this's two files to that
release by hand, with `nix run .#publish-models -- DIR` (nix/publish-models.sh): each is checked against the app's
pins first and uploaded only once.

The sheets and lyrics are other people's work. Keep your library private.
