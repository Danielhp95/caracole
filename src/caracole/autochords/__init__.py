"""Auto-chords: a chord sheet for a song nobody has charted, from audio you bought.

Three steps, run offline by the ``caracole-autochords`` unit:

1. ``btc.BTCRecognizer`` turns the audio into timed chords with the BTC model;
2. ``beats.detect_beats`` finds the beats and downbeats with beat_this;
3. ``merge.build_sheet`` snaps the chord changes to the beats and lays them out
   over LRCLIB's lyrics as ``sheet (auto).txt``; ``align.lyrics_offset`` first
   shifts timed lyrics LRCLIB timed for audio of another length, from those
   chords and beats, when one shift fits them clearly.

``run`` does all three for the songs that are due. Only ``merge`` is imported
here: it is pure Python, as ``align`` is, while ``btc`` and ``beats`` need torch,
librosa and beat_this, which only the auto-chords environment has.
"""

from caracole.autochords.merge import (
    ChordSegment,
    LrcLine,
    build_sheet,
    parse_lrc,
    parse_lrc_words,
    snap_to_beats,
)

__all__ = ["ChordSegment", "LrcLine", "build_sheet", "parse_lrc", "parse_lrc_words", "snap_to_beats"]
