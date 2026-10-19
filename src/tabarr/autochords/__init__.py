"""Auto-chords: a chord sheet for a song nobody has charted, from audio you bought.

Three steps, run offline by the ``tabarr-autochords`` unit:

1. ``btc.BTCRecognizer`` turns the audio into timed chords with the BTC model;
2. ``beats.detect_beats`` finds the beats and downbeats with beat_this;
3. ``merge.build_sheet`` snaps the chord changes to the beats and lays them out
   over LRCLIB's lyrics as ``sheet (auto).txt``.

Only ``merge`` is imported here: it is pure Python, while ``btc`` and ``beats``
need torch, librosa and beat_this, which only the auto-chords environment has.
"""

from tabarr.autochords.merge import ChordSegment, build_sheet, parse_lrc, snap_to_beats

__all__ = ["ChordSegment", "build_sheet", "parse_lrc", "snap_to_beats"]
