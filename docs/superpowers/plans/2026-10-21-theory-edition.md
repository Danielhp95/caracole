# The music theory edition: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Roman numerals beside or instead of chord names, with a glossary; chords outside the key explained;
progressions named; the key on the neck; chords you can hear.

**Architecture:** a new module `viewer/harmony.py` answers every theory question on top of `viewer/theory.py`;
`viewer/page.py` hands its answers to the viewer as tables per mode (as it does `data.mapped`); viewer.js only
looks up. `viewer/version.py`, `pdf_text.py` and `songbook.py` carry the chord-names display to PDFs and
songbooks; `library_page.py` and `search.py` carry each song's progressions for searching.

**Tech stack:** Python 3.14, the viewer's hand-written JavaScript and CSS, Web Audio, chordpro 6.050.7.

**Spec:** docs/superpowers/specs/2026-10-21-theory-edition-design.md (approved by the owner 2026-10-21; the
look of each part is settled afterwards in a visual-companion session, so build it plainly and consistently
with the viewer's current style, and keep each part's look in CSS classes easy to restyle).

## Global constraints

- Theory in Python: viewer.js computes no music theory; it reads page.py's tables.
- `viewer/harmony.py` goes into `page.BUILD_FILES` (test_viewer_book.py checks).
- harmony.py's answers are cached and frozen like theory.py's (a list handed out is a copy).
- Numerals are written against the tonic's major scale (♭III, ♭VI, ♭VII in minor); case for quality.
- The address parameter for the chord-names display is `nm`: absent = chords, `both`, `numerals`.
  `Version.names`, a songbook `Setting.names` and `[version]` entries use the same three values.
- file:// pages keep their hashed CSP; the served viewer keeps `sandbox allow-scripts`; no network.
- 390x844 and 1280x800, light and dark: no sideways scroll, 44 px touch targets (`helpers.targets`),
  contrast rules, no layout shift.
- Tests first; `nix develop -c pytest -q`; browser tests `@in_chromium`; docs/usage.md and AGENTS.md in
  step; conventional commits; no AI attribution.

## Review focus

1. A key read wrong (an A minor song estimated as C major) gives every numeral a different meaning: the
   numerals' tooltip and the glossary name the key they are read in.
2. A slash chord whose bass is not a chord tone (C/D, G/F): its bass degree shows, never a wrong inversion.
3. Audio on a phone: an AudioContext starts only on a tap and resumes after the page was in the background.
4. A sheet with no section headings, a section with no chords, and chords theory.py can't read (N.C.).
5. A long song's viewer size: tables only for what the page shows.

---

## Lane H: the theory core (starts now; Python only)

### Task H1: harmony.py

**Files:** create `src/caracole/viewer/harmony.py`; add it to `page.BUILD_FILES`. Test:
`tests/test_viewer_harmony.py`.

**Interfaces — produces:**
```python
@dataclass(frozen=True)
class Numeral:
    accidental: str          # "", "♭", "♯" against the tonic's major scale
    roman: str               # "I".."VII", lower case for minor and diminished
    quality: str             # "", "°", "ø", "+"
    extension: str           # "", "7", "maj7", "6", "9", "sus2", "sus4", "add9", "5", ...
    bass: str | None         # the bass's degree for a slash chord, Arabic: "3", "♭7"
    of: str | None           # the target of a secondary chord: "V" in "V/V"
    @property
    def text(self) -> str: ...   # "♭VII", "vii°7", "V7/V", "I/3"
def numeral(chord: Chord, key: Key, next_chord: Chord | None = None) -> Numeral
@dataclass(frozen=True)
class Relation:
    kind: str                # "in", "borrowed", "secondary", "leading", "outside"
    source: str | None       # "C minor", "C Mixolydian" for borrowed
    target: str | None       # the chord a secondary chord leads to, as named in the key: "G"
def relation(chord: Chord, key: Key, next_chord: Chord | None = None) -> Relation
def family(chord: Chord, key: Key) -> str | None           # "home", "away", "pull", None outside the key
def explain(chord: Chord, key: Key, next_chord: Chord | None = None) -> str   # the tooltip's one line
def glossary(chords: Sequence[Chord], key: Key) -> list[tuple[str, str, str]]  # (symbol, meaning, example)
def chord_tones(chord: Chord, key: Key | None) -> list[tuple[str, str]]       # [("C","R"),("E","3"),("G","5"),("Bb","♭7")]
def solo_scale(chord: Chord, key: Key) -> tuple[str, tuple[str, ...]]          # ("D Dorian", ("D","E","F",...))
def key_scale(key: Key) -> tuple[int, ...]; def pentatonic(key: Key) -> tuple[int, ...]
@dataclass(frozen=True)
class Progression:
    numerals: tuple[str, ...]    # one cycle, repeats folded
    repeats: int
    name: str | None             # from CATALOGUE, in any rotation
    ending: str | None           # "authentic", "plagal", "half", "deceptive"
CATALOGUE: tuple[tuple[str, tuple[str, ...]], ...]
def progressions(sections: Sequence[tuple[str, Sequence[Chord | None]]], key: Key) -> list[tuple[str, Progression]]
def progression_key(numerals: Sequence[str]) -> str   # key-free, rotation-normalized, for search
```

- [ ] **Step 1: failing tests**, among them: C major's seven diatonic triads and sevenths are I ii iii IV V vi
  vii° and Imaj7 ii7 iii7 IVmaj7 V7 vi7 viiø7; A minor's i ii° ♭III iv v ♭VI ♭VII and E7 = V7; C Mixolydian's
  B♭ = ♭VII; D7 → G in C is V7/V with relation "secondary", target "G"; B♭ in C is ♭VII "borrowed" from C minor
  (or Mixolydian: say which rule picks); C/E = I/3 and C/D = I/2; N.C. gives no numeral; `explain` lines for
  vi, ♭VII and V/V; `glossary` lists only symbols the chords use; `chord_tones` of C7 and Am7♭5;
  `solo_scale` of Dm7 in C (D Dorian) and of D7 → G in C (D Mixolydian); `progressions` names I–V–vi–IV in
  every rotation and key, folds "vi IV I V ×4", reads the Andalusian cadence in A minor and the 12-bar blues,
  and gives authentic/plagal/half/deceptive endings; `progression_key` matches a rotation of the same cycle.
- [ ] **Step 2: run, FAIL. Step 3: implement. Step 4: run, PASS; the whole suite.**
- [ ] **Step 5: commit** `feat(viewer): harmony.py, numerals, relations, progressions and scales for every chord`.

---

## Lane HV: the viewer (after H merges)

### Task HV1: numerals on the sheet, the glossary, the role colours

page.py adds per mode `numerals[mode][i]` (text and parts), `relations[mode][i]`, `families[mode][i]`,
`explains[mode][i]`, and `glossary[mode]`; viewer.js: the "Chord names" setting (Chords · Chords + numerals ·
Numerals only, `nm` in the address, kept like the other settings), numerals beside or instead of chord names
(chord positions over syllables unchanged), tap/hover tooltips (a tap on touch, hover on a mouse; Escape and a
tap elsewhere close it), "What do the numerals mean?" in settings, role colours with a setting to turn them
off, the outside-the-key mark. No key: the setting says why and offers chords only. Tests in
`tests/test_viewer_numerals.py` (Chromium): every display in C major and A minor; a mode chip re-labels;
transposing leaves numerals; the tooltip's text; touch targets; dark mode; no sideways scroll at 390 px with
numerals on.
Commit `feat(viewer): chord names as numerals, with a glossary and role colours`.

### Task HV2: the key on the neck and the chord card's notes and scale

The rail's first neck is the key's (scale, tonic marked, a major/minor pentatonic switch), following key,
mode and capo; on a phone, in the Harmony panel (HV4). The chord card lists `chord_tones` and `solo_scale`.
Tests in `tests/test_viewer_necks.py` and `tests/test_viewer_panels.py`.
Commit `feat(viewer): the key's scale on the neck, and each chord's notes and solo scale`.

### Task HV3: hear it

Tap a chord name or its card's diagram: the voicing shown (chosen position, standard tuning, capo) strummed by
a plucked-string synthesis in Web Audio; one sound at a time; volume in settings; nothing until a tap; the
AudioContext resumed on the next tap after the page was hidden. Tests (Chromium): a tap creates and starts one
AudioContext; the notes' frequencies for a known voicing (expose them for the test on a data attribute or a
test hook, not to users); no sound without a gesture; the served sandbox and file:// both work.
Commit `feat(viewer): hear a chord, strummed in the browser`.

### Task HV4: the Harmony panel

A panel beside settings (docked on a phone, rail on a laptop, as settings): each section's progression,
name, repeats and ending; a tap scrolls to the section; ▶ plays the progression (HV3's synthesis, a chord per
bar, tempo in the panel, default 80 bpm) and marks the chord playing; ■ stops; with numerals on, a section's
heading shows its progression's name. "Songs with this progression" links to
`index.html#prog=<progression_key>` (relative). Tests (Chromium) and `test_viewer_panels.py`.
Commit `feat(viewer): a Harmony panel: each section's progression, named, played`.

---

## Lane HD: PDFs, songbooks and the library (after H merges; beside HV)

### Task HD1: chord names in versions, PDFs and songbooks

`Version.names` (`nm`), parsed and written by `version_from_query`/`version_query`; `apply_version` and
`pdf_text(..., names=...)` print numerals beside (`both`) or instead of (`numerals`) chord names; a numerals
chart says its key under the title and has no diagrams; both end with a legend of the symbols the song uses
(`harmony.glossary`). `Setting.names` in songbooks.toml (`caracole songbook set --names both|numerals|chords`);
`[version]` carries `nm`; the export page and Make this my version carry it. Real-chordpro tests that the
numerals print (pdf_strings) and a numerals chart has no diagrams.
Commit `feat(render): PDFs and songbooks in numerals`.

### Task HD2: songs by progression

`library_page` data gives each song its sections' `progression_key`s and names; the library page filters by
`#prog=` (a line saying "Songs with vi–IV–I–V · Show all"); typing a progression ("vi IV I V") or a catalogue
name ("andalusian") in the served search finds songs; `caracole search --progression "vi IV I V"` prints them.
Tests in test_library_page.py, test_web_page_search.py, test_search.py, test_commands_search.py.
Commit `feat(library): find songs by their progressions`.

## Order and merging

H now (beside wave 2's G and R). Then HV and HD in parallel (HD1 after the open-v lane, which changes
version.py and songbook.py, has merged). Each lane: one review round, merge, whole suite, push. Then the
owner's visual-companion session on how each part looks, then the README text (screenshots later).
