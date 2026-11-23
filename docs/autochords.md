# Chords from audio (auto-chords)

For a song no site has charted, auto-chords works out the chords from its audio, on your computer, with local models.
It is optional: the default package doesn't have it.

## What you get

- For a song with no human sheet: the chords and the beats, as `sheet (auto).txt`, with a PDF and a viewer page.
- The sheet starts with "auto-generated, unverified". A complete human sheet found later takes its place.
- The to-do page lists the songs still without a human sheet: with YouTube, where each stands; without, where to buy it.

## Where the audio comes from

- **A song you bought:** drop the DRM-free file into `music_dir` (`~/Music`); caracole matches it by its tags and length.
- **YouTube, a few songs a night:** the nightly run takes the audio of songs with no human sheet.
- **A video you paste** on the library page, or the one it suggests for a search: the sheet is made at once.
- A purchase comes first: one you drop in later takes the video's place.
- Wrong video? Paste the right one under `[youtube]` in overrides.toml, or run `caracole youtube --song … --url URL`.

Details: [usage.md](usage.md#audio-from-youtube).

## YouTube is your choice

- Taking audio from YouTube goes against its robots.txt and its terms of service.
- It is the one site whose robots.txt caracole goes against. It never works around a block: no cookies, login or proxy.
- The audio stays in caracole's cache, outside your synced library.
- `[providers.youtube] enabled = false` turns it off. Auto-chords then works from your purchases alone.
- More: [Sites, and being a good guest](sources.md).

## Lyrics under the chords

- With timed lyrics, each chord goes over the lyrics where it starts.
- Without them, you get a chord chart, then the plain lyrics. With no lyrics at all, the chart alone.
- Lyrics a site gives later go under the sheet; timed ones put the chords over the words at the next run.
- Audio longer or shorter than the one the lyrics were timed for: auto-chords shifts the lyrics to fit, and says so.
- If no shift fits clearly, it shifts nothing: chart, then plain lyrics.
- No site has lyrics and the audio came from YouTube? caracole can hear the words with Whisper (`caracole transcribe`).
- caracole serve's library page offers it on the song's card: **Transcribe the lyrics**.
- That sheet says "Lyrics transcribed from the audio (Whisper), unverified". Lyrics a site has later win.

Details: [timed lyrics](usage.md#timed-lyrics-of-another-length), [transcribed lyrics](usage.md#lyrics-transcribed-from-the-audio).

## What it needs

- The `autochords` package: torch, librosa, beat_this, their model files and yt-dlp. About 3 GB more.
- Transcribing lyrics also needs Whisper large-v3, HTDemucs and demucs-rs. The Nix package brings them.
- No GPU needed: the chords take a few minutes a song on the CPU.
- With an NVIDIA GPU, `autochords-cuda` (about 7 GB, unfree CUDA libraries) transcribes in a couple of minutes, not up to half an hour.

## Turn it on

- With Nix: `nix profile add 'github:Danielhp95/caracole#autochords'`, or `#autochords-cuda` for the GPU.
- On NixOS: `services.caracole.autochords.enable = true;`, plus `services.caracole.autochords.cuda = true;` for the GPU.
- The service then makes the sheets after each successful nightly run, with no network.
- On Ubuntu without Nix: [deploy.md's section 12](deploy.md#12-auto-chords). It doesn't transcribe lyrics.
- caracole.toml's `[autochords]`: model files other than the package's, and where Whisper runs (`transcribe_device`).

Details: [install.md](install.md#with-nix), [deploy.md](deploy.md#4-auto-chords), [checking it works](deploy.md#checking-auto-chords).

## Commands

- `caracole autochords [--song "Artist - Title"]`: auto sheets from the audio you have, bought or from YouTube.
- `caracole youtube`: YouTube audio for the songs with no human sheet, as the nightly run takes it.
- `caracole youtube --song "Artist - Title" [--url URL] --sheet`: audio, lyrics, chords and PDF for that song, now.
- `caracole youtube --song "Artist - Title" --none`: no YouTube for that song.
- `caracole transcribe --song "Artist - Title"`: the words heard from the audio, then the sheet again over them.

Details: [usage.md](usage.md#one-step-at-a-time).

## Not on the phone

- The phone never runs auto-chords or yt-dlp. For a sheet from a YouTube video, use caracole serve in a browser.
