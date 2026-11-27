#!/usr/bin/env bash
# Writes the decode gate's files (decode*.*: the design's §4.3), once, by hand, from steady.wav's first 6 s; no test
# runs it, and no test needs ffmpeg. ffmpeg is no dependency of caracole: run it from nixpkgs, at the repository's root,
#   nix shell --inputs-from . nixpkgs#ffmpeg -c bash tests/fixtures/autochords/encode.sh
# then regenerate decode.jsonl (README.md says how). Each is CC0, as steady.wav is.
#
# - decode.mp3: LAME VBR, 22,050 Hz mono (MPEG-2, 576 samples a frame), with LAME's Xing header: its length and its
#   encoder delay and padding, which a reader trims.
# - decode-headerless.mp3: LAME VBR with no Xing/Info or VBRI header, 0.05 s of loud noise first, so that its first
#   frame's bitrate is far above the file's mean (tests/fixtures/audio/make.sh's short-guess.mp3 on this clip):
#   libsndfile decodes only as far as it guesses from that frame, and the computer reads it again through FFmpeg
#   (autochords/audio.py load_mono); nothing trims it, every frame is decoded.
# - decode.m4a: FFmpeg's AAC-LC, 22,050 Hz mono, its priming in the MP4 edit list; no perceptual noise substitution
#   (-aac_pns 0, FFmpeg's default on), whose bands each decoder fills with noise of its own, so no two agree there.
# - decode.ogg: Vorbis, 22,050 Hz mono. decode-opus.ogg: Opus, from 48 kHz (the rate both sides decode it at), mono.
# - decode.flac: 16-bit, 44.1 kHz stereo; decode.wav: 16-bit PCM, 48 kHz stereo; the right channel 0.6 of the left,
#   so a mixdown that isn't the mean shows. decode.aiff: 24-bit big-endian PCM, 44.1 kHz mono.
set -euo pipefail
cd "$(dirname "$0")"
plain=(-map_metadata -1 -fflags +bitexact -flags:a +bitexact)
ff() { ffmpeg -v error -y "$@"; }
clip=(-t 6 -i steady.wav)
stereo="pan=stereo|c0=c0|c1=0.6*c0"

ff "${clip[@]}" "${plain[@]}" -id3v2_version 0 -c:a libmp3lame -q:a 4 decode.mp3
ff -f lavfi -i "anoisesrc=d=0.05:c=white:a=1.0:r=22050:s=1" "${clip[@]}" \
  -filter_complex "[0][1]concat=n=2:v=0:a=1" "${plain[@]}" -id3v2_version 0 -ac 1 -ar 22050 \
  -c:a libmp3lame -q:a 9 -write_xing 0 decode-headerless.mp3
ff "${clip[@]}" "${plain[@]}" -c:a aac -aac_pns 0 -b:a 64k decode.m4a
ff "${clip[@]}" "${plain[@]}" -c:a libvorbis -q:a 4 decode.ogg
ff "${clip[@]}" "${plain[@]}" -ar 48000 -c:a libopus -b:a 64k decode-opus.ogg
ff "${clip[@]}" "${plain[@]}" -af "$stereo" -ar 44100 -sample_fmt s16 -c:a flac decode.flac
ff "${clip[@]}" "${plain[@]}" -af "$stereo" -ar 48000 -c:a pcm_s16le decode.wav
ff "${clip[@]}" "${plain[@]}" -ar 44100 -c:a pcm_s24be decode.aiff
