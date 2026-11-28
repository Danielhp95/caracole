# :youtube's device test assets

Made here for these tests, CC0 (no recording, no download): nothing of YouTube's, or anyone's.

- `clip.m4a` (37,982 bytes): 6 s of music synthesized by `tests/helpers/synth_music.py` (`render(Spec(6.0,
  (Part(120.0, ("C", "G", "Am")),)), 5)`: 120 BPM in 4, a chord a bar), encoded to AAC in MP4 by FFmpeg 9.0.1:

      ffmpeg -i clip.wav -c:a aac -b:a 48k -map_metadata -1 -fflags +bitexact -flags:a +bitexact \
          -movflags +faststart clip.m4a

  YtDlpServiceTest and KillTest serve it on 127.0.0.1 as `audio/mp4` for yt-dlp to download through the gate.
- `loopback.p12`: a self-signed EC (P-256) certificate for 127.0.0.1 and its key, PKCS12 with the password
  `loopback`, which the tests' HTTPS server presents (yt-dlp is told `--no-check-certificates` for that target alone):

      keytool -J-Dkeystore.pkcs12.legacy -genkeypair -alias loopback -keyalg EC -groupname secp256r1 \
          -sigalg SHA256withECDSA -dname CN=127.0.0.1 -ext SAN=ip:127.0.0.1 -validity 36500 -storetype PKCS12 \
          -keystore loopback.p12 -storepass loopback -keypass loopback
