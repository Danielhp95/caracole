# Chords from audio

Some songs have no chords on any site. With this optional add-on, caracole listens to the song
and writes the chords itself, on your computer.

The result is a draft, and the sheet says so ("auto-generated, unverified"). If a site gets a
proper sheet later, caracole uses that one.

## Where the audio comes from

- A file you bought. Put it in `~/Music` and caracole matches it by its tags.
- YouTube. The nightly run takes the audio of a few songs that have no sheet.
- A video you choose. Paste its link on the library page and the sheet is made right away.
- A file from your computer: the **+** on the library page (or drop the file on it, or a song's
  Sheet from an audio file…), or `caracole audio FILE`. caracole keeps a copy as the song's audio, in place
  of anything it had, and makes the sheet right away.

An MP3 that never says its length (a recorder's, with no Xing or VBRI header) is measured by its frames and heard
whole, and a sheet an older caracole made from only its first part is made again once, by itself.

Each sheet remembers what was heard (the chords with their times, the beats, the song's length), which caracole
made it, from which file (its name and a hash of its bytes) and with which models. A song has one
sheet from audio, whichever of your caracoles made it. A sheet made before this remembers none of it, and is left as
it is.

Taking audio from YouTube goes against its robots.txt and its terms of service. That is your
call. `[providers.youtube] enabled = false` in caracole.toml turns it off, and the add-on then
works from your own files only. caracole never tries to get around a block.
More on this: [the sites caracole reads](sources.md).

## Lyrics

When a site has the lyrics, the chords go over the words. If the lyrics were timed for a
recording of another length, caracole shifts them to fit and says so on the sheet.
When lyrics arrive after the sheet was made, or become other words, the sheet is laid out again over them in seconds
from what was heard, without listening to the song again; the same words retimed (other times on a sheet already
timed) change nothing. A sheet made before caracole kept what was heard is made again by the models instead, as
before, and one made before caracole kept track of its words isn't made again for other words.

When no site has them and the song has audio of its own (YouTube's, a purchase's or a file you gave it),
**Transcribe the lyrics** on the song's card (or `caracole transcribe`) writes them down from the audio with Whisper.
The sheet is marked as transcribed, and lyrics from a site replace them later.

A sheet from a video you paste, or from a file you give, does this by itself: the lyrics sites first, then, if every
one missed, the words heard from the audio, then the chords over them. If the transcription fails, you still get the
chords, and the card still offers Transcribe the lyrics. `[autochords] transcribe = false` in caracole.toml turns this
off.

The nightly auto-chords run does the same for up to three songs a night, newest first, before their chords
(`[autochords] transcribe_per_run`, 0 for none). A song past that gets its chords tonight and its words on a later
night, and its sheet is made again then. On a CPU each song heard takes about 7 times its length, so three 4-minute
songs are about an hour and a half. If hearing a song fails (the separator, a stem cut short, Whisper's setup), the
night stops hearing, and the next nights pass over that song for 30 days, or until its file changes, so that the
others are heard; the to-do page lists it, and its card still offers Transcribe the lyrics.

With the GPU build (`autochords-cuda`), the nightly unit hears no words: its separator needs the GPU, and the nightly
unit doesn't see it. The to-do page says so. The words then come from the library page's jobs: a sheet from a video,
or Transcribe the lyrics on the song's card. With the CPU build, the nightly unit hears them on the CPU.

Audio Whisper can't read still gets its chords, wherever its words were to be heard. caracole then stops offering to
transcribe it until the file changes, and the to-do page lists it.

When caracole gets it wrong, the card lets you say otherwise. A song in which nothing sung was heard has **Transcribe
anyway**; one whose sheet is over its transcript has **Not sung: chords only**, which drops the words and never hears
that audio again (a new file is heard once more).

## Install

```sh
nix profile add 'github:Danielhp95/caracole#autochords'        # about 3 GB
nix profile add 'github:Danielhp95/caracole#autochords-cuda'   # for an NVIDIA GPU, about 7 GB
```

On NixOS, set `services.caracole.autochords.enable = true`, and `.cuda = true` for the GPU
([deploy.md](deploy.md#4-auto-chords)). On Ubuntu see [deploy.md](deploy.md#12-auto-chords);
lyrics are not transcribed there.

You don't need a GPU. Chords take a few minutes per song on a CPU. Transcribing lyrics takes up
to half an hour on a CPU and a couple of minutes on a GPU.

## Commands

| Command | What it does |
|---|---|
| `caracole autochords [--song "Artist - Title"]` | Makes sheets from the audio you have |
| `caracole youtube` | Takes tonight's audio from YouTube now |
| `caracole youtube --song "Artist - Title" [--url URL] --sheet` | Makes that song's sheet from a video, now |
| `caracole youtube --song "Artist - Title" --none` | Never uses YouTube for that song |
| `caracole transcribe --song "Artist - Title"` | Transcribes the lyrics, then remakes the sheet |
| `caracole transcribe --song "Artist - Title" --force` / `--none` | It is sung after all / it isn't sung |
| `caracole audio FILE [--song "Artist - Title"]` | Makes that song's sheet from an audio file of yours, now |

None of this runs on the phone. Details: [Audio from YouTube](usage.md#audio-from-youtube).

## The models for the phone

Chords on the phone are not built yet. A first step is in: `nix build .#chord-models` exports both
models to ONNX, the format the phone will run them in.

| File | Size | What it is |
|---|---|---|
| `btc-graph.onnx` | 1.4 MB | BTC, the chords model, without its weights |
| `btc_model_large_voca.pt` | 12.2 MB | BTC's weights: its authors' own file, unchanged. The graph reads them from it |
| `beat_this-final0.onnx` | 83.2 MB | beat_this, the beats model |
| `beat_this-final0-fp16.onnx` | 42.7 MB | the same, its weights stored at half precision |

caracole never republishes BTC's weights; the graph only points into its authors' file. Two builds
give the same bytes. beat_this's graph works out its attentions one slice at a time: the same answers, to
the bit, in about half the memory (a phone's limit is 1 GB).

BTC's graph takes the raw features and normalizes them itself. Its metadata gives the mean and
standard deviation it uses (`mean`, `std`) and the SHA-256 of the weights file it expects
(`weights_sha256`). Check the file against that hash before running the graph. Pad the frames
after the end of the audio with that mean, never with 0, or the chords of the last 10 seconds
come out wrong.
