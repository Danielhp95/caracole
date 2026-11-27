#!/usr/bin/env bash
# Writes the decode gate's files (decode*.*: the design's §4.3), once, by hand, from steady.wav's first 6 s; no test
# runs it, and no test needs ffmpeg. ffmpeg is no dependency of caracole: run it from nixpkgs, at the repository's root,
#   nix shell --inputs-from . nixpkgs#ffmpeg nixpkgs#lame -c bash tests/fixtures/autochords/encode.sh
# then regenerate decode.jsonl (README.md says how). Each is CC0, as steady.wav is.
#
# - decode.mp3: LAME VBR, 22,050 Hz mono (MPEG-2, 576 samples a frame), with LAME's Xing header: its length and its
#   encoder delay and padding, which a reader trims.
# - decode-lame.mp3: the clip's first 3 s by the lame program itself, whose Xing header's LAME tag ("LAME4.0", nixpkgs' lame, which
#   FFmpeg's bitexact "Lavf" is not) mutagen reads: its length is the frames' less the encoder's delay and padding.
# - decode-headerless.mp3: LAME VBR with no Xing/Info or VBRI header, 0.05 s of loud noise first, so that its first
#   frame's bitrate is far above the file's mean (tests/fixtures/audio/make.sh's short-guess.mp3 on this clip):
#   libsndfile decodes only as far as it guesses from that frame, and the computer reads it again through FFmpeg
#   (autochords/audio.py load_mono); nothing trims it, every frame is decoded.
# - decode.m4a: FFmpeg's AAC-LC, 22,050 Hz mono, its priming in the MP4 edit list; no perceptual noise substitution
#   (-aac_pns 0, FFmpeg's default on), whose bands each decoder fills with noise of its own, so no two agree there.
# - decode-11k.m4a: the same at 11,025 Hz, 3 s: its last frame's padding (up to 1,023 samples) is past 0.05 s.
# - decode.ogg: Vorbis, 22,050 Hz mono. decode-opus.ogg: Opus, from 48 kHz (the rate both sides decode it at), mono.
# - decode.flac: 16-bit, 44.1 kHz stereo; decode.wav: 16-bit PCM, 48 kHz stereo; the right channel 0.6 of the left,
#   so a mixdown that isn't the mean shows (the WAV's first 2 s); decode.aiff: 24-bit big-endian PCM, 44.1 kHz mono,
#   2 s; decode-24.flac: 24-bit, 44.1 kHz mono, 1.5 s.
# - hearing.mp3 and hearing.m4a, the end-to-end gate's files (heard whole by both models, against the computer's
#   hearing of the same file: models.jsonl's "hearing" records): long.wav's first 20 s, the right channel 0.6 of the
#   left, as LAME VBR (-q:a 6) at 44.1 kHz stereo and as AAC-LC at 96 kb/s and 48 kHz stereo, the forms most of the
#   owner's own files take.
# - decode-frag.m4a and decode-dash.m4a, the fragmented MP4 yt-dlp leaves on the phone, which has no FFmpeg to remux it
#   ("writing DASH m4a"): decode-frag.m4a is decode.m4a's very AAC frames (-c copy) as fragmented MP4 (an empty moov,
#   its samples in a moof); decode-dash.m4a the clip as YouTube's itag 140 is coded, AAC-LC at 128 kb/s and 44.1 kHz
#   stereo (the right channel 0.6 of the left), as a DASH-style fragmented MP4: a dash brand, a global sidx, a moof and
#   an mdat a second. FFmpeg writes no edit list in either: the encoder's priming is in no box (README.md). Written on
#   2026-11-27 by `encode.sh fragmented`, which writes these two alone, with ffmpeg 9.0.1 (which writes decode.m4a
#   byte for byte as it is).
set -euo pipefail
cd "$(dirname "$0")"
plain=(-map_metadata -1 -fflags +bitexact -flags:a +bitexact)
ff() { ffmpeg -v error -y "$@"; }
clip=(-t 6 -i steady.wav)
stereo="pan=stereo|c0=c0|c1=0.6*c0"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

fragmented() {
  local frag=(-movflags frag_keyframe+empty_moov+default_base_moof)
  local dash=(-movflags dash+global_sidx+frag_keyframe+empty_moov+default_base_moof -frag_duration 1000000)
  ff -i decode.m4a -c copy "${plain[@]}" "${frag[@]}" decode-frag.m4a
  ff "${clip[@]}" "${plain[@]}" -af "$stereo" -ar 44100 -c:a aac -aac_pns 0 -b:a 128k "$work/itag140.m4a"
  ff -i "$work/itag140.m4a" -c copy "${plain[@]}" "${dash[@]}" decode-dash.m4a
}
if [ "${1:-}" = fragmented ]; then
  fragmented
  exit
fi

ff "${clip[@]}" "${plain[@]}" -id3v2_version 0 -c:a libmp3lame -q:a 4 decode.mp3
ff -f lavfi -i "anoisesrc=d=0.05:c=white:a=1.0:r=22050:s=1" "${clip[@]}" \
  -filter_complex "[0][1]concat=n=2:v=0:a=1" "${plain[@]}" -id3v2_version 0 -ac 1 -ar 22050 \
  -c:a libmp3lame -q:a 9 -write_xing 0 decode-headerless.mp3
ff "${clip[@]}" "${plain[@]}" -c:a aac -aac_pns 0 -b:a 64k decode.m4a
ff -t 3 -i steady.wav "${plain[@]}" -ar 11025 -c:a aac -aac_pns 0 -b:a 32k decode-11k.m4a
ff -t 3 -i steady.wav "$work/clip.wav"
lame --quiet -V 4 "$work/clip.wav" decode-lame.mp3
ff "${clip[@]}" "${plain[@]}" -c:a libvorbis -q:a 4 decode.ogg
ff "${clip[@]}" "${plain[@]}" -ar 48000 -c:a libopus -b:a 64k decode-opus.ogg
ff "${clip[@]}" "${plain[@]}" -af "$stereo" -ar 44100 -sample_fmt s16 -c:a flac decode.flac
ff -t 2 -i steady.wav "${plain[@]}" -af "$stereo" -ar 48000 -c:a pcm_s16le decode.wav
ff -t 2 -i steady.wav "${plain[@]}" -ar 44100 -c:a pcm_s24be decode.aiff
ff -t 1.5 -i steady.wav "${plain[@]}" -ar 44100 -sample_fmt s32 -c:a flac decode-24.flac
ff -t 20 -i long.wav "${plain[@]}" -af "$stereo" -ar 44100 -id3v2_version 0 -c:a libmp3lame -q:a 6 hearing.mp3
ff -t 20 -i long.wav "${plain[@]}" -af "$stereo" -ar 48000 -c:a aac -aac_pns 0 -b:a 96k hearing.m4a
fragmented
