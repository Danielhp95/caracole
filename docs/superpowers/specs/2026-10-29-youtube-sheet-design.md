# A sheet from a YouTube video, from the library page

Date: 2026-10-29. The owner's ask: "implement the in-UI flow for pasting a youtube link and from there
getting the chords and the lyrics, essentially to make a page as if it were a normal ultimate guitar
chords + lyrics sheet". Worked example: **Nick Cani - Vikingos veganos**,
`https://www.youtube.com/watch?v=lzN7Thn3FV4`. Lines marked *(my call)* are decisions the owner didn't
make and may still change.

## What exists

The pieces are all there, on the command line: `caracole youtube --song "Artist - Title" --url URL`
writes the video under `[youtube]` and takes its audio with yt-dlp (youtube.py, youtube_fetch.py);
`caracole autochords` works out the chords of every song that has audio and no human sheet, laying them
over LRCLIB's lyrics (autochords/merge.py); `caracole render` makes `sheet (auto).pdf` and the viewer
`sheet (auto).html`, the same viewer a UG sheet gets. Nothing joins them for one song, `caracole
autochords` can't be run for one song, and the library page offers none of it.

## The flow

1. On the served library page, the owner opens the request form ("Not in the list? Request it by
   name"), types **Nick Cani** and **Vikingos veganos**, and pastes the video's address into its new
   field, **YouTube video**. Or, for a song the library has and no human sheet, they open its card
   (its line's chevron) and paste the address into **Sheet from a YouTube video**.
2. Request (or Make the sheet) queues one job. The song's line (a new song's under the search box)
   says how it goes, as a lookup's does: "Taking the audio from YouTube…", "Fetching the lyrics from
   LRCLIB…", "Working out the chords…", "Rendering the sheet…", with a chip a step under it: Song,
   Audio YouTube, Lyrics, Chords, PDF.
3. Ready: the song's title and its Open open `sheet (auto).html`, the sheet viewer, with the chords
   over the lyrics. The Requests tab says Ready, and what the sheet holds ("Chords over LRCLIB's timed
   lyrics.").

## Where it lives

- **The request form** gets an optional **YouTube video** field *(my call)*: a new song needs a name,
  and the form already asks for it. With a video, the request makes the sheet from it instead of a
  lookup; "Fetch it now" doesn't apply then. The song still goes into wanted.txt first, as every
  request does (`wanted_line`): a song comes only from a wanted.txt line.
- **A song's card**, for a song with no human sheet that isn't ignored and has no purchase linked:
  a small form, the address and **Make the sheet** (`POST /youtube`). It replaces the video a song
  had from YouTube, as `--url` does.
- **The name** is typed by the owner. Prefilling it from the video's title would be one more yt-dlp
  run that asks YouTube for the video's page before anyone chose to download it: no *(my call)*.
- Where this caracole can't make the sheet (`youtube_fetch.route_problem`: no auto-chords packages,
  no model files, no yt-dlp, or YouTube turned off), the request form has no field, and says why in
  one line; the cards offer nothing and say nothing *(my call)*: the default package has no
  auto-chords, and a line on every card of a song with no sheet would say the same thing many times.
  Nothing is offered that would fail.

## The command and the job

`caracole youtube --song "Artist - Title" --url URL --sheet [--progress]` makes the song's auto sheet
now, in one process, under caracole's lock, its stages reported as `caracole get` reports its own
(`--progress`: a JSON line per event, for caracole serve). Its logic is youtube_sheet.py's:

| Stage | What it does |
|---|---|
| `song` | found in the library, else added to wanted.txt as `caracole add` adds it and synced; refused when ignored, with a human sheet or with a purchase linked; the video written under `[youtube]` |
| `audio` | the youtube step for that song alone (`youtube_fetch.youtube_pass`): `make_youtube`'s budget, pauses and lock; nothing asked when the song has that video's audio already |
| `lyrics` | LRCLIB for that song alone, at the bulk pace (`fetch_pending_lyrics`), asked with the audio's length when the song has none of its own, so the timed lyrics LRCLIB picks fit the audio |
| `chords` | auto-chords for that song alone (`autochords_pending(only=…)`), after handing the lock to a waiting lookup |
| `pdf` | `render_all(song_ids=…)`: the PDF and the viewer |
| `pages` | `_todo.md` and `index.html` |

*(my call)* One process rather than four queued commands: the stages share one lock and one reading
of the song, a stage that can't go on stops the rest with its reason, and the line and the chips come
from the stages, as a lookup's do. `caracole autochords --song "Artist - Title"` exists too, on its
own, for a purchase or audio taken earlier.

The server queues it as one job (`jobs.youtube_sheet_steps`) under its own key, `youtube:` and the
song's identity key, so it never joins the song's lookup, nor a lookup it *(my call)*; one at a time a
song: asked again while one waits or runs, that one is the answer. Its view is the song's (`kind`
"song", its `identity` the song's key), so the song's line follows it. status.py says its running
stage (`STAGE_LINES`); outcome.py draws its steps (`YOUTUBE_STEPS`) on the song's line and in the
Requests tab, and says how it ended.

It is a command, not a lookup: it keeps the bulk pace for LRCLIB and the youtube provider's budget
and pauses, and `caracole get` still never runs yt-dlp.

## How it ends

| Case | Exit | The line | The Requests tab |
|---|---|---|---|
| The sheet made | 0 | Ready, Open | Ready: what the sheet holds |
| A block, a cooldown, a spent budget, a network error | 0 | Not made yet · Details, the chips showing where it stopped | Not made yet: the site's words; Try again |
| No lyrics on LRCLIB | 0 | Ready | Ready: chords alone, LRCLIB has no lyrics |
| A human sheet, ignored, a purchase linked | 1 | Failed: why, in the stage's words | Failed; Try again |
| A video YouTube won't give (a login, given up after 3 failed downloads) | 1 | Failed: paste another video | Failed |
| Auto-chords can't read the audio, or can't run | 1 | Failed: why | Failed |
| No auto-chords here | refused by the route (409), and the command exits 1 asking nothing | | |

The route refuses up front what it can tell (not a YouTube address, a song with a human sheet,
ignored, a purchase linked, no auto-chords) with `pages.Refused`; the command checks again, as the
library may change while the job waits.

## What the sheet looks like

As every auto sheet (merge.py): with LRCLIB's timed lyrics whose length fits the audio within 2 s,
each lyric line gets the chords that fall in it, above it, as a UG sheet has them; where the voice
rests two bars or more, chord-only lines of bars. With plain lyrics only (or timed ones of another cut
of the song: a video's intro, say), a chord chart of the whole song, then the lyrics. With none, the
chart alone. Asking LRCLIB with the audio's length is what makes the first case likely for a song new
to the library; a song whose lyrics came earlier keeps them.

## The YouTube exception

Unchanged but for who starts it: the owner, choosing the video, from the page. A song with no human
sheet only; yt-dlp only through `make_youtube` (the budget, the pauses, one at a time, the lock); its
arguments as youtube.py gives them (`--retries 0`, audio alone, its own environment, no cookies); a
bot check, a 429 or a 403 a `ProviderBlocked`, which cools YouTube down and sends one ntfy alert.
AGENTS.md's exception says the page can start it.

## The units

PyTorch generates code at run time, so the caracole-autochords unit and `caracole-admin` run without
`MemoryDenyWriteExecute`. caracole-web now runs auto-chords too, in the job's child process: with
auto-chords on, it drops `MemoryDenyWriteExecute` as they do (nix/module.nix, module-check.nix, and
deploy.md's Ubuntu section 12). Without auto-chords it keeps it, and the page offers no YouTube sheet.

## Not done

- The song's lyrics fetched earlier are not asked again with the audio's length; their timings may
  belong to another cut, and the sheet then has the chart and the lyrics apart.
- No aligning of timed lyrics to audio of another length (an offset search): research, not plumbing.
