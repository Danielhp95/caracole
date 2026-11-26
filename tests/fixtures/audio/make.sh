#!/usr/bin/env bash
# Writes this folder's synthetic audio files, once, by hand; no test runs it, and no test needs ffmpeg.
# ffmpeg is no dependency of caracole: run it from nixpkgs, at the repository's root,
#   nix shell --inputs-from . nixpkgs#ffmpeg -c bash tests/fixtures/audio/make.sh
#
# - short-guess.mp3: a VBR MP3 with no Xing/Info or VBRI header whose first frame is loud (0.05 s of noise) and the
#   rest a quiet tone, so its first frame's bitrate is far above the file's mean: libsndfile and mutagen guess its
#   length from that frame (the file's size over it), far too short, and libsndfile's reads stop at the guess.
# - long-guess.mp3: its mirror, a quiet start at 32 kbps and then noise at 320, its first frame's bitrate far below
#   the mean: the guess far too long.
# - cbr.mp3: a CBR MP3 with no header, whose guess is exact; xing.mp3: a VBR MP3 with LAME's Xing header, whose
#   length is the header's; tone.m4a: AAC. The three every reader agrees on.
# - cbr-22k.mp3: a CBR MP3 at 22.05 kHz (MPEG-2, 576 samples a frame), for a stream that changes its rate.
set -euo pipefail
cd "$(dirname "$0")"
quiet=(-map_metadata -1 -fflags +bitexact -flags:a +bitexact -id3v2_version 0 -ac 2 -ar 44100)
ff() { ffmpeg -v error -y "$@"; }
noise() { echo "anoisesrc=d=$1:c=white:a=$2:r=44100:s=1"; }
tone() { echo "sine=f=$1:d=$2:r=44100"; }

ff -f lavfi -i "$(noise 0.05 1.0)" -f lavfi -i "$(tone 440 10)" \
  -filter_complex "[1]volume=0.05[t];[0][t]concat=n=2:v=0:a=1" \
  "${quiet[@]}" -c:a libmp3lame -q:a 9 -write_xing 0 short-guess.mp3
# LAME starts every stream with a large frame, its reservoir empty: a stream of 32 kbps frames, then one of 320 kbps,
# joined frame by frame (FFmpeg's concat, copied), as a recorder that changes its bitrate would write them.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
ff -f lavfi -i "$(tone 440 1)" -af volume=0.01 "${quiet[@]}" -c:a libmp3lame -b:a 32k -write_xing 0 "$work/quiet.mp3"
ff -f lavfi -i "$(noise 1 1.0)" "${quiet[@]}" -c:a libmp3lame -b:a 320k -write_xing 0 "$work/loud.mp3"
printf "file '%s'\n" "$work/quiet.mp3" "$work/loud.mp3" >"$work/list.txt"
ff -f concat -safe 0 -i "$work/list.txt" -map_metadata -1 -fflags +bitexact -id3v2_version 0 -write_xing 0 \
  -c copy long-guess.mp3
ff -f lavfi -i "$(tone 330 2)" "${quiet[@]}" -c:a libmp3lame -b:a 64k -write_xing 0 cbr.mp3
ff -f lavfi -i "$(tone 330 2)" "${quiet[@]}" -c:a libmp3lame -q:a 9 xing.mp3
ff -f lavfi -i "$(tone 330 1)" "${quiet[@]/44100/22050}" -c:a libmp3lame -b:a 32k -write_xing 0 cbr-22k.mp3
ff -f lavfi -i "$(tone 330 2)" -map_metadata -1 -fflags +bitexact -flags:a +bitexact -ac 2 -ar 44100 \
  -c:a aac -b:a 64k tone.m4a
