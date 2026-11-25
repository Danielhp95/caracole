# Chords from audio

Some songs have no chords on any site. With this optional add-on, caracole listens to the song
and writes the chords itself, on your computer.

The result is a draft, and the sheet says so ("auto-generated, unverified"). If a site gets a
proper sheet later, caracole uses that one.

## Where the audio comes from

- A file you bought. Put it in `~/Music` and caracole matches it by its tags.
- YouTube. The nightly run takes the audio of a few songs that have no sheet.
- A video you choose. Paste its link on the library page and the sheet is made right away.

Taking audio from YouTube goes against its robots.txt and its terms of service. That is your
call. `[providers.youtube] enabled = false` in caracole.toml turns it off, and the add-on then
works from your own files only. caracole never tries to get around a block.
More on this: [the sites caracole reads](sources.md).

## Lyrics

When a site has the lyrics, the chords go over the words. If the lyrics were timed for a
recording of another length, caracole shifts them to fit and says so on the sheet.

When no site has them and the audio came from YouTube, **Transcribe the lyrics** on the song's
card (or `caracole transcribe`) writes them down from the audio with Whisper. The sheet is marked
as transcribed, and lyrics from a site replace them later.

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
give the same bytes.
