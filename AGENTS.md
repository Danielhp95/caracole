# AGENTS.md

What a coding agent needs before changing caracole. User documentation: README.md, docs/.

## What caracole is

caracole is a Python CLI, run every night by a NixOS service, that builds, for the songs in `wanted.txt`, a private
library of:

- sing-along chord sheets (Ultimate Guitar, LaCuerda);
- lyrics (LRCLIB, then Megalobiz for timed ones, AZLyrics for plain ones where neither has any);
- PDFs (ChordPro);
- Guitar Pro files (downloaded from gtptabs.com, or filed from what the user drops into `_inbox/`);
- harmonica tabs (harptabs.com);
- chord charts of jazz standards (iReal Pro's forum), as the sheet of a song the sheet sites left with none.

For a song nobody has charted, `caracole autochords` writes a sheet from audio with local models (torch, optional):

- a purchase;
- or audio the nightly run takes from YouTube with yt-dlp (youtube.py, youtube_fetch.py), up to 25 songs a night, only
  where auto-chords is;
- or that of a video the owner pastes on the library page, made into the song's sheet at once (youtube_sheet.py);
- or an audio file the owner gives it, `caracole audio FILE`, kept in `state_dir/audio/` (audio_store.py) and made
  into the song's sheet at once (audio_sheet.py).

The Android app (built in the `./android#ml` shell; the release on arm64 phones) makes such a sheet from an audio file
too, chords and beats heard on the phone with no words (android/: `:autochords`, `:ml`, AudioRunner, ModelsRunner; docs/autochords.md, "On
the phone").

The design lives in three files:

- `plan.md`: design v2.1, and why. Its code sketches are older than the code: its module runs
  `caracole run --config …`, which the CLI rejects (`--config` is a root option: `caracole --config FILE run`).
- `docs/superpowers/plans/2026-10-18-caracole.md`: the task plan, with amendments A1–A7 made during the build:
  A2 `wanted.txt`, A3 Chinese titles, A4 command plug-ins, A5 agent rules, A6 bare-id tabs, A7 `index.html` and
  `caracole search`.
- `docs/spike-2026-10-18.md`: what the live sites did when checked. It corrects plan.md:
  - UG's `Pro` is a public Guitar Pro file;
  - a slugged tab answers only at its slugged URL.

## Layout

In `src/caracole/`, `caracole run` (pipeline.py) runs these steps in order, each one even when an earlier one failed.

Each module's docstring says what it does and why, and each package's `__init__.py` how the package is laid out
(commands/, web/, viewer/, library_assets/, autochords/): the details live there, beside the code they describe, and
change with it. This section says where things are, and the rules a change there keeps.

### The run's steps

Below the table, a section for each step whose modules have more to say.

| Step | Modules |
|---|---|
| sync | sources.py, wanted.py (the one source of songs), songs.py |
| icons | icons.py (each source's mark) |
| index | ug/sitemap.py, ug/index.py |
| ug-directory | ug/bands.py, ug/directory.py |
| match | match.py, ug/lookup.py |
| lyrics | lyrics.py, lyrics_search.py and lyrics_pick.py (`caracole lyrics --song`: no step) |
| megalobiz | megalobiz.py, megalobiz_fetch.py |
| azlyrics | azlyrics.py, azlyrics_fetch.py |
| fetch | ug/fetch.py, ug/page.py, ug/artist.py, ug/artist_tabs.py, rank.py, coverage.py, versions.py, sheet_versions.py |
| lacuerda | lacuerda.py, lacuerda_fetch.py, lacuerda_index.py, lacuerda_search.py |
| ireal | ireal.py, ireal_fetch.py, ireal_index.py |
| scan | music.py (Music/; a song linked again, `follow_audio`: what was heard of the same bytes follows them), inbox.py (`_inbox/`), musicxml.py, audio_store.py (`tidy`) |
| gtptabs | gtptabs.py (URLs, parsing), gtptabs_fetch.py (the step) |
| harptabs | harptabs.py, harptabs_fetch.py, harptabs_index.py |
| gametabs | gametabs.py, gametabs_fetch.py, gametabs_index.py |
| musescore | musescore.py (URLs, parsing), musescore_fetch.py (the step) |
| youtube | youtube.py, youtube_urls.py, youtube_fetch.py, youtube_sheet.py, youtube_search.py |
| render | chordpro.py, render.py, pdf_text.py, viewer/, songbook.py |
| todo | todo.py (`_todo.md`), library_page.py (`index.html`), library_assets/, songbook_section.py, song_sites.py |
| backup | backup.py |

#### ug-directory

UG's artist directory (docs/superpowers/specs/2026-11-17-ug-artist-directory-design.md, its owner's decisions above the
rest): every artist UG's letter listings name, then every bare artist's page, so that a search finds an artist UG's
sitemaps list by bare ids alone, and the fetch their page.

- ug/bands.py: a listing page read (`/bands/<letter>.htm`, `<letter><N>.htm`, `LETTERS`: `0-9` and a–z):
  `parse_listing`, each artist's id, name, slug ("" for a bare `/artist/{id}`), page, tabs and last update;
  `ListingParseError` for another listing or page than the one asked, no data, or a page cut short (fewer than 50
  before the last).
- ug/directory.py: `ug_directory` (schema 16), the pass and what it holds.
  - `directory_pass`: the listings due, each letter's first `FIRST_PAGES` first, then the letters one by one, a page
    a savepoint (`store_page`: its artists upserted, `seen_at` moved on, the letter's round in kv
    `ug:directory:letters`), a letter read again `REFRESH` (30 days) after its last whole read; then the bare
    artists' pages due (`due_bare`: never read, or their row's `tabs` or `updated_at` moved since and 30 days past),
    most tabs first, each read by ug/fetch.py's `read_artist_page` with a client that sends nothing (`_Planned`),
    whose misses the workers fetch, then the read again: no rule of the fetch's written twice.
  - A listing never removes an artist; an artist's own page's 404 does (`_gone`). A page cut short, unparseable or a
    404 is an error, the round going on from it the next time.
  - `artist_page_for`: the page the directory names for an artist's keys (ug/fetch.py's `_known_artist_page` and
    `artist_is_known`, after `[artist_url]` and the learned kv): the first key that names any, a whole name before a
    part, the part that is more of the name, the most tabs, the most popular.
  - `index_state` (`DirectoryState`: letters, artists, bare, read, `complete`), `letter_of`, `ensure_current_keys`
    (kv `ug:directory:keys`).
  - Its keys join `ug_artists` (the artist vocabulary) by triggers that state no conflict clause; a key goes with the
    last row of `ug_index` and `ug_directory` that has it.
- Its client is `_common.directory_client` (`make_parallel_client`: http.py's `ParallelClient`, `[ug_directory]`'s
  concurrency, delay and budget), its step `ug-directory` (pipeline.py, after the index, before match; skipped while
  the index is empty), its command `caracole ug --directory [--budget N]` (commands/ug.py, a `builds_index` word).

#### lyrics

- lyrics.py: LRCLIB.
  - `Lyrics.provider` and `.url`: who answered and the page to link back to.
  - `fits` and `another_version`: the matching rules another site's picker keeps.
  - kv `lyrics:failed:`: the songs LRCLIB failed on.
  - `[lyrics]` (`Overrides.lyrics`, each pass's `picks=`, AZLyrics' `lyrics=`), the three sites alike: `asked_as`, the
    name asked under (its `as`, cleaned: NFC, control characters out, `ASKED_MOST` characters, with no album; one that
    cleans to nothing no name); `picked_record` and `picked_due`, a record picked final: only its site asks, for it
    alone (`fetch_lrclib_record`, `/api/get/{id}`; Megalobiz's `fetch_record`; AZLyrics' page), while the song is
    pending, or missing for 30 days; that record gone its lyrics missing, logged ("the record you picked is gone"),
    and asked past the cache from then on (Megalobiz's and AZLyrics' kv `checked:`, which an error leaves; LRCLIB's
    `lyrics_at`, an error leaving the song missing). A record wins over an `[azlyrics]` page, which wins over `as`.
    An entry on a song already missing waits for its 30 days. Without it, every request is what it was.
  - Every caller hands the passes `overrides.lyrics` (pipeline.py's three steps, commands/lyrics.py, get.py,
    youtube_sheet.py; the phone's three lookup stages `ctx.overrides.lyrics`), a lookup the table read again after a
    turn. A lookup's and a YouTube sheet's lyrics stage with a record picked on Megalobiz or AZLyrics asks that site
    alone (the frame's short cut, LookupRun.kt `lyrics` alike), and get.py's put-back to pending (Megalobiz skipped
    for its cooldown) never touches a song with a record: no other site concerns it. Their words: `said_under`, the
    name said once, first, when a site was asked under `as` ("under “A - T”: LRCLIB has none; …"; the frame's,
    LookupRun.kt by `StageContext.askedUnderName`; `PAGE_NAMED` after AZLyrics' words for an `[azlyrics]` page while a
    name holds), `picked_said` ("the record you picked: lrclib 9", "… is gone: …", "… isn't asked now: …", an LRCLIB
    record within its 30 days too). A song with a record and no lyrics is never heard (transcript.py
    `picked_without_lyrics`).
  - After a hand-over in a pass's client's pauses (a pick, a clear or a search of the owner's let in), the three
    passes read `[lyrics]` again, one rule: lyrics.py's `Turns` (each pass's `reload_overrides=`, every caller's;
    provider_pass.py `Reread`): before each song's turn (`due`), and after it, an answer of a turn a hand-over came
    in kept only for a song still due with the entry the turn asked under (`answered`), an error's put-back to
    pending or LRCLIB's `lyrics:failed:` only for a song still asked so (`still_asked`); so a pick stays final and
    a cleared record is never asked (the pass tests' `helpers/handing_over.py`).
- lyrics_search.py: `caracole lyrics --song X --as "A - T"` (commands/lyrics.py `_lyrics_as`, the typed text read by
  song_names.py's `read_names`, each part cleaned as `as` is), an interactive lookup in the lane: the name written as
  `as` first (`set_lyrics_name`; the song's own name takes it out), then `search_lyrics` asks each site once by a
  lookup's client of its own: LRCLIB's `/api/search` (its query kept, `Search.lrclib`), `/api/get` only when no record
  of it fits (`pick_candidate` over the records with lyrics), Megalobiz's search, AZLyrics' artist page (none for a
  name with no Latin letter): 2–4 requests, each through the cache for `PICKABLE_FOR` and asked again past it once
  older (`max_age`, a cached 404 alike; the passes read the same addresses with no age: a fresher copy is theirs
  too); LRCLIB's search rows kept when its get then fails or is cut. Rows (`Row`: `record`, site,
  names, album, length, timed, `best`, `fits`), the best fit first (LRCLIB's `pick_candidate`, else `pick_result`, else
  `pick_song`), then those that fit, then the rest, `MOST_ROWS` (40); an instrumental or empty record counted, never
  listed; a record only by an id the site answered, of `[lyrics]`' shape (`overrides.LYRICS_RECORD_IDS`), checked as
  it is read and again from kv. Each site's `state` (`STATES`: rows, none, off, cooling, spent, blocked, failed) and
  its words (`said`), never a miss, the others listed; `last_line`: "Searched: " rows, "Nothing found: " every site
  asked answered none (a site off isn't asked: left out), "Not searched: " a site cooling, spent, blocked or failing.
  A block at any of a site's requests is its strike, with no good run recorded over it. Kept in kv `lyrics-search:<song id>` (`KV`, in `songs._PER_SONG_KV` and SongKv.kt; no unit's,
  never crossing to the phone), replaced by the next search, never under an id another song took meanwhile;
  `kept_search` gives it for `PICKABLE_FOR` (7 days), `row_of` a record's row; past it `last_search(now)` gives the
  name and the day alone, no row, and the nightly lyrics step (pipeline.py `_lyrics`) keeps only those
  (`sweep_searches`: one scan of kv, no request, a record that won't read deleted). A search's and a pick's length of
  the audio is one rule (`audio_length`: the line's, else the video's, else the file's; staged.py `_audio_length`),
  their off and cooling words one (`not_now`). It changes no stored lyrics; a new name
  resets the question (`ask_anew(renamed=True)`, right after the entry's write: for a song pending or missing alone,
  kv `lyrics:failed:`, `megalobiz:checked:` and `azlyrics:checked:` deleted and `pending` with no `lyrics_at`; found
  lyrics or an instrumental verdict keep their state and stamps), so no transcription is offered before every site
  answered under it. A pick (any state: a verdict yields to it) and a clear reset through the same function. Its
  words for what stopped an ask are `stopped` (`whose`, `why`), the pick's too.
- lyrics_pick.py: `caracole lyrics --song X --pick N | --record SITE:ID` (commands/lyrics.py `_lyrics_pick`), a
  `StagedRun` (`_Pick`, `STAGES` song, lyrics, chords, pdf, pages) under the lock as asked for now, never in the
  lane; its client a lookup's (`make_client(..., interactive=True)`), 0 or 1 request:
  - song: by its identity key, the row of its `kept_search` (`--pick` its Nth, `--record` one of its rows: never a
    record from the argument alone); refused not in the book, ignored, no search, one over a week, not listed;
  - lyrics: LRCLIB's from the search's cached answers (`/api/search`, its `/api/get`; `CachedAnswers`, no request),
    else `fetch_lrclib_record`; Megalobiz's `fetch_record`, AZLyrics' `fetch_azlyrics(page=)`. None now: skipped,
    nothing kept; off, cooling, spent, blocked: skipped, an error: failed (lyrics_search.py `stopped`'s words,
    `whose="this pick's"`, a block's reason said), each with no change to the song, its `[lyrics]` or its kv (errors
    are never misses), the command exiting 0. Kept, in this order: `write_lyrics`, then `set_lyrics_record` (`as`
    kept: before the savepoint, so a failure to note it keeps nothing; a pick cut off between them is picked again,
    as no pass asks a found song's record), then in one savepoint `ask_anew`, found, and the auto sheet made due where the words changed
    (`autochords_mtime` cleared, as new audio clears it: run.py `_skip_reason`, so a sheet made before its
    `lyrics_key` is remade too; never for a sheet that keeps `heard`, `_models_remake`), then info.json; the
    files or overrides.toml failing puts the files back
    (`_put_back`), changes nothing else and fails the job (`_fail`, exit 1);
  - chords (§4.5): a sheet that keeps `heard`, of the audio the song has now (`relays_here`), laid out again over
    the words picked, in seconds, no model, whatever auto-chords' state (staged.py `_relaid`, "chords over the
    lyrics"); else skipped "no new lyrics", "its sheet is a site's: …", "no audio to make an auto sheet from" or
    "auto-chords isn't here (…); tonight's run makes it again" (`youtube_fetch.autochords_problem`; a chart takes
    plain words at the PDF's render meanwhile, sheet_lyrics.py); else `_after_a_lookup`, then `_autochords_sheet`,
    which makes the sheet or makes it again (models imported only then); pdf: `render_all` whenever it keeps any
    sheet, a failure the job's (`_fail`); pages.
  - `clear_pick`, `--clear`: `overrides.clear_lyrics_record` (`as` kept), the lyrics that record gave dropped (files,
    `lyrics_json`, the auto sheet due, or re-laid as its chords alone by the render after it where it keeps `heard`),
    `ask_anew`, no request, under the lock as asked for now; exit 1 with no record;
    a lyric file that can't be removed is said, the clear standing.
  - A search's reset, a pick or a clear changes the song unit's `lyrics_status`, `lyrics_json` and `lyrics_at`
    (peer_sync.py `SONG_COLUMNS`) and its `[lyrics]` entry: a sync carries them; the kv it deletes is no unit's.
    On the phone, the search, `--record` and `--clear` run (android/'s "Lookups on the phone").

#### megalobiz

- megalobiz.py: Megalobiz's public API: its search and a record read, `pick_result`; `MegalobizParseError`.
- megalobiz_fetch.py: the step.
  - The songs LRCLIB left, missing, failed on or plain only: `songs_to_ask`.
  - A miss: kv `megalobiz:checked:`, asked again after 30 days.
  - An error puts a song LRCLIB missed back to pending, and so does a lookup that skips it for its cooldown, unless
    AZLyrics then finds the lyrics (get.py `lyrics`, LookupRun.kt `lyrics`).
  - The link back its fair use asks: info.json's `lyrics_from` and the card's Lyrics tile, `library.lyrics_from`.
- Also in `caracole lyrics`, a lookup and a sheet from a YouTube video.

#### azlyrics

- azlyrics.py: its pages read:
  - an artist's address from their name, `artist_url`;
  - their page's songs, `parse_artist`, `pick_song`;
  - a lyrics page, `parse_lyrics`;
  - `AzLyricsParseError`.
- azlyrics_fetch.py: the step.
  - The songs still with no lyrics, missing or failed on by LRCLIB: `songs_to_ask`.
  - Two requests a song, no index and no list of artists.
  - `[azlyrics]`: a page named, one request.
  - A miss: kv `azlyrics:checked:`, asked again after 30 days.
  - An error puts a song LRCLIB missed back to pending.
  - The link back as Megalobiz's: `library.LYRICS_PAGES`.
- Also in `caracole lyrics`, a lookup and a sheet from a YouTube video.

#### fetch

- ug/fetch.py: UG's chords and text tabs, and its Ukulele Chords as the sheet of a song with no chords there:
  `UKULELE_KINDS`, `sheet_group`.
- ug/page.py: tab pages; `KINDS`, the types caracole uses: chords, tabs, ukulele.
- ug/artist.py: artist pages.
- ug/artist_tabs.py: the tabs of every artist page read, kept for searches: `ug_artist_tabs`, schema 7.
- ug/fetch.py's `read_tab_page` and `read_artist_page`: a tab page and an artist page's lists read by the fetch's
  rules, of no song's, which a song's fetch and ug/link.py share.
- ug/link.py: a UG link pasted into the library page's box (docs/superpowers/plans/2026-11-17-ug-link.md):
  - `known`, what caracole knows of its page, the database and the HTTP cache alone: its state (`found`, `auto`,
    `cooling`, `spent`, `failed`, kv `ug:link-failed` of the hour, `other`, `gone`), the tab's names, its artist's
    page, the song's keys;
  - `read`, `caracole ug --link`'s: the tab's page, its artist's page learned and its lists read, or an artist's
    lists; a budget, a block or an error after the tab's page no failure of the link.
- rank.py, coverage.py, versions.py (`auto_version_of`: a song's one auto sheet version, whatever its tab id).
- sheet_versions.py: a song's UG chords versions in rank order, or its ukulele chords ones when its sheet is one
  (`sheet_kind`, `group_of`).
  - The one and those kept beside it as `version-<tab>.txt`, `.json`, `.html`: the versions the fetch scores,
    written by ug/fetch.py's `_keep_beside` with no request more, a pinned sheet's from the cache alone.
  - `in_library`: the list as the library holds it; and `in_library_of`: many songs' in a few queries, the library
    page's.
  - `may_keep`: those a keep may still keep, the page's count of the rest.
  - `as_data`: the pages' JSON.

#### lacuerda

- lacuerda.py: URLs, parsing, its search's pages.
- lacuerda_fetch.py: the sheets.
  - `may_ask`: the songs LaCuerda may have, for the step and the to-do page.
  - `popular_pages`: the most popular artists' pages once the listings are read whole.
- lacuerda_index.py: its listings of every artist, for searches.
  - `backfill_cached`: the artist pages the HTTP cache holds.
  - `store_search`: what its search answered.
- lacuerda_search.py: its own search, one query at the lookup pace, `caracole lacuerda --search`.
  - `gate`: whether the pages may send it.

#### ireal

iReal Pro's forum, forums.irealpro.com (XenForo), the owner's choice of 2026-11-18 (Politeness, below):

- ireal.py: URLs, its sitemaps' threads (`IndexRow`, a slug's key `slug_key_of`, which a title's key begins:
  `begins_with`, words alone), a title's key (`title_key`: "Girl From Ipanema, The" is "The Girl From Ipanema", a
  leading article dropped), and:
  - a thread page read (`parse_thread_page`: its title, forum, posts, each post's charts, a link quoted in a reply
    never the reply's) and the jazz forum's page (`parse_forum_page`: its sticky threads, the playlists);
  - a chart link read (`parse_link`, `irealb://` and the older `irealbook://`, a playlist's name last; `unscramble`,
    the documented scramble, its own inverse);
  - a tune's chart as a sheet in UG's markup (`Tune.chart`): bars four a line between bar lines, which the sheet's
    page draws as cells (5c, viewer/sheet.py `bars`), a section, an ending or the coda a `[label]`, notes (comments, To
    Coda, a time) a line under theirs after a blank one, `x` and `r` the bars before written out, an empty bar the last
    chord before it held on (after an opening bar line and before a closing one too), an alternative chord and the
    app's layout marks left out; chords named as sheets name them (`chord_name`: C^7 Cmaj7, D-7 Dm7, Bh7 Bm7b5, the
    app's own `C*-^*`); the composer first name first (`composer_name`);
  - a tune that reads no chord, or more than `UNREAD_MOST` characters that read as nothing (a link cut short inside a
    block leaves its end scrambled), is `IRealParseError`, the one error the decoder raises on any input (the review's
    fuzz: random music and every cut of the real pages' tunes; "T4", a time of one digit at the music's end, once an
    IndexError).
- ireal_index.py: the thread pages read into `ireal_threads` and `ireal_charts` (schema 17, a composer's folded key
  `composer_key` for searches), and `playlist_pass`: the sitemaps when due, the curated Jazz 1460 Standards
  (`ireal.JAZZ_1460`) first, the jazz forum's page (`ireal.PLAYLIST_FORUMS`, kv `ireal:forums`), its sticky threads,
  each again after 30 days, a thread's first page alone; `index_state`; `ensure_current_keys` (kv
  `ireal:charts:keys`). A page's `read_at` is when the site answered it: `read_thread` stores a copy from the cache
  only where the index lacks it, at its fetch's time, so a song's read of a playlist from the cache never puts off
  the playlist's next read (test_ireal_fetch.py, the review's sequence).
- ireal_fetch.py: the step, `ireal_sheets`.
  - Its songs: no human sheet kept (after UG and LaCuerda; one with an auto sheet alone among them), not asked in 30
    days (kv `ireal:checked:`), a candidate in the index (never a request); a kept chart the library lost written
    again.
  - A chart is the song's (`_matching`) only when it is titled as the song is and one of its artists is the chart's
    composer or the name its thread's slug gives after the title (`composer_fits`, `names_an_artist`, words in any
    order: "Jones Thad"), or it comes from the Jazz 1460 Standards (`ireal.JAZZ_1460`), where the title alone is
    enough ("Bill Evans - Autumn Leaves"); the jazz forum's other playlists (practice exercises, fusion, gypsy jazz…)
    need the composer as any thread does; an `[ireal]` pick always counts. The rulings of 2026-11-18, after a title
    alone gave "Ren - Patience" Guns N' Roses' chart and "Jorge Rivera-Herrans - Open Arms" Journey's
    (test_ireal_fetch.py `NAMESAKES`).
  - A song's artists (`artist_names`, the re-review's ruling of 2026-11-18): each artist whole, by its
    `normalize.name_forms`; and each one a line names among several, between " / ", " & ", ", ", " and ", " with ",
    " feat. " or " ft. " (any case), a whole name when it is two words or more ("Thad Jones / Count Basie", "Thad Jones &
    Mel Lewis"), a surname alone when it is one, meeting a composer's first word as iReal Pro writes them, last name
    first (`composer_surnames`), or a slug's last word, never a suffix (jr, sr, ii, iii, iv): "Simon & Garfunkel" is
    Paul Simon's, "Sam & Dave" no Dave Brubeck's, "Harry Connick, Jr." no Grover Washington Jr.'s; "Hall & Oates" is
    Jim Hall's, and "Crosby, Stills, Nash & Young" Victor Young's, a title and a surname both matching (accepted).
  - `candidates`: the pages read that hold a chart of the song (the cache's, no request), then the threads whose slug
    names one of the song's artists after the title, then those of the title alone, the oldest first, never one that
    names someone else, `CANDIDATES` (3) pages at most; none more once a chart whose composer is the song's artist is
    in hand.
  - A chart is read only once it is the song's (`_charts_of`): one that won't is passed over, logged, and only when
    every chart that would be the song's won't is the song's turn that `IRealParseError`, never a miss.
  - Every chart of the song a version (provider `ireal`, kind `chords`, tab id `<thread>/<post>/<place>`); the best
    (`best`: the artist's composer, the curated playlist's, a thread naming its composer, the oldest thread, its
    latest post) the sheet, `sheet.txt` and `sheet.json` (its `tune` as the link gave it), its version's
    `tonality_name` the tune's key; its coverage scored as any sheet's, so UG's or LaCuerda's sheet with words replaces
    it (`versions.replaces_sheet`), unless `[ireal]` picked it (ug/fetch.py `_sheet_slot`, lacuerda_fetch.py
    `_charted`).
  - `[ireal]`: a chart you picked (a thread, `#post-N` its post, a later page's `…/page-K#post-N` that post; written
    as the post's own address, `…/post-N`, `IRealPick.url`, Picks.kt alike, as a later page's chart links), kept in
    place of any sheet but a UG `[pin]` or a `[lacuerda]` pick; a post its thread's first page doesn't hold is found
    by asking its own address, which the forum redirects to its page (`_post_page`, each hop a request), read out of
    the index; a later page's address alone names no chart (overrides.py, Addresses.kt).
  - After a lookup its client let go first, overrides.toml read again (`reload_overrides`, as LaCuerda's pass does):
    before the next song, and a song whose turn a handoff came in kept only while it still is one to try with the
    pick the turn read.
- Its step `ireal` (pipeline.py, after lacuerda); in a lookup, the sheet stage's last resort (get.py `_ireal`: after
  UG's and LaCuerda's, its pick `--ireal` first, "from iReal Pro" its running detail, `SHEET_FROM`), no stage of its
  own; its command `caracole ireal [--index] [--budget N]` (commands/lyrics.py); `search.search_ireal`, the charts
  of the threads read, and `search.search_ireal_threads`, the threads its sitemaps name that caracole never read, by
  their names alone (`/api/search`'s `ireal`, those `read: false` after the charts, and its mark last in `looked`,
  both once its index holds a thread read or the sitemaps' threads, search_routes.py `_ireal_read`); a card's site
  mark once it was asked or gave the chart (song_sites.py); its mark `IR`.
- Its index is the computer's alone: it isn't in `index_transfer.SITES`, so no export, merge or sync carries it, and
  the phone's tables of it (schema 17) stay empty; a song's chart, its versions and `[ireal]` travel in its unit. A
  lookup with nothing to ask there (`ireal_fetch.wants_a_chart`, no request, no client, no kv) says and writes nothing
  of it, so the phone, whose lookup never asks it, answers alike; its search gives no `ireal`, as an empty index's.
- What it adds to the conformance corpus is kept to a few KB (vectors/web's budget): nothing while its index is empty
  or a song has nothing to ask there (no fixture's index holds a thread, read or named: the phone's search answers
  none).

#### harptabs

- harptabs.py: URLs, and:
  - its sitemap's rows (a tab's key with a contraction's end joined to its word, `joined`, which `title_keys` meets);
  - a tab page read;
  - an artist page read: its name, the tabs it says they have and the 30 it lists, `parse_artist_page`;
  - `song_title`, `song_key`: the song a tab's title names;
  - what the site answered caracole's probe.
- harptabs_fetch.py: the step.
  - A song's candidates by title, its artist confirmed on the page, the most viewed kept as `harmonica-N.txt`,
    provider `harptabs`, kind `harmonica`.
  - `inbox.harmonica_files`, which library_page.py and render.py read: the viewer's data `harmonicaTabs`, each with
    its `page`, `inbox.harmonica_page`.
- harptabs_index.py: its artist pages read into `harptabs_artists` and `harptabs_artist_tabs`, schema 11, for
  searches.
  - `artist_pass`: the step's with what its budget leaves and `caracole harptabs --index`'s; your songs' artists
    first, each page again after 30 days, resumed across runs.
  - `read_artist`: one page now, `caracole harptabs --artist`.
  - `index_state`: how far it has got.

#### gametabs

- gametabs.py: URLs, and:
  - its sitemaps' rows (a slug's number, `main-theme-108`, one more tab of a title, `IndexRow.key`, never part of
    it, `slug_key` the whole slug's);
  - a tab page read: its `data-tab` JSON, else its microdata, and its `<pre>`;
  - a game page read: each tab's composers and instruments, 50 a page, the site's instruments by its shuffle
    dialog's names.
- gametabs_fetch.py: the step.
  - A song's candidates by title, of a game or a composer its artist is (`game_forms`: "Hollow Knight OST" is the
    game).
  - The most viewed agreeing page kept as `gametab-N.txt`, provider `gametabs`, kind `gametab`, opened as text as
    UG's `tab.txt` is.
  - `[gametabs]`: a tab you picked.
- gametabs_index.py: its game pages read into `gametabs_games` and `gametabs_game_tabs`, schema 13, for composers.
  - `game_pass`: the step's with what its budget leaves and `caracole gametabs --index`'s; your songs' games first,
    each page again after 30 days, resumed across runs.
  - `index_state`.

#### youtube

- youtube.py: running yt-dlp; and the phone's half, which the computer never runs: `phone_argv` (`PHONE_DOWNLOAD_ARGS`,
  m4a by its format alone, QuickJS, the gate as `--proxy`; no run of a target but a video's plain address, a value
  holding a NUL, an empty search or download folder) and `classify` (`CLASSIFY_STEPS`: `_OUTDATED`,
  `PHONE_PASS_OVER` on the ERROR line, out of date after a broken solver's warning, `_DEGRADED`), the corpus's
  youtube/youtube.json (tests/test_conformance_youtube.py). `choose` reads a song's artist forms in `name_forms`'
  order, the whole name first (`_Names.artist_slugs`, a tuple, never a set), so `choose` is the same under any hash
  seed (a featuring artist's video was accepted or dropped by a set's order); a duration no float holds (an int
  past one, in a search's, a video's or a download's answer) is an answer error in the words of an answer that isn't
  JSON (`_duration`), never a bug.
- youtube_urls.py: a video's address.
- youtube_fetch.py: the step.
  - `song_states`: where each song stands for the pages: `todo.write_pages` asks once and hands it to both, a
    one-song card asks of its song alone.
  - `songs_for_youtube` passes over a song whose auto sheet another caracole made and no pass here would make again
    (`_left_elsewhere`, autochords/run.py `left_as_made_elsewhere`: R3), unless it is chords alone, no site has the
    words and words heard here would replace it (R5, the words still to hear): its audio would be for nothing.
  - `phone_due(conn, overrides, now, paired=)`: the songs a phone takes the audio of by itself (its automatic pass),
    within `songs_for_youtube`: no audio of their own, no sheet at all (either side's); on a paired phone only those
    it noted (kv `youtube-wanted:<id>`, `WANTED_PREFIX`); the noted first, failures last. Held by
    vectors/youtube/due.jsonl (fixture libraries, tests/test_conformance_youtube.py), which core.youtube's port
    replays.
- youtube_sheet.py is no step but `caracole youtube --sheet`: one song's auto sheet from a video now.
  - Its stages song, audio, lyrics, vocals, words, chords, pdf, pages (`STAGES`), reported as a lookup's (staged.py's
    `StagedRun`).
  - LRCLIB asked with the audio's length.
  - Its vocals and words are `HearsWords`' (transcribe_job.py, below), the owner's "transcribed by default"
    (2026-11-25): only after the lyrics stage, and only where every lyrics site missed (`_why_not_heard`:
    `why_not_offered`, "not transcribed: …"), `[autochords] transcribe` is on (`TURNED_OFF`) and this caracole can
    transcribe (`transcribe_reason`, "not transcribed here: …"); a site's words or instrumental verdict
    (`SITES_ANSWERED`) said first, whatever this caracole can do, the controller's ruling of 2026-11-25 (on a
    caracole that can't transcribe, a sheet whose lyrics were found would read as a fault); `make_sheet(hears=)` True
    passes over the setting and the machine (tests), False is off. After each hand-over the song still one for YouTube
    (`_still_ours`: `_unsheeted`, not ignored and no human sheet, and no audio of its own, bought or given, else a
    refusal) and still offered (else that stage skipped, the chords over the lyrics a lookup found).
    `WORDS_FAIL_THE_JOB` false: a failure to hear fails its own stage alone, the chords made chords-only, the command
    exiting 0, the song still offered Transcribe the lyrics; audio Whisper can't load filed nothing against the chords
    ("Whisper can't read the audio": auto-chords' own reader, the one the vocals read the mix with, gives its verdict as
    the chords are made), noted as Whisper's alone (`transcribe:unreadable:`), offered no transcription until it
    changes; nothing sung is the words' done "nothing sung was heard (why)".
  - `autochords_pending(only=)`, once, after the words: run.py `_generate` hands sheet.py's `make_sheet` the
    transcript; before it, the audio still the one the vocals separated (`_same_audio`) where they ran.
  - caracole serve's sheet from a YouTube video runs it (web/youtube_routes.py).
- audio_sheet.py is no step either but `caracole audio FILE` (commands/audio.py): one song's auto sheet from an audio
  file the owner gives it now, the YouTube sheet's `_Sheet` with its download swapped for keeping the file
  (`_AudioSheet`, `make_audio_sheet`, `AudioRequest`).
  - Its stages song, audio ("Your audio file"), lyrics, vocals, words, chords, pdf, pages (`STAGES`): the song found or
    added as the YouTube sheet's (`_Sheet._the_song`, a new line with the file's album and length, so LRCLIB is asked
    with it), refused ignored or with a human sheet alone (`_still_ours` is `_unsheeted`: an upload always wins, the
    owner's decision of 2026-11-25, so a purchase or YouTube's audio is no refusal); the audio stage
    `audio_store.keep` (a file of your own copied, `--upload ID` a staged upload moved), saying which audio it replaces
    as the song's source, "has this file's audio already" for the same file; lyrics, vocals, words and chords the
    YouTube sheet's, the lyrics sites first, the words heard only once every one missed.
  - `names_of`: a file's song, its artist and title tags (the title `song_names.clean`ed), else its name less its
    extension and track number (music.py `_TRACK_PREFIX`) through `read_names`, else that name as the title alone.
  - The command reads the file first (`audio_store.examine`, an upload's staged record) and refuses, before the lock,
    what isn't audio it reads, as it refuses a caracole that makes no chords (`youtube_fetch.autochords_problem`:
    neither YouTube nor yt-dlp needed); a file that names no artist with no `--song` exits 2.
  - caracole serve's "+" runs it (web/audio_routes.py), `--upload ID`.
  - A moved upload leaves its marker, `.upload-<id>.kept` (0600, the kept file's name and the song's id), written
    before the data's move; the staged record goes only once the song's row names the kept file. So the same job
    again (Try again after the Audio stage: a lyrics site's wait, the chords failing, Interrupted; or a run cut off)
    goes on by its marker (`audio_store.marked`): the staged data still there, the move done; moved and the row not
    written, `adopt` (that exact name, for that song, else "gone"); all done, "has this file's audio already" while
    the song's `audio_path` is the file the marker names. An upload gone with no marker (lost before its keep: a
    waiting job Interrupted, its staged file swept or let go by another upload), or whose file is no longer the song's
    (a later upload kept since), is refused "That upload is gone…" (commands/audio.py `_given_already`, audio_sheet.py
    `audio`). `stage` and `sweep` never take a marked id for a staged upload no job names; `sweep` lets a marker go,
    with what is left of its upload, `MARKED` (the Journal's 30 days, web/history.py `DAYS`: Try again can't come
    later) after its keep, and before that only once the kept file it names and its staged data are both gone and no
    waiting or running job names its id (a marker is written before the move: one with its data still staged is a keep
    under way or cut off), so a cut-off keep can be finished for 30 days; `tidy` spares the file a
    marker of an unfinished keep names (`_live_kept`).
  - No kept file is deleted while another song's row names it (`audio_store._named_by_another`, one query): not by
    `keep` replacing a song's file, nor by a removal, whose plan then names no audio of yours to delete.
  - A song merged into another (songs.py `_merge`, `_given_audio`) keeps a file given: the merged song's audio is
    `other`'s when it is one and `keep`'s isn't (over a purchase's link, YouTube's audio or none), and of two the one
    given last (the later `audio_mtime`), the older deleted by the next `tidy`. The file keeps its name, the other
    song's id in it: `kept_in`, `uploaded`, `tidy` and removal's `uploaded_audio` go by `audio_path`, never by that id
    (`audio_store.given_file` tells a given file with no config: a kept file's name in a folder named `audio`).
  - The name a file was given under (an upload's as sent, a file of your own's: `audio_store._display_name`'s) is kv
    `audio:name:<song id>` (`NAME_KEY`, `given_name`), written by `keep` (and `adopt`) as the song's row names the
    file, replaced by the next file given, gone with the song (`songs._PER_SONG_KV`, SongKv.kt) and with its file at a
    merge (`_given_audio`); the auto sheet's raw names it (`audio_name`); no sync carries it (not `CARRIED_KV`).
- transcribe_job.py is no step either but `caracole transcribe`: a song's lyrics transcribed from its own audio,
  then its auto sheet made again over them (`make_transcript`).
  - Its stages song, vocals, words, chords, pdf, pages (`STAGES`), reported as a lookup's (staged.py's `StagedRun`).
  - Only a song `transcript.why_not_offered` offers one, by its identity key, never added to wanted.txt; read again
    after each hand-over (`hand_over` before vocals, words and chords), checked still offered before vocals, words
    and chords (its transcript kept no refusal before the chords), and its audio still the one vocals separated
    before words and chords (`_same_audio`), else a refusal.
  - Its own audio's transcript kept with no auto sheet over it (the chords failed or were cut off: Try again), the
    job goes straight to the chords (`_sheet_to_make`, run.py `_skip_reason`, guarded as `_due` guards it: a record
    that won't read a refusal in its words), neither model run again.
  - Refused or failed at the chords, its words kept (`TranscribeResult.transcript_kept`, set as the chords begin,
    taken back for a song that left the book): the command's "Transcript kept; no sheet made: …" (a refusal "… needs
    no sheet over its transcript now: …", `_still_due_its_sheet`; a failure auto-chords'), and "Transcript and sheet
    kept: …" for a bug after the sheet was made.
  - Each long stage says what it does as it runs (staged.py `_doing`, a running event each change): the vocals the
    minutes demucs-rs has run against about how long it takes here (hearing.py `_separating`, separate.py's
    `on_tick`, `CPU_PACE`, `GPU_PACE`), the words Whisper loading then how far it has heard the mix (hearing.py
    `_heard`, transcribe.py's `on_progress` off Whisper's own progress bar), the chords auto-chords' steps (run.py
    `on_step`, `STEPS`), as a YouTube sheet's audio (a video searched for, then its download: youtube_fetch's
    `on_download`) and chords do too; status.py's `LONG_STAGES` put them on the line and the bar.
  - Its vocals and words stages are `HearsWords`' (a mixin for a job of stages, on autochords/hearing.py's `Hearing`,
    below): the job says whether it hears the song (`_why_not_heard`: here, its transcript kept already, vocals
    skipped "transcribed already") and checks the song after each hand-over (`_still_to_hear`: None to go on, a skip
    of that stage in its words, or a refusal; here, still offered else a refusal);
    `WORDS_FAIL_THE_JOB`, true here, makes a failure to hear and nothing sung fail the job, else they end their
    stage alone (nothing sung done "nothing sung was heard (why)"); audio Whisper can't load fails it in words that
    say what to do.
  - The owner's word over caracole's (`TranscribeRequest(force, none)`, `--force`, `--none`): `force`, "it is sung",
    offers the song by `why_not_offered(anyway=True)` (nothing sung, caracole's or the owner's word, and Whisper's
    refusal of the audio passed over) and hears it with hearing.py's `anyway`; `none`, "it isn't sung", only for a
    song with its own audio's transcript kept (`transcript.why_not_unsung`), vocals skipped "you said nothing is
    sung", words done "transcript dropped" (`drop_transcript`: kv `transcribe:none:` `by` "you", for that audio
    alone, so neither the nightly pass nor a sheet from a video hears it again until `force` or a new file, a new
    start; no new kv prefix, and it never crosses to the phone), then the chords alone, said as the owner's word,
    never as nothing heard: the sheet's note `transcript.NOT_SUNG`, raw `not_sung_by` "you" beside `heard_nothing`,
    the chords stage's `youtube_sheet.HOLDS["said"]` (outcome.py passes the chords' words through), the card's
    `unsung` (Transcribe anyway, "You said it isn't sung.") apart from `nothing`.
  - Nothing sung, by words.py's rule (no sung span or under `MIN_SUNG_S` of them: Whisper isn't run; too few words
    kept, under `MIN_WORDS` or `MIN_WORDS_A_MINUTE`), is noted with why, and the job fails "no singing heard".
  - The stem in hearing.py's work folder under `cache_dir`, gone with the job.
  - caracole serve's Transcribe the lyrics runs it (web/transcribe_routes.py).
- youtube_search.py is `caracole youtube --search`: a search's first video and its thumbnail, suggested on the
  library page (`gate`, `sheet_on_screen`, `checked_jpeg`).
  - And `caracole youtube --video`: a pasted video's metadata (`video_gate`, `read_video`, `song_of_video`).
- A pasted video's "Artist - Title" is song_names.py's, from its title and channel.

#### render

- **chordpro.py**: UG markup to ChordPro; a chord-only line keeps its bar lines, as `[*|]` marks (`sheet.BAR`, which
  the page reads).
- **render.py**: PDFs.
  - **First steps**: `render_all` puts lyrics on a chart made before `heard` was kept (sheet_lyrics.py
    `lyrics_onto_sheets`), then lays a sheet that keeps it out again over other words (`relay_onto_sheets`, its
    `between`), both counted in `RenderStats.given`, then renders as ever, those songs' PDFs and pages with the rest.
  - **Chinese sheets**: a Chinese sheet's (`page.written_script`) in Simplified characters, and in Traditional ones
    beside it, `songs.TRADITIONAL_PDFS` (`sheet (Traditional).pdf`, `sheet (auto, Traditional).pdf`).
    - `_render_traditional`, kv `render:<id>:trad`, gone with its sheet's Chinese.
    - The printed text converted as the viewer converts the page (`hanzi.chordpro`, `_in_script`), the .cho as
      written.
    - An export in the characters its viewer showed, `trad=1` (`export_traditional`, its label ", Traditional").
    - songbook.py's `songbook (Traditional).pdf` for a songbook with a Chinese song.
  - **Kept versions**: a viewer page alone for each version kept beside the sheet, `version-<tab>.html` from its
    `.json`, with no Export PDF (an export is the one's), recorded in `render:files:` and dropped once the version
    leaves.
  - **Harmonica tabs**: a page for each harmonica tab kept, `harmonica-N.html` beside its `.txt` (how, below),
    recorded in `render:files:` and dropped once the tab leaves or its text is gone (test_render_harmonica.py,
    test_viewer_harptab_browser.py).
  - **What every viewer of the song carries**:
    - `versions`, `sheet_versions.as_data` with `sheet`, the one's provider, `pinned`, whether a `[pin]` chooses it
      (`sheet_versions.sheet_pins`, what `caracole versions --clear` takes out), and `this` on each entry, true on the
      page's own;
    - `kinds`, right after it, what else the song keeps to play from, as its library card names it (`_kinds_data`):
      its sheet's kind (`sheet`, `ukulele`: `sheet_versions.sheet_kind`) and page, then its Guitar Pro, text tab,
      harmonica, game music and score files, a group a kind in the card's order, each item's label with its source as
      `icons.SOURCES` names it ("Guitar Pro 1 · gtptabs", none for the inbox), a Guitar Pro file's `browser` and
      `download`, a harmonica tab's `page` (`_SCORE_FORMATS`, library_page.py's, test_render_kinds.py); none on an
      auto sheet beside a human one;
    - `guitar`, the song's kept Guitar Pro files caracole serve shows in the browser (`inbox.guitar_files`),
      linked in served settings as Guitar Pro tab;
    - and `sung`, its data's last member, the song's timed lyrics (`_timed_lyrics`: its stored LRC, lyrics.py
      `synced_lines`, read once a song; none for lyrics that can't be read) matched to that page's own lines
      (viewer/sung.py), on sheet.html, sheet (auto).html and each `version-<tab>.html` alike; none where they meet too
      few lines. Except that an auto sheet made over a transcript (its version's `raw["lyrics_source"]` is
      `"transcript"`) lights by that transcript's LRC, `raw["transcript"]` (`_auto_sheet`, `_Sheet.timed`), and no other
      page does: the song's own lyrics stay none while they're missing. Remade over a site's lyrics, the sheet loses
      the keys and lights by those.
  - **Exports**: `render_version`, an export: the PDF in a viewer's version of the sheet `export_viewer` names, the
    human one else the auto one, on the instrument its `inst=` names (`export_version`; `sheet (A Major, piano).pdf`),
    while `sheet.pdf` is the guitar's (`on_the_guitar`).
    - Listed under PDF exports in its line's ⋯ on index.html, where Sheet versions lists the UG versions kept beside
      the sheet (`sheet_versions.in_library`, library_page.py `_versions_data`).
  - **The song's own version**: `own_version`, the song's own on one of its sheets, overrides.toml's `[version]`:
    - kept by the key it plays in, as Make this my version writes it (`ExportSheet.entry`, `key=Gm&mode=dorian&capo=0`:
      the key of the shapes in the mode the sheet's chords are read in, a mode only where one was chosen, shapes by
      their frets);
    - which each sheet takes by a songbook setting's rule, its chords read in the notes of its own key, so a replaced
      sheet plays in that key, and one that reads the same chords in the relative key, or names the parallel one for
      them (`version._fitting`), plays them;
    - or, written before, a `t=` move from the sheet, which Make this my version, asked again, keeps by its key.
    - `own_versions_upgraded`, at the start of `render_all` and `render_songbooks`, rewrites once
      (kv `keys:own_versions`, through `overrides.add_version`) an entry kept by a major letter alone on a sheet now
      read minor, in the minor key that plays it where it did.
  - `version_pdf`: `render_version`'s PDF as bytes, made in a private folder and written nowhere (caracole serve's
    Export PDF, a download).
  - **The chordpro plumbing songbook.py shares**:
    - `run_chordpro`, a run's errors as `RenderError`s;
    - `private_dir`, the 0700 folder chordpro works in;
    - `pdf_font`, the font a text needs;
    - and `written_entry`, the one reading of a file written's record.
- **pdf_text.py**: each PDF's own text.
  - `names`: the theory edition's chord names: each chord and its numeral, or the numerals alone in a chart with no
    diagrams, with a legend from `harmony.glossary`.
  - Its two columns end level, at a section, by `line_heights` and `column_height`: chordpro's layout in caracole's
    style, chordpro-style.json's sizes and the PDF fonts' widths (pdf_fonts.py), which test_render.py pins to the
    real chordpro's pages in the built-in fonts and in Adwaita's.
  - On another instrument, a version's text with a song config of its own, `##config: json`:
    - `instrument_config`: a ukulele's `tuning`, so its four strings take each `{define}`; the piano's keyboard,
      `KEYBOARD`, a `{define: X keys …}` of the viewer's first position, `version.define_keys`;
    - the harmonica's harps and each chord's holes (harp.py `header_line`, `play`) or the winds' scale in place of
      diagrams;
    - the instrument and its folded capo under the title;
    - the rows of diagrams `column_height` counts read from that config.
  - One chordpro run draws one number of strings, chordpro 6.050.7's tuning being global, so a songbook draws its
    most common one and writes the others' shapes as frets, `diagrams=False`.
- **viewer/**: sheet.html, songbook.html, and:
  - **version.py**: a viewer's version applied to a sheet in Python, and where a key plays a sheet.
    - `Setting`: key, mode, capo, instrument.
    - `in_setting`: the setting's key as the key of the shapes played (on an instrument with no capo, the key it
      sounds in), its mode and capo.
    - A `Version`'s `inst`: the viewer's `inst=`, which `apply_version` shapes for (a ukulele's frets, the piano's
      keys, none for the harmonica and the winds) and `played_key`, `version_label` and `played_label` fold the capo
      in for ("A Major, piano").
    - `KeyVersion`: a `[version]` kept by its key, its swaps and shapes by their chords' names: `key_version` reads
      one, `version_entry` writes one, `in_key` plays it on any sheet.
  - **harmony.py**: what each chord does in its key on top of theory.py:
    - Roman numerals, relations, families, glossary lines, chord tones, solo scales;
    - progressions named from its `CATALOGUE` (each row with its source; a row of `_LOOPS` from any of its chords,
      the others from their first; a cycle a section plays whole, or `contains`, the ones played within a longer
      section, within each pass of one played round) and their endings;
    - a section's repeats folded round a pass that varies them (`_fold`);
    - `progression_key` for searching, `name_of` and `read_typed` for numerals typed.
  - **harmony_tables.py**: its answers as the tables a viewer's data carries, per mode, each text naming notes
    written for every transposition, for viewer.js to look up.
  - **strum.js**: a chord's shape strummed in Web Audio, `window.caracoleSound`, each instrument's voice.
  - **screen.js**: the screen's choices kept for every viewer page (the theme, the minutes the screen stays on), the
    key map (`keys`, below) and the screen kept on (`awake`, below), `window.caracoleScreen`, inlined in the head of
    every viewer page (`_page`'s `head_scripts`, the Kotlin frame's
    `headScripts`), so the theme is the page's before its body is drawn; at start-up it touches the root, the address,
    storage and the navigation alone, and what needs the body waits for DOMContentLoaded or reads what the page's
    script gave it (it looks up no element of its own, test_viewer_theme.py; at key time it walks the sheet's lines it
    was given; it listens to the page only once `awake` is called); no script guards it.
  - **overlay.js**: the rail of a wide screen, Guitar (the necks), Harmonica (the circle of fifths, the key on the
    harp chosen, each chord's holes, the slim bar) and, on a sheet with a key, Harmony (the page's own pane, viewer.js
    `harmonyPane`: the key's neck, each section's progression), and narrower the phone's sheet,
    `window.caracoleOverlay`, which viewer.js and harptab.js draw with what they look up.
  - **harp.py**: the Richter harmonica:
    - its layout in every key, positions by Wikipedia's circle-of-fifths numbering;
    - the overlay's tables by steps above the tonic (`ring`, `holes`, `key_scales`, `outside`, `chord_steps`);
    - the chords a harp plays (`play`: whole, as its triad, a minor substitute, or not);
    - and the harps for a song (`choices`, `header_line`), ranked by one rule in one place (`candidates`,
      `CHORD_FIT`, `TONIC_WEIGHT` and `ranking`): a major key's 1st position, then its 2nd, the owner's; any other
      mode by the chords each plays.
  - **winds.py**: the flute's and the soprano recorder's fingerings (baroque and German), a melody's octave (`fit`),
    a key's scale and a chord's notes as they read them.
  - harp.py and winds.py, each with its `tables` in a viewer's data, for **winds.js**, which registers the Harmonica,
    the Flute and the Recorder with instruments.js:
    - the harmonica's line in the header's facts (Harmonica: the harps for the song), a chord's holes on the card and
      the strip, its settings row (a harp of the line chosen, each chord on it, the song's `harmonicaTabs` linked);
    - the winds' fingerings of a chord's notes and their row (A–G or Do–Si, the recorder's baroque or German, the
      key's scale);
    - the notes heard in strum.js's `reed`, `flute` and `recorder` voices.
  - **instruments.py**: the instruments the viewer draws chords for, `INSTRUMENTS` (guitar, ukulele high and low G,
    baritone, piano, harmonica, flute, recorder: tuning, capo or none, where its shapes are, easy keys):
    - the ukuleles' shapes from chords-db (voicings-ukulele.json, filed by the guitar's keys, the baritone's a fourth
      lower);
    - the piano's computed (`piano_positions`: root position and two inversions, a left-hand bass);
    - `chord_shapes`, what the viewer shows a chord on one;
    - and version.py's `for_instrument`, the capo folded in on one that takes none.
  - **instruments.js**: their box and keyboard and `window.caracoleInstruments`, where another instrument's script
    registers its drawing, a line of the header's facts and a settings row.
  - **sung.py**: the song's timed lyrics (an auto sheet over a transcript: that transcript's) matched to the sheet's lines, the data's `sung`, `[[ms, n or null], …]`
    (`sung_lines`; n indexes page.py `_drawn_lines`, the lines `pinyin` reads):
    - top to bottom, the most lines paired, each as early as it can be: a chorus the sheet writes once lit the first
      time alone;
    - two lines meet by `line_key` (normalize.py `name_words`, accents, case and punctuation folded; a line that
      holds Chinese by its pinyin first, `romanize`, as coverage.py compares: either script, 妳 for 你, a tabber's
      spaces) at rapidfuzz's `ratio` `LINE_MATCH` (80) or more, rapidfuzz imported in `sung_lines` alone, pypinyin
      only for a line with Chinese;
    - fewer than `MIN_LINES` (4), or than `MIN_SHARE` (half) of the sheet's lines with words, lights nothing (None);
    - a time from 0 to under `MAX_SECONDS` (a day) alone, `round(seconds * 1000)` half to even.
- **songbook.py**: songbooks.toml: a song is a string, or a table with its own `Setting`, `instrument` among its parts
  (`caracole songbook set --instrument`, the Songbooks tab's chip; `_run_strings`, the strings its PDF draws).
  - `SongbookSong`, `Songbook.songs`, `.texts`.
  - `set_song_setting`, and `with_capo`, the capo a key or a mode `caracole songbook set` gives plays at now, so a
    replaced sheet keeps the key it sounds in, and `on_instrument`, the key and capo `--instrument` alone takes to
    keep the pitch, songbooks.js's menus' rule.
  - Its files play each song through `apply_version`, never chordpro's `{transpose}`, where `in_setting` puts it,
    the rest the song's `own_version`.
  - `plays_in`: that in words, "key unknown, as written" for a sheet with no key that a setting or the song's own key
    can't take.

#### render: a harmonica tab's page

`harmonica-N.html` comes of `_render_harmonica`, whatever came of the sheet's PDF:

- viewer/harptab_page.py `build_harmonica_viewer`, page.py's `_page` with viewer.css and harptab.css, screen.js in
  its head, and strum.js, overlay.js, layers.js, kinds.js and harptab.js after its body.
- **Its version line and list**, the sheet's viewer's (page.py `_VERSIONS` after the artist line, `_VERSION_LIST`
  after the pill; kinds.js): render.py passes `versions=_on_page(listed, None)` (no `this`) and the song's `kinds`,
  its data's last members after `overlay`. The line names its kind and which of its kind's pages it is ("Harmonica ·
  Tab 1 of 2", kinds.js's `hereIn`), its icons the sheet's; the list's Chords group the sheet's, none of it this
  page, and this tab ticked in its group. harptab.js attaches it with its `"list"` layer (`openLayer`, `closeLayer`,
  `inSight`), `carry` the screen's choices as the ‹ back to the sheet takes them (`screenChoices`), `sheetPath` the song's
  sheet's path in the library, none for a song with no sheet, so served its versions are kept and chosen on the
  song's sheet; on a phone the list docks (`.top`, `data-dock="version-list"`), from 900 px a popover
  (test_viewer_versions.py's section "a harmonica tab's page", test_render_kinds.py).
- **harptab.py reads the tab**, its holes over syllables in the sheet's `.s` columns:
  - a notation is data (`Notation`, its `Symbol`s: a mark, its meaning, before, after, around or between holes;
    `PRESETS` signs, brackets, letters, signs after, barrett, the commonest first);
  - its tokenizer compiled from it (`scan(notation=)`);
  - the tab read under each candidate and the best kept by Q = P × T (`read`, `Reading`: the share of its lines of
    holes explained, times the share of holes `harp.hole_note` plays; ties to the commoner, `MARGIN` for a less
    common one, `TAB_Q`);
  - a legend of `SYM = meaning` lines one more candidate and a weight, never an order (`legend`, `LEGEND_WEIGHT`);
  - the harp chip harptabs.com's page names (`inbox.HarmonicaFile.harp`, `parse(harp=)`: Chromatic is the text as
    written, Diatonic one more candidate, `STAR_BENDS`);
  - `DOTS` where a dot comes before a hole;
  - `parse(notation=)` a reading pinned, drawn whatever its Q (`pinned`, a pin of overrides.toml's `[harmonica]`: a
    preset, "legend", or a table, `check_spec`; `readings`, every reading weighed, best first, `spec_of` the pin of
    each);
  - what a notation can't read: a group of kind "unread" in place, never dropped;
  - the tabber's words in a line of holes: one of kind "words" (`Scan.prose`, `Scan.explained`: a row with its words
    aside, `is_row`);
  - a row under `ROW_TRUST` (`Row.trusted`): its text as written; a tab not `Tab.readable`: all of it;
  - a row's words: the line by it no section's name (`_is_label(beside_row=)`: "End of the road" is sung) and no line
    of holes (`Scan.holey`), the line above it in a tab whose words above fit its rows better, syllables to holes
    (`_above`, `Row.above`);
  - the page's "Read as" line: `Reading.symbols`, none for `Reading.standard` (harptabs.com's own key, guessed: its
    familiar legend), its source a link served to caracole serve's `/harmonica` (harptab.js; a standard tab's or one
    shown as written, "Change how it's read" at its foot).
- **harpfit.py** chooses the harp it starts on, with the record by the sheet's chords, else the tab's words,
  harptabs.com's key, the song's key, a C harp, `Choice.why` (`tabs_harp`, the record's or the words', the overlay's
  "the tab's", which `_tab_harps` gives the sheet's viewers, page.py `harpTabs`).
- **Its overlay**: Harmonica first, its harp the page's both ways, Guitar the sheet as written, harptab_page.py
  `_overlay_data`.
- **The bar**: the bar's harp −/+, Notes, a hole tapped and a line's ▶ in strum.js's reed voice, every note looked up
  in harp.py's `hole_tables`.

#### todo

- todo.py: `_todo.md`; its Artists to find on Ultimate Guitar gone once UG's artist directory has read every listing
  whole, and meanwhile only the artists whose listing it hasn't (ug/directory.py `index_state`, `letter_of`).
- library_page.py: `index.html`.
- library_assets/.
- songbook_section.py: its Songbooks tab's data.
- song_sites.py: which sites have each song, had nothing or weren't asked yet: its card's marks, rows.js
  `siteMarks` (card.js `sitesOf`).

#### backup

- backup.py: a whole copy of the database, `VACUUM INTO` on the run's connection, into `state_dir/backups/`.
  - Checked by `PRAGMA quick_check` before it takes an old one's place.
  - The newest `KEEP` (3) of each label kept (the nights', a merge's, a sync's); none made and none deleted without
    room (`needed`, `Skipped`).
  - The one step that waits for a run no step of which failed, and a copy failing its check fails the run.
  - `caracole backup` (commands/backup.py) makes one by hand, and `index merge` one before it changes anything.

### Each step's report, and the log

- Each step returns a `report.StepResult` (what it did, counted; the songs a provider's error left, with the error;
  what needs the user), which report.py turns into the run's summary on stdout and ntfy: a new step plugs in by
  returning one.
- The log goes to stderr, set up once by the root callback (logs.py: `-v`, `-vv`, `-q`, journal priorities; under
  systemd, the information of `JOURNAL_INFO`'s loggers too at the default verbosity: page_log.py's, pipeline.py's
  step lines and `caracole.progress`'s; `logs.level`; `clears_first`, a live line taken off stderr before a record).
- While it goes, the run says where it is (pipeline.py `_run`): "[6/20] lyrics…" as a step starts, "[6/20] lyrics:
  <status> (1 min 2 s)" as it ends, one line for a step that doesn't run; between them its `Ticker` (progress.py,
  `StepContext.ticker`) says how far the step is, its last word the unit's status line (`_last_word`).

### Shared by the steps and the commands

| Module | What for |
|---|---|
| config.py | caracole.toml and directories, and no secret (ntfy is a topic's URL alone); `name`, what the pages call the library (`Config.library_name`: else its folder's name); `[ug_directory]` (`DirectoryPolicy`: UG's artist directory's concurrency, delay and budget, politeness that never crosses to the phone) |
| index_transfer.py | `caracole index export` and `merge` (below) |
| catalogues.py | `caracole index publish DIR`: every site's index as one public gzip, `indexes-s<schema>-<UTC minute>.sqlite.gz`, its sidecar `published.json` and the Keep rule (`name_for`, `read_name`, `publish`, `kept`), each step told as it goes (`Progress`: the export, each table's rows by `index_transfer.export`'s `copied` and `omitting`, the check, the gzip's bytes read), which commands/index.py's `_Publishing` says through progress.py's `Console` (a terminal's live line at most four times a second, a journal's line a quarter); `index_transfer.PUBLIC_OMIT` leaves out the database's path and LaCuerda's search rows, and a file holding a path of this machine is refused (`_no_paths`: a value with this config's folders, the home folder, the database or `/nix/store/` in it, or beginning with a machine root, `ROOTS`; a name that merely begins with "/" is a site's); a clock that reads earlier than the last file's minute is refused too (`publish(after=)`, the sidecar's last publication), which `--force`, passing the rows' guard alone, never passes; the Keep rule's publishing schema is the higher of the uploader's and the newest the names hold, so an uploader built before a schema bump never prunes what a service after it keeps |
| peer_sync.py | two caracoles compared and synced, unit by unit (below) |
| canonical.py | canonical JSON: one text, so one digest, for a value in Python and in Kotlin (`dumps`, `digest`, `read`, `stored_hash`; docs/superpowers/specs/2026-11-03-canonical-json.md); the standard library alone |
| peer_push.py | a push: the units another caracole (the phone) gives this one, staged by caracole serve, taken by `caracole peer take` (below) |
| peer_file.py | a library in a `.caracole` file: `caracole peer export` writes one, `caracole peer import` syncs with one (below) |
| peer_import.py | a file to import, staged part by part in `state_dir/peer/import-<id>/` (peer_file.py, below) |
| politeness.py | the settings the computer gives the phone at a sync (`settings_document`: caracole.toml's name, the user agent, each provider's switch and lookup settings, `[match]`, `[rank]`), never its politeness (Two caracoles, each its own politeness, below); the standard library alone |
| service.py | whether this machine runs caracole as a service (below) |
| db.py | the schema, migrations, `kv`, `savepoint` (atomic writes on the autocommit connection); an upgrade, and a wait for another caracole's, said on the progress log (`caracole.progress`, never under -q) |
| http.py | `PoliteClient`, robots rules, cached answers (`stale`, `read_once_more`; `cached` and `CachedAnswers` read the cache alone, sending nothing); `ParallelClient`, PoliteClient's rules with several requests in flight (`get_many`; each request cleared one at a time under a lock, `_claim`; the events held and drained into the caller's thread, `drain`): UG's artist directory's alone |
| health.py | cooldowns, `events` |
| normalize.py | keys, pinyin, `name_forms`; `name_words`, `holds_run` and `PINYIN_PARTIAL_SCALE`, Chinese in pinyin only as whole words, for search.py and lacuerda_index.py |
| song_names.py | the artist and the title a free text names, the one parser of it (below) |
| inline.py | what a page holds inline: a script or a style by its hash, a JSON data block; the standard library alone |
| pdf_fonts.py | the fonts every PDF is set in (below) |
| page_log.py | the library page's line in the log, one a build (below) |
| page_icon.py | caracole's logo (docs/logo/) drawn in SVG, its black and its copper traced by docs/logo/trace.py: every page's tab (`LINK`, a `data:` URI for a page's head; `SVG`, caracole serve's `/favicon.ico`) and bar (`mark`); the standard library alone |
| library_name.py | which library a page shows (below) |
| overrides.py | overrides.toml (`[harmonica]`: a tab's reading pinned, `add_harmonica`, checked by viewer/harptab.py `check_spec`; `[lyrics]`: the name a song's lyrics are asked under and the record picked, `LyricsPick`, `LyricsRecord` (`site:id`, a site of `LYRICS_RECORD_IDS` and an id of its shape alone), `set_lyrics_name`, `set_lyrics_record`) |
| ug_urls.py | UG's addresses as an address bar shows them, the one reading of them: overrides.py's (`ug_path`, `pin_url`, `artist_page_address`) and a pasted link's (`read_link`), which library.js's `ugLink` mirrors (helpers/ug_links.py's shapes); the standard library alone |
| library.py | song folders, safe file access in the synced library |
| download_names.py | the name a kept file downloads under ("Eagles - Hotel California (2).gp5"): web/app.py's `Content-Disposition`, the `download` of index.html's and the viewer's links; the standard library alone (the viewer imports it) |
| notify.py | ntfy |
| mpeg_frames.py | an MP3's length counted from its frames (`count`, `counted_length`), for one whose first frame names none (no Xing/Info frame count, no VBRI), where mutagen and libsndfile guess the size over the first frame's bitrate: ID3v2 at the start, ID3v1 and APE at the end left out, junk between frames (and within `FIRST_WITHIN`, 64 KiB, after the ID3v2 tags) passed over, each frame's samples over its own rate (a stream that changes its rate, version or layer counted through), about 0.4 µs a frame (4 ms for a four-minute CBR song); music.py `read_audio` and audio_store.py `_read` take it in place of mutagen's (`scan_music` once a file: kv `music:frames`, `FRAMES_KEY`, each headerless MP3's length by its path, size and mtime, the files gone leaving it), autochords/audio.py `load_mono` checks libsndfile's decode by it; the standard library alone |
| site_index.py | a site's sitemaps into a table, resumed across runs; one that answers cut short, before its closing `</urlset>` or `</sitemapindex>`, an error that leaves the table as it was, never fewer rows |
| stamps.py | how caracole stores a time and shows one (below) |
| provider_pass.py | one song at a time through a provider (`each_song`, `PassStats`): the lyrics, LaCuerda, gtptabs.com and YouTube passes share its ladder of errors that are never misses, and name the songs an error left (`failures`); each song read again before its turn (`as_now`, `again`), and what a pass holds of overrides.toml after a hand-over (`Reread`) |
| keys.py | a song's musical key and where it came from (below) |
| removal.py | `caracole remove` and the web page's Remove; the tombstones it leaves are songs.py's |
| audio_store.py | the audio files you give caracole for a song, in `state_dir/audio/` (0700, each file 0600): an upload staged by its 16-hex id (`stage`, `staged`, `drop`, `sweep`, one no job names at a time), a song's own `<song id>-<sha256 16 hex><ext>` (`keep`, `uploaded`; its digits read from the name, `given_sha16`), what no song names deleted (`tidy`, the scan step's); the format from the bytes (`sniff`, `FORMATS`), then mutagen's read, imported inside (a file of your own's too, `examine`), an MP3's length its frames' where its first frame names none (mpeg_frames.py), the 30 minutes judged by it, a song gone a refusal of `keep`'s; an upload always wins, the owner's decision of 2026-11-25: `keep` replaces a purchase (its file in Music/ stays) or YouTube's audio, and `music.scan_music(uploads=)` links no purchase over it |
| sites.py | the library page's Sites tab's data (below) |
| progress.py | a command's output: a live line on a terminal, plain lines elsewhere, fitted in display columns of the stream's own width; `Ticker` (`ticker()`), what long work is doing as it goes: a live line on stderr on a terminal at the default verbosity alone, off for good once a write fails, a `caracole.progress` line a minute, the unit's status line (`systemd_status`, sd_notify `STATUS=`, where `$NOTIFY_SOCKET` is set); `Requests`, a client's requests against its budget (`make_client(ticker=)`, `make_youtube(ticker=)`, its runs with no time left); `Counted`, work of a known size (`directory_pass(progress=)`, `render.rendering`); a staged job by hand (`caracole transcribe`, `youtube --sheet`) its long stages' running details on one (commands/get.py `_Lines(ticker=)`, none with `--progress`, nor for `caracole get`); they only count, never pace |
| staged.py | a job of stages over one song, each reported as a lookup's stages are, run in order under the lock as asked for now (`StagedRun`: `_run`, `stage`, `_fail`, `_after_a_lookup`, `_song_again`, `_refuse`; the stages both jobs end with, `_autochords_sheet`, `pdf`, `pages`; `StagedResult`; the command's last lines, `_common.staged_end`): youtube_sheet.py's (and audio_sheet.py's, a subclass of its), transcribe_job.py's and lyrics_pick.py's (`_audio_length`, the song's audio's length, theirs) |
| progressions.py | each song's progressions (below) |

#### index_transfer.py

- `caracole index export` and `merge` (commands/index.py).
- **Export**: every site's index (`SITES`: its tables and the kv records of its progress) into a new SQLite file, in
  one read transaction, with its `caracole_export` table (format, schema, sites).
- **A partial export** (`export(have=)`, `POST /peer/index/newer`: the phone's take of the computer's indexes alone;
  a `peer sync` between computers and `.caracole` files keep whole exports): for an asker that says what it holds
  (`read_have`, data from another device: `Have`, its record of each sitemap it holds but its `checked_at`, and
  `since`, the computer's own `exported_at` of the last export of its the asker merged, null for none), each site's
  sitemaps (LaCuerda's listing pages) whose record differs from the asker's or that it lacks, each with all of its
  rows (`SITEMAPPED`, by `_unchanged` over the site's fields: a site_index.py record's etag, date, rows and keys;
  UG's etag, date, rows and `indexed_at`, its record having no keys; a listing page's etag, date, rows, pages, total
  and `gone`), LaCuerda's artist pages' and search's rows whole (no time), the rows of the tables read a row or a page
  at a time (`_TIMED`: UG's artist pages' tabs and directory, harptabs.com's artist pages, gametabs.net's game pages,
  each page with all its tabs) read or seen at or after `_bound` (`since` less `SINCE_MARGIN`, an hour, for a read
  stamped before an export's snapshot and stored after it; and earlier, to the earliest time of their rows, for each
  merge here since that took rows of those tables, kv `index:arrived`, `ARRIVED_KEY`, this side's own: a phone's
  pushed pages, another caracole's, a file's, whose times are another clock's; every row with no `since`: a
  catalogue's stamp is no bound), and the kv records whole; META's `partial` says what it was cut by (`{site:
  {since, from, same}}`). `merge(arrivals=)` notes the arrivals (kv `index:arrived`, at most `ARRIVALS_KEPT` a site,
  the oldest two made one); the phone, which makes no export, and the corpus's merges note none. An arrival reaches a
  phone only once its gate opens (the computer's `newest` for the site later than what the phone holds, the phone's
  `newerThere`), as before partial exports. A `since` later than this side's clock as it exports is none (every row,
  once). Times are compared as text, as the merge compares them (`_TIMED`: UTC "Z" stamps; one of another offset by
  its digits). The risk accepted, for one owner's NTP-synced computer: after its clock steps back by more than
  `SINCE_MARGIN`, pages stamped between the stepped-back time and the cut less an hour reach the phone only once read
  again. `read_have`'s count (`HAVE_SITEMAPS`) never refuses a body the route's 1 MiB lets through (a sitemap named
  in 6 bytes at the least), so its 413 is the one size refusal.
- **Merge**: such a file into the database under the lock:
  - refused whole (`TransferError`, status 2) for another schema or other columns, its words naming a copy caracole
    keeps (a sync's download, a staged export or import) as the file it is, never by its path, wherever they reach the
    Journal or the Sync sheet (`refusal_words`: "The other side's index export", "The file", "The index export");
  - else per site what the file read more recently:
    - a sitemap or LaCuerda listing page by its record's time (UG's rows upserted as a refresh stores them, its new
      tabs' songs marked); a site_index.py sitemap or a listing page whose record differs only there (a re-check
      found it unchanged: its etag, date, rows and keys alike, or a listing's etag, date, rows, pages and total,
      `_unchanged`) its record alone, no row written and no site of a sync's report;
    - of a partial export, a sitemap its META's `partial` says it left out (`_left`, refused whole when it can't be
      read) never read as gone: neither its rows nor its record taken unless the database's record says it holds
      those rows already (`_held`; the phone's Merged.unheld names the others, after which the sync records nothing
      as held);
    - harptabs.com's artist and gametabs.net's game pages by `read_at`;
    - UG's artist pages' tabs a row at a time;
    - UG's artist directory (`ug_directory`): a row seen later in a listing (`seen_at`) its listing columns, a page
      read later (`read_at`) its read columns, a listing's round in kv `ug:directory:letters` where it got further
      (`_round`: its last whole read, its round's start, its next page), never back; no row is removed;
    - LaCuerda's artist pages and search rows only where the database has none;
  - progress records move on, never back;
  - backed up first (backup.py, `before-merge`) only when a row changes (one that moves records alone makes no
    backup, the copy being there to undo rows), so a second merge writes nothing;
  - each index's `ensure_current_keys` after, whole where the file's keys record differs;
  - its progress, `merge(progress=, backing_up=)`, which the phone's merge mirrors: `progress(site, action, done,
    total)` once before it plans (`("", PLANNING, 0, sites)`), and once anything changes, `backing_up()`, then
    `(site, "", i, sites)` before each site, one that changes nothing too, `(site, noun, 0, n)` before each action,
    and `("ug", UG_TABS, rows taken, rows)` after each chunk of UG's sitemap rows, a statement for each `UG_CHUNK`
    (50,000) by `tab_id` range, in one statement's order and savepoint, so its rows come out the same (the index
    corpus with `UG_CHUNK` 1 unchanged); `MergeWords` the words (`peer sync`'s and `peer import`'s with `held`, the
    sites this side holds rows of, `held()`, and `there`: "gtptabs.com · 1 sitemap newer in the file", UG's "… tabs
    checked"), commands/index.py `Merging` where they go (`index merge`'s stderr or `--progress` detail; `peer
    sync`'s and `peer import`'s `index` stage), stderr's by the ticker's rules (`merge_console`: `progress.live_here`,
    quiet at -q; a live line taken off before a log record, `logs.clears_first`; any write that fails, a broken pipe,
    a terminal gone, a stream closed, the last it tries).

#### peer_sync.py

- Two caracoles synced: `caracole peer diff`, `sync`, `pull` and `new-id` (commands/peer.py); the design is
  docs/superpowers/specs/2026-10-31-phone-server-sync-design.md.
- **Units** (`library_state`): a library cut into units, each taken whole:
  - `song/<key>`: its names, decisions, versions, kept files' hashes and every overrides.toml entry about it
    (`overrides.song_entries`);
  - `removed/`, `songbook/`, `alias/`, `artist_url/`, `block/`;
  - never what caracole makes of one, nor what a lookup finds again.
- Each unit's `digest` is its canonical JSON's SHA-256 (canonical.py's `digest`), a version's raw record and a song's
  lyrics hashed canonicalized (`stored_hash`), so the phone's Kotlin gets the same digest of the same record.
  - A version's raw record is hashed without what `VOLATILE_RAW` names for its provider (`stored_hash`'s `without`):
    UG's ratings and votes, the owner's choice of 2026-11-03 ("Don't count them for the sync"); the version's JSON
    kept beside a UG sheet or tab (`sheet.json`, `tab.json`, `version-<tab>.json`) holds neither
    (ug/fetch.py `KEPT_WITHOUT`, the phone's `Slots.keepText` alike), so a tab read on both sides on two days is no
    conflict (`test_fetch.py::test_a_tab_read_on_two_days_is_kept_alike_and_is_one_song_to_a_sync`). A JSON kept
    before that holds them until the fetch keeps it again.
- **FORMAT 3** (`FORMAT`) is of every document a side answers (the state, a unit, a push) and of the base each keeps
  (`{"format": 3, "units": …}`): a base of another format reads as none, so the first sync after a format bump
  compares as a first sync (no shim). FORMAT 2's digests hashed UG's ratings and votes.
- **The state document** (`state_document`) says who its side is with the schema its database is at (`schema`,
  `db.SCHEMA_VERSION`, after `caracole`; `PeerState.schema`, an integer or none): a sync with a caracole of another
  asks for no index either way, before any download (`sync_routes.indexes_skipped`: `INDEXES_NEWER`,
  `INDEXES_OLDER`; the phone's `SyncEngine.indexesSkipped`), since each side's merge refuses the other's export; the
  units sync as ever. A state that says none is an older caracole's, its indexes asked for as before.
- **The song keys' rules**: units are named by identity keys, so two caracoles that key songs by different rules (a
  `normalize.KEY_VERSION` bump on one side alone) would read each song the upgraded side re-keyed as removed and a new
  one. The state document, the push document and a `.caracole` file's manifest say their side's (`key_version`), and
  one of other rules (`other_keys`, as `!=` compares it) is refused before anything changes, in `OTHER_KEYS`' words:
  `Peer.state` raises `OtherKeys` (`peer diff`, `sync`, `pull`: exit 1; the Sync tab's Test and compare: 409), a push
  is refused at `POST /peer/push` (409) and by `caracole peer take` (exit 1), a file at `read_file`
  (`peer_file.OTHER_KEYS`; the Sync tab's import compare 409, `peer import` exit 2); no base is re-keyed, and FORMAT
  stays 3. A document that says none is an older caracole's, read as before:
  the one gap, which closes only once both sides are updated.
- **Both** (`schema` and `key_version`, each side's state and a file's manifest): other key rules refuse the whole
  comparison as the state or the file is read (`Peer.state`, the phone's `PeerClient.state`; `read_file`, the
  phone's `SyncFiles.read`), so with both differing it is that refusal alone that is said; another schema alone
  leaves the units to sync and the indexes skipped.
- **Comparing** (`compare`): three ways, against the base.
  - The base is each side's agreements with that peer (kv `sync:base:<peer id>`: a digest or None, and when),
    recorded by `record_agreement` at the end of every pull, and merged with the peer's by the later
    (`merged_base`).
  - Whatever took it, what a take made this side's is recorded as agreed as that take ends (`record_taken`: each
    unit taken that this side now holds at the digest taken, or lacks as the other does, its kept answer dropped; no
    other unit touched, none agreed writing nothing), before anything after it: a pull or a sync with the peer at its
    clock as the take began, `peer take` with the pusher at the push's `at`, an import with the file's caracole at its
    `made` (`peer_file.record_taken`, of the units the file speaks for; none for an index export). So one stopped
    after its take (a give refused or cut off, the agree's read of the peer failing, a render that raises or is
    killed) leaves what it took agreed, and a later change on one side alone is that side's, never a conflict; the
    other side, which took nothing, records nothing, and `merged_base` reads this side's later record from either
    side. What a sync meant to give, and what any of them left, stay as they were; the command still fails
    (test_commands_peer.py
    `::test_what_a_sync_took_stays_agreed_when_its_give_fails_so_a_later_change_there_alone_is_theirs`,
    `::test_a_take_of_a_push_whose_render_fails_keeps_what_it_took_agreed_with_its_sender`). The same file imported
    again after an import killed so leaves its taken units out (`newer_than`: agreed at its `made`) and is refused as
    no newer only when nothing else is left to take; a "keep mine" the kill lost (kept at the agree) is a conflict
    again, so the file is still offered (test_commands_peer_file.py
    `::test_an_import_killed_after_its_take_keeps_what_it_took_agreed_and_its_file_still_offers_the_rest`,
    `::test_a_file_an_import_killed_after_its_take_took_whole_is_no_newer_the_next_time`).
  - A unit changed on one side is that side's; on both, differently, a `CONFLICT` (`decide`: as chosen, else
    `--prefer`, else left).
- **The remembered answer**: an import's "keep mine", kept beside the base (`record_kept`, `kept_of`: its `"kept"`,
  `{unit: [digest here, digest there, when]}`, at the file's `made`), since a file can't take this side's version.
  - `state_document(kept=)` carries those kept for the asker (`"kept"`, no member unless given; `PeerState.kept`),
    which `GET /api/peer/state` serves from sync-exchange on; `merged_kept` takes, a unit at a time, the latest of
    each side's agreement and kept answer, an agreement on a tie, the other's swapped.
  - `compare(..., kept=)`: a unit changed on neither side since is the chooser's (`KEPT_HERE`, `KEPT_THERE`), never
    a conflict asked again; changed on the chooser's side alone, the chooser's still, in the usual words; changed on
    the other side, whose version still lacks the one kept, a `CONFLICT` (`_since_kept`), never taken unasked: left
    by a sync with no `--prefer` and by the phone's unattended one (`Conflicts.LEAVE`).
  - An agreement (`record_agreement`, given each side's whole state) drops the answer of each unit it agrees on,
    both sides' alike or both lacking it, and a base with none is written as before.
- **Parts** (`PARTS`: library, songbooks, indexes; `part_of`, by a unit's kind; no unit is of the indexes):
  - `in_scope` keeps a unit of a part asked for, or a song a songbook lists while the songbooks are (`listed_songs`:
    by any cut of an entry's "Artist - Title", `songbook.entry_keys`), which comes along to a side that lacks it and
    is never removed (a removal given, taken or asked, the library's, is left out);
  - with a file's `holds`, a unit the file lacks of a part it doesn't hold is never read as removed;
  - `change_of`: what each side did since the base (new, changed, gone); `names_of`: a song's names from its label.
- Both are written for the phone, `vectors/sync/kept.jsonl` and `scope.jsonl` (tests/test_conformance_sync_kept.py),
  which sync-core ports.
- **Ids**: each side's id is kv `sync:id`, made by schema 15 for every database, so caracole serve answers one
  without writing; `new_id` gives a copied database another.
- `Peer` is the other's caracole serve over HTTP, never a site.
- **Taking** (`apply_units`), under the lock: each unit read whole (`unit_document`) and refused when it is no longer
  as compared.
  - A song through its wanted.txt line and `sync_wanted` (the one way a song is added), then its record's
    `SONG_COLUMNS`, versions, kept files checked by SHA-256 (`song_file`), `CARRIED_KV`, lyrics files and
    `overrides.put_song_entries`.
  - A song gone there is removed as `caracole remove` does.
  - A tombstone there whose song the owner settled here (given in a sync, kept at an import) is part of that answer
    (`answered_by_its_song`, on `decide`'s lists): neither taken nor left; in a sync the song given clears the other
    side's tombstone and the agree records both lacking it, and an import remembers its answer with the song's
    (`kept_answers`), so the same file is then no newer. Only while its song's difference is left unsettled (the
    unattended sync, no `--prefer`, a skip) is it left, `SONG_HERE` ("its song is here: its removal there is not
    taken"), never said taken, nothing agreed of it, and shown again at the next sync.
  - The songs the take respells as it writes a song's artist (`Applied.respelled`) come with their digest as it ended
    (`respelled_digests`, the phone's `respelledDigests`): `peer sync` gives one in its give at that digest (its push's
    `compared_here`, `--here`'s pull line), the change being the sync's own; any change after the take (a lookup's,
    once the lock is let go of, or in a hand-over between two pushes) still leaves it `CHANGED_HERE`.
  - `songbook.put_songbook`, `overrides.put_alias`, `put_artist_url`, `put_block`.
  - Then each command that takes (`peer pull`, `sync`, `take`, `import`), after a backup (`before-sync`), records what
    it took as agreed (`record_taken`, above), and renders the songs taken, the songbooks and the pages, songbooks.toml
    read once for the record and its agree (`_songbooks`).
- **Giving** a side what it takes, two ways: `caracole peer sync --here` asks the other to pull (`POST /peer/pull`),
  and `--push` pushes (peer_push.py `Pusher`), as the phone, which serves nothing to the network, always does. Either
  failing fails the sync (exit 1) before its agree; what its take recorded stays.
- **A push** (peer_push.py): `POST /peer/push/new` names the files its units keep by their SHA-256, `POST
  /peer/push/file` sends each one this side needs, `POST /peer/push` the document, checked against each unit's digest;
  then `caracole peer take DIR` takes its units from the staging folder as a pull takes a peer's, and deletes it.
  A push that fails after `push/new` (a file or its document refused, a network that drops) is let go of there at once:
  the pusher (`push_units`, the phone's SyncEngine give) posts `POST /peer/push/drop`, its own failure never hiding
  why the push failed; and a sender's next `push/new` lets go of its push never sent (`new_push`): one open push a
  sender, so no failed push holds one of the `OPEN` (2) slots for the hour; an interrupt (Ctrl-C, the phone's job
  cancelled) drops it too (`BaseException`, `NonCancellable`), then goes on; a drop is asked once, within
  `DROP_TIMEOUT` (5 s; the phone's `DROP_TIMEOUT_MS`), never after reading the state again for a token.
  - A give goes in as many pushes as the other side's limits ask (`push_units`, `_cut`; the phone's `Give.cut`), one
    at a time, each followed to its take's end (`between`, `wait_for`) before the next is opened: each document within
    `DOCUMENT_MAX` (16 MiB), each `push/new` within `NEW_MAX` (1 MiB), each push's files within `PUSH_MAX` (2 GiB), a
    song and its tombstone in one push; each take agrees on what it took as it ends. A push that fails stops the give
    there (`PushStopped`): the pushes before it stay taken and agreed, the rest isn't given, and the error says how
    far it got ("Couldn't give them 700: 350 given in the first push of 2; then push 2 of 2: … The pushes taken there
    stay taken; the next sync gives the rest."), the last push's wait too; the units left before the push it stopped
    at are said all the same (`PushStopped.left`).
  - `peer sync --push` holds caracole's lock through each wait but the last's (the last's lock let go of, as ever),
    so no nightly run starts between two pushes of one give; each of those waits is a hand-over point (`between`'s
    `wait_for` sleeps through `_handing_over`: `_common.hand_over` between two polls, its connection in no
    transaction). After a wait in which the lock went to a lookup (`handoffs()` moved), this side's state is read
    again (`again`: overrides.toml by `overrides_since`, songbooks.toml) and each unit still to push whose digest moved
    since it was compared is left (`CHANGED_HERE`), for the next sync, the pushes after it carrying that state
    (`test_commands_peer.py::test_a_lookup_waiting_for_the_lock_gets_it_while_the_give_waits_between_two_pushes`,
    `::test_a_unit_a_lookup_changed_while_the_give_waited_is_left_changed_here_never_pushed_stale`). The phone, with
    no lock, waits as before.
  - Left out of a give, with why, never sent to be refused: a song with a kept file past `FILE_MAX` (64 MiB) in the
    export's words (peer_file's `TOO_BIG`, the phone's FileError's), a unit that alone passes a document
    (`TOO_LONG`) or a push's files (`TOO_HEAVY`). Left, not failed, and not agreed.
  - The phone's limits are PeerClient's constants (`PUSH_NEW_MAX`, `PUSH_DOCUMENT_MAX`, `MAX_FILE`, `PUSH_MAX`), held to
    the routes' by `vectors/sync/push.jsonl` (tests/test_conformance_sync_push.py: the limits, the words, `_cut`'s
    cases; GiveTest). On its take the phone takes no kept file past `MAX_FILE`: refused by its Content-Length before a
    byte is read, or, an answer with no length, once its bytes pass it, the song left "score-1.pdf is over 64 MiB: the
    phone takes no file that big" (PeerClient.file); a Content-Length lower than what is sent is read no further than
    it says, whose bytes then aren't the file's ("… changed since compared").

#### peer_file.py

- A library in a `.caracole` file: `caracole peer export FILE` writes one, `caracole peer import SOURCE` syncs this
  library with one as if its caracole were here (commands/peer.py); the design is
  docs/superpowers/specs/2026-11-03-sync-redesign-design.md, the layout docs/superpowers/plans/2026-11-03-sync-redesign.md
  §3.3.
- **The file** (`FORMAT` 1): a zip of what a sync reads from the other side, its members in order:
  - `caracole.json`, the manifest (the caracole, schema and sync format that made it, the rules its songs are keyed
    by, `key_version`, the library's id and name, `made`, its parts, its counts, its indexes' sites);
  - `state.json` (`peer_sync.state_document` of its units), `bases.json` (every base it keeps), `units.jsonl` (each
    unit's document), `files/<sha256>` (each kept file once);
  - with the library, `pages.json` and `pages/<sha256>`, the pages made of its units (`offline_routes.library_pages`:
    `GET /api/offline`'s manifest cut to them), so a phone that takes a song opens its sheet: each page's bytes
    once, none for a page that is a kept file (held once, under `files/`), so a page is read from `pages/`, else
    `files/` (`FileSource.page`);
  - with the indexes, `indexes.sqlite` (`index_transfer.export`).
  - Its parts (`peer_sync.PARTS`): the library whole, the songbooks with the songs they list (`listed_songs`), the
    indexes. JSON deflated, blobs stored and copied by the MiB, every member dated `made`.
  - Its units read in one read transaction and its indexes in their own (`index_transfer.export`'s), state.json
    naming their newest read as indexes.sqlite holds it; each page read once, one no longer as its manifest says
    left out; taking no lock; written under a name of its own and renamed, never over a file.
  - A song whose kept file changed since caracole kept it, or is past `FILE_MAX`, is left out (`Made.left`, with
    why: `CHANGED`, `TOO_BIG`), its state still naming it, so the file never reads as having lost it.
  - `file_name`: download_names' cleaning of the library's name, then `-dd-mm-yy.caracole`.
- **Reading** (`read_file`, `SyncFile`): the manifest first, then every name in the layout, each once, each blob at
  most `FILE_MAX` (64 MiB), each JSON member `JSON_MAX`, the whole `IMPORT_MAX` (8 GiB); the indexes held only at this
  database's schema; an index export (`index_transfer.META`) a file of the indexes alone, with no id.
  - `check_whole` reads every member through before an import takes anything (its CRC, each blob its SHA-256, each
    document its state's digest, each kept file a song names and each page pages.json lists held): a file that can't
    be read whole is refused whole.
- **Refusals**, in the owner's words and the phone's alike, the whys caracole's own (`NOT_A_FILE`, `OTHER_FORMAT`,
  `OTHER_KEYS`, `OWN_EXPORT`, `OLDER`, `UNREADABLE`): `read_file` refuses a manifest of songs keyed by other rules
  (`peer_sync.other_keys`; one naming none read as before); `check_importable` refuses a library's own export;
  `newer_than` (in `compare_file`) leaves out each unit agreed on or answered with the file's caracole at or after its
  `made`, and refuses a file with nothing left to take (no difference this side would take, no index read more
  recently) and no newer than this side's last sync with its caracole (its base's latest time, the kept answers'
  included), so an import of some parts, or one that left a unit, leaves the rest of the same file to take.
- **An import is a sync with the file**:
  - `compare_file`: this side's base for the file's caracole merged with the one the file keeps for this side, and the
    answers both remembered (`peer_sync.merged_kept`), within the parts the file holds (`in_scope(holds=)`);
  - `FileSource`, the take's `UnitSource`, so `apply_units` takes a file's units as a peer's: a unit of a part it holds
    that its state lacks is one its caracole hasn't got (a removal, against the base); one it names without a document,
    or of a part it doesn't hold, a `PeerError`, left, never a removal;
  - `record_import`: what the two agree on, stamped `made`, of the units the file speaks for alone (`speaks_for`: of a
    part it holds, or that it carries), every other unit's base as it was; then each "keep mine" (`kept_answers`)
    remembered (`peer_sync.record_kept`), a file taking nothing back; none for an import of the indexes alone, so the
    same file's library may still be imported after.
  - commands/peer.py's `peer import` takes a staged folder only once its file is whole (`peer_import.whole`), and
    exits 2 for a file refused or an option it can't take (a `--choose` of no difference), 1 for `STALE`, a "Go on?"
    answered no, overrides.toml or songbooks.toml unreadable, nothing taken for want of a backup, its indexes not
    merged or a bug, else 0, never 1 for a unit left (no failure, as a sync's: the Journal's "Shared · 1 change left as
    it was", the phone's words, its staged file still kept); with `--progress` its report comes whatever it took.
- **peer_import.py**: an upload staged part by part, `state_dir/peer/import-<16 hex>/` (0700: `file.caracole` and
  `open.json`, 0600), one at a time, each part 8 MiB at most and the next one, 8 GiB in all; one untouched an hour is
  swept unless `held`; `staged_folder` checks the folder `peer import` is given, which it deletes once the file is
  refused or taken with nothing left, and keeps for a comparison again else (`STALE`, a unit left), its hour from
  then (`kept`).
- `peer sync --parts` and `peer import --parts`: the parts of a sync, a difference outside them neither taken, given
  nor said; a sync compares with the kept answers, so a unit kept here at an import is given there at the next one.
  - `peer sync --compared HASH` applies the comparison its hash names: with the kept answers (`peer diff`'s, and
    caracole serve's Sync tab's, sync_routes.py `_compared`), or without them, a comparison made before them
    (commands/peer.py `_Compared.named`).
- Written for the phone: `vectors/sync/file.jsonl`, `vectors/sync/files/*.caracole` (`full`, `songbooks`, `indexes`,
  `left`) and the fixtures `file_conflict` and `file_indexed` (tests/test_conformance_sync_file.py), which the Kotlin
  sync ports: an export, a file read and refused, a unit taken from one, an import.

#### service.py

- Whether this machine runs caracole as a service: its marker, `/etc/caracole/service` (`MARKER`, a few lines of TOML
  naming its `state_dir` and `library_dir`), which nix/module.nix and deploy.md's Ubuntu steps write, and
  `CARACOLE_SERVICE_FILE` another, which conftest.py points at no file for every test.
- `elsewhere`: the service when a caracole with no config named (no `--config`, no `CARACOLE_CONFIG`) would use
  another database than its. Then, unless the root `--home`:
  - `_common.load_cfg` refuses a command that builds an index (`builds_index=`, its words: run, index build and
    refresh and publish (but `publish --kept`, which reads no config), gtptabs, musescore, harptabs, gametabs, ireal and lacuerda `--index`, ug `--directory`) with status 2;
  - and any other says `warning` once before it writes (`_common.warn_elsewhere`, as it first takes the lock, or as
    add and serve write first).
- The standard library alone.

#### song_names.py

- The artist and the title a free text names, the one parser of it (`read_names`: its rules in order, cleaned first
  by `clean`, a video's channel by `clean_channel`; a known artist, a one-word artist of your library only once
  credible).
  - Two parts, each its own words (`_own`: less its CJK title groups, 【】《》「」『』〈〉, else the first one's
    content), then, where no mark parts the text, its first title group the title (`_bracketed`: "米津玄師
    MV「Lemon」", "《孤勇者》陈奕迅"; words before it that begin with the channel or a known artist and go on the title
    instead; its artist's loose tail cut as `clean`'s, `_loose_at`, an artist after it less a leading "by"), before a
    known artist, the channel's song and the suggested video's.
  - A bracket of a version's or a tag's words alone (`_TAGS`: "【Live】", "【翻唱】") is never a title: leading the text
    or a part it goes (`_untagged`), after the song's words it stays as written.
  - A 「」 or 『』 quote is a lyric when it has a space between two CJK characters, is longer than `LYRIC_CHARS`, or
    ends as a sentence (`_lyric`, `_lyric_unless_named`), unless it is alone once the video's groups go (`_alone`);
    one that ends so, or a long one of Latin words alone, is a title after an artist known whole (`_decoration`,
    `_whole_artist`: the channel's name or a known artist; `clean` knows none).
- Every path that turns text into a name uses it:
  - `/api/search`'s `names` (with the YouTube video suggested for the query), which the library page's request form,
    its Make sheet and the lookup page's form by name fill in, each field until you type into it (no page splits
    a text itself: test_web_page_names.py);
  - a pasted video's guess (youtube_routes.py `pasted_video`);
  - `/request` and `/lookup` given one text, `q` (library_routes.py `named_form`);
  - `caracole add TEXT` and `caracole get TEXT` (`_common.read_song_text`; ARTIST TITLE, two arguments, are never
    read).

#### pdf_fonts.py

- The fonts every PDF is set in (`pdf_fonts`, `CARACOLE_PDF_FONTS`): a folder of `regular`, `bold`, `italic` and
  `mono` (`in_folder`).
- What `metrics` reads of each: the characters it has and their widths as ChordPro's PDF library counts them, which
  render.py's `pdf_font` (a letter the regular font lacks brings in the CJK font, for the words alone:
  `fonts_options`, `PDF_FONT_ELEMENTS`) and pdf_text.py's layout read.
- Without the folder, ChordPro's built-in fonts, as before.
- The standard library alone.

#### page_log.py

- The library page's line in the log, one a build (`PageBuild`: caracole serve's at `/`, library_routes.py, with the
  host; `todo.write_pages`'s `index.html`): its songs found, wanted, ignored and in review, its songbooks, the
  database's path, size and time, how long it took.
- A page with no songs, or a database that can't be opened or read: a warning that says what tells why, the page
  answered as ever:
  - the database before and after the build opened it, its owner, WAL, schema version and `songs` rows read straight
    from it, read-only;
  - the folders, the process's uid and gid.
- Information the journal keeps by default (logs.py `JOURNAL_INFO`): `journalctl -u caracole-web | grep 'library page'`
  (test_page_log.py).

#### library_name.py

- Which library a page shows (`LibraryName`): its name after caracole's in the header and the tab's title of
  index.html and every page caracole serve writes itself (top.py, pages.py, lookup_page.py, guitar_page.py:
  `WebApp.library_name`).
- On caracole serve's alone, a badge for a library that isn't the owner's usual one, with the logo on its colour
  (`scratch_badge`, once at start):
  - `caracole serve --label`, else `SCRATCH` for a config file, library folder or state folder in a temporary folder;
  - never the NixOS or Ubuntu service's /var/lib/caracole nor a library run by hand at home: test_library_name.py;
  - never on the written index.html, a viewer or a songbook's page.
- On the Android app's page, `WebControls.in_app` (`ServerControls.inApp`, set by Assembly): no name row, its own
  bar names the library; the title still does.
- The standard library alone.

#### stamps.py

- How caracole stores a time (ISO 8601 UTC to the second, a naive time is UTC) and shows one (`shown`, in UTC;
  `local=True`, the Requests tab's, in the server's zone, named).
- A stored time missing or unreadable is older than any (`before`).
- The standard library alone.

#### keys.py

- A song's musical key and where it came from.
- A key named by its letter alone (UG's `A`, a sheet's `Key: A`, LaCuerda's `Tono: La`) is its parallel minor where
  the sheet's chords say so, one rule for every reader:
  - `theory.bare_key`: their key is that minor, or has its notes, or the minor's a capo lower, and neither major's, or
    is the relative minor of the letter's major, that minor (`C` over Am F C G Am, A minor), and no chord plays that
    tonic major, A or A7;
  - keys.py reads sheet.json's capo, page.py's `_song_key` a sheet's `{key}` by `theory.named_key` and trusts a
    keys.py source's key as given.
- Hotel California's `A`, capo 2, is A minor, sounding B minor (test_keys.py, test_viewer_theory.py).

#### sites.py

- The library page's Sites tab's data (`sites_data`, its `data["sites"]`):
  - each site's role, robots.txt in words with the closed paths worth naming (each in `http.ROBOTS_DISALLOW` but
    YouTube's), its terms note;
  - what its index holds, what your library keeps from it, last night's requests (kv `run:last`) and its status
    (`status_of`, which todo.py's health table reads too).
- Read with no request.

#### progressions.py

- Each song's progressions, read by render.py as it renders the song's sheet (its human one, else its auto one:
  `test_progressions.py::test_a_song_that_keeps_both_sheets_is_found_by_its_human_sheet_never_the_auto_one`) into
  kv `render:progressions:<song id>` (`record`; harmony.py's `progressions` and `progression_key`).
- So that these read one row a song, never a sheet:
  - index.html's data (each song's `progressions`, the page's `catalogue`);
  - `#prog=` (any rotation of it, made the key by library.js's `progKeyOf` as `progression_key` makes one);
  - `/api/search`'s `progression`;
  - and `caracole search --progression`.
- `read_progression`: numerals or a catalogue name typed.
- A named progression stands for every reading of its name (the pop progression in a major key and in its relative
  minor) and finds a section that plays it within it (a record's `contains`).

### Rules a change there keeps

The Invariants below are the others.

#### The pages caracole writes and serves

The pages caracole writes and serves are index.html, sheet.html, songbook.html and caracole serve's own.

- **They load nothing from the network.**
  - A Content-Security-Policy allows each inline script and stylesheet by the hash of the very text inlined
    (inline.py `sha256_source`), and a page's data is a JSON block with each `<` escaped (`inline.json_block`).
  - Each carries `page_icon.LINK` in its head, which its policy allows with `img-src data:` (test_page_icon.py).
  - Their scripts build every element with `createElement` and `textContent`, never `innerHTML`, and connect to
    nothing but caracole serve.
- **A page caracole writes into the library** is served only through `app.written_pages`, and only while it holds the
  bytes caracole recorded (`files.read_written_page`).
  - A new kind goes there, with its record and its policy.
  - A kept version's page, `version-<tab>.html`, is a sheet viewer by its name, and a harmonica tab's page,
    `harmonica-N.html`, a kind of its own by its name, served as a viewer is: `app.written_page`.
  - index.html itself, recorded by `library_page.write_library_page`, only at `/offline/index.html`, with no sandbox.
- **The one page that loads anything from caracole serve is the Guitar Pro page** (`web/guitar_routes.py`,
  `guitar_page.py`: a song's kept `guitar-N.*` file drawn and played by alphaTab, made per request, nothing written
  into the library).
  - Served in a sandbox, it loads alphaTab's one bundle (`web/alphatab.py`: the library, its font and its SoundFont,
    from `CARACOLE_ALPHATAB_DIR`) by `<script src integrity crossorigin>`, which its policy allows by the bundle's
    SHA-256, as it does the `@font-face` stylesheet alphaTab adds (`alphatab.font_face`, pinned by
    test_web_guitar_browser.py).
  - The bundle route answers any origin.
- **A suggested video's thumbnail**: the served library page shows the thumbnail of a YouTube video it suggests for a
  search from caracole serve (`GET /youtube/thumb/<id>.jpg`, youtube_routes.py: a JPEG of caracole's cache, checked by
  its bytes), which its policy allows with `img-src 'self'` alone; the file on disk has none.

##### Searching from the pages

- **Search mode** (library.js `searchMode`, `enterSearch`, `leaveSearch`, `backFromSearch`): `body.search-mode` is on
  as the box takes the focus, or while it holds a query (`render`), served or from a file, at every width, with the ←
  at the box's left (body.html's `#leave`, "Back to your songs", the one control so named: no row over the results
  says it); a blur leaves it on. It ends with the ← (`backFromSearch`), Back, or Escape in the empty box, and nothing
  else (`leaveSearch`: the box empty, the sites' results closed, the focus out, the address written in place); × clears
  the box and keeps the focus in it, still searching (test_library_search_mode.py).
  - Entering it from the empty box pushes one entry, `{ search: 1 }` (none when the entry is search's already: a
    reload, Forward); `searchFor` pushes `{ search: n + 1 }`; the ← is `history.go(-n)` (`leaving`, so popstate then
    leaves it whatever query was under its steps), else, with no steps, `leaveSearch` in place; popstate to an entry
    with no `search` marker and no query ends it.
- **The page's history**, every script of the library page's
  (docs/superpowers/plans/2026-11-17-library-page-redesign.md, "Where the lanes meet" 1):
  - every `history.replaceState` passes `history.state`, never `null`;
  - a script that pushes an entry pushes an object with a marker of its own (tabs.js `tab`, search's `search`,
    card.js's `caracoleMenu`), and any entry pushed while `body.search-mode` is on also carries `search:
    (Number(history.state && history.state.search) || 0) + 1`, never `search` spread from `history.state`;
  - a `popstate` handler acts on its own marker alone, and a `pushState` that throws falls back quietly (the change
    made in place, with no step).
  - A card's ⋯ menu (card.js `caracoleMenus`, its one `popstate` listener): on a touch screen (`(pointer: coarse)`)
    opening it pushes `{ caracoleMenu: n }` (n a serial), with `search` one more than the entry under it in search
    mode, at the same address, so Back (or the ← of search) closes it and leaves the card open; closed otherwise
    (a choice in it, Escape, a press elsewhere, its card drawn again), it takes its entry back once the press's own
    handlers ran, so an entry another script pushed meanwhile stays; never `history.back()` for a press that leaves
    the page or steps back (a same-window link but a download, a download too on a page opened as a file, search's
    `#leave` while the entry is search's; the Navigation API's `navigate` and `pagehide` besides), whose entry stays,
    replaced as `{ …its fields, caracoleMenu: "closed" }`; Back passes over a closed menu's entry, and Forward too
    where `navigation.currentEntry.index` says the way; Back from the page a link opened lands on it in a document shown
    again, which steps back over it on `pageshow` (`history.back()` for a closed entry, or any menu's entry of a page
    loaded as `back_forward` or shown again from the back-forward cache, where `leaving` is reset and a closing menu's frozen
    timer may still be pending; Forward onto
    one from another page spends a step: the direction isn't told); a reload with a menu open leaves its entry the page's (one
    Back spent); a mouse pushes nothing; no other script copies `caracoleMenu` into its entries (test_library_card.py).
- **Enter in a search box never spends a request on a guess**:
  - on the lookup page it acts only on `/api/search`'s `best` (or opens the leading artist's songs);
  - on the library page, whose served bar searches `/api/search` as you type (which asks no site), it only moves the
    focus to the first result;
  - the exceptions are LaCuerda's search, which Enter sends when its gate allows, and YouTube's suggestion, below.
- **YouTube's first video**: a served library page's search with no sheet on the sites
  (`youtube_search.sheet_on_screen`) asks YouTube for its first video once the query has settled (1.5 s; Enter at
  once), when `/api/search`'s `youtube` says `auto` (`youtube_search.gate`).
  - `POST /youtube/search`, a queued `caracole youtube --search --progress`, one yt-dlp run and the video's thumbnail.
  - Its row (library.js `ytRow`) fills the request form in, and sends nothing itself.
- **A YouTube video's link** typed or pasted into that box (library.js `youtubeVideo`, youtube_urls.py's shapes) is no
  query at all: no site, LaCuerda or YouTube search goes for it.
  - Its panel (`showLink`) reads `GET /api/youtube/video` (no request: what caracole knows of the video, its name read
    by song_names.py, the library's song of it).
  - For a video not read yet, it sends `POST /youtube/video` once (a queued `caracole youtube --video --progress`: one
    yt-dlp run of its metadata and its thumbnail).
  - Only its Add and make sheet sends the request form (`POST /request` with the video): nothing is downloaded
    before.
- **An Ultimate Guitar link** typed or pasted into that box (library.js `ugLink`, ug_urls.py's `read_link`: a tab's
  page or an artist's) is no query either, its panel beside the video's (`ugPanelFor`, `askUg`, `readUg`,
  `showUgLink`):
  - it reads `GET /api/ug/link` (no request), and for a page caracole hasn't read (`auto`) sends `POST /ug/link` once a
    link a page (`caracole ug --link --progress`), followed on /api/jobs, asked again once its `tab` stage is done and
    once it is over;
  - its Fetch this version posts the lookup a search's row posts, with `tab` (`caracole get --tab`); an artist's songs
    are search lines (rows.js `indexLine`);
  - `/api/search` given a link (a UG page's or a video's) answers no `unseen`, `hint`, `lacuerda_search` or `youtube`
    (search_routes.py `is_link`).
- **LaCuerda's own search** is one of the two requests a search may bring.
  - Both pages send it by themselves (`POST /lacuerda/search`, a queued `caracole lacuerda --search --auto`) once the
    query has settled, the box unchanged for 1.5 s, when `/api/search`'s `lacuerda_search` says `auto`.
  - Enter sends it at once, by hand as the button does (no `--auto`), when it says `auto` or `button` (for the query's
    answer on the screen, else with the answer on its way, unless Escape leaves the results first; the settle's timer
    then sends nothing).
  - Never twice for a query in a page.
  - `button` (the hour's share of such searches spent) and `failed` (it failed within the hour, or three did) offer it
    by hand, a line under the results (rows.js `lacuerdaSearcher`).
  - Its rows come with the search asked again once the job is over, the focus Enter moved to a result staying on it,
    an artist's songs Enter opened on the lookup page staying open, and a search refused or failed has the button its
    words name: test_web_page_lacuerda_search.py.
  - One LaCuerda button on the screen at a time, worded Ask LaCuerda:
    - the search's own, "Ask LaCuerda: “…” · 1 request", only where the results offer no name's page;
    - where they do (`lacuerda_unlisted`), Ask LaCuerda's folded under `nothingFound`'s line or in
      `notesLine` stands for both, sending the search while its gate says `auto` or `button` (the searcher's `ask`,
      which the pages' `does.ask` tries first) and reading the name's page else, the search's line then its words
      alone.
  - A test that drives the pages for something else passes `WebApp(searches_lacuerda=False)`, which caracole serve
    never does.
- **A row for one instrument says which**, a badge as a source has its mark, on both pages (rows.js
  `instrumentBadges`: Ukulele for UG's Ukulele Chords, Harmonica for harptabs.com's tabs, Score for MuseScore's,
  Guitar, Bass… for gametabs.net's, as its game pages name them; a song's card's `instruments`, library_page.py
  `instruments_of`).
  - The Filter panel's Matches keep a site's songs too while the sites' results show, the owner's ask of 2026-11-22
    ("search yoko kanno while looking only for harmonica songs"): a site's song by what its rows have something for
    (library.js `rowHas`, `itemHas`: UG's chords, tabs or Ukulele Chords by its counts, LaCuerda's chords, iReal Pro's
    chart, gtptabs.com's Guitar Pro file, gametabs.net's tab by its instruments, harptabs.com's harmonica tab,
    MuseScore's score), a group's "+ N more" and read offers and a title alone by what its site has (`SITE_HAS`,
    `siteKeeps`), your songs as in the list (`instOf`, a line's holds read the same way). Status, Key and a progression
    keep to your songs alone: a site's song has no status and no key its index knows. The panel is the search bar's
    (body.html), so it opens over the results, under Filter, and stays open as you tap (the bar over the list of
    requests meanwhile, `.searchbar:has(> .filter-panel[open])`; its body, `.fbody`, the one that scrolls on a short
    window, its arrow outside it; the sheet from the bottom where less than `POPOVER_LEAST`, 240 of the text's pixels,
    would show under Filter with the bar stuck at the window's top, the same kind wherever the page is scrolled to:
    test_library_filter.py); its chips and its Show N songs count what the results show
    (`resultsHas`, `resultsShown`, drawGroups); the marks under the box count the lines shown (`foundNow`); the results'
    head says what is kept, with Show all (`keptSaid`), and what the Matches hide whole is said, with Show all
    (`filteredOut`; test_web_page_search_filters.py), each giving the focus to the first result (`focusList`).
- **harptabs.com is searched as UG's index is** (`search.search_harptabs`, `/api/search`'s `harptabs_artists` and
  `harptabs`):
  - its artists, named from their page once read (harptabs_index.py);
  - and a song's tabs by an artist whose page caracole read, a song a line, the most viewed first under its "⋯"
    (rows.js `harpTabsOf`), each Fetch a lookup that keeps that tab (`harptabs`, `caracole get --harptabs`,
    `[harptabs]`);
  - a tab no page read names is a title alone, as MuseScore's pages, apart.
  - An artist's group ends with "+ N more by … on harptabs.com" (`/api/artist?harptabs=`) or, for a page never read,
    the offer to read it (`POST /harptabs/artist`, `caracole harptabs --artist` queued, a job of no song's,
    `jobs.INDEX_READS`).
  - Its `looked` mark says how far its artist index has got ("harptabs.com: 1,204 of 10,428 artists", its name and
    tooltip).
- **gametabs.net's tracks of games** (`search.search_gametabs`, `/api/search`'s `gametabs`) are songs whose artist is
  their game:
  - a line in the game's group, their tabs under its "⋯" (rows.js `gameTabsOf`), each Fetch a lookup that keeps that
    tab (`gametabs`, `caracole get --gametabs`, `[gametabs]`);
  - their instruments badges, none while it is turned off;
  - its `looked` mark says how far its game pages are read ("gametabs.net: 2 of 7 games", search_routes.py
    `_gametabs_looked`).
- **iReal Pro's forum's charts and threads** (`search.search_ireal`, `search_ireal_threads`, `/api/search`'s `ireal`)
  are songs whose artist is their composer, or the by-line a thread's name gives:
  - a chart a line under its composer, "iReal Pro chart"; a thread caracole never read (`read: false`) a line under
    its by-line, "thread not read yet", and on both pages "Named from the thread's name" folded under its line or ⋯
    (rows.js `THREAD_SAID`, `THREAD_NAMED`), a song of yours on the same line as ever;
  - each Fetch the lookup that keeps that chart, a thread's reading it for its chart (`ireal`, the thread's address,
    `caracole get --ireal`, `[ireal]`): nothing is sent before it; a pick whose thread holds no chart of the title,
    nor one alone, says so in the sheet stage (get.py `IREAL_NONE`: "iReal Pro's forum: no chart titled “Blue” in that
    thread"), before what Ultimate Guitar, asked after it, kept;
  - a thread whose name names no by-line (no artist caracole knows ends it, or the query is in the middle of it): a
    title alone, apart, in an "iReal Pro" group, its thread to open, never a Fetch (rows.js `titleLine`,
    `TITLE_SITES`; library.js `model.threads`): a lookup needs its artist, and a wrong one would name the song and
    keep another title's chart as its sheet;
  - its `looked` mark says how far its playlists are read ("iReal Pro: 1 of 7 playlists", search_routes.py
    `_ireal_looked`).

##### What a search says beside its results

It is rows.js's, shared by both pages:

- `countMarks`: under the box, in the bar kept at the top, what each site found:
  - your songs' count by the page's logo, then a mark of `looked`'s and a count for each site that found something, in
    `looked`'s order, its songs as the lines show them (`foundOn`; the library page's, library.js `foundNow`, with those
    "+ N more" listed since), its name in full (`.count-name`, from 720 px), a state in a colour and a glyph, never a
    colour alone, no control;
  - then one quiet mark for every other site, whatever its state (a blocked or turned-off one is searched nowhere: its
    0 is one of them), `li.count-mark.rest`, "0 on N more", each one's name and state for a screen reader
    (`siteSaid`), its `countSaid` line and detail in its tooltip;
  - none at all, `[]`, when every count is 0, yours too.
- `fitCounts`: the names only while the row fits on one line, else the list is `short`, fitted again as the list or
  its row resizes (a `ResizeObserver` a list, its fit in the next frame).
- `drawCountMarks(list, data, yours, found)`: the row drawn, hidden when it has no mark, fitted; the one call both
  pages make for it (library.js `drawCounts`, lookup_page.py `showCounts`).
- `countsSaid`: the counts in words ("Nothing in your songs or the sites' indexes" when every one is 0), then a site
  that blocks caracole ("MuseScore turned us back"), row or no row, so a block is never the tooltip's alone (a site
  turned off, the owner's choice, the rest's words alone); the line's live region and the box's description, a
  screen reader's alone once the marks said it, and where no mark shows (every count 0) the row takes no room
  (`.counts-row.counted`).
- `nothingFound`: a query that found nothing on the sites:
  - a line of the list under a quiet band that says where it looked ("Nothing for “q” in your songs or the sites' indexes", or
    "… in the sites' indexes" alone when `does.yours`, the songs of yours the search shows, is above 0; the card is
    made again when that number changes), the query as the line's title, Request (`.miss-request`, the one filled
    button) after it, under it on a phone, the one Request then, no marks of its own (and no row under the box unless some of yours match);
  - folded under it (its name or its blank space unfolds them) Ask LaCuerda and `unseen`.
- `notesLine`: those two under results.
- On the lookup page, `didYouMean` (`/api/search`'s `suggest`, a row each, a song's as the search's rows are, before
  any result).
- The library page draws a suggestion as an artist's band of its own, first, a song suggested a line in it
  (`indexLine`, or your own line), which leaves the miss's line in place (library.js `mergeSites`, `foundNothing`,
  `tailOf`); the line under the box names the first (`meantName`).

##### The library page's list

- On the library page, library.js's `mergeSites` puts your songs and every index's rows under one header an artist
  and one line a song, by the two parts of the identity key (the rows' `artist_key` and `title_key`, an artist's
  `group_key`, a song's `identity` in the page's data), each line rows.js's `indexLine`.
- A removed song's line asks for it again as the request form does.
- **Bands and folding**, by what a group holds as each draw makes it (library.js `artistGroup(artist, items, counts)`):
  - an artist of two lines or more is a 34 px band over them (`--band-h`), the group's tail under them
    (`artist.tail`, `tailOf`'s: "+ N more", Their songs, a page's read offered);
  - an artist of one line and nothing else (no tail, no "Did you mean", a group that names an artist: never
    MuseScore's or harptabs') folds into it (`section.artist.folded`), in the list and the results alike: its heading
    a screen reader's alone, the name in it no button, and the line's `.line-by` its overline, the name that searches
    (rows.js `indexLine`'s too, `onSearch`);
  - on a phone library.css's folded grid puts the overline over the title, `.line-title` `display: contents` (its
    `.line-plays` a direct child, card.css's seam: test_library_assets.py), the title's column keeping rows.css's
    4rem; from 720 px the flat line's columns, the title, then the overline in `by` right after it, then the status,
    its buttons, the action and the key, at its end (the owner's order; no chevron after it since 2026-11-22: below);
    Select mode's are songbooks.css's
    (test_library_bands.py); the same rules are `section.flat .line`'s, a list sorted by title or by when they came
    folding every line;
  - where a line's buttons go, `plays-under` (library.js `placePlays`: measured in the one row, where its last button
    wraps below its first, once a line, by the list's width, the root's font size and line height (`textSize`: the
    app's pinch grows the second alone) and Select, again when the line changes or stops being folded or flat;
    batched once a frame, `placePlaysSoon`; a line of a run off the screen once its run comes near it,
    `contentvisibilityautostatechange`, `placeRuns`, never by laying the run out: below), its first row then the
    title (a folded or flat line's artist right after it), the status, the action and the key, its buttons a row of
    their own under the title, at its end, left of the key's column (library.css, songbooks.css selecting), so none
    ever pushes the key off the line:
    - a folded or flat line from 1200 px, in the 760 px list beside the pane (where the lanes meet, 12): one row while
      its buttons fit, else `plays-under`;
    - a band's line from 720 px, its title's column keeping 64 of the text's pixels: its buttons beside its title where
      they fit on one row, else `plays-under` (where they wrap in their column, and from 1200 px also where its title
      is cut), never one a row beside the title (test_library_card_place.py, test_library_bands.py,
      test_library_text_size.py).
- **The card's place**: from 1200 px a song's card is in the laptop's pane, `#card-pane` (body.html's `.lib-cols`, the
  list's `.lib-main` beside it), one at a time, never under its line; under 1200 px under its line, in one column of
  800 px from 720 px (`#library-view`, the masthead keeping the page's width) (library.js, below; library.css).
- A "Did you mean" band's "Their 7 songs on UG ›" opens that artist's group from `/api/artist`, as "+ N more" does.
- A song of yours under its ⋯ (Fetch again; Use LaCuerda's sheet, `lacuerdaSheet` or the search's LaCuerda row of it)
  posts `/lookup` exactly as the lookup page's rows of it do (test_web_page_again.py).
- A hit's name on the lookup page presses its Fetch (or Add again), disabled while that button is (rows.js
  `nameDoes`): never in place of a title that opens a sheet, and only a click or a key on it. On the library page a
  line's name, a site's song's too, is its row's, which opens what the line holds and never asks a site (below), so
  that a tap a little off its Fetch never spends a request (the owner's choice of 2026-11-22).
- **An artist's name**:
  - An artist's name (a header's, a line's, a site's row's, a lookup row's) searches for them as typing it would,
    served or from a file (library.js `searchFor`, a step of the browser's history, search's `{ search: n + 1 }`,
    which rows.js's `does.searchArtist` is too; lookup_page.py `searchArtist`), which asks no site: rows.js
    `artistOf(name, onSearch, cls)`, a `button.artist.artist-search`. There is no funnel and no view of one artist's
    songs alone.
  - A viewer's artist line (sheet.html, a version's page, a songbook's song: page.py `artist_line`) is a plain link to
    `index.html#by=<name>`, which library.js's `addressed` reads as the same press, served or from a file, as it
    reads `#artist=<key>`, the one-artist view's address once, then writes its own address in its place (`cameBy`:
    Back is the sheet).
  - Your songs there keep to the Filter panel's filters (`kept`), as the list's do.

##### Songs gone, and the page's tabs

- select.js knows only the songs the page was loaded with, less those gone since: a line offers Add to a songbook…
  for those alone.
- Remove, the owner's ask of 2026-11-26 from the phone ("the tile should dissapear"; the line stayed until a reload,
  as tall as its open card, which a phone's app never does), and the ruling after it, one line waits:
  - through the five seconds with Undo nothing moves: the card stays open, its buttons waiting (`holdForms`), Undo on
    the line;
  - as the removal is sent its card closes (`sendRemoval`, `closeForGood`: its ⋯ menu closed, its history entry taken
    back as card.js does; from 1200 px the pane let go, `unselect`), and its line alone, one line tall, says
    "Removing…", then Removed once its job is done (a song removed elsewhere and learnt of as below says Removed
    too), for `GONE_AFTER` (2 s, the timers' `gone`), then leaves (`leaveSoon`);
  - leaving, the list is drawn again by `render` (a fresh page's bands, folds, runs, counts and A-Z strip, no removed
    song), the lines above where they were on the screen (`steady`), the focus on it given to the next line of its
    list (#list's, the results' or "Just requested"'s), else the one before, else the search box; a line under "Just
    requested" just goes;
  - what moves the page (the close at send, the leave) waits while a pointer is down and 400 ms after the last let go,
    while a finger is on the screen (touches counted apart: a pan fires `pointercancel` at once) and while the page
    scrolls (`SCROLL_SETTLE`, 180 ms with no scroll, or its `scrollend`), `PRESS_MOST` (3 s) at most from when it fell
    due (`whenFree`: pointers and touches let go of on blur, a hidden page and `lostpointercapture`);
  - a removal that fails puts the line back with its reason, its card closed, to open again;
  - the live region says Removed once, on the line; its leaving says nothing more (`tell` writes a count only when it
    changes) (test_library_remove.py).
- songs.id has no AUTOINCREMENT, so the next song added may get a removed song's id:
  - library.js knows a song gone by its removal done on the page, or by a view or a card of `/jobs.json` that names
    another song's identity under its id (the view's `identity`, `jobs_routes.view`);
  - removed elsewhere, its line says Removed, the song that has the id now is new to the page, and select.js and
    songbooks.js let it go (`caracole:gone`; songbooks.js's set lists show a lookup on a line of the same identity
    alone);
  - every form that names a song by its id sends its `identity` beside it (library.js `songForm`, Remove's question
    and confirmation, a result's Get it, songbooks.js, outcome.py's next steps), and the route answers 409 when the id
    is another song's now (app.py `same_song`, the phone's `LookupForms.sameSong`; test_web_same_song.py); a finished
    job's answer kept in `app._ended` is worked out again once its id is another song's (jobs_routes.py `_still_its`).
- The page's tabs are tabs.js's (body.html's tablist, `tab-NAME` buttons, `#tab=NAME`, `window.caracoleTabs`,
  "caracole:tab"): Library, Songbooks, Sites, then Requests, served alone, then Sync, the last, on caracole serve's
  page alone (the phone's has none); from 720 px Library and Songbooks on the left, Sites, Requests and Sync on the
  right (sync.css), a phone's one row, each tab 48 px, scrolling sideways when five don't fit (test_library_tabs.py, test_sync_sheet.py, test_requests_tab.py).
- **Back** returns to Library from any other tab: leaving Library is one entry of tabs.js's own, `{ tab: 1 }` (with
  `search: (Number(history.state && history.state.search) || 0) + 1` beside it while `body.search-mode` is on),
  remembered as `fromLibrary` (popstate sets it again from that marker, so Forward to the step makes Library Back
  again); between the other tabs each replaces the one before; the Library tab (clicked, or reached with the
  tablist's keys) while `fromLibrary` is `history.back()` and nothing else (pressed again before popstate, the same
  Back), its focus given back once popstate shows it; the library shown by a script or a link meanwhile
  (songbooks.js's + New songbook) takes that step back too (`back()`), the library shown at once, so what the script
  does next lands on it, and popstate showing nothing again (test_songbooks_tab.py). An address that names a tab (the
  page's first, Back, Forward) shows it with no step, and a `pushState` that throws changes the tab in place
  (test_library_tabs.py).
  - Every `history.replaceState` of library.js, tabs.js, songbooks.js and sync.js passes `history.state`, never
    `null`, so an entry's marker survives the page's own address writes.

##### The Sync tab and its sheet

- One flow on both devices, written once in library_assets/ (sync.js, sync-words.js, sync-sheet.html, sync-panel.html,
  sync.css; the plan: docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4–3.7, §9), served byte for byte by
  caracole serve and the phone; `WebControls.sync` says which page has what:
  - `"tab"`, caracole serve's: the Sync tab, its three panels (Sync with a server: the address remembered, Test, the
    last sync, Sync; Export; Import a file) and the sheet;
  - `"sheet"`, the phone's (`ServerControls.sync`): the sheet alone, which the app's sync button opens; None, neither.
- The sheet (`<dialog id="sync-sheet">`, `data-view` what, conflict, going, done) opens from the tab's buttons and
  from the address: `#sheet=sync`, `#sheet=export`, `#sheet=import`, taken out once open; `#tab=sync` on a page with no
  Sync tab is `#sheet=sync` (outcome.py's Compare again).
- **What to sync**: it compares as it opens (`POST /sync/compare`, or `/sync/import/compare` for a file), then the three
  parts, Library, Songbooks and Site indexes, ticked, each with what waits in it, and above them ↓ to take, ↑ to give,
  ⚠ changed on both, counted in the parts ticked as `peer_sync.in_scope` counts them for `POST /sync/apply` (sync.js
  `inScope`, with `_removes`: a song a songbook lists comes along with Songbooks, but a removal of it is the
  library's), and the chips Compared, Your choice and the parts. A part a file doesn't hold: "Not in this file".
  A removal there of a song this side gives (proposed so, or a conflict chosen here) is that answer, never to take
  (sync.js `answeredByItsSong`, `peer_sync.answered_by_its_song`'s, held to kept.jsonl's cases by test_sync_sheet.py),
  counted again once its song is chosen there.
  With a caracole of another schema, Site indexes says why none goes, in the server's words (the comparison's
  `indexes_skipped`), there alone: the done view adds nothing of it, and it is no failure.
- **A card for each conflict** in those parts: its two documents (`GET /api/sync/unit`, once a card; a file's read from
  the file) told apart by sync-words.js's `differ`, this device on the left; a button for each side, named for it
  (Phone and Computer, This computer and the server's name, File: `#sync-keep-here`, `#sync-keep-there`), and Same
  for the other N, `#sync-same`, a checkbox the next side pressed applies to every conflict left. No Skip, and nothing
  who changed what, or when. A song's auto sheet is a line of its own, "Its auto sheet" (`autoOf`, from the auto
  version's raw the document carries whole: "made on the phone from “song.mp3”, chords over LRCLIB's timed lyrics",
  "none"): its maker named by sync id as the sides are (sync.js `makersNow`: GET /api/sync's `server`, the peer's, a
  file's by its library's name; "another caracole" only with both ids known, else no maker guessed), its audio's name
  as text, control and format characters out, cut at 60 characters, the words' site the song's own found lyrics'
  where they hold the kind the sheet was laid over; no unit, digest or route changes for it.
- **Cancel queues nothing**, at any step before Sync goes, and forgets every side chosen on a card; Escape is Cancel
  before it and Done after it. Sync posts the parts and each conflict's side in one field (`POST /sync/apply`); a 409
  says the server's words and compares again, keeping, within that opening, the side of each conflict as it was.
- **A sync on its way** (the page's, or the server's `jobs` as it loads: a reload, a second tab, the phone's
  notification) is followed quietly (`caracoleLibrary.track`), never started again; the sheet opened meanwhile shows
  it. Once `POST /sync/apply` is sent its answer is followed whatever the sheet does meanwhile (`posting`: Escape, as
  Hide, only hides it).
- **What it did**: "Synced with:" and the other side's name (the summary's one bold text), when, the two sides as icons,
  and a section a kind of change (`.sync-section[data-kind=taken|given|conflicts|songbooks|indexes|pages|left]`, `left`
  the units the sync left as they were, with why, never a removal whose song is here, `peer_sync.SONG_HERE`: the view's
  outcome leaves it out, `status.changes_left`, as the Journal's line and outcome count none of it, and so do the
  phone's Status, Outcomes, JobViews and `SyncOutcome.changesLeft`, its "Left as it was:" lines too, one rule,
  `Take.isChangeLeft`), each a button that
  opens its rows, closed at first; drawn from the comparison, the choices and the cards' documents the sheet sent, and
  the view's `outcome` and its `report` (§3.5), from the outcome alone for a sync the page didn't start. A file's has no
  given section. Its indexes say what each merge added, never a site's whole size as if new (sync-words.js `indexNews`,
  `newTabs`): "+231 new tabs" and "1,503,236 in all", "up to date", "1,503,236 tabs, all new here" for a side that had
  none, a fall in red; the headline the sites (each once, one taken and given too) and their new tabs, each side's apart
  when it took and gave ("+231 new here · +40 on Studio", never one sum), each row then saying which way it went
  (`went`: "taken from Studio", "given to Studio"); a side whose tabs only fell said too ("−210 tabs here · +40 on
  Studio"); a site given with nothing new "nothing new for Studio". A conflict is listed as kept only where its side
  came: chosen there and taken, chosen here and given (a file's here once its job is done), so a sync refused before any
  change says "Nothing was taken or given.". A stage that failed though the sync went on past it (the phone's indexes or
  its copy of the computer's pages, its job done; the computer's indexes, its job failed) is said in its words, with no
  tick, the title "Synced with:" where changes were taken or given ("Not synced with:" only where none was), and a row
  of its own (`indexes` "Indexes not brought up to date", `pages` "Pages not brought up to date"). The Journal's outcome
  agrees with that title for any sync that took or gave changes and then failed, whatever stage (the give or one of its
  pushes, the agreement, the pages, the indexes) or the server stopping it: what was shared first, then the failure
  ("Failed" where the job failed, "Shared" waiting where it is done but a stage failed, "Interrupted", which ends
  "Compare again to finish.", the action its entry offers, `INTERRUPTED_SYNC_RAN`, never Try again's; a take's and a
  pull's and a merge of the phone's index pages, which offer none, send the owner to the other side,
  `INTERRUPTED_TAKE_*`, `INTERRUPTED_PULL_*`, `INTERRUPTED_MERGE_*`), the count of what was given said once (a give
  stopped after a push counts it in its own words, "1 given in the first push of 3", so the lead then says what was
  taken alone, `_GIVEN_SO_FAR`, reading commands/peer.py's `given_so_far`); with nothing shared the failure alone
  (outcome.py `_peer_outcome`, `Outcomes.peerOutcome`). Indexes skipped for the other's database of another schema
  (the report's `indexes_skipped`, commands/peer.py's and SyncEngine's) are its indexes row, "Indexes not synced". The
  headline's tone is the one its sides share, none when they differ. Sending a file says both numbers in the size's
  unit (sync-words.js `sizeOf`, "1.5 of 2.1 GB", the phone's `Sizes.of`).
- **Export**: `GET /api/sync/sizes`, the parts with their sizes, Site indexes unticked; `POST /sync/export`, then the
  file's link (`a[download]` to `api/sync/export?export=ID`), clicked once by the page: the browser saves it, the
  phone's `DownloadListener` shares it; clicked again it says the file was sent once (caracole serve answers 404
  after). **Import a file**: `#sync-file` (`accept=".caracole,.sqlite"`, the phone's picker), sent in parts of 8 MiB,
  one at a time (`POST /sync/import/open`, `/sync/import/part`, `Blob.slice`), then the sheet as a sync with the file;
  a file no Sync took (a Cancel, the sheet closed after its comparison, an upload that failed) is dropped at once
  (`POST /sync/import/drop`), so that the next one needn't wait: caracole serve stages one at a time.
- Where it departs from §3.7's words: an override's line says its value where it is a text or a list (a pin's
  address), "set" else, so that two sides holding it differently read apart; an own key names the instrument it is
  played on (", on the ukulele", version.py `instrument_words`).
- Its words are sync-words.js's (`window.caracoleSyncWords`, frozen: texts alone, never an element): sides, changes,
  numbers grouped by hand, dates in the device's time (test_sync_words.py pins them in Madrid's zone).
- Every request relative, the reads with the form token in their header; no `innerHTML`
  (test_sync_sheet.py's `FakeSync` answers §3.4's shapes, which test_web_sync.py holds to the real routes).

##### The Songbooks tab

- The library page's Songbooks tab (`#tab=songbooks`) is songbooks.js's, drawn from the data's `songbooks`
  (songbook_section.py):
  - each songbook's set list, where it plays each song as `songbook.plays_in` says it;
  - each song's Guitar Pro mark, `guitar`: a file kept, else none;
  - and the setting's menus' names, the theory's, and the instruments.
- `/jobs.json` gives them again once a job is over (`jobs_routes.views`: a songbook's change, a lookup, which makes
  the songbooks its song is in again, or a removal; a LaCuerda artist's read changes none).
- library.js lends it `window.caracoleLibrary` (`track`, `showLine`, `focusOn`, and `fold`, the search's
  normalize.fold, for Add a song; and `stepList`, requests.js's) and tells it every job's view (`caracole:job`) and
  the songbooks (`caracole:songbooks`).
- library.js posts the Select bar's songbook too, and gives the bar its ticks back when that make fails
  (`caracole:unmade`; the songbook stays on the tab until it is made, under its name or with those ticks under
  another, or its Forget is pressed: songbooks.js `letGo`).
- A song's chip sends the capo with the key and the mode (`/songbook/set`, as `caracole songbook set` keeps it), and
  the instrument once it changes (on one with no capo, the key it sounds in, `at.sounds`, its capo menu off).
- Add a song looks a song the library hasn't got up first (`/songbook/add-song`: `search_routes.lookup_request`, then
  `caracole songbook add`, both or neither: `JobQueue.submit_all`).
- A change that ends seconds after its tap moves nothing on the screen: what it took away says so where it was until
  the next click or key (test_songbooks_tab.py).
- A songbook's line on the list says its counts and its day (`5 songs · 3 without a sheet`, `made 26/11/26`) a line
  each, neither able to wrap (songbooks.js `metaOf`, songbooks.css `.book-meta`; the separator between them visually
  hidden, so its text reads as one): the font's digits are proportional, so a day or a count a hundredth of a pixel
  wider wrapped the line, and a lookup that turned "3" into "2" un-wrapped it and moved every line and + New songbook
  under it. The test pins a wide day (`made_on`), never the clock's.

#### index.html's assets (library_assets/)

- index.html's stylesheets, scripts and markup are the .css, .js and .html files of library_assets/, inlined byte for
  byte in the order of `library_page.STYLESHEETS`, `SCRIPTS` and `TEMPLATES`, where a new file is listed
  (test_library_assets.py).
- **Four corner radii** (stage 1f; base.css `:root`): `--radius-s` 4 px, `--radius-m` 8 px, `--radius-l` 12 px and
  `--radius-pill` 999 px, besides square and 50 %; every stylesheet takes its radii from them. test_page_calm.py lists
  the elements shown with another (`helpers.targets.odd_radii`), every one of the page, in each tab, a song's card (its
  tiles, a tile's drawer, the ⋯ menu), the Filter panel, a search, the Sync sheet and the tray, at 390 and 1280 px,
  light and dark. steps.css and requests.css (lane 2's) were already on the tokens, with fallbacks
  (`var(--radius-m, 8px)`), which stage 1f dropped as a named crossing; songbooks.css (the Songbooks tab's) it brought
  to them. The test serves the page with a lookup running and one queued, a songbook and each tab, and asserts each
  state drew what it names (it measures elements, never pseudo-elements). caracole serve's own pages, base.css inlined
  first (a pick, a removal, a message, the lookup page, the Guitar Pro page: pages.py, lookup_page.py, guitar.css),
  take theirs from the same tokens (`test_caracole_serves_own_pages_have_the_same_four_radii`, alphaTab's drawing
  inside `#score` left out, its box measured).
- **The text's pixel** (base.css `--sp`, the owner's ask of 2026-11-22: on the phone a pinch that grew the text alone
  left the tiles and the chevrons as they were): the Android app's pinch sets the WebView's text zoom, which sizes the
  text and its line heights, never a length in px or rem (WebView 133, measured: `1rem` stays 16px at 200 %), so what
  sits beside the words on the library page (a song's play buttons, its Fetch, its key's column and its row's height,
  its card's tiles, chevrons and closes, an artist's band, the bar's field and Filter and Sort, the sites' marks, the
  list's estimates `--band-h`, `--line-h`, `--fold-h`) is `calc(N * var(--sp))`. `--sp` is `1rlh / 16` (`html`'s line
  height is 16px for it), at most `(100vw - 82px) / 152`, so a phone's line stays one row, its key on the screen (its
  title's least room, a button (43.2) and its key's cell (44 on a touch screen) are 152 of them; 82px the page's, an opened card's and the line's
  paddings, borders and gaps; 192 and 88px while it had its chevron; in Select mode the lists' own, `.selecting .list`
  and `#found`, at most `(100vw - 132px) / 152`, its box's 44 px and gap off the room, and Select's columns in it too,
  songbooks.css), and 1px at least from that room; never in a
  `font-size` or a `line-height`, which the zoom sizes already (a line height in it grows twice), nor where a box's height is a line height (a count's
  digits centred by the grid). The tiles' container queries are in `rlh` (24.9375rlh is 399px at the pages' own
  size). test_library_text_size.py (the root's line height grown, Chromium having no text zoom), PinchTest on a
  device.
- **No outline around the list** (stage 1f; library.css, rows.css): a list of lines or rows (`.groups`, `.lines`,
  `.rows`: index.html's list and a search's results, the lookup page's rows) has no border, shadow or fill of its own,
  the page's background under it: the bands (`--raised`) and the 1 px dividers between lines, rows and groups are its
  shape, the first band as square as the others. A line's key (`.line-key`, `.row-key`) is plain text, muted and bold,
  in no box; every song's title is semi-bold (600; a search's results' too, one weight for all), a band's name bold
  (700) in `--artist`, its count muted. test_page_calm.py's `test_no_outline_around_the_list_or_the_key` measures them
  on the page opened as a file (by artist and by title), a served search's results and the lookup page, at 390 and
  1280 px, light and dark, and that each state drew what it names.
- **A long list** (stage 1e; library.js `render`, library.css `#list .cv`): what is off the screen isn't laid out.
  Each band group of `BIG_GROUP` (50) lines or fewer is a `.cv`, a larger one's lines in runs of `RUN` (40) inside its
  `.lines`, under its band; folded artists in a row, and a flat list's lines, in runs of 40 too (`div.run`, each a
  `.cv`), the last of a row `RUN_MIN` (8) or more (a shorter rest goes with the run before it), a row shorter than 8 in
  none (`runsOf`); never a line alone.
  - A `.cv` is `content-visibility: auto`, its `contain-intrinsic-size` `auto` and what it holds (`--bands`, `--lines`,
    `--folds`, by `style.setProperty`: the page's policy allows no `style` attribute in markup) times library.css's
    heights (`--band-h`, `--line-h`, `--fold-h`, by width and pointer, the means over tests/helpers/big_library.py's
    songs), each within a quarter of what it lays out to; once laid out, as tall as it was; a flow root, so that an
    open card's margins never move it as its containment comes and goes (test_web_page.py's Remove: no shift).
  - Its containment clips what is painted outside it `overflow-clip-margin: 6px` out, room for a focused line's ring
    (base.css's, 2 to 5 px outside the line, as wide as its run: test_library_long.py reads its four sides' pixels).
    One that holds an open card is laid out whole
    (`.cv:has(.line-panel:not([hidden]))`), so that its containment never cuts the card's "⋯" menu or
    its shadow; the dividers' rules follow the runs (a run's first line or group keeps the one over it, but the first
    in its box); find in page finds a line off the screen.
  - The A–Z strip's smooth jump, whose end is set while the runs it passes are as tall as their estimates, is taken
    where it aimed once it ends, smoothly too (`landsOn`, on `scrollend`; a wheel, touch, key or press in between
    leaves the scroll to the reader; a jump with no scroll begun two frames on waits for no end, so no later scroll's
    is taken for its).
  - What reads a line's layout reads it where the line is laid out: `placePlays` measures a line only while
    `checkVisibility({ contentVisibilityAuto: true })`, or in a run whose own box is on the screen (a list just drawn,
    whose runs on the screen the next frame would lay out anyway: placed before that frame is painted), and the others
    as their run comes near the screen (that run's lines alone, `placeRuns`, not every line again each frame of a
    scroll); reading one inside a skipped run off the screen lays it out for that read (test_library_long.py counts
    none).
  - Every line stays in the DOM: no virtualized list (the redesign's rule).
- The play buttons', the foot's and the opened card's box's rules are card.css's; where the buttons sit on a line (a
  selector ending `.line-title > .line-plays`, rows.css and library.css) and the laptop's pane (`#card-pane …`,
  library.css) are lane 1's: test_library_assets.py.
- A song of yours closes to a line: its title, then, at the line's end, left of its action and its key (the owner's
  ask of 2026-11-22: "always right aligned. That is, left of the key"; rows.css's margin, library.css's columns,
  under its title where they would wrap beside it, library.js `placePlays`: Bands and folding, above), a button for
  each thing to play from, none first (card.js
  `plays`, from `things`, what the card's tiles are made of too: each a link that opens it at once, its instrument's
  `glyph`, inline SVG made with `createElementNS`, the one address the page names, an icon tile at every pointer (27 px with a mouse, 43.2 px on a touch screen, a tenth under 30 and 48 by the owner's ask of
  2026-11-23, its target 1.2 px past its edges there by an `::after`, `--hit`; no
  words), the marks of the sites its versions came from at its foot, how many at its corner; the lyrics none), Fetch's download glyph where it has one (rows.js `fetchIcon`, a site's
  song's Fetch too) and its key, at its end, one row on a phone and a laptop (test_library_plays.py). Its title, as
  its blank space, opens it as a card (card.js `caracoleCard`, card.css):
  - no chevron drawn, the owner's choice of 2026-11-22 ("Remove the chevron icons all together, I want to regain that
    space. I'll have it so that clicking in the name of a song or it's blank space yields the same result"): a click
    on any line's own row (rows.js, one listener for the page after `foldMore`, a line as it is now: refill's too; a
    site's song's too) presses its chevron, a button out of sight (rows.css: no column, the keyboard's and a screen
    reader's disclosure, `aria-expanded` and `aria-controls`, the line drawing its focus ring), never a click on a
    link, a button, a field or a summary in it, on what left the line as its own click was handled (Undo), in its open
    card, while Select ticks lines, or at the end of a text being selected; the line keeps the height its chevron gave its row (`--line-row`, 28 px of the text's, 24 from 720 px,
    44 for a thumb: a mark of no width in its key's cell, `.line::after`), so the long list's estimates hold and a line
    stays a thumb's target (test_library_plays.py, test_web_page_search.py's names);
  - made the first time it opens, from the song and its request as they are then (library.js `cardFor`, rows.js
    `resultRow`'s `more` a function): until then its panel, `.line-panel.song-card`, is empty and hidden, the
    chevron's `aria-controls` naming it (test_library_card_place.py);
  - its parts in the phone's order, at every width: `cardHead` (`.card-head` > `.card-head-in` > `h2.card-name` and
    `.card-close`, `aria-hidden` and tabindex -1 in place), the facts, what needs you, the tiles, the foot (Fetch
    again, Use LaCuerda's sheet, Add to a songbook…, ⋯), Lyrics under another name… (served), the Files group, On the
    sites, Elsewhere, Progressions (test_library_card_place.py); a song with no lyrics has its lyrics' search in what
    needs you instead, open, above Transcribe the lyrics (`lyricsPanel`, web/lyrics_routes.py's);
  - in place, its head takes no room and sticks under the search bar (`--bar-h` on `:root`, the bar's border box,
    which a ResizeObserver writes; the panel a flex column, so it sticks the whole card): shown (`head-away` on the
    card) only while the card is on the screen and the whole of its line (its title's row, a request's `.progress`
    and `.steps`) is under the bar, so it never lies over a part of the line: one IntersectionObserver over each card
    open in place and the mark at its top, `.card-top` (out of the flow, at the top of its content), whose screen
    begins under the bar (library.js `watchAway`, `cardToggled`: no layout read); its margins (library.css) leave
    the card laid out as with no head, its own place over the card's top, and let it go with the card's end; a card
    closed in place, however, scrolls its line back into view under the bar (`scrollIntoView` `nearest`,
    `scroll-margin-top` `calc(var(--bar-h) + 8px)`, `smooth()`: at once with reduced motion), and the head's close
    gives the chevron the focus (test_library_card_place.py);
  - a crossing with card.css: lane 1's head rule (library.css) reads card.css's gap between a song card's parts and
    its bottom padding as `var(--card-gap, 14px)` and `var(--card-pad-end, 14px)`, which card.css defines once, on
    `.line-panel.song-card` (the card wherever it is: its gap and padding), and its rules use. For
    Task 1d.6: `.line-panel > .card-head` (sticky, height 0) and `.card-head-in` (absolute, hidden until
    `.head-away`) aren't scoped to in place, only the head's margins are (`.line > .line-panel.song-card >
    .card-head`): the pane undoes both (`#card-pane .card-head`, `.card-head-in`: static, shown);
  - from 1200 px in the pane, `#card-pane` (library.js `selectLine`, through rows.js foldMore's `onToggle`,
    `cardToggled`): opening a line's card moves it there, the line `.selected` and `aria-current="true"` (filled with
    `color-mix(in srgb, var(--accent) 8%, var(--surface))`, never the play buttons' `--raised`, the accent along its
    edge; among a search's results, over rows.css's `#results .line.have`, at 7 points over base.css's `--have-tint`
    (16 %, dark 22 %), so it reads as the one open; no opened card's box: card.css's box, an opened
    line's, keys on `:not(.selected)`), the card's head its
    heading (out of `aria-hidden`, its close tabbable, the pane `aria-labelledby` its name), the focus on its
    `.card-name` when the chevron's click came from a key (`isTrusted`, `detail` 0); closing it, another line's opening,
    or its line no longer shown after `render` and `drawGroups` (`keepSelected`) puts it back right after the
    line's chevron, closed (`unselect`); `paneWide` (`matchMedia("(min-width: 1200px)")`) crossing down puts it back
    open (watched in place), crossing up takes the card opened last of those in place (`awayCards`' order) and closes
    the others quietly (`shut`; `toWide`, put off while another tab shows, until `caracole:tab` shows the Library);
    either way the focus on a node of the card moved is given back to it, else to the chevron (`focusAgain`); Escape
    in the pane that the card's parts left gives the focus to the line's chevron;
    a refilled selected line's new card takes its place (`placeAgain`; none, a song removed: the pane empty and as
    tall as it was); the selected line's steps listed under the head (`showSteps`, a copy of its `.steps >
    .step-list`; steps.css leaves a `.selected` line its frozen bar); a card, opened or closed, adds no history entry
    (test_library_card_place.py, test_web_page_steps.py); Select puts the pane away (songbooks.css);
  - wherever a line's card is: `cardOf(item)` (by its chevron's `aria-controls`), `itemOf(node)` (`closest("article")`,
    else `selected` for a node in the pane), `partsOf(item)` (the line, and its card when it is outside it) and
    `inItem(item, selector)`, which the forms posted in place, a removal's held buttons and focus, `paint`, the picker
    and Recently opened go through;
  - the pane's own rules, library.css's `#card-pane …` (its card's padding and gap, its head, `.foot-menu` opening
    downward, the steps), the one way lane 1 names a card's part; what is inside the tiles is laid out by the card's
    width, never the window's (card.css: `.tiles` a container, `container: tiles / inline-size`, its `@container
    tiles` rules: a version's four columns from a card 560 px wide, stacked below), so the card reads the same in the
    pane's 400–480 px as under its line (test_library_card.py);
  - a tile for each thing to play from, every one alike, one row at every width (its body, its sources' marks, its
    chevron: on a touch screen 56–64 px tall from a 360 px phone, a long name wrapping at 320; 48 at most with a
    mouse; on a touch screen under 400 px no open arrow, a download's glyph kept, and the sheet's version without "in
    use", a mouse keeping both at any width, the pane's at 1200 px too; its rating, `.tile-rated`, whole or not at
    all), its chevron opening its drawer under it, touching it (its downloads, then a part a source of its versions),
    which reads the page's data alone, never a request;
  - its UG versions not kept are counted (`versions.rest`, `sheet_versions.may_keep`), and Fetch them keeps them,
    `caracole versions --keep-more`, within a lookup's budget (test_library_card.py).

#### viewer/

- **What a page is made from** is `page.BUILD_FILES`, hashed into `page.build_version`: a module the viewer comes to
  import goes there (test_viewer_book.py checks).
- **Music theory**:
  - theory.py, harmony.py and `voicings.voicing_keys` keep their answers, so `Chord` and `Key` stay frozen with every
    field compared, and a list handed out is a copy (test_viewer_theory.py, test_viewer_harmony.py).
  - harmony.py's docstring holds the rules where music theory reads a chord two ways (B♭ in C is borrowed from C
    minor; D in C is V/V only going to G; C7 in C is V7/IV only going to an F that is no dominant seventh): change a
    rule there and in its test.
  - version.py names and shapes every chord as viewer.js does, so a PDF made in a version is what the viewer shows
    (test_viewer_version.py compares the two in Chromium).
  - viewer.js computes no music theory: a chord's numeral, its line, its notes, its solo scale and the key's scale are
    looked up in harmony_tables.py's tables, whose texts name notes as the page names them in the key shown
    (test_viewer_numerals.py checks them against harmony.py on every transposition).
  - Nor does harptab.js: a hole's note on any harp is harp.py's `hole_tables` (`hole_note`), its name
    `theory.spelling`'s, a group's effects the data's (`groups[i][2].fx`, which `drawGroup` draws again), how the tab
    was read Python's words (test_viewer_harp.py, test_viewer_harptab_page.py, test_viewer_harptab_notation.py).
- **A sheet's lines** (page.py `_line_html`): a chord-only line that writes bars (`sheet.BAR`) is a row of
  `span.barcell`s, each chord's beats from `sheet.bars` (`BEATS` a bar, shared evenly). It is still one
  `p.l.chords`, so the data's `pinyin` keeps its lines. A word a chord falls inside (`_glued`) is one `span.word`,
  which wraps whole; a line's columns are `p.l .s, p.l .w`, nested or not (viewer.js `fit()`, viewer.css's pinyin
  rules), never its children (test_viewer_lines.py).
- **strum.js**, inlined before viewer.js (and in a songbook), is the one place a page makes sound:
  - a plucked-string synthesis into AudioBuffers, no sample, worklet or request;
  - an AudioContext only on a tap (`navigator.userActivation`), suspended when the page is hidden or silent, resumed
    on the next tap.
  - `caracoleSound.play` is what a part that plays chords in sequence calls (its header documents it; the Harmony
    tab's ▶ does), never another synthesis (test_viewer_sound.py, test_viewer_harmony_tab.py).
  - It times a progression on the context's clock alone (a strum it comes to late moves the rest on, never two
    crammed together).
  - Every stop (■, another ▶ or strum, the Harmony tab left, the page hidden or left) leaves no note to begin and no
    timer of it, even when the notes cut tell they ended late.
  - A sound asked while the context wakes plays only if nothing was asked after it, and a context woken for nothing
    sleeps again.
  - test_viewer_sound.py's `SCHEDULE` records each note and timer the page makes, and plays a slow device on demand
    (a resume held, `ended` events late).
- **Versions**: kinds.js (`window.caracoleKinds`, inlined on a sheet's page after layers.js and before viewer.js, which
  attaches it with its layers and `carry`, its `vAddress`, and on a harmonica tab's page before harptab.js) draws, from a sheet viewer's data `versions`
  (sheet_versions.as_data, with each entry's `this` and the one's provider, `sheet`) and `kinds` (render.py
  `_kinds_data`), the version line under the artist ("Chords · Ver 3 of 13 · ★ 4.86 (408)") with an icon a kind the
  song keeps and how many, and the list it opens; no ‹ ›, the list opens each kept version (test_viewer_versions.py);
  the songbook has neither.
  - The list's place: on a phone a sheet from the bottom, docked on the bar as the settings are (one of `DOCKED`);
    from 900 px a popover under the line, never a rail (no `data-panel`: the song's column stays), beside the settings
    or the key list: kinds.js's `place()` calls layers.js's `placeUnder(list, #ver-now)` (its `--pop-top` and
    `--pop-left`, 6 px under the line's box, at its left, in the page's coordinates, so it scrolls with the page),
    which viewer.js's `place()` calls as a layer opens or closes and the window resizes.
  - The popover keeps 8 px within the window less the rails (the room body's padding leaves them: `data-necks`,
    `data-panel`), as wide as fits there (`--pop-room`), and ends above the bar (`--pop-y`, its top in the window as
    placed, in viewer.css's `max-height` with `--foot`), so its own scroll reaches its last row on a short window;
    its head (its ×) is sticky at every width (test_viewer_versions.py's short window, rails and resize tests).
  - The list is a group a kind (`#kind-groups`, `section.kind-group[data-kind]`, `h3.kind-head`): Chords first
    (`#ver-acts`, `#ver-items`: every version UG has, or the chord sheet alone), then each other kind in the card's
    order, a row each named as the card names it, a tap from the list: a harmonica tab's page with `carry`, a Guitar
    Pro file caracole serve draws its `/guitar?file=` page (served alone), any other file the file itself; this page's
    own row ticked, `aria-current`, no link. The settings keep their Guitar Pro row beside the list's group.
  - Its icons are the library card's: `GLYPHS`, rows.js's drawings copied (with its `check`, the tick), and
    `GLYPH_OF`, card.js's glyph of each kind, which
    `test_viewer_versions.py::test_the_kind_icons_are_the_library_cards_drawings` holds to rows.js and card.js: a
    library lane that redraws a glyph, or draws a kind with another, fails it, and kinds.js follows.
- **What moved**: viewer.js's `moved()`, how far the chords shown moved from the sheet as written by your hand (the
  shapes' move on an instrument that takes a capo, so a sheet's capo taken off is "no capo · +2"; the transposition
  alone on one that takes none), is the one count the bar's word under its key (`changes()`, `keyShort`), the
  settings' Transpose and the header's Key say (test_viewer_bar.py, test_viewer_header.py), and the key list marks
  (`mod12(moved())`).
- **The key list** (page.py `_KEY_LIST`, `#key-list`): the bar's key is a button (`#key-now`, `aria-expanded`;
  disabled on a sheet with no key) that opens the twelve keys in the mode played, `data.keyNames`' names from the
  chords as written on this instrument (`writtenAt()`: the sheet's capo folded in on one with no capo), the first
  `.key-as` "· as written" across its row; `chooseKey(k)` transposes there the nearest way (`step`, the capo kept),
  then closes it. A layer in `DOCKED` and `rails`; book.js's `busy()` keeps the arrows with it; the harmonica tab's
  page has none (test_viewer_key_list.py). A button being no live region, `#key-status` (page.py, beside
  `#scroll-status`, outside the bar) says the key's line as − and + move it (viewer.js `sayKey`: not on load, nor
  while the settings' outputs or the key's own name say it; test_viewer_bar.py).
- **The rail of necks** (from 1200 px) is the overlay, overlay.js's:
  - three tabs on a sheet, Guitar, Harmonica and Harmony, and two on a harmonica tab's page, Harmonica first, the tab
    shown kept for that page alone (test_viewer_overlay.py);
  - Harmony (D12 B), a sheet's with a key (viewer.js `hasHarmony`, where the settings' Harmony row was: no Harmony
    panel, no row), is the page's own pane, overlay.js's `page.harmony(pane)`, drawn on each draw while it shows
    (`harmonyPane`: `#harmony-key`, the key's neck, which then leaves the Guitar tab where the necks are the instrument
    played's, `necksAt().played`, else stays heading it, `#tempo-row`, `#progs`), each control with a `data-f` the
    focus comes back to, its sizes the rail's `--nk` times the phone's (text in em, targets and room in
    `calc(… * var(--nk))`); leaving it (`page.left`, another tab; `close(necksEl)`; `showNecks(false)`; `drawNecks()`
    drawing no Harmony pane while one plays) stops every sound, as the panel's ✕ did (`stopPlaying(true)`), and while
    one plays `#harmony[data-playing]` keeps a songbook's arrows (book.js `busy()`; test_viewer_harmony_tab.py,
    test_viewer_sound.py, test_viewer_songbook_browser.py);
  - viewer.js and harptab.js hand it what they look up, and Harmonica's notes, scales and harps are harp.py's tables,
    by steps above the tonic as the song sounds, a transposition moving every harp and a capo none
    (test_viewer_harp.py, test_viewer_overlay.py, test_viewer_harptab_browser.py).
- **Below 1200 px** the bar's neck (`necks-open`, after the key) slides it up as the phone's sheet (the page's
  `sheet()`, `data-sheet` half or full: its handle and ✕ for Hide), a dialog not modal and, in viewer.js, one of the
  layers docked on the bar (`--dock`):
  - each page opens with it closed, Scroll leaves it at half, the rail's Hide and the bar's `necks-toggle` don't touch it
    (test_viewer_overlay_sheet.py);
  - one control each (D11): the rail's button, `necks-toggle`, takes the neck's place after the key from 1200 px, and
    the strip of shapes has no button in the bar, ⋯'s All chord shapes (`strip-toggle`) its one switch
    (test_viewer_bar.py);
  - the strip of shapes shows by default here (`stripShown()`: `state.shapes`, null until a hand presses the switch,
    then true or false, kept per song; from 1200 px the rail holds the shapes and the strip waits for its switch),
    above the song's first section (test_viewer_strip.py).
- **Layers and Back**: layers.js (`window.caracoleLayers`, inlined on every viewer page before its own script) keeps
  a page's layers in the browser's history, one entry each while it is open, marked `history.state.caracoleLayer`
  (its depth, from 1), so Back closes the one on top and leaves the page only once none is open:
  - viewer.js's stack (`layers`, `{el, opener, nested}`, the last on top; `open`, `close`, `closeAll`, `topLayer`)
    says how many are open after each change (`restack()`: `layerHistory.sync(layers.length)`); a Back that takes k
    entries off closes the k on top and writes the page's address again (`save()`), and a layer the page closes itself
    (Escape, ×) takes its entry off with the address it wrote meanwhile (layers.js carries it down);
  - every `history.replaceState` in viewer/'s scripts passes `history.state`, never `null`, so an entry keeps its
    depth through what the page writes into its address;
  - below 900 px one layer at a time (opening one closes every other, but for a `nested` one, opened over another and
    leaving it open); from 900 px the rails (`rails`: the settings, the key list) one at a time, a card and the
    versions list beside them;
    `DOCKED` (panel, card, vList, necksEl, keyList) docks at the foot on a phone, the top one of them
    (`dock()`);
  - a harmonica tab's page (harptab.js) has `"sizes"` (Aa), `"sheet"` (the necks' sheet), `"list"` (the versions
    list) and `"full"`: `layers`, `openLayer(name, opener)`, `closeLayer(name, refocus)`, one at a time below 900 px;
    from 900 px the list and the sheet open together, either over the other (the sheet closing full screen, the list
    opening over it); Aa giving way to the sheet and the list at every width, the top of the sheet and the list docked
    on a phone (`topDocked`, `docked`, `dock`, `restack`), Escape closing the top one; it has no More panel;
  - `history.scrollRestoration` is `manual` from a layer's entry on, so a step down leaves the song scrolled where it
    is, and `auto` again once the page is back at its own entry, for a reload;
  - a history that refuses entries (a `pushState` that throws) turns it off: the layers open and close as before,
    and Back leaves the page (test_viewer_layers.py).
- **From 1200 px the bar is a toolbar** under the song's title (D13 C; test_viewer_toolbar.py), for viewer.js and
  harptab.js alike through layers.js's `toolbar(bar, head)` (`{ wide, place(), edge(), room(pill, docked) }`, neither
  script holding a copy):
  - `place()` puts `#bar` right after `head()` (`.page > header.head`; a songbook's shown song's own, `#sheet`'s
    parent's `:scope > header.head`) while `wide` (`TOOLBAR`, `(min-width: 1200px)`), back where the page wrote it
    (before `#pill`) while narrow, the focus kept on the control that had it: at load, and as `wide` changes; the tab
    order changes with it (the toolbar right after the title);
  - viewer.css's `@media screen and (min-width: 1200px)` block: sticky at the window's top once the title scrolls
    away, on the page's background, `z-index` 6 (over the song, under every layer and popover), a row of pills in the
    phone's order, none pushed to the end, 56 px tall (`--toolbar`); `--foot` is the safe area alone there, and
    `html:not([data-full])`'s `scroll-padding-top` keeps what is brought into view below it; the bar's
    `html[data-panel]` inset is below 1200 px alone;
  - the key's pill keeps its floor (`min-width` 172 px: − and + at 44, the key at three quarters of "Ab mixolydian"),
    and where a rail on either side leaves `.bar-in` (a container, `toolbar`) under 37.5 rem, the tools are their
    icons alone, their words visually hidden, still their names;
  - it never slides away (the scroll handlers slide the bar below 1200 px alone); while autoscroll counts down and runs
    it is `bar[data-asleep]` (`visibility: hidden`, its room kept: viewer.js `dock()`, harptab.js `showScroll()`, at
    every width, where below 1200 px viewer.js hides the bar and harptab.js slides it, harptab.js's `showScroll()`
    again as the window crosses 1200 px), and `edge()` writes `--toolbar-bottom` on `<html>`, only when it changes (on
    scroll, resize and full screen's coming and going too), which puts the pill under it;
  - a card or a numeral's tooltip goes above its chord only where it clears the toolbar while it is stuck to the
    window's top (`place()`, `placeTip()`: `barFoot()` the ceiling, else the window's top: a card may cover the unstuck
    toolbar's pills while it is open; the window's foot the floor, `barTop()`); `layout()` takes `--toolbar` off the
    window's room for columns (`toolbarRoom()`, none in full screen); full screen hides it as the bar
    (`data-controls`), its handle staying at the window's foot.
- **The song's end**: `.page`'s padding is the bar's room (`--foot`), which `layout()` measures columns against (from
  1200 px less the toolbar's at the top), and the pill's while it shows (`--pill`) below 1200 px alone: from 1200 px
  the pill sits under the toolbar, its room the toolbar's at the top (`room()`), and `html[data-pill]`'s `--pill` is
  0 there, so a song laid out again while it shows keeps its columns (test_viewer_layout.py); the half screen of
  over-scroll is `.page::after`, never in it, and print drops it.
- **The line being sung** (viewer.js `lightSung`, viewer.css `.l.sung`; test_viewer_sung_browser.py): while autoscroll
  is on, the line of `songLines` (the lines `pinyin` reads) that the data's `sung` names at the lyrics' clock:
  - `sungClock`, in ms (`at`, and `since`, null while it stands): `run()` starts it once the count-in is over
    (`goClock`), `standClock` stands it in `pauseScroll` and `countdown` (Scroll pressed again while it runs) and while
    the page is hidden, which draws no frames (`visibilitychange`; it goes on once shown, never while hidden), the line
    lit staying; `endScroll` puts it back at 0, none lit; the line lit is the last timed line's at or before it, none
    before the first, nor for one sung nowhere (null);
  - a tap on a timed line's words, never its chords (whose card opens), while autoscroll is on sets it at the line's
    first time (`timeOf`); a finger pauses the scroll as ever, a mouse click pauses nothing; the scroll's speed is its
    own;
  - a band behind the line, `--sung` (light `#fdf1e4`, dark `#2f2418`, in both dark copies), a box shadow past its
    edges, so nothing on the line moves and a Chinese line keeps its columns with pinyin; its words and chords 4.5:1
    on it; no transition; none on paper (`@media print`);
  - none without `sung` (no timed lyrics, too few lines met) nor in a songbook, whose data carries no lyrics.
- **No page takes a key** (the owner's choice of 2026-11-22, for Vimium: "Remove the keybindings that caracole takes
  entirely", D16 B's pedal map among them; test_viewer_keys.py, test_web_page_search.py's slash test,
  test_web_guitar_browser.py): no viewer page (a sheet, a version's, a songbook, a harmonica tab's), the library page or
  the Guitar Pro page binds a key on the document. Space, Enter, the page keys, the arrows and letters are the
  browser's (and Vimium's): a page turner's pedal scrolls the page as the browser does, a scroll by hand that pauses
  autoscroll (viewer.js's frame); Home and End pause it at once, their key still the browser's. Only caracole's own
  controls keep theirs: a focused chord's or hole's Space, a dialog's Escape and Tab, an open layer's or panel's
  Escape, a widget's arrows (the rail's tabs, a segmented control, the tablist), the search box's Enter, ↓ and Escape.
  screen.js `steer`: a pointer's press on the bar's `#scroll` or a pill button takes no focus (`pointerdown` and
  `mousedown` prevented, the click as ever), so that no button the bar hides holds the next key; `#scroll` gives the
  pill's `#go` the focus only when it had it as it was pressed (the keyboard's own press). A songbook goes from song to
  song by its pagers' and its contents' links and a swipe; no key changes the version.
- **Columns** (from 1100 px, on the screen alone, viewer.css; test_viewer_layout.py) only where the whole song shows
  that way, its end in the last column (`layout()`): the fewest that do, two to five (`MOST_COLUMNS`), each at least
  the song's widest line (`widest()`: each `.sec > .l` and `.tab` as wide as its content, `.sheet.measure`, after
  `fit()`) within `COLUMN_EM`, 16 em at least and 24 em asked at most (a song of long lines as before, the owner's
  narrower columns, D8), the owner's ask of 2026-11-18; at the reader's own text size, never a smaller one, spread
  across the window with 5 % of the room each side, the room over widening the columns (`column-count`), the gap
  narrower from three; `data-columns` says how many, which viewer.css keys on (`:not([data-columns="1"])` the wide
  page, a rule a count); else one column, `--fs` + 3 px, as a harmonica tab's page (no `data-columns`). A trial
  count's `fit()` runs in one column that wide (`fitIn`), never in balanced columns.
  - Autoscroll reads a song in columns in place (viewer.js `columnsEnd`, test_viewer_scroll.py's columns tests): each
    frame goes no further than brings `#sheet`'s top to the top of `toolbar.room()` (the key map's cap in columns),
    never back up, nor past the page's end; there it pauses "Paused · end of song", as one column does at the page's
    end (`moving()` false: the screen back to its minutes, the bar back, the loop stopped), at once for a song with no
    `sung`, else once the lyrics' clock passes `SUNG_END` (the last entry's time where it is `[ms, null]`, LRCLIB's
    empty stamp at the lyrics' end; else the last's and the timed lines' median gap, 3 s at least), running and
    lighting lines until then.
- **Full screen** (the sheet viewer's) is one of those layers, its element the handle (page.py `_HANDLE`,
  `button.handle#handle`, after the pill): `open(handle, opener)` sets `html[data-full="on"]`, which hides every
  element marked `data-controls` (the bar; a new control that full screen hides is marked so, nothing else changes),
  `.facts` and `.why` (viewer.css, the screen's alone), and `railOn()` and `drawNecks()` read it (the rail and the
  necks' sheet gone, the song in the width they leave):
  - opened by the settings' Hide controls (`_FULL_ROW`, `#full-open`, the first of `#places`) or a double tap beside
    the song: layers.js `doubleTap(root, skip, then)` (two clicks within `DOUBLE_MS` 350 ms and `DOUBLE_PX` 30 px,
    neither inside `skip` by the click's dispatched path, a keyboard's never) with `MARGIN_SKIP`, the song's own
    elements and the controls, which the harmonica page extends with its own (one selector, in layers.js);
  - closed by the handle, Escape or Back; a double tap while `data-full` is set does nothing; on a phone a layer opened
    over it takes its place (the controls back), from 900 px one opens over it; it pauses no scroll
    (test_viewer_full_screen.py).
- **The rail is sized** by viewer.css's `--nk` (1.15: the owner's 15 % over the first 300 px), its width, padding,
  text and targets alike.
- **Settings kept for every page at once**:
  - **The necks**: whether the rail shows (`state.necks`) is the one setting kept for every page at once:
    - localStorage `caracole-viewer-necks`;
    - and `necks=0` in the address, which book.js's `carryScreen` takes on to a songbook's next address, for its
      sandbox with no storage, as a link to another of the song's pages does (a version's in the list, a harmonica
      tab's and its ‹ back to the sheet, viewer.js `screenChoices`, the view's `carry`, harptab.js `backToSheet`);
    - with its Hide and the bar's button in step (test_viewer_necks.py).
  - **Pinyin**: so is the settings' Pinyin (`state.py`, off at first: localStorage `caracole-viewer-pinyin`, `py=1` in
    the address, which `carryScreen` takes on too), each Chinese character's reading over it, between its chord and
    it:
    - pinyin.py reads them at render time (pypinyin in context, a Traditional sheet in Simplified characters through
      normalize.py's table, its 著 as 着 but in a word Simplified writes with 著) into the data's `pinyin`, a reading
      per character of each `section.sec > p.l`;
    - viewer.js draws each as a `<ruby>`, its row of the line kept by every column, so a chord stays over its
      character's column, on or off, at 390 px too (test_viewer_pinyin.py).
  - **Chinese characters**: so are the settings' Chinese characters, Simplified or Traditional, a segmented control
    right above Pinyin, where Pinyin's row shows (`state.trad`, Simplified at first: localStorage
    `caracole-viewer-hanzi`, `trad=1` in the address, which `carryScreen` takes on too):
    - hanzi.py converts every text the sheet writes in its words (page.py `_written_texts`: its lines, the notes
      before the song and their peek, the sections' labels, its tabs) at render time with OpenCC, word by word (发 發
      or 髮), into the data's `hanzi`, `simplified` and `traditional` by the text;
    - a sheet is written in the script most of its own characters are, and shows as written in it: a Traditional
      sheet's Simplified is `tw2s`'s, a Simplified one's Traditional `s2tw`'s;
    - each a character for a character (one of another length made again a character at a time), which viewer.js cuts
      where the page cut the text, each reading over the character shown;
    - and the song's title, its artist's name and the page's title, each judged alone (`hanzi.names`), in a
      `song-names` block on a page whose sheet is Chinese (page.py `names_table`, `is_chinese`), each element that
      shows one marked with it as written (`zh_attr`, `data-zh`):
      - sheet.html's and a version's header;
      - a songbook's contents, pagers and headings (book.js draws them on its contents, viewer.js on a song);
      - a harmonica tab's page's heading (harptab.js reads the choice kept, no row);
      - the library page's lines and artist headers, by each card's `hanzi` (library_page.py, a song whose sheet's PDF
        record names its `script`: `render.chinese_songs`), library.js reading the choice kept
        (test_viewer_hanzi.py, test_library_page_hanzi.py).
  - **The Instrument**: so is the Instrument (`state.inst`, the guitar at first: localStorage
    `caracole-viewer-instrument`, `inst=` in the address while it is another, which `carryScreen` takes on too):
    - a songbook song's own version may name one, where it starts, and the songs after it on the player's (the one it
      came with, or the last chosen there by hand: book.js `player`), which never moves the song;
    - every instrument's shapes are instruments.py's, per root in the data's `voicings` (viewer.js looks them up);
    - one with no capo (the piano) names the chords as they sound (viewer.js `capoNow`, version.py `for_instrument`);
    - and the menu offers only what the page draws, an instrument of another kind once its script registers it
      (instruments.js documents that API);
    - test_viewer_instruments.py, test_viewer_instruments_page.py, test_viewer_sound.py.
  - **A numeral's tooltip**: so is the view of a numeral's tooltip (the chord's notes on a twelve-note circle,
    or tiles over a keyboard: localStorage `caracole-viewer-tipview`, the circle with none):
    - it draws only what `tones` (with each note's pitch class) and `keyScale` give;
    - a chord's card opens it too, by its chord, with the chords' names alone (its Circle & keyboard, viewer.js
      `tipDraws`): test_viewer_numerals.py.
  - **The theme**: so is Aa's theme, Auto, Light or Dark (screen.js, `html[data-theme]` `light` or `dark`, none
    for Auto, the system's; viewer.css's palette on screen, paper light):
    - localStorage `caracole-viewer-theme` (`auto`, `light`, `dark`), and `theme=` in the address while it isn't Auto,
      which `carryScreen` and `screenChoices` take on (`caracoleScreen.carry`);
    - applied by screen.js in the head, before the body is drawn (no other palette painted first on a slow phone), so
      a songbook's contents follow it too; Reset all leaves it;
    - the library page is not affected (test_viewer_theme.py).
  - **Keeping the screen on**: so, last, are the minutes the screen stays on after the last touch (D18 C), More's Keep
    the screen on (`#awake-row`: `#awake-down`, `#awake-at` "Off" or "10 min", `#awake-up`; Off to 60 by 5, 10 by
    default, `caracoleScreen.MINUTES`); the harmonica tab's page has no control and follows them:
    - localStorage `caracole-viewer-awake`, and `awake=` in the address while they aren't 10 (`awake=0` for Off), which
      `carryScreen` and `screenChoices` take on (`caracoleScreen.carry`); Reset all leaves them;
    - screen.js is the one place a page asks for a screen wake lock (`awake(moving)`, called by viewer.js and
      harptab.js with their `moving()`, unguarded; its `sync()` again wherever autoscroll starts, pauses or ends):
      wanted while the page shows and it moves by itself or the minutes haven't passed since the last `touchstart`,
      `pointerdown`, `keydown`, `wheel` or `scroll` (captured, passive) or the page shown again, `performance.now()`
      the one clock, one timeout for when they run out; asked again when the page shows again after the browser let
      go of it (its `release` event); `html[data-awake="1"]` while one is held;
    - never through `navigator.permissions.query`, whose answer Android's WebView gets wrong ("denied" while it grants
      the lock); a request refused is asked again at the next touch, key or wheel, never a scroll
      (test_viewer_awake.py, its fakes helpers/viewer_pages.py's `WAKE_LOCK`, `LONG_TIMERS`, `DENIED`).

#### `commands/`

- One module per area, each with `register(app)`, which `cli.build_app` finds by itself (A4: add a module, never edit
  cli.py).
- `_common.py` holds what they share (config, the database, the lock, clients at either pace, pages, `fail`, `warn`,
  `song_named`): use it rather than another copy.
- A command's logic lives in a module outside commands/, imported inside the command's function (Heavy imports,
  below):
  - get.py is `caracole get`, one song looked up now:
    - the run's steps for that song alone, sheet first, at the lookup pace;
    - then its `songbooks` stage: the songbooks of songbooks.toml that list the song, `songbook.songbooks_listing`,
      made again by `render_songbooks(only=…)`, then `write_pages` again once one was, as `caracole songbook render`
      writes the pages after;
    - `--progress`, a JSON line per event, for caracole serve.
  - versions_cmd.py is `caracole versions`: a song's UG chords versions listed from sheet_versions.py with no request.
    - `--keep`: one tab page at the lookup pace, `ug.fetch.keep_version`, noted as yours in
      `sheet_versions.kept_by_you`.
    - `--keep-more`: the versions `sheet_versions.may_keep` gives, kept so in rank order through one client until the
      lookup's budget or the hour's is spent, those it can't keep noted (`note_unkeepable`) and never read again.
    - `--choose`: get's `--tab`.
    - `--clear`: `overrides.remove_pin` then get.
  - harmonica_cmd.py is `caracole harmonica`: how each of a song's harmonica tabs is read and the readings weighed,
    with no lock.
    - `--as` and `--symbol`, `--clear`: `overrides.add_harmonica`, then the song rendered again, under the lock,
      waiting as a lookup does.
  - lacuerda_search.py is `caracole lacuerda --search`: LaCuerda's own search, one query, one request at the lookup
    pace.
  - ug/link.py is `caracole ug --link` (commands/ug.py): a UG page pasted, read at the lookup pace; ug/directory.py
    is `caracole ug --directory`: UG's artist directory, bulk work at the pace the owner chose for it.
  - youtube_sheet.py is `caracole youtube --sheet`: a song's auto sheet from a YouTube video now, at the bulk pace: a
    command, never a lookup.
  - audio_sheet.py is `caracole audio` (commands/audio.py): a song's auto sheet from an audio file the owner gives it,
    now; asked for now, never a lookup.
  - transcribe_job.py is `caracole transcribe` (commands/transcribe.py): a song's lyrics transcribed from its YouTube
    audio, its sheet made again; asked for now, never a lookup, and asking no site.
  - review.py, search.py, removal.py and songbook.py are `caracole review`, `search`, `remove` and `songbook`.

##### search.py

- search.py reads the local indexes alone, never a site:
  - UG's sitemap index and the artist pages caracole read (ug/artist_tabs.py);
  - gtptabs.com's, MuseScore's, LaCuerda's, harptabs.com's (its sitemap's and the artist pages read,
    harptabs_index.py) and gametabs.net's tables (its sitemaps' and the game pages read, gametabs_index.py);
  - iReal Pro's forum's charts of the thread pages read (`search_ireal`, ireal_index.py), a chart's title by one
    composer a hit, the composer its artist; and the threads its sitemaps name that caracole never read, by their
    names alone (`search_ireal_threads`, `ThreadHit`, the owner's rulings of 2026-11-18), a possible match:
    - a slug that begins with the query's key first, then, for a query of two words or more, one it ends (a
      composer's threads), then one that holds every word of it, each the oldest first, `THREAD_ROWS` (8) at most;
      a query of no word of three letters or more (an article aside: "1", "i", "so", "the") none, and one with a
      shorter word only those it begins;
    - a name once (by its slug's key), never a thread read (its charts stand for it), nor one a chart hit is again
      (`_charted`: its slug begins with the chart's title and the words after it hold its composer's: the Jazz 1460's
      standards; a composer spelled otherwise stays);
    - its by-line, after the query's words that begin it, the longest run of its last words that is an artist caracole
      knows (`_KnownArtists`: a composer of the charts read, by his words, even of one word; of two words or more,
      Ultimate Guitar's `ug_artists` or your library's), the words before it the title, less a last "by"
      ("misty-roses-tim-hardin" is Misty Roses by Tim Hardin); for a query that ends it, the query; none known, or the
      query in the middle, its words a title alone;
  - the tombstones of removed songs (`search_removed`: never `lead` or `best`, shown with the `caracole add` line that
    brings one back, and in `/api/search`'s `removed`, which the library page shows with Add again);
  - UG's artist directory (`directory_artists`, ug/directory.py's table): an artist the query names whole whose page
    caracole hasn't read and whom the index has no row of (`DirectoryHit`), `/api/search`'s `ug_directory` (with the
    requests reading their page takes at most and ug/link.py's state of it), a group on the library page whose tail,
    as "+ N more" is (library.js `tailOf`, `ugOffer`, never the heading), and a row on the lookup page, offer Read
    their page on UG, pressed by hand alone (rows.js `readArtistPage`'s `ugPage`: `POST /ug/link`);
  - the words of the UG index's artists' names (`ug_artists_fts` and its vocabulary `ug_artist_words`, schema 8, kept
    by triggers on `ug_index` and, schema 16, `ug_directory`, a key going with its last row):
    - an artist by a word of their name, `ArtistHit.part`, bounded by `WORD_LETTERS` and `WORD_ARTISTS` (LaCuerda's
      by `lacuerda_index.WORD_ARTISTS`), placed before a small namesake by `_with_parts`, leading by `_part_leads`
      and, against LaCuerda's, `lacuerda_leads`;
    - and `suggest_artists`, the artists spelled close to a query nothing matches well, UG's, LaCuerda's and
      harptabs.com's ranked together;
  - the words of every row of `ug_index` (`ug_index_fts`, schema 12, its content `ug_index`'s own, kept by triggers on
    `ug_index`) and of every key (`ug_key_words`, kept by a trigger on `ug_keys`, which only grows; read once a
    process, then only the words added since, `_Vocabulary`):
    - `suggest_titles`, the songs whose titles are spelled close to such a query, an artist's words beside them
      maybe, UG's, LaCuerda's and harptabs.com's, a song on several once, under its artist (`Suggestion.title`,
      `.hits`);
    - `suggestions` ranks both kinds together (a tab as `TAB_SONGS` of an artist's songs, `_cut`), `/api/search`'s
      `suggest` (a song's `title`, its row on each site, `song`, your song's row, `library`), the pages' "Did you
      mean".
- `gtptabs_songs` counts an artist's songs on gtptabs.com (an artist row's `gtptabs` in `/api/search`, the "Guitar
  Pro 12" of their header).
- `--progression` reads progressions.py's records alone, your songs only (`songs_with`).
- Its prefilter reads ug/key_search.py (`rows_like`: the keys' trigram index), which must find exactly what a `LIKE`
  scan of `ug_index` finds
  (`test_search.py::test_the_prefilter_finds_through_the_key_index_what_a_scan_of_every_row_finds`):
  - except that a pattern in more than `KEYS_PER_PATTERN` keys (a common word) brings in its shortest keys and those
    every pattern is in (`::test_a_common_word_brings_in_its_shortest_keys_and_those_every_word_is_in`).

#### `web/`

`caracole serve` (commands/serve.py).

##### Routes by area

- **guitar_routes.py** is the Guitar Pro page and alphaTab's bundle (alphatab.py):
  - the page: guitar_page.py, guitar.js, guitar.css: the tracks laid out, each muted on its own with
    `changeTrackMute`;
  - guitar.js `mend` patches alphaTab 1.8.4's canvas, which drew a part black when it began in the colour the last
    part ended in and cut the header's first line, so an alphaTab upgrade re-checks it: test_web_guitar_browser.py
    reads the header's pixels;
  - a song's kept Guitar Pro files are `inbox.guitar_files`, which library_page.py (`guitarPage`),
    songbook_section.py (a set list's `guitar`) and render.py (the viewer's `guitar`) read too.
- **youtube_routes.py** is `POST /youtube` (and the request form's YouTube video, `POST /request` with `youtube`): a
  song's auto sheet from the video pasted.
  - `caracole youtube --sheet --progress` queued under `jobs.YOUTUBE_SHEET` and the song's key (never joining its
    lookup), its stages its line's steps (status.py, outcome.py `YOUTUBE_STEPS`).
  - Offered only where `youtube_fetch.route_problem` says it can be made, the request form saying why not otherwise
    (library_page.py `server.youtube`, a card's `youtubeSheet`).
  - `POST /youtube/search`: a search's first video (`caracole youtube --search --progress`, `jobs.YOUTUBE_SEARCH`,
    among `INDEX_READS`), and `GET /youtube/thumb/`, its thumbnail.
  - `GET /api/youtube/video` and `POST /youtube/video`: a video pasted into the library page's search box
    (`caracole youtube --video --progress`).
- **transcribe_routes.py** is `POST /transcribe` (`song`, `identity`): a song's lyrics transcribed from its own
  audio, its auto sheet made again over them; and `GET /transcribe`, read-only, for the page's script alone
  (`script_only`, as /jobs.json): the served `server.transcribe` member as of now, `library_page.transcribe_member`,
  the one function the page is built with too.
  - `caracole transcribe --progress --song=…` queued under `jobs.TRANSCRIBE` and the song's key (`transcribe_steps`,
    titled "Lyrics from the audio: Artist - Title"), never joining its lookup nor a lookup it, one at a time a song
    (pressed again, the job waiting or running is the answer), and the queue's, never the lane's, so two songs' run
    one after the other; its view the song's (`kind` "song"), its stages its line's steps (status.py `STAGE_LINES`
    vocals and words, outcome.py `TRANSCRIBE_STEPS`), Ready once its chords stage made the sheet, as a YouTube
    sheet's.
  - Refused 409 where it can't run (`youtube_fetch.transcribe_reason`, "No lyrics transcribed here: …") and for a
    song not offered one (`transcript.why_not_offered`, in the command's words "… isn't offered a transcription: …").
  - `force=1` (Transcribe anyway) queues `--force`, refused as `why_not_offered(anyway=True)` says; `none=1` (Not
    sung: chords only) `--none`, titled "Not sung, chords only: Artist - Title", refused as
    `transcript.why_not_unsung` says ("… can't be said not sung: …"); both, 400.
  - Offered only on the served page, from served-only data: library_page.py `server.transcribe` (`transcribe_member`:
    `ok`, `why`, `songs`, `nothing` and `unsung` (Transcribe anyway, heard nothing or the owner's mark, its hint "You
    said it isn't sung.") and `transcribed` (Not sung: chords only), all four `transcript.offers` when `ok`, `time`
    `transcribe_time` when `ok`, else `[]` and `""`; the phone's LibraryPage.kt the same shape), the cards' own data
    unchanged (the phone writes the same cards, and its member says it can't); library.js `transcribeOffer` (and
    `overrideOffer`, Transcribe anyway or Not sung) on a card, and requests.js on the newest request that ended Ready of
    a song offered one (matched by `display`, the name a song's requests go by, none while a request of it waits or
    runs), through `caracoleLibrary`'s `offeredSong`, `transcribeHint` and `transcribing`; asked for, neither offers it
    while its request waits or runs.
  - Where `ok` is false, `transcribeOffer` is `heardElsewhere`: a song not ignored with an auto sheet (`auto`) and
    lyrics `missing` has one hint line, `p.hint.transcribe-elsewhere`, `why` as it is, no button; the phone's `why`
    (LibraryPage.kt `TRANSCRIBE_PROBLEM`) says where its words are heard: "No lyrics site has its words. The computer
    hears them from its own audio of this song." (test_web_page_transcribe.py, PhonePageDataTest).
  - Read again live, never left to a reload (library.js `readTranscriptions`, one GET at a time): once a song's job the
    page follows is over (`offerAfter`) or a request the Journal saw waiting or running is over
    (`caracoleLibrary.requestOver`), when the song is offered one of the four or may be (`mayBeOffered`: its card's
    lyrics `missing` and `youtubeSheet` or `auto`), and only where `server.transcribe.ok`; each song whose offer changed
    has its card made again where it was made (`cardAgain`, `refill`), and requests.js draws its answer again
    ("caracole:transcribe"). So a sheet from a video that found no lyrics offers it at once (the sheet's lyrics stage
    asks LRCLIB, Megalobiz and AZLyrics, each noting its miss), a transcription that failed on the GPU offers it again,
    and one made from a terminal meanwhile no more.
- **audio_routes.py** is an audio file uploaded from the library page, made into its song's auto sheet:
  - `POST /audio/upload?name=` (a `bytes` route, `audio_store.AUDIO_MAX`, 128 MiB, one body: the form token in its
    header, the cross-origin check, refused unread past it): the bytes staged (`audio_store.stage`, `named` the uploads
    the waiting and running jobs name, `jobs.uploads_named`, so a new one lets go of every other; `sweep` first), the
    answer its id, name (a name to show alone), size, format, length, tags, the song they name (`guess`,
    audio_sheet.py `names_of`) and the library's song of it (`song`: `has_sheet`, `sheet`, and `audio`, "purchase",
    "youtube", "upload" or null, so the dialog says what the file replaces; sent from a card with `song` and
    `identity`, that song, whatever the file names: 404 none, 409 another's identity, before anything is staged); each
    `AudioError` its status and words. A file staged and then not used (a refused Make sheet, a Cancel whose upload had
    already arrived, the page left) is let go by the next upload or the hour's sweep.
  - `POST /audio` (`upload`, and `song` with `identity`, or `artist` and `title`, written to wanted.txt first with the
    file's album and length): `caracole audio --progress --upload=<id> --song=…` queued under `jobs.AUDIO_SHEET` and the
    song's key (`audio_sheet_steps`, by the id, never a path), "Sheet from an audio file: Artist - Title", the queue's,
    never joining its lookup nor a lookup it; asked again while one waits or runs, that one is the answer and the
    second file is dropped; its view the song's, its steps outcome.py `AUDIO_STEPS`, Ready as a YouTube sheet's.
    Refused 409 ignored or with a human sheet (a purchase or YouTube's audio never: the owner's decision of
    2026-11-25), 400 or 404 an upload not staged.
  - `POST /audio/drop` (JSON `{"upload"}`): deleted now, 409 while a job names it.
  - 409 for the upload and Make sheet where this caracole makes no chords ("No sheets from audio files here: …",
    `audio_reason`).
  - Make sheet and a drop hold the store's lock (`audio_store.held`, an RLock) from what they read of the queue to what
    they change; an upload reads the file first and then the jobs' uploads under it (`stage`'s and `sweep`'s `named`, a
    function called under the lock), so an upload from another tab never lets go of a file Make sheet is queueing, and
    no route waits for another's file to be read
    (`test_web_audio.py::test_an_upload_from_another_tab_while_make_sheet_queues_never_lets_go_of_its_file`,
    `::test_an_upload_holds_the_store_only_to_read_the_jobs_uploads_and_let_go_of_the_others`).
  - The page's side (library.js `audioDialog`, `audioSheet`; filter.css): where library_page.py's `server.audio`
    (`audio_member`: `ok`, `why`, `limit`, `too_big` the route's words for a file past it; the phone's LibraryPage.kt
    the same from `Phone.audioProblem()`) says so, the bar's
    "+" (`#add-audio`, before Filter, and its hidden `#audio-file`, made by the script alone: none on the file, nor on
    a phone that makes none) and a file dropped on the Library while it shows open `dialog#audio-sheet` (a sheet from the bottom under
    720 px, sliding up there alone): XHR's upload, sent as `application/octet-stream` (a File's own type is refused
    415), its count `aria-hidden` beside the live region, which says only its start and its outcome; a file past
    `limit` refused unsent in `too_big`'s words; of several files the first, the dialog saying so; a file dropped on
    the open dialog a new choice; the guess in Artist and Title, the library's song and what the file replaces;
    Make sheet through `sendRequest`, the request form's own path (the line under the bar, `track`); Cancel or
    Escape `POST /audio/drop`. A card's Sheet from an audio file… (not ignored, no human sheet by its `files`, a
    purchase or YouTube's audio no matter: the cards' data unchanged) opens it for that song, its names not to edit,
    and posts its `songForm` in place (`song`, `identity`, `upload`; `form.audio-sheet`, a class the dialog shares,
    whose box filter.css gives `dialog.audio-sheet` alone), its upload sent with the song so the dialog says
    what that song's audio is; its transcription offers read again as after a YouTube sheet (`offerAfter`). The served
    page never lets a drop load another page (library.js `keepDrops`): a file dropped where nothing takes it, or a
    link or text outside a field, is taken and nothing done; into a field a drop is the browser's.
    test_web_page_audio.py.
- **ug_link_routes.py** is a UG link pasted into the library page's box: `GET /api/ug/link` (ug/link.py `known`, no
  request and no lock: its state, the tab's names, its artist's page, `guess`, the library's `song`, `hits` as
  /api/search's `index` items) and `POST /ug/link` (`caracole ug --link --progress` queued under `jobs.UG_LINK`, among
  `INDEX_READS`, its stages `UG_LINK_STAGES`, when the state is `auto`; 409 known, other or gone, 429 not now).
- **lyrics_routes.py** is a song's lyrics looked up under a name the owner types, for the card's panel (library.js
  `lyricsPanel`, below):
  `POST /lyrics/search` (`song`, `identity`, `artist`, `title`: `caracole lyrics --song --as` queued under
  `jobs.LYRICS_SEARCH`, the lane's, a lookup the owner presses, never sent by the page by itself; 202 `{job, url, as}`,
  `as` the name the command reads from the fields joined, lyrics_search.py `typed_name`, never the fields as typed;
  pressed again, the search on its way, its `as` that one and `said` naming it when another was typed), `GET
  /api/lyrics/search?song=` (no request, no lock, no write: `[lyrics]`' `as` and `picked`, `picked_why`
  (`transcript.picked_without_lyrics`), the audio's `length`, the kept search however old, `lyrics_search.last_search`,
  past its week the name and the day alone, no row, `line` None; the song's `lyrics` and, pending under its `as` with
  no record, `lyrics_note` ("Its lyrics are asked for again under “…”, tonight or at a lookup."); with `card=1` its
  card as `/jobs.json` gives one;
  its `as`, the `length` its rows were scored against, rows each with `far` (`lyrics_search.far`) and `facts` (its
  line as the command lists it, `row_facts`), `asked` (`asked_line`: the name it asked under and when), `said`, `state`,
  `instrumental`, `pickable`, `notes` (`lyrics_search.notes`, the command's lines of each site with no rows) and
  `line`, its last line's words, `lyrics_search.last_line`; and `picked_note`, the card's sentence of the record
  picked), `POST /lyrics/pick` (`record`, a row of the kept
  search within its week, 409 "Search again: …" else; its site on; `caracole lyrics --record --progress` under
  `jobs.LYRICS_PICK`; another record while a pick waits or runs refused 409 in words, never dropped) and `POST
  /lyrics/clear` (`caracole lyrics --clear` under `jobs.LYRICS_CLEAR`; 409 nothing to clear); each 404 no song, 409
  `same_song`, 409 ignored (test_web_lyrics_routes.py). The phone answers the four alike (server/routes'
  `LyricsRoutes`, vectors/web/lyrics_routes.jsonl, WebReplay.lyricsRoutes), its searches, picks and clears run by
  LyricsRunner.
  - The card's panel (library.js `lyricsPanel`, card.css `details.lyrics-search`) is served where the data's
    `server.lyricsSearch` is true (`WebControls.lyrics_search`, which library_routes.py sets; last in the member, the
    phone's LibraryPage.kt `true` at the same place; the cards' own data unchanged), for a song not ignored with no
    request of it waiting or running (`freeToAsk`): open in what needs you, before `transcribeOffer`, for a song with
    lyrics `missing` (the lyrics sites before Whisper), else folded right under the foot, a part of its own. Opened
    it reads the GET once; only its Search (or Enter in its fields) posts `/lyrics/search`, never the card opening,
    typing or a timer. The search, a job of no song's, is followed on `/api/jobs/N` (`followSearch`, kept by song id
    in `lyricsSearches`, so a card drawn again meanwhile follows it), its live line (`p.lyrics-said`, a status
    region kept in the accessibility tree while empty) "Asking LRCLIB, Megalobiz and AZLyrics under “…”…", then the
    GET read again and drawn with its words as given, none composed on the page but its controls' and the search's
    progress: `search.line`, `search.asked`, `picked_note`, `search.notes` (lyrics_search.py `notes`, the command's
    own lines) and each row's `facts`. Its form is the pasted
    link's (`.link-form`, `.f`), its rows the drawer's version rows (`ol.vrows`, `.vrow`, `.ver`, `.stars`, `.note`,
    `.vbtns`, `.inuse`, `.cur`), its notes `.hint` lines; a long list grows the card (from 1200 px the pane scrolls).
    A busy button is `aria-disabled` (`busyWith`), never `disabled`, so the focus a key gave it stays; a card drawn
    again while its panel held the focus gives it to the same control (`lyricsFocus`, `lyricsRefocus` in `refill`,
    for the line being drawn again alone: another song's touches no focus).
    Use these lyrics and Clear the pick post in place (`postHere`: the focus to the song's line, the panel hidden,
    the line following the job, a refusal said in the panel's line), and once that job is over the offers are read
    again (`lyricsJobs`, `readTranscriptions`). A search it followed over, it reads the GET with `card=1`: a song the
    search asked anew (its `lyrics` changed: missing, pending now) has its card drawn again (`songAgain`, as a job's
    view's card is, the focus kept by `refill`) and the offers read again, so Transcribe the lyrics goes with no
    reload. A search over 7 days old lists no rows, its asked line alone (test_web_page_lyrics_search.py).
- **offline_routes.py** is `GET /api/offline`, the manifest caracole's Android app copies the library by (read-only:
  each file the written index.html links to, as `WebApp._file` sends it now, its bytes' SHA-256 and its headers;
  test_web_offline.py).
- **peer_routes.py** is `GET /api/peer/state`, this library's units for another caracole to compare, with the schema
  its database is at (`schema`), what it agreed on with the asker and the answers its imports of the asker's files
  kept (`kept`), the settings a phone takes (`settings`, politeness.py) and the form token (no wider than a
  page's, which any client that reaches the server reads, for a sync's `POST /peer/pull`); `GET /api/peer/unit` and `/api/peer/file` (peer_sync.py, read-only, as
  `/api/offline` is); and `POST /peer/pull`, `caracole peer pull` queued as any change (test_web_peer.py).
  - A push, the phone's (peer_push.py): `POST /peer/push/new`, `/peer/push/file` and `/peer/push`, `json` and `bytes`
    routes with the form token in their header, then `caracole peer take --progress DIR` queued; `POST
    /peer/push/drop` (`{"push", "from"}`, the token in its header) deletes a push never sent, asked by the caracole
    that opened it, as a send is (`peer_push.drop`: 404 none, 409 once its document was taken, its take queued).
  - `GET /api/peer/index[?sites=]`: this library's site indexes as `caracole index export` writes them, a SQLite file
    streamed from a temporary export (`cache_dir/peer/`), one at a time.
  - `POST /peer/index/newer`: the part of them the phone doesn't hold (`index_transfer.export(have=)`), a `json`
    route (the form token, `HAVE_MAX` 1 MiB) that is a read: what the body says is data (`index_transfer.read_have`,
    400 in its words), compared with this side's records alone, nothing written but the temporary export, no lock;
    streamed as the whole is, one copy at a time. The phone asks it first (PeerClient.indexNewer, its document
    core.index.Have) and the whole on a 404 or 405 (an older computer) or a 413 (its document too large) alone,
    any other refusal (a 400 among them) its index stage's failure.
- **sync_routes.py** is the library page's Sync tab (its label Share; library_assets/sync.js, sync-tab.html,
  sync-panel.html), the sync redesign's §3.4.1:
  - `GET /api/sync`: this caracole, its `device` (`computer`, the phone's `phone`), its songs and songbooks counted;
  - `POST /sync/test`: one `GET /api/peer/state` of the other caracole, nothing written, its counts, newest index read
    and the last sync in words (`tested_words`), refused as a comparison is;
  - `POST /sync/compare`: one `GET /api/peer/state`, then a `GET /api/peer/unit` for each songbook that differs and
    the other has; compared with the kept answers (`peer_sync.merged_kept`), as `peer sync` compares; each
    difference's `names`, `change`, `part` and `with` (`peer_sync.names_of`, `change_of`, `part_of`,
    `listed_songs` of both sides' songbooks), `songbooks` (both documents of each that differs), `indexes` (the sites
    newer on either side; none with a caracole of another schema, `indexes_skipped` saying why, null else); kept 10
    minutes (`Compared`, its `found` for a Sync's scope: one kept without it has every conflict it proposes chosen
    first);
  - `GET /api/sync/unit` (script only): a kept comparison's unit, both documents, the other's asked now, an import's
    read from its staged file (`sync_file_routes.file_unit`, as the phone's `SyncEngine.documents` reads a file's);
  - `GET /api/sync/indexes`: each site's newest read and tabs (`index_transfer.newest`, `tab_counts`), which the
    phone, a client, reads;
  - `POST /sync/apply`: `parts` (`parts_of`; none sent, all three), a conflict of those parts (`peer_sync.in_scope`)
    with no side refused, then `caracole peer sync --push [--parts=…] --compared HASH --choose=…` queued, a job of
    kind `sync`.
  - The phone's server/routes/SyncRoutes.kt answers the six alike (SyncJson; vectors/web/sync_routes.jsonl, under
    UTC, which `WebReplay.syncRoutes` replays with the other side's `peer_units`), but its `device` `phone` and the
    computer's `kind` `computer`; `tested` is Settings' Test too, and `alone(address)` the unattended sync (the three
    parts, `Conflicts.LEAVE`, none queued while one with that address waits or runs).
- **sync_file_routes.py** is the sync's Export and Import a file: `GET /api/sync/sizes` (what an export would hold:
  the library's bytes, its songbooks, the indexes' bytes by SQLite's dbstat, `peer_file.indexes_size`, and their
  tabs), `POST /sync/export` (`peer_file.export_file` of the parts named into `cache_dir/peer/`, one at a time) and
  `GET /api/sync/export` (that file once, an attachment named `peer_file.file_name`, streamed); `POST
  /sync/import/open` and `/sync/import/part` (a file sent in parts, `json` and `bytes` routes with the form token in
  their header, staged by peer_import.py for `caracole peer import`), `POST /sync/import/compare` (the staged file
  read whole and compared as `caracole peer import` compares it, `sync_routes.comparison_answer`, kept as a
  `Compared` of source `import:<id>`, kind `file`, holding the file's parts; refused in peer_file.py's words and
  deleted) and `POST /sync/import/drop`.
  - `POST /sync/apply` on that comparison reads the staged file again (409 `STALE` once this library moved) and queues
    `caracole peer import --yes --progress [--parts=…] --compared HASH --choose=… -- FOLDER` under `import:<id>`, a
    job of kind `sync` (`status.PEER_KINDS`), "Sync with a file from <name>".
  - `caracole peer sync`'s index stage gives a site read more recently here through these routes
    (peer_import.py `Uploader`: open, parts, compare, apply of the indexes alone, then `peer_push.wait_for`), and
    takes one read more recently there (`peer_sync.Peer.index`, then `index_transfer.merge`), each counted for its
    report (`{"event": "report"}`, `jobs.Job.report`, `jobs_routes.peer_outcome`'s `report`).
  - The phone's SyncFileRoutes answers alike (vectors/web/sync_file_routes.jsonl, its routes' limits among them).

##### The router

- web/__init__.py names its parts, and web/app.py's docstring the modules of routes and the checks every request
  passes.
- app.py is the router and what every route shares (`Request`, `Response`, the answers' shapes, `WebApp.db()`,
  `.overrides()`, `.submit()`, `.queued()`).
- A route lives in its area's `*_routes.py`, as a `Route` in its `ROUTES`, which the router gathers from every such
  module, and a line of its docstring (test_web_app.py checks both): neither a new route nor a new module of them
  changes app.py.
- A route declares its body's kind and limit (`Route(..., body="form"|"json"|"bytes", limit=bytes)`): server.py asks
  `app.body_limit` before it reads a body (16 KiB for an unknown path); a `json` or `bytes` route needs the
  cross-origin check and the `X-Caracole-Form-Token` header, a form route its `csrf` field.
- A route refuses with `pages.Refused`, which `WebApp.handle` answers as the message page, or to the page's script as
  JSON: every refusal as data.

##### What keeps other sites out

- Every `/api/` read is refused to another site's fetch (`security.own_page_read`), and every write passes
  security.py's cross-origin check and carries the form token.
- **The one exception is Make this my version from Export PDF**, the owner's explicit choice:
  - `GET /export.pdf?…&mine=1` (export_routes.py), a plain link the sandboxed viewer follows, queues
    `caracole render --song --version --mine` with no form token and no cross-origin check.
  - A site could change a song's saved version with a link of its own; nothing is lost (Reset or another version
    undoes it), and the host-name check holds for it as for every request.
  - Widen it to nothing else without the owner (security.py,
    `test_web_export.py::test_mine_is_a_plain_link_with_no_token_but_the_host_check_still_holds`).
- There is no sign-in, by the owner's choice: no access token, no cookie, no secret; whoever can reach the server may
  use it, so it is for a network they trust (a LAN, a tailnet).
- What keeps other sites' pages out is the host-name check (DNS rebinding), the cross-origin check, the form token and
  `own_page_read`, with Referrer-Policy `same-origin` (header and every page's meta tag), so that a form a phone posts
  over plain HTTP carries its Origin (`test_web_server.py::test_a_phone_on_the_lan_cancels_a_request`).

##### Jobs and requests

- Beyond a wanted.txt line, every change runs as a `caracole` command queued in jobs.py (One caracole at a time,
  below): in the queue, one at a time, or in the lookups' lane (`jobs.lane_of`: a lookup, a pasted UG link,
  LaCuerda's search, an artist's page, a song's lyrics searched under a name, `lyrics --as`), up to `LANE` (3) at once
  on workers of their own (`caracole-lane-N`), started at once unless the song has a job in the queue. The queue's
  worker starts a job only while no lane job runs or waits, a lane worker the first lane job whose song has no job
  running (`JobQueue._take`, which `_next` wraps; `jobs.song_of_job`, Make this my version's and a harmonica reading's
  jobs the song's too, and a lyrics search's, `LYRICS_SEARCH`, no song's everywhere else, among `INDEX_READS`): a song
  never has two jobs running, a lyrics search, its pick (`LYRICS_PICK`, `lyrics --record --progress`, the queue's and
  the song's, `song_key_of`, joining no lookup), the pick taken back (`LYRICS_CLEAR`, `lyrics --clear`, the queue's and
  the song's, no stages) and its transcription never at once
  (`test_web_jobs.py::test_a_lyrics_search_and_a_pick_or_transcription_of_one_song_never_run_at_once`), and its own
  job keeps its order (`test_web_jobs.py::test_a_songs_own_job_keeps_its_order`,
  `::test_a_lookup_asked_while_the_songs_own_change_waits_or_runs_goes_into_the_queue_behind_it`). A queued one's
  line counts what it waits for (`jobs.ahead`: a lookup the lane's before it, any other every one before it and every
  lookup), and the Journal says its place among those queued in its own place, the queue's next "Queued · next,
  after the lookups" while a lane job runs or waits (feed.py `AFTER_LOOKUPS`), every running one under Now in the
  order they were asked (feed.py; test_web_feed.py); with no lane, as one queue, the phone's, to the byte.
- The one line a request shows is status.py's, read from the job's steps and the song's state, never from which
  commands ran: a step's label is that line while it runs ("Adding to the book…").
- The library page's Requests tab (its label Journal), its last, says that line its own way (outcome.py): `#tab=requests`,
  library_assets/requests.js, drawn from `/requests.json`: web/feed.py; no page of its own, every link and redirect to
  a request is `/#tab=requests&job=N`, status.py `details_href`.
  - Its finished requests keep their steps (feed.py `_finished`, `"steps"` right after `"reason"`): a lookup's, a
    sheet from a YouTube video's, a transcription's, a sheet from an audio file's or a lyrics pick's that started
    (`outcome.lists_steps`; the phone's
    `Outcomes.listsSteps`, whose `RequestsRoutes` hands `Feed.feed` their chips), never one cancelled before it ran
    nor a request of other commands.
  - The four staged jobs over one song (staged.py: a sheet from a YouTube video, `YOUTUBE_STEPS`; a transcription,
    `TRANSCRIBE_STEPS`; a sheet from an audio file, `AUDIO_STEPS`, the YouTube sheet's, its Audio step naming no site;
    a lyrics pick, `LYRICS_PICK_STEPS`, Song, Lyrics, Chords and PDF, its Lyrics step naming the record's site) share
    outcome.py's rules, each given its own stages (`_staged`, a `Staged`: its steps, the stage of its words that may
    wait, the stage whose words its Ready says, the chords or the pick's lyrics, and the step that names a site and
    which): `_staged_steps`, `_staged_holds` (Ready: what that stage says, the sheet's chords or the lyrics a pick took
    and what they replaced, or why its words wait; a YouTube sheet whose lyrics were done but whose heard words failed:
    "Chords only, no lyrics: the words couldn't be heard here (why)."; a YouTube sheet's one Words step is its vocals
    and words stages) and `_staged_stopped` (Not made yet, a pick's Not kept: the first stage after the song's that
    stopped it).
  - A lyrics search (`LYRICS_SEARCH`, no stages) says its step's label while it runs, then its last line's words as
    LaCuerda's search's (`_artist_read`: Searched, Nothing found, Not searched with Try again; cut at its first "; "
    or " (" outside a “quoted” name, `_cut`, Status.kt's `cut`, so "(Live)" in the name is said whole); a lyrics pick
    (`LYRICS_PICK`) is Ready once its lyrics stage kept them, its chords skipped but for no new lyrics said after what
    it took ("… No audio to make an auto sheet from."), else Not kept: a wait or an error with Try again, a record
    gone (`lyrics_pick.NO_LYRICS_NOW`, status.py `record_gone`) missing with none; failed after the keep it says so in
    the command's last line ("Lyrics kept; the job failed after: …", `lyrics_pick.KEPT_FAILED_AFTER`, status.py
    `_kept_failed`), and interrupted after it "Lyrics kept." before the stop; that pick taken back (`LYRICS_CLEAR`, no
    stages) says its step's label while it runs, then its command's one line ("Cleared the record you picked for …",
    `lyrics_pick.CLEARED`, status.py `cleared`; outcome Cleared and the rest of it), and for a song with no record
    picked "Nothing to clear: …" (`lyrics_pick.NOTHING_TO_CLEAR`), an answer, never a failure; Status.kt and
    Outcomes.kt alike.
- The library page's lines read only its steps (`outcome.progress`: while a lookup runs, once it has run a second
  (`BAR_AFTER`), its line, a song's or a result's row, is a bar of them, library.js `showLine`'s `barred`: a segment
  a step, `segsOf`, then the step in hand, its site and `count`, `stepWords`, "Sheet · Ultimate Guitar · 3 of 7",
  what a screen reader hears; while a nightly run holds the book, the view's `waits`, "Waiting for the book · 1 of
  7", that step drawn waiting, `waitsIn`; ended otherwise than Ready, its words, and under them that bar frozen,
  `drawSteps`' `.step-bar`, a picture for a screen reader, named by every step and its state; and the list of the
  steps, `stepList`, also `window.caracoleLibrary.stepList`, the one function that draws one (a line a step: its
  mark, name, site and what it found; once over, the skipped ones folded into one last line), shown in the frozen
  bar's place while the song's card is open, following a running lookup under its bar), never the rest: a finished
  one's outcome, a reason from its stages and its song's state (never made up: Not on the sites says UG has no
  chords only once the fetch asked it, `SongFacts.asked_ug`), and its next step.
  - Its steps are every one the lookup has from its start, a step whose every stage ended skipped kept in its place
    (`skipped`), so the total only rises; a sync's, a take's and a request of commands still leave a skipped one out.
  - `at` and `count` ("3 of 7") are the step in hand (`outcome._in_hand`): while it runs the running step, else the
    first waiting, else the last; once over the first that failed, else none; the bar shows them while the request
    runs, and the frozen bar once it is over. `doing`, right after them, while that step's running stage is a long
    one that says what it does (status.py `LONG_STAGES`, `doing`: a YouTube sheet's audio and chords, a
    transcription's vocals, words and chords; the number first, nothing the step's name says, "1:20 of 3:45", "~12
    min", "2 of ~12 min"), which `stepWords` says after the count (`.step-doing`, in the room the step and its place
    leave, `flex: 1 1 0`; under 400 px its bar's place a screen reader's alone, `.step-count` clipped, and its own
    " · " left out, `.step-sep`, so 320 px shows it whole; for the eye alone, `aria-hidden`, changed in place on the
    same bar, `sayDoing`, so the line's live region never reads each of Whisper's windows). status.py's line says
    every long stage's words after its own ("Transcribing the lyrics · 1:20 of 3:45…"), a sync's or an import's
    `index`, the phone's `mirror`, an index `merge` and a take's or an import's `render` too, which have no bar,
    their line the Journal's and the tray's ("Making pages of what was taken · 12 of 20 songs…"); the phone's
    `Status.LONG_STAGES` and `Outcomes.progress` alike. `waits`, true, while that step's running stage waits for the
    book (`outcome._waits_for_the_book`: its detail begins as status.py's `_WAITING`, the test `_stage_line` makes
    for "Waiting for the book…"; the phone's `Outcomes.waitsForTheBook`, by the same rule though it takes no lock).
  - Each step (`outcome.Chip`, `{name, site, state, found}`) names its site in full (`site`, `outcome.SITE_NAMES`
    of its tag: "Ultimate Guitar", "LaCuerda", "YouTube"; a tag it lacks as it is) and what it found (`found`,
    `outcome._found`: its stages done in their words, one failed in the outcome's words where they parse, else in
    its own, joined by " · "; nothing for a plain, a skipped or a waiting step, nor from a stage the server cut
    off, whose words are what it said while it ran); a sync's, a take's and a command's step has neither.
  - Nothing for a request's first second (`outcome.BAR_AFTER`, decided by the server, so a reload agrees): no steps
    until it has run one at the view's `now` (one a `/jobs.json` answer, `jobs_routes.views`, the phone's
    `JobsRoutes`), and none ever for one over within it, frozen or not.
- Cancel takes a request that hasn't started out of the queue (`JobQueue.cancel`, a lookup waiting for a slot in the
  lane among them, never one that runs, with the jobs `submit_all` queued `together` with it), keeping it in the
  history as over ("cancelled"), so a page that follows it hears it ended.
- Try again queues a finished one's steps again (a removal's asks its question again).
- **A sandboxed viewer reaches a form** only through a GET page of the server's own, whose form posts with the token:
  - `/versions` (versions_routes.py: Make this the one, Keep and Back to our pick,
    `caracole versions --choose`, `--keep` and `--clear`, with `--progress`: the job's stages, a lookup's for
    `--choose` and `--clear`, which run `caracole get`), each a job under the song's key, which jobs.py's `_pick` joins
    as a lookup's `--tab`;
  - and `/harmonica` (harmonica_routes.py: a harmonica tab's readings, each pinned, or Back to our guess,
    `caracole harmonica --as` or `--clear`), linked from the tab's page by harptab.js when served, each job under
    `jobs.READING`, the song's change as Make this my version's `EXPORTING` is (status.py, jobs_routes.py).
- What a done job came to is read from the song's state and overrides.toml again (`caracole get` exits 0 on a block or
  a spent budget, the sheet unchanged).
- **Its Export PDF is no page**: `GET /export.pdf` (export_routes.py) renders the version in this process (render.py
  `version_pdf`, in a private folder under the cache) and answers it as an attachment, writing nothing into the
  library and recording nothing, with no lock and no queue.
  - With `mine=1` (the exception above) it queues Make this my version too, under the song's key (`jobs.EXPORTING`,
    `jobs.MINE`).
  - The viewer's Export PDF is a link to it, which its sandbox may download (`viewer_csp`: `allow-downloads`, nothing
    else added), the page staying where it is.
  - On a version whose music differs from the song's own (key, mode, capo, swaps, shapes: viewer.js `musicOf`; never
    a reading setting nor the instrument, the player's), a modal dialog asks first, Make mine
    (`mine=1`), Download only or Cancel (test_viewer_panels.py, test_web_server.py's download in the real sandbox).

#### `autochords/`

- merge.py is pure Python and the only module `__init__.py` imports.
- sheet_lyrics.py, no model either (render.py imports it, in any package), puts lyrics that came after a sheet of none
  on it, `render_all` first thing, so every path to a page gives it them (`merge.with_plain_lyrics`, a version's
  `raw["lyrics"]` then "plain", and `raw["lyrics_key"]` their words' `lyrics_key`, sheet.py's, which it re-exports),
  for a sheet without `heard`; then re-lays one that keeps it over its words (`relay_onto_sheets`, below).
- sheet.py, no model and no audio reader either (no music.py, mutagen, torch or numpy; the lyrics module only inside
  a function: `test_the_sheet_half_reads_no_audio_file`), is the sheet half: `Heard(segments, beats, downbeats,
  duration)`, what run.py's `_hear` gives (the models' chords and beats, and `music.read_audio(audio).duration_s`, the
  one length the sheet is laid out against); `make_sheet(song, heard, *, source, transcript, silent, said) -> Made`,
  `synced_for(song, lyrics, heard) -> Timed | None` (`Timed.note`), `raw_of(song, made, *, video, maker)`, the
  version's raw; `synced_key`, `song_lyrics_key`, `lyrics_key` and `wider_lines`, what that raw keeps of the song's
  lyrics. Since E12 the raw also keeps what was heard and who made it from what (the design's §4.4), after its other
  members: `heard`, `heard_record(made.heard)` (`{"contract": CONTRACT, "duration", "chords": [[start, end, label],
  …], "beats", "downbeats"}`, floats as the models gave them, the labels the common names `make_sheet` takes, about
  19 KB for a dense ten minutes), which `heard_of(raw)` gives back (`read_heard`, strict: numbers never bools or
  texts, chords `[number, number, text]`, else ValueError) so that `make_sheet` lays out the very bytes again with no
  model (`test_a_sheet_laid_out_again_from_what_its_raw_kept_is_the_same_bytes`); and a `Maker`'s `made_on`
  ("computer", run.py `MADE_ON`), `made_by` (kv `sync:id`, peer_sync.py `own_id`), `models` (`chords`, `beats`:
  btc.py's and beats.py's `model_name(path)`, `name@<sha16 of the file>`, hashed once a process, no folder),
  `runtime` (the recognizer's, "torch 2.13.0"), `audio_name` (a purchase's file name; a file you gave's as it was
  given, audio_store.py's kv `audio:name:`, none for one kept before that record; none for YouTube's audio) and
  `audio_sha16` (audio.py `sha16`, read in 1 MiB blocks once a hearing: about 0.05 s for 70 MB), each where known (a
  fake recognizer names no model). The new members hold no path and no clock; the raw's older `audio` and the
  version's `url` still hold the audio's path, as before. A sheet without them (made before E12) is never due for
  that alone.
  run.py keeps the hearing half: the models, `on_step`, the words' hearing, `_skip_reason`, `_keep` (into the song's
  one auto version, versions.py `auto_version_of`, whoever made it: one taken at a sync keeps the other caracole's
  tab id, else the song's id; a second one no kept file names, from before E12, let go of with a warning,
  `auto_versions_beside`), and calls remeasure.py's `remeasure_once`; the models failing on the audio is the file's
  (`_unreadable`), the length's read after them failing caracole's (`_LengthUnread`, `_error`: the song still due,
  nothing filed against its audio).
  test_autochords_sheet.py pins what each kind of sheet made before the two halves were parted, by the bulk pass and
  a staged job's chords stage, a file that names no length among them.
- btc.py (with the vendored btc_model.py and LICENSE-BTC) and beats.py need torch, librosa and beat_this; run.py runs
  them over the library (`autochords_pending`), logging each song it works on and its place among those due
  ("Working out the chords of A - T (3 of 12)…", `_count_due`), and telling `on_step` each step (`STEPS`: the models
  set up, a song's chords, beats and sheet, then a song's vocals and words), which a staged job's chords stage says.
  - Before a song's chords, `autochords_pending(hearing=, transcriptions=)` hears its words (hearing.py, `_Listening`):
    up to `transcriptions` songs a run (`[autochords] transcribe_per_run`, 3; the command passes 0 with `transcribe`
    off), newest first, each one `why_not_offered` offers (the lyrics sites asked first, in the nightly run's own
    steps); its vocals, a waiting lookup let go first (`_Turns.hand_over`, the same `between` as between two songs),
    the song read again and still offered with the audio separated, then its words, a transcript or nothing sung
    making its sheet due (`_skip_reason`). A song past the cap gets its chords now, its words a later run.
  - In bulk: the setup's failure stops the hearing for the run, kept as `AutoStats.transcribe_problem`, the chords
    going on and the command exiting 0 on its account, and is noted against that audio (`note_hearing_failed`, kv
    `transcribe:failed:`, in `songs._PER_SONG_KV` and SongKv.kt: path, mtime, when, the words), so the next nights
    pass over the song (`hearing_failed`, `_Listening.first`, `_count_due`; no slot, no separation) until its audio
    changes or `transcript.RETRY_DAYS` (30) go by, todo.py listing it; by hand it stays offered, and any hearing that
    comes to something (a transcript, nothing sung, Whisper's refusal) drops the note; after the words a waiting
    lookup goes first before the chords (`turns.hand_over`), the song read again; audio Whisper can't load (the vocals
    read it with auto-chords' own reader) noted as Whisper's alone, its chords made tonight, never heard again (no
    separation, no slot) until it changes, todo.py listing it under the words not heard, never the files auto-chords
    can't read; a bug one of the run's `errors` (exit 1), logged with its traceback, its chords made all the same
    (`_hearing_bug`). The cap counts the songs whose hearing started; `_count_due` counts as due the first
    `transcriptions` songs offered their words. kv
    `autochords:status` keeps `heard`, `silent` and `transcribe_problem`, which todo.py says ("Lyrics that couldn't
    be transcribed", with the songs whose audio Whisper can't load while that alone keeps their words unheard).
  - The command builds no `Hearing` where `youtube_fetch.transcribe_problem` says this machine can't transcribe;
    the pass then says why once a song waits for its words. The owner's decision of 2026-11-25: the nightly unit
    gets no GPU (nix/module.nix), so with the CUDA build it hears no words (its wgpu separator has no adapter), the
    to-do page says so, and the words come from caracole serve's jobs; with the CPU build it hears them on the CPU,
    about 7 times a song's length each.
- audio.py, `load_mono`: every model's audio, mono at a rate, through librosa (libsndfile: WAV, FLAC, Ogg, MP3), else
  torchaudio (FFmpeg, through torchcodec) for the AAC of an .m4a, as YouTube's audio always is (youtube.py) and an
  iTunes purchase, and for an MP3 whose first frame names no length where libsndfile's decode is more than
  `DISAGREES_S` (0.5 s) off its frames' length (`mpeg_frames.counted_length`; libsndfile stops at its guess, the size
  over the first frame's bitrate, with no error), a WARNING naming the file (the journal keeps it at the default
  verbosity; such a file is rare and worth seeing), and should FFmpeg then fail, libsndfile's part kept with a
  WARNING of how much of the file it is, as before the fix: every other file read as libsndfile reads it;
  btc.py `load_audio` and separate.py `frame_db` both read through it (beat_this its own loader, FFmpeg's first,
  beats.py: one loader for both is not built, as it would move every file's beat samples), and `load_librosa` gives
  numba a cache folder first (a hardened unit has no writable home).
- remeasure.py, `remeasure_once`, at `autochords_pending(remeasure=True)`'s start (the bulk `caracole autochords`
  over every song, never a staged job about one song, nor `--song`), once ever (kv `autochords:remeasured`): every
  song with no human sheet, not ignored, whose MP3 names no length and whose guess (`mpeg_frames.Count`'s `guessed`)
  is `DISAGREES_S` off its frames' length: its auto sheet made due again (`autochords_mtime` cleared); read short, its
  transcript (`transcript:`) and caracole's nothing-sung verdict (`transcribe:none:` by "caracole") dropped, heard
  from a cut-short mix, so it is offered its words again, the owner's not-sung (`by` "you"), `transcribe:failed:`
  (its setup's) and `transcribe:unreadable:` (Whisper's own, whole read) kept; where its wanted.txt line is exactly as
  caracole writes one with the guess (`wanted.retime_wanted`), the line and its record corrected and, its lyrics
  missing, LRCLIB and Megalobiz asked again (`lyrics_at` cleared, `megalobiz:checked:` dropped). Each such song a
  WARNING, the run's `AutoStats.remeasured` (its summary's "remeasured N whose MP3 names no length, made again: …")
  and kv `autochords:status`'s `remeasured`, which todo.py lists under "Made again: MP3s that name no length" for that
  run alone.
- align.py, pure Python too, is run.py's: how far to shift timed lyrics LRCLIB timed for audio of another length, from
  the chords and beats alone:
  - `lyrics_offset`: candidate shifts scored, the best taken only by a clear margin, else the plain lyrics as before;
  - `shifted_lrc` moves line and word stamps alike, so word-timed lines keep their words;
  - the shift said on a line of the sheet's after the song's name, after the video's credit for audio from YouTube,
    and kept as `raw["lyrics_shift"]`.
- A song's lyrics transcribed from its own audio, which hearing.py composes from, for transcribe_job.py:
  - words.py, pure Python: where someone sings, from the stem's loudness against the mix's (`sung_spans`); the words
    outside it dropped (`guard`); nothing sung (`too_little_sung`: under `MIN_SUNG_S`, 10 s; `too_few_words`: under
    `MIN_WORDS`, 8, or `MIN_WORDS_A_MINUTE`, 20, each with its why, "sung 6.2 s", "5 words in 1:10 sung"); the lines
    (`lines_of`) and the enhanced LRC (`to_lrc`);
  - transcript.py, no third-party import (every page build asks it): kv `transcript:<id>` and `transcribe:none:<id>`
    (`keep_transcript`, `note_heard_nothing`, its `why` and `by`), `transcribe:unreadable:<id>` (`WHISPER_CANT_READ`,
    `note_whisper_cant_read`: audio Whisper can't load, which auto-chords reads; of the current audio alone), and which
    songs are offered one (`why_not_offered`, which also reads run.py's `autochords:failed:<id>`, its key
    `UNREADABLE`; "Whisper can't read its audio" for the second, `anyway` or not; a song with a `[lyrics]` record and
    no lyrics never, `anyway` or not, after a human sheet and before its lyrics' status, by the record alone and no
    `checked:` kv: `picked_without_lyrics`, `PICKED_NONE` "the record you picked (lrclib 9) has given no lyrics: pick
    another, or clear the pick" while missing, true whether its site answered it a miss or a record written by hand on
    a song missing under its own name waits its 30 days, `PICKED_UNREAD` while it is pending, the owner's rule of the
    databases first, as one record of one site is all that is asked; Not sung: chords only, which runs no Whisper, as
    before it, `why_not_unsung` and `offers`' `transcribed` weighing no record, `without_picks`). Its four records of
    a song's audio (`RECORDS`: the transcript, nothing sung, Whisper's refusal, a failed hearing) are "of its audio" by
    one rule, `of_audio`, the owner's "yes" of 2026-11-27 (a file moved, renamed or touched keeps what was heard of
    it): its path and mtime the song's, else the same bytes by its content key (`audio_key`: `audio_size`, and
    `audio_sha256`, a given file's 16 hex digits from its kept name, audio_store.py `given_sha16`, no read; any other
    file's SHA-256, read only once the sizes agree, once a process while its stat stays, `_HASHED`; written only while
    the file's mtime is the one the record names, so a file changed during a hearing, or replaced since the song's
    row was read, keys nothing); one with no key (kept before keys were) other audio once path or mtime differ; a read
    that fails no verdict, nothing kept; a page build after a bulk move or touch between scans reads each such file
    once a process. A read answers so and writes nothing (a page build,
    `search`, the to-do page); `follow_audio`, where a write is allowed, re-points such a record (its path and mtime
    the song's) and keys an unkeyed one of the song's path and mtime: music.py `scan_music` right after it links a
    song's file again, and the nightly pass (`autochords_pending`) before each song. auto-chords' own
    `autochords:failed:` stays by path and mtime (run.py drops it once the file changes: a moved file is tried once
    more). A move rewrites no auto sheet's raw (its `audio` and the version's `file://` URL name the old path until
    the sheet is made or re-laid again): `audio_path` is no column of a song unit (peer_sync.py `SONG_COLUMNS`), so a
    move alone changes no digest; a rename keeps the mtime (`autochords_mtime` still its audio's: not due), a touch
    makes the sheet the models' again (its transcript, by content, used: no Whisper). The phone's Relay reads the
    path and mtime, else a given file's name against the key, never a purchase's bytes: it keeps none of these records
    of its own;
  - separate.py: demucs-rs, a program run as a subprocess (`DemucsSeparator`; `SeparatorFailed` in its own words,
    its output read as UTF-8 with what isn't replaced; a wgpu demucs-rs that dies by a signal after "Done!" with the
    stem written, as it does from Python, has separated it, logged; on success, what it said of its device logged
    at INFO, as it names no adapter: its GPU shaders, NVIDIA's "NVVM" line), and
    each frame's loudness (`frame_db`, audio.py's `load_mono` and librosa imported inside);
  - transcribe.py: Whisper large-v3 (`WhisperTranscriber`), torch and whisper imported inside, after `os.environ`
    gets Triton's cache (`TRITON_CACHE_DIR`) and, where NixOS has the driver's libcuda, `LIBRARY_PATH` for the linker
    of Triton's kernels (nixpkgs' Triton names no libcuda folder: Whisper's word timing would try to build them on
    every 30 s, fail, and fall back); that fallback's warnings (`TRITON_FALLBACK`, twice a window where no C
    compiler builds them, as in caracole-web's unit) kept back from the request's Output and said once at INFO;
    `SetupFailed`, the GPU's (`is_setup_error`: out of memory, CUDA, cuDNN, device-side; at load as while hearing)
    or the model's ("Whisper's model won't load": any other load failure, on the GPU too), never the audio's;
    `is_audio_error`, Whisper failing to load the audio.
  - hearing.py, the one place both models run, no third-party import at its top and no job's stages
    (`Hearing(cfg, separator=, transcriber=)`, for a job of stages, transcribe_job.py's `HearsWords`, or a pass alike):
    `vocals(song, on_doing=)`, the mix's loudness, the stem, the sung spans (`Vocals`); `words(conn, song, vocals,
    stamp, on_doing=, anyway=)`, words.py's rule applied (Whisper not run under `MIN_SUNG_S`; nothing kept on too
    few words), the transcript kept (`Kept`) or nothing sung noted with why, by "caracole" (`Nothing`); `anyway`
    skips both rules, Whisper run whatever the spans, its words kept within them, or all of them with no span (the
    whole song one), only no word at all nothing sung; `close`. `words` refuses (ValueError, in its own words,
    before Whisper runs) vocals that aren't this Hearing's current stem of the song's audio as it is now: another
    song's, of audio replaced since, or a stem the next song's separation removed (`_current`).
  - It works in a `transcribe-*` folder under the cache (`WORK_PREFIX`), one song's stem at a time, gone with
    `close`; one a killed job left is swept at the next job's start (`sweep`: a folder no live Hearing holds
    (`_held`), its `OWNER`, `.owner`, flocked while it lives, as another transcription asked for now may take the lock
    while this one lets the lookups have it).
  - It builds the default separator and Whisper once a Hearing, at their first use, Whisper run first on run.py's
    test tone (`_test_tone`); demucs-rs not (it fails on the song as on a tone, the setup's alike, and each run costs
    about 30 s). Its failures are `HearingFailed(kind, words)`, told apart as run.py's: the setup's and the audio's.
    The setup's (`"setup"`) record nothing against the song, which stays offered: `frame_db` failing on the mix,
    whatever it raises ("can't measure the audio here (…)": a reader's failure is no proof the audio is bad),
    `SeparatorFailed`, a stem `frame_db` can't read or one more than `SHORT_STEM_FRAMES` (4, 0.2 s) shorter than the
    mix ("the separator can't run here (…)"), and `SetupFailed`. The audio's (`"audio"`, "Whisper can't read the
    audio") is Whisper's own "Failed to load audio" on the mix alone (transcribe.py `is_audio_error`), noted as
    Whisper's alone (`note_whisper_cant_read`, kv `transcribe:unreadable:`), whichever job or pass heard it, never
    filed against the chords, as Whisper reads through the ffmpeg program and auto-chords through its own reader,
    which says; `why_not_offered` reads it ("Whisper can't read its audio", after a site's lyrics, ignored and a human
    sheet, which come first) until the audio changes, or by hand (`anyway`, `caracole transcribe --force`, after an
    ffmpeg or Whisper upgrade), a refusal adding what to do (`refused_for`, `WHISPER_UNREADABLE_DO`);
    anything else Whisper raises is a bug, raised as it is, filing nothing; and nothing sung is noted.
- Which words go under the chords (sheet.py `make_sheet`): a site's lyrics whenever the song has any (a site's
  verdict that it is instrumental wins too: a chart alone, the transcript kept unused), else the
  transcript of its current audio (transcript.py `transcript_of`: of its own audio by `of_audio`, its path and mtime
  or, moved, its bytes), else none.
  - A transcript is used as timed lyrics whose duration is the audio's: no `synced_for`, no shift searched. The sheet
    says `transcript.NOTE` after the credit and the shift's line.
  - The version's `raw` gets `lyrics_source` "transcript", `transcript` (the LRC) and `transcript_made_at`, and none of
    the three otherwise; `raw["lyrics"]` stays "synced".
  - A sheet over the song's own lyrics (synced or plain, no transcript) keeps `raw["lyrics_key"]`, 16 hex digits of
    the SHA-256 of their plain text, its lines stripped and its blank runs folded (sheet.py `lyrics_key`,
    `song_lyrics_key`): `_skip_reason` makes it due again once the song's are other words; one with no key (made before
    it) never for that.
  - `_skip_reason` makes the song due again when such a sheet finds a site's lyrics or an instrumental verdict, or finds the kept transcript's
    `made_at` is not its own (other audio, or transcribed again), and when a sheet of none finds a transcript (not for an instrumental song).
  - youtube_sheet.py's `holds` says "chords over the transcribed lyrics" for it.
  - Those are a sheet's that keeps no `heard` alone (made before E12: the models', the design's R4). Since E13 (R2) a
    sheet that keeps it is never due for its words: `_skip_reason` says `RELAID` while they changed, else "up to date";
    other audio than it was heard from (`_skip_reason`'s new audio, checked first) or a sheet gone makes it the
    models' again, words or not. It is re-laid only where `sheet.relays_here(song)`: heard from the audio this side
    holds now (`autochords_mtime` its `audio_mtime`, never the path), or this side holds none (`audio_path` empty: a
    sheet taken from another caracole). Its words re-lay it with no model and no audio:
    sheet.py `relay_due(song, raw, noted=None)`, those same reasons moved as they were, plus a sheet over a site's
    words (keyed) whose song has none now or is instrumental (what a pick taken back made due by clearing
    `autochords_mtime`); `relay(song, raw, noted=None) -> Made`, `make_sheet` over `read_heard(raw["heard"])`, the
    video `raw["youtube"]` names and `noted` (`Noted`: transcript, silent, said; by default `noted_in(raw)`, what it was
    laid with), `Made.kept` the raw's `RELAY_KEEPS` (`audio`, `youtube`, `made_on`, `made_by`, `models`, `runtime`,
    `audio_name`, `audio_sha16`) that `raw_of` writes in their places, so the raw is a fresh hearing's but for those
    (`test_a_re_lay_is_the_sheet_the_models_would_have_made`), a pure function: no clock, no kv, no machine
    (`test_two_caracoles_re_lay_the_same_sheet_over_the_same_words_alike`). sheet_lyrics.py: `noted_of(conn, song,
    raw)`, this caracole's kv (`transcript_of`, `heard_nothing`, `said_not_sung`) only where the song has audio here
    and `relays_here` (a file moved and relinked with its mtime is the same audio), else `noted_in`; `relay_reason`,
    None for a sheet without `heard`, for one heard from other audio (`relays_here`), and for one whose `heard`
    `read_heard` refuses (a newer contract, a damaged record:
    neither re-laid nor due, a WARNING once a process by song and reason, only where a re-lay was otherwise due);
    `relay_onto_sheets(conn, cfg, overrides=None, only=None, *, between=None) -> list[Song]`, `render_all`'s second
    step after `lyrics_onto_sheets` (which now takes only sheets without `heard`: none handled by both): one query
    over the kept auto versions whose raw has `heard` (of `only`'s ids in the SQL), no file read, each candidate read
    as it is before its re-lay
    (`between` two, overrides.toml read again after a hand-over), not ignored, no human sheet; `set_raw` and
    `keep_file` in one savepoint, info.json after (its failure said as its own, the sheet re-laid all the same); one
    that can't be laid or written logged, the others go on, never a miss, a bug one of `errors=` (the nightly pass's
    `stats.errors`, exit 1); the version's row (`tab_id`, `url`, `fetched_at`) untouched. `autochords_pending`'s
    `_due` re-lays a `RELAID` song itself (its words heard that night, say), counted `AutoStats.relaid` ("1 laid out
    again over new words"), apart from generated, skipped and failed. The staged jobs' chords stage re-lays first
    (staged.py `_relaid`, in `_autochords_sheet` and lyrics_pick.py's `chords` before its auto-chords check: no model,
    no hand-over, its words `holds`'), where `relays_here` (new audio a job brought, a file or a video, is heard by the
    models), and a pick or a clear clears `autochords_mtime` only for a sheet without `heard` (lyrics_pick.py
    `_models_remake`); transcribe_job.py's `_sheet_to_make` takes `RELAID` as a sheet to make.
  - A sheet another caracole made (E14, the design's R3 and R5): its raw's `made_by` not this side's id
    (sheet.py `made_by_another(raw, own)`, sheet_lyrics.py `made_elsewhere(conn, raw)` and `auto_made_elsewhere(conn,
    song_id)` by peer_sync.py `own_id`, a read; a raw that names none, made before E12, is this side's own, as
    ever). `_skip_reason(..., asked=False)` checks it before the audio's mtime (a take writes none; this side's
    `autochords_mtime` says nothing of whose the sheet is): `MADE_ELSEWHERE` ("made by another caracole from your audio
    there", sheet_lyrics.py's) by itself, whatever audio this side holds or gets, `RELAID` while its words re-lay it
    (`relays_here(song, elsewhere=True)`: from its own `heard`, never this side's transcript, `noted_of` giving
    `noted_in`); `_count_due` counts it nowhere, no failure, the to-do page and the card its chords done
    (youtube_fetch.py `song_state` CHORDS). None (made here, this side its maker, its one auto version's tab id kept)
    for an ask: `autochords_pending(only=, asked=None)`, `asked` by default whenever `only` names songs (`caracole
    autochords --song`; staged.py `_autochords_sheet`, which skips `_relaid` for such a sheet: a sheet from a video,
    from an audio file, a transcription's chords; transcribe_job.py `_sheet_to_make` asks `asked=True`); a lyrics pick
    is no ask (lyrics_pick.py `chords`: re-laid, else skipped in `MADE_ELSEWHERE`'s words, no model). And None for its
    chords alone (`lyrics` "none", no transcript of its own) once this side keeps a transcript of its own audio and no
    site has words or an instrumental verdict, while transcript.py `WORDS_WIN` (§11.5's yes, one constant: False
    leaves it; `why_not_offered` offers it either way, the card's Transcribe by hand); never one the owner said isn't
    sung (the raw's `not_sung_by` "you", the one trace of their word that crosses a sync). run.py `_words_replace`
    says which sheets words would replace, and `_hears_here` whether a pass spends Whisper and a slot on the song
    (an ask, a sheet of this side's or none, else `_words_replace`), `_Listening.first` and `_count_due` alike: a sheet
    made elsewhere over a transcript or a site's words is never heard again here. A lyrics pick on one whose `heard`
    can't be read says so (lyrics_pick.py `ELSEWHERE_UNREAD`: ask for a new sheet here); the to-do page says its
    chords were done on your other caracole (todo.py), the card's `youtube` note still says YouTube's (a later task).
    `caracole peer new-id` makes every earlier sheet another's.
- export.py, for the phone (nothing on the computer runs it but `nix build .#chord-models` and its tests): BTC and
  beat_this as ONNX graphs, `CONTRACT` what each takes and gives, torch's TorchScript exporter at opset 17:
  - `export_btc`: `btc-graph.onnx`, raw log-CQT frames (`features`, [N, 108, 144]) to `logits` ([N, 108, 170]),
    normalized inside in float32 as btc.py does (a window's frames past the audio's end are the checkpoint's mean),
    its layer norms' unbiased std written out, nothing folded; every tensor of the state dict an external initializer
    at its offset in the authors' `btc_model_large_voca.pt`, copied beside it unchanged, its bytes checked there:
    BTC's weights are never re-hosted; its `metadata_props` the float32 `mean` and `std` it normalizes with (a
    window's frames past the audio's end are padded with that mean, never 0) and the file's `weights_sha256`, the one
    thing that says which `.pt` belongs beside it;
  - `export_beats`: beat_this's final0, `spect` ([1, T, 128]) to `beat` and `downbeat`, and with `fp16` its weights
    stored as float16, cast to float32 as it loads; its nine attentions over time (`_ATTENDS_OVER_TIME`: the
    frontend's three a frequency band, the transformer's six a head) each one Scan of MatMul, Softmax and MatMul over
    a slice at a time (`_attention_by_slices`), the whole attention's answers to the bit in a fraction of the memory
    (a 1500-frame chunk's scores and softmax were two [32, 1, 1500, 1500] float32s at once, 576 MB of the phone's
    peak, `_attention_by_slices`' docstring);
  - `pt_offsets`: each tensor's offset and length in a checkpoint in torch's legacy format (pickles, then each
    storage's raw float32 bytes), since the phone will fetch such a file read by `_Strict`, the standard library's
    pure-Python unpickler guarded opcode by opcode (its notes): protocol 2's opcodes alone, the six globals of
    `_ALLOWED`, stand-ins that run nothing, BUILD only on a numpy dtype and a state dict's `_metadata`, no dictionary
    key but a text or a number (a deep tuple's hash overflows CPython's C stack), no read past the file's end
    (`_Bounded`); each record checked again where it is used, every failure a ValueError; it imports no torch.
    tests/helpers/legacy_pt.py writes such files with the standard library, so its tests run in any shell;
  - tests/test_autochords_export.py holds them to torch's answers in `.#autochords` (ONNX Runtime and mir_eval, its
    test-only packages): BTC's max abs 1e-4 and every argmax, beat_this's 1e-4 in fp32, the fp16 one 1e-2 on seeded
    frames and beats F ≥ 0.99 on music, the same bytes twice, and the sliced attention's answers bit for bit the
    whole one's (`sliced=False`) at 300 MB less peak over a chunk (a fresh process's VmHWM: `ru_maxrss` a child keeps
    from the process it was forked from).
- What the phone's port is held to, the conformance corpus's `autochords` area (tests/test_conformance_autochords_models.py,
  in `.#autochords`): the committed clips, tests/fixtures/autochords/*.wav (CC0, made by tests/helpers/synth_music.py,
  `render(spec, seed)`, pure Python, their README's table each one's spec), and PyTorch's answers on them, on one
  thread, as its sums' order moves the last bits with the threads (tests/helpers/autochords_reference.py,
  `reference(path)`: the computer's every step, BTC's and beat_this's own code; `python -m
  tests.helpers.autochords_reference IN OUT` the same for the owner's songs, never committed; its length read_audio's,
  and a song whose decoded samples, mel frames and length disagree by more than 0.1 s not written, saying which,
  `lengths_disagree`; `--hearings IN OUT` the compact one, the corpus's `hearing` record of each song,
  `hearing_record`, its `file` its name and SHA-256, `<stem>.hearing.json`, beside `meta.json`, models.jsonl's gates
  as committed, for ParityRunTest and the bench's B1 mode):
  - `vectors/autochords/frontend.jsonl`: each clip's log-CQT (float32) and log-mel (stored as float16), their frames'
    norms, its samples' SHA-256 and mutagen's length; three excerpts' log-CQT (long.wav's 2048, 2049 and 4095 samples
    from its second chunk on, btc.py's last chunk alone); its meta's `gates`, the design's B1 feature gate
    (`FRONTEND_GATES`: equal frames, each frame's cosine median ≥ 0.9999 and least ≥ 0.999 over the frames not
    silent, a silent one within 1e-3 of its floor and the phone's silent too);
  - `models.jsonl`: BTC's logits of that log-CQT (the last window padded with the mean), each frame's top two and
    margin, the chords; beat_this's logits of that log-mel as stored, its beats and downbeats; the chords and beats
    as played;
  - `data/caracole/autochords/frontend.json` (`frontend_json`, 67 KB): librosa 1.0's CQT of one chunk as it ran,
    watched step by step (each `audio.resample` and each `__cqt_response`: its STFT and its sparse complex64 basis),
    the lengths its scale divides by, btc.py's settings (`LOG_FLOOR` among them), and beat_this's mel window, norm and
    slaney filterbank (sparse): never recomputed on the phone, `:autochords`' resource;
  - `data/caracole/autochords/btc-graph.onnx` and `models.json` (the pins: each file's bytes and SHA-256, BTC's git
    blob, repository and commit, its mean and std, each model's name for `raw["models"]`), exported in the test from
    the shell's model files, the same bytes as `.#chord-models`; on the phone `:ml`'s resources, so a build with `:ml`'s
    (`:core` leaves `caracole/autochords/` out of its resources, so a build without `:ml` carries none of it);
  - every record checked against `BTCRecognizer.recognize` and `detect_beats` on the clip, exactly;
  - the gates the phone's runtime is held to, in models.jsonl's meta record (`gates`, the test's `GATES`, the
    design's §4.2): BTC's argmax equal on every frame but where the stored top-two margin is under 1e-3, its logits
    within 1e-4; beat_this's fp32 logits within 1e-3; the fp16-stored file's beats and downbeats at F ≥ 0.99
    (±0.07 s, mir_eval's 5 s trim), no logit bound. `test_onnx_runtime_meets_the_gates_on_the_stored_inputs` reads
    them there and holds this machine's ONNX Runtime to them;
  - the bytes hold on a CPU of the meta's `cpu_capability` (torch's kernels); on another the byte check is skipped,
    saying so, and the gates are the check.
  - around the models, pure functions of no model file, made in the test's own process: `peaks.jsonl` (beat_this's
    minimal postprocessor over seeded logits, int8 q·0.125 or float32, and hand-made edges), `chunks.jsonl`
    (`split_piece` and `aggregate_prediction` of every piece of 0 to 4,000 frames, each length's chunk starts and
    lengths and the runs each chunk fills, int32 deflated), `scores.jsonl` (mir_eval's WCSR by `majmin` and `tetrads`,
    `mir_eval_wcsr`, evaluate()'s own steps, and `beat.f_measure` untrimmed and after `trim_beats`, with their edges
    and refusals) and `data/caracole/autochords/scores.json` (mir_eval's pitch classes, qualities and MAX_TIME);
- its default-shell half, tests/test_conformance_autochords.py: `labels.jsonl` (btc.py's vocabularies, common names,
  `spell_for_key`, `frames_to_segments` and `round(k · FRAME_SECONDS, 3)`, over test_autochords_models.py's
  `COMMON_NAMES`, `SPELLINGS` and `FRAMES` and seeded songs and frames) and `data/caracole/autochords/labels.json`
  (btc.py's tables).

#### `tests/`

- Named after what they cover (test_fetch.py is ug/fetch.py's), and `test_commands_*.py` for the CLI.
- conftest.py has the `conn` and `cfg` fixtures (every directory under `tmp_path`, in /dev/shm if it will do; `conn`
  copies a database migrated once per process), `add_song` and `subprocess_pythonpath`.
- tests/helpers/ holds what the tests share, a module each, whose docstring says what it gives and how
  (`from helpers.<module> import ...`); look there before writing another:
  - fake sites behind a real `PoliteClient`, a fake yt-dlp, synthetic files, a song rendered;
  - a PDF's text where it is drawn (pdf_pages.py), a wait for caracole's lock seen, Chromium (Browser tests, below).
- test_harness.py tests what makes the suite fast.
- fixtures/ holds samples of what each site answers (real response shapes, trimmed) and synthetic lyrics, sheets and
  files; fixtures/audio/ the MP3s whose length a reader guesses wrong and three every reader agrees on, written once by
  its make.sh with FFmpeg (no test runs it).

#### `nix/`

- **package.nix**: `buildPythonApplication`.
  - The wrapper puts `chordpro` on PATH and defaults `CARACOLE_CJK_FONT`, `CARACOLE_PDF_FONTS` and
    `CARACOLE_ALPHATAB_DIR`.
  - pdf-fonts.nix: nixpkgs' adwaita-fonts as four files, static Regular, Bold and Italic instances of Adwaita Sans
    made by pdf-fonts.py with fontTools, each glyph record padded to an even length, Adwaita Mono, and the OFL.
  - alphatab.nix: alphaTab's npm package, fixed-output, three files and their licences.
  - `withAutochords` adds the extra, the model files (the wrapper's `CARACOLE_BTC_WEIGHTS`,
    `CARACOLE_BEAT_CHECKPOINT`, `CARACOLE_WHISPER_MODEL` and `CARACOLE_DEMUCS_MODEL` defaults), and `yt-dlp` and
    `demucs` (demucs-rs) on PATH.
  - `cudaTorch` (flake.nix's `autochords-cuda`, on `pkgsCuda`'s torch-bin; its demucs-rs the wgpu build) sets
    `CARACOLE_TORCH_CUDA=1` in the wrapper, as the `.#autochords-cuda` shell does: youtube_fetch.py
    `transcribe_time` reads it, with `[autochords] transcribe_device` not "cpu" and `/dev/nvidiactl` there, to offer
    a transcription as "a couple of minutes" rather than "up to half an hour"; the package check fails a CPU wrapper
    that sets it.
- **autochords.nix**: the model files, fixed-output.
- **autochords-onnx.nix**: `packages.chord-models`, export.py's four files from autochords.nix's pins, the same bytes
  every build (`nix build --rebuild`).
- **module.nix**: `services.caracole`: units, timer, `caracole-admin`.
  - No `credentials` option, as caracole reads no secret, so no unit and not `caracole-admin` loads one.
  - With auto-chords on, the nightly unit runs the auto-chords package, for its youtube step, and caracole-web and
    `caracole-admin` run it too, so their pages agree.
  - caracole-web then without MemoryDenyWriteExecute, as the auto-chords unit and `caracole-admin`, since a sheet from
    a YouTube video runs the models in it.
  - `autochords.cuda` picks `autochords-cuda` as the flake's default `autochords.package`; then caracole-web and
    `caracole-admin` (the units whose children transcribe) get `PrivateDevices = false`, `DevicePolicy = "closed"`,
    `DeviceAllow` (`char-nvidiactl`, `-nvidia-caps`, `-nvidia-frontend`, `-nvidia-uvm` from nixpkgs' ollama module,
    `char-drm` for Vulkan) and the `video` and `render` groups. The nightly units never get them (the owner's
    decision of 2026-11-25), so the nightly auto-chords pass of this build hears no words, and says so (run.py).
    Without `autochords.enable` it does nothing, and the module warns (a `warnings` entry, not an assertion);
    nix/module.nix alone, without the flake, doesn't switch `autochords.package`.
    `whisperModel` and `separatorModel` are `CARACOLE_WHISPER_MODEL` and `CARACOLE_DEMUCS_MODEL`.
  - And `/etc/caracole/service`, the service's marker, service.py's.
  - caracole.service has `NotifyAccess = "main"` (deploy.md's Ubuntu unit too): the run tells systemd its status line
    (progress.py `systemd_status`), the wrappers exec'ing, so caracole is the main process.
  - `publish` (off): `caracole-publish.service` and its weekly timer run `caracole index publish` offline into
    `publish.folder` (2750), with no network and no token, which `caracole-admin` may then write too. The upload is
    the owner's own systemd user service in their own configuration (`caracole-upload.service`), running
    `publish-indexes DIR` with their `gh` login (docs/deploy.md); the module has no token file and no upload unit.
    `publish.uploadUser` (null by default; set without `publish.enable`, a `warnings` entry) starts it:
    `caracole-publish.service`'s `OnSuccess=` is `caracole-publish-upload-notify.service`, a oneshot as root, every
    program by its store path: `systemctl is-active user@<uid>.service` first, and when the user's manager isn't
    running one line (the upload waits for their catch-up timer) and exit 0; else `runuser -u <user> -- env
    XDG_RUNTIME_DIR=/run/user/<uid> DBUS_SESSION_BUS_ADDRESS=… systemctl --user start --no-block
    caracole-upload.service`, whose failure (no such unit, a bus error), as no such user, fails the notifier, never the
    publish. Never `systemctl --user --machine=<user>@`: its PAM bridge starts a manager that isn't running, for logind
    to stop seconds later, with gh's keyring locked. module-check.nix runs the notifier with stand-ins for id,
    systemctl and runuser in each case. No user path unit: systemd watches every folder from / down to
    `published.json`, and the 0710 dataDir refuses the user's inotify watch. A publish by hand (`caracole-admin index
    publish`) starts no upload.
- **module-check.nix**: `checks.module`, which loads the marker with service.py.
- **publish-models.sh** (`.#publish-models`, publish-models.nix): the owner's upload, by hand, of beat_this's two
  converted graphs (`.#chord-models`' `beat_this-final0.onnx` and `-fp16.onnx`) to the GitHub prerelease `models`
  the phone's models' job fetches from: the files checked against models.json's pins (PINS) first, each uploaded once
  and read back, one already there with the pinned digest left, one of another digest never replaced, no other asset
  touched; tests/test_publish_models.py against helpers/fake_gh.py.

#### `docs/`

- usage.md: configuration, commands, the to-do page, overrides.toml, the library folder.
- deploy.md: a server: the NixOS module, or Ubuntu 24.04 without Nix, whose units and caracole-admin do what
  nix/module.nix's do, so a change to a unit there changes them too.
- install.md, and the design files above.
- A short page for each thing caracole does, which the README's bullets link to: sheets.md, search.md, songbooks.md,
  autochords.md, phone.md; sources.md: the sites and the exceptions to their rules. README.md is the front page: what
  it is, computer and phone, Install, the Gallery, links. usage.md is the reference under them. All in plain, short
  prose (the owner's ask of 2026-11-23: concise, for people, nothing that reads as machine-written).
- web-search.md designs a search-API fallback for matching, not built.
- android_port.md: caracole in Kotlin on the phone, its plan and what is built of it, milestones 1 to 6 (its research:
  superpowers/specs/2026-11-02-android-native-port-feasibility.md).
- screenshots/: the README's and the pages' pictures, of a demo library of public-domain songs, and make.py, which builds that
  library with no request and takes them again (its docstring says how): retake them when the pages they show change.
- logo/: caracole's logo, its masters (caracole_icon.png, the project's and every page's, with a small copy for the
  README; app_logo.png, the Android app's launcher icon) and trace.py, which traces a master's black and copper into
  page_icon.py's paths or the launcher icon's (`drawable/ic_launcher_foreground.xml`, `ic_launcher_monochrome.xml`):
  trace them again when a master changes.
- superpowers/plans/2026-11-03-android-port-m1-m3.md and 2026-11-03-android-port-m4-m6.md: the Kotlin port's plans
  for milestones 1–3 and 4–6, their lanes and their interfaces; plans/2026-11-03-sync-redesign.md with
  specs/2026-11-03-sync-redesign-design.md, the sync sheet and the `.caracole` file;
  specs/2026-11-03-conformance-corpus.md, specs/2026-11-03-canonical-json.md, specs/2026-11-03-html-parsing.md and
  specs/2026-11-03-politeness-crossing.md, the contracts it rests on; spikes/2026-11-03-android/, the spikes'
  Kotlin, kept as `.kt.txt`.

#### android/

The Android app and caracole's rules in Kotlin (android/README.md; the plan above). A Gradle build of its own
(`android/flake.nix`: JDK 17 headless, Gradle, the SDK), packages under `io.github.danielhp95.caracole`:

- `:mirror`: the computer's pages on the phone, as `GET /api/offline` lists them (manifest, blobs, the sync), each
  page gated by its unit (`UnitGate`, `Mirror.pageFor`).
- `:core` (plain JVM): caracole's rules, each package the port of a Python module:
  - `db/`: db.py, its migrations from `caracole/schema/migrations.json` in the bundled SQLite (sqlite-bundled 3.50.1,
    FTS5), and the phone's own tables (`phone.sql`: `phone_overrides`, `phone_songbooks`);
  - `py/`: Python's Unicode and string semantics (unicodedata 16.0.0's tables, `re`'s classes); `keys/`:
    normalize.py and library.safe_name; `pinyin/`: pypinyin; `fuzz/`: rapidfuzz-cpp;
  - `json/`: canonical.py (canonical JSON, digests) and `json.dumps`'s kv text;
  - `search/`, `ug/`, `sites/`, `lacuerda/`: search.py, ug/key_search.py, ug/artist_tabs.py, lacuerda_index.py and
    the other sites' search; `names/`: song_names.py; `index/`: index_transfer.py's merge (its guards: a file of
    tables alone, read in its `sqlite_master` before any table, `trusted_schema` off while attached, kv's columns
    checked; its `progress`, `MergeProgress`, index_transfer.merge's events one for one: `planning`, each site, each
    action, `tab` after each `UG_CHUNK` of UG's sitemap rows, by `tab_id` range in one statement's order, and the
    phone's own `optimize`; `Paced`, a stage's words at most once a second, a step's first and last at once);
  - `library/`: songs.py, removal.py's rules, overrides.toml and songbooks.toml as tables, audio_store.py
    (`AudioStore`, below); `sync/`: peer_sync.py, and the phone's sync engine and peer client;
  - and milestones 4–6's, each in its section below: `http/`, `health/`, `config/`, `html/`, `lookup/`, `ug/`,
    `match/`, `lyrics/`, `lacuerda/`, `sites/`, `inbox/`, `share/`, `songbooks/`, `backup/`, `catalogues/`
    (GitHub's release of the site catalogues, below) and `models/` (the chord models' download, below).
  - testFixtures: `Corpus`, `Fixtures`, `TestDb`: how every Kotlin test reads the corpus and makes a database.
- `:server` (plain JVM): web/ on the phone, on Ktor CIO at 127.0.0.1 behind a launch secret: `http/` (app.py,
  security.py, inline.py, the message page), `files/`, `page/` (library_page.py's page, from library_assets/ copied
  byte for byte at build time), `jobs/` (jobs.py, jobs_routes.py), `routes/`, and `Assembly.kt`, the phone whole.
- `:app`: the Android app on its own server (`Caracole.kt`: one `Phone` a process, its server on
  `http://127.0.0.1:8738`, the debug build's 8739 (`Caracole.PORT`, BuildConfig's `SERVER_PORT`), else a free port;
  the launch's secret a cookie, `caracole-launch`, set in the WebView, which loads that exact origin alone,
  `mirror.Links`); the bar's sync button, the library page's sync sheet
  (`SheetAddress`, `#sheet=sync`; Settings' Sync, beside Test, opens it at `#sheet=sync`, a blank address said in
  place as Test says it, and Export and Import a file at theirs, the page's file input reaching
  Android's picker, `FileChooser`, its export the share sheet, `Exports`); Sync on Wi-Fi, that sync unattended
  (`Syncs.run`: `Phone.sync.alone`, a notification on channel `syncs` for the conflicts it left; its line, Settings'
  last outcome and the bar's, `Syncs.said`: "Up to date" only with nothing left and no index skipped, else what it
  took and gave, each conflict left "changed on both sides", every other unit left "not synced", and the index
  stage's words where the computer's database is of another schema (`Outcomes.indexesSkipped`), the line ending with
  what to do, ": tap Sync to choose" for conflicts (the sheet the tap opens compares afresh and shows each) or ": the
  Journal says why" for the rest (that sync's entry's Output lists each unit taken and given, then each unit left by
  its name and its why: SyncRoutes.said, Feed's step of what a request of the phone's own said, `Feed.SAID`; a fresh
  comparison wouldn't);
  a stage that failed, its words); the queue's work, a
  sync among it, in a foreground service (`SyncService`).
  - Its debug build is an app of its own beside F-Droid's release (`io.github.danielhp95.caracole`, the release key):
    `io.github.danielhp95.caracole.debug` (`applicationIdSuffix`, versionName `…-debug`), "Debug caracole" with an
    amber icon and a DEBUG mark (src/debug/res), its own data and port, its tests
    `io.github.danielhp95.caracole.debug.test`; the classes stay in `io.github.danielhp95.caracole` (the namespace).
    `android/scripts/phone-install.sh` builds a checkout's and installs it on a real phone (tests/test_phone_install.py).
- `:viewer` (plain JVM, milestone 5): the page builder, viewer/ in Kotlin, with viewer/'s `.js`, `.css` and voicings
  copied byte for byte at build time (`copyViewerAssets`).
- `:e2e`: the end-to-end phases against a real caracole serve (`PhoneScenarioTest`, driven by
  tests/test_android_e2e.py, below).
- `:ml` (Android library, the chords-on-the-phone design): BTC and beat_this on ONNX Runtime 1.27.1 built from its
  source (`OrtModels`: `chords`, `beats`, a chunk at a time, `padding` the graph's mean, `RUNTIME` "onnxruntime
  1.27.1"; Gate R, the owner's "Build 1.27.1" of 2026-11-27), an `implementation` of the app, both builds (stage S,
  E33), and only in the `./android#ml` shell, whose `CARACOLE_ONNXRUNTIME` names the runtime's Maven folder: without it
  settings.gradle.kts includes no `:ml`, and the app takes src/noMl's `PhoneChords` and `PhoneExaminer` (none) for
  src/ml's, no Chords bench (`BuildConfig.CHORDS_BENCH`), and leaves out src/debugMl, src/testDebugMl and
  src/androidTestMl, so the other shells build and test the rest with no ONNX Runtime; any release packaging task
  (assemble, bundle, package, install) refuses there as the task graph is ready, before anything runs. The release carries the chord models' libraries for arm64-v8a alone (app/build.gradle.kts `releaseMlAbis`,
  `BuildConfig.ML_ABIS`; SQLite's for both): `MlChordModels.deviceProblem(carried=)` says "no chord models for this
  phone's processor" on an x86_64 phone; `checkApkSize` (after every release build) fails an APK over 100 MiB.
  - The runtime: nix/onnxruntime-android.nix, with no network: nixpkgs' pin of the v1.27.1 source
    (`sha256-i2u/JnfbJ/srsZY3ATb2YsBBXEhTGhatsr3+9eHVV3M=`, cache.nixos.org's: github.com/microsoft/onnxruntime answers
    404), its CMake dependencies deps.txt's zips by SHA-256 in a local mirror; android/scripts/build-onnxruntime.sh's
    `java` (the bindings by javac, once: ORT's own Java path runs Gradle, which fetches), `native` (an ABI, arm64-v8a
    and x86_64, NDK r28c, the CPU provider alone, telemetry off: 1.27.1's is opt-in, never set; the kernels of
    android/ml/onnxruntime-ops.config's ops alone; at most 8 jobs; paths mapped, no build id, `EPOCH` its one date:
    two folders give the same bytes) and `aar` (no provider, no permission, every zip's entries sorted). No Maven AAR and
    no TelemetryInitializer to remove: `ORT_DISABLE_TELEMETRY` is still set before the first environment, for a later
    runtime (the app's `NoTelemetryTest`); `ApkScanTest` scans the AAR in the ml shell's `gradle test` (skipped,
    saying so, elsewhere) and both APKs by `gradle :app:apkScan`. Built once a machine (about ten minutes an ABI), the ml
    shell's entry roots it (`$XDG_STATE_HOME/caracole/gcroots/onnxruntime-android`), as `nix build
    ./android#onnxruntime-android -o PATH` does.
  - Its ops: android/scripts/onnxruntime-ops.sh (`--check` holds the committed list to the graphs) over `.#chord-models`'
    three graphs, as they are and as ONNX Runtime 1.27.1 (nixpkgs' python3Packages.onnxruntime at the android flake's
    pin, `./android#onnxruntime-ops-python`) optimizes them, ORT_ENABLE_ALL and ORT_ENABLE_EXTENDED, on x86_64 and on
    aarch64 under qemu-user (`./android#onnxruntime-ops-aarch64`, cache.nixos.org's aarch64 build: the phone's CPU's
    fusions), read by ORT's own tools/python. An op left out fails loudly at session load, never silently; Android's own
    arm64 build is the one thing the list was not read on, which the owner's bench on the phone checks.
  - Its sessions: no arena and no memory pattern by default (beat_this's peak RSS halved on the emulator), ORT's own
    with `arena = true`. Its `ModelParityTest` (its own test APK) holds it to vectors/autochords/models.jsonl on the
    emulator, every threshold the records' `gates`, beat_this's chunking, postprocessor and F-measure through
    `BeatThis`, which keeps no copy: it delegates to `:autochords`' `Chunks`, `Peaks` and `Scores` (`BeatThisTest`), the
    models `.#chord-models` (`./android#ml`'s `CARACOLE_CHORD_MODELS`), pushed by `device-test.sh --ml`; its test APK
    runs under AndroidJUnitRunner (no HTTP code there, so no `caracole.network=loopback`). `:ml` carries
    `caracole/autochords/` (BTC's graph, models.json), which `:core` leaves out.
  - **The Chords bench** (§9.1, Gate B0's numbers from the owner's phone, run by hand): `Bench.session` (one model on
    one thread count and arena setting: its load timed apart, then each file `passes` times back to back; the model's
    time alone, a look every second at the process's PSS and the phone's `Heat`, each run's true peak RSS or null where
    its reset didn't take; the heat guard stops it at critical; anything thrown, OOM too, its failure, an OOM known as
    one; the session written whole after each run, so whatever ends it loses only the run in flight), `BenchInputs` (the
    committed clips' records, kind `clip`; an `autochords_reference` JSON of the owner's, kind `reference`, streamed,
    its decoded samples dropped; one whose duration its mel's frames disagree with by more than 0.1 s timed by the
    mel's length and flagged, `BenchInput.lengthOf`, the report's `length_flags` and each run's `length_note`, and
    a line on the screen's log), `Heat` (thermal status from API 29, headroom from 30 at most every 10 s, the battery's
    charge counter, plugged, Battery Saver: unknown or null where the phone gives none), `BenchCodec` (a session's
    result across processes), `BenchReport.of` and `ofSessions` (`caracole-bench-<UTC>.json`: device, SoC, Android,
    runtime, app; the whole battery; each session; each run's seconds, RTF, PSS, reset and RSS peak, thermal states,
    battery change; a summary of the references with Gate B0's `speed_ok` and `memory_ok`, the clips' apart with none;
    `memory_ok` from the whole-life peaks of that setting's fresh sessions that finished every planned run, the load and
    the first run in (null with a `memory_note` where one didn't, false where one ran out of memory), the gates' limits
    in `summary.gates`, the warm runs' steady peak beside it; each session's `pid` and `fresh`; a later session's parity
    that differs from the first's in `differs`; `Parity` against the computer: BTC's frame agreement but near ties,
    fp32's logits, fp16's beats F, each file and setting once), held by `BenchReportTest` on the JVM. The app's
    src/debugMl alone has its screen (`ChordsBenchActivity`, Settings' Chords bench row under
    `BuildConfig.CHORDS_BENCH`) and its
    foreground service (`BenchService`, a special use, a partial wake lock, the screen-off round, the report saved after
    each session), in process `:bench`; each session in a fresh process, `:benchrun` (`BenchSessions.run` binds
    `BenchWorkerService` a session, its result a file, unbound and gone before the next; given up after no write for
    four times the run in flight's audio (5 minutes at least), or a minute after Stop, its last write kept and why it
    ended said (a hang or a dead process its failure, the bench going on; only Stop and the heat guard end the bench,
    `Bench.endsTheBench`, `runSessions`); its writes numbered, read by their number (`SessionWrites`), a failed rename
    its failure; Android's exit reason read for memory; what a crashed one left swept as the bench starts); the folder
    the owner picks (`BenchFolder`, the Storage Access Framework: the model files, checked by models.json's SHA-256 and
    copied into `no_backup/bench-models/`, `BenchModels`; the references; the report) and the clips as debug assets
    (`autochords/`, app/build.gradle.kts). Its whole-pipeline mode (Gate B1, the screen's Hear the songs (B1),
    `BenchService.HEARINGS`): the folder's songs and its `hearings` folder copied into `no_backup/bench-hearings/`,
    each song heard whole through `MlChordModels` (a fresh `:ml` a song, no checkpoint kept, Stop sent as its CANCEL),
    scored by `EndToEnd` (`BenchHearings`), the report's `hearings` member (`BenchReport.hearings`, `HeardSong`: each
    song's scores against the thresholds, lengths, stages, `ml_peak_mb`, and over all, no pass while a song wasn't
    heard, `not_heard`; null where it didn't run; no report file where the run threw). `ChordsBenchTest`
    (`device-test.sh --ml`) runs its sessions over the clips on the emulator, a process each, and the B1 mode over
    hearing.mp3 and hearing.m4a.
  - `android/scripts/release-check.sh` holds the release to it: onnxruntime and `:ml` on its runtime classpath (which
    names `:core`: read); ONNX Runtime's libraries for arm64-v8a and no chord models' library for x86_64 (SQLite's
    kept); classes under `ai/onnxruntime/` and of `:ml`; `caracole/autochords/`; one model file, BTC's graph, no
    weights' file; MlService in its `:ml` process; no bench name or Settings' row's words in its dex, no
    `assets/autochords/` entry, no TelemetryInitializer or bench entry in its manifest; 100 MiB at most; each APK by
    output-metadata.json's name, both built in the ml shell; the controls: the debug APK's bench and x86_64 libraries,
    `.#chord-models`' names, the runtime's AAR declaring no provider, `gradle :app:apkScan` (ApkScanTest's control
    finding each string where it would be), and native-check.sh over both APKs' runtime and libsoxr (both ABIs in
    the debug one, arm64-v8a's alone in the release). It handles
    no text: no ForbiddenApiTest.
  - Its native build (stage B1): `externalNativeBuild` of autochords/native/CMakeLists.txt for arm64-v8a and x86_64,
    NDK r28c (`ndkVersion`, the app's too, whose strip needs it; android/flake.nix's `ndkVersion` and `cmakeVersion`
    3.31.6): `libcaracole_soxr.so`, 16 KB aligned, stripped, no debug information (`-g0`), its reproducibility flags
    the CMakeLists' (§7: `-ffile-prefix-map` of the source and the binary folders, `--build-id=none`,
    `--hash-style=gnu`, `.comment` removed), `-ffp-contract=off`, every symbol but the JNI's hidden;
    `android/scripts/native-check.sh` checks the debug APK's, and `:youtube`'s `libqjs.so` (stored and aligned or,
    every build extracting its libraries since Y5.1, compressed; segments 16 KB aligned, stripped, no build path, its
    SHA-256).
  - **The decoder** (stage B1, E7): `Decoder.decode(file, into)`, audio.py `load_mono` at the file's own rate, into
    interleaved little-endian float32 written a buffer at a time, `into` deleted on any failure, every failure
    `UndecodableAudio` in words. `Decoded`: rate, frames, channels, the codec, what was trimmed, and `durationS`, the
    length music.py `read_audio` states by the computer's rule for the container (an MP4's `mdhd`, `Mp4`; a fragmented
    one's, yt-dlp's m4a on the phone, which has no FFmpeg to remux it, its fragments' length, `statedSeconds`, what the
    computer's remux of it states, yt-dlp's FixupM4a; an MP3's Xing frames less a LAME tag's delay and padding where
    mutagen reads the tag, `MpegHeader`; else the frames decoded, an MP3 that names no length's counted so). A WAV or an
    AIFF by `autochords.frontend.Pcm`, no codec; else MediaExtractor's first audio track and Android's own software
    decoder (`c2.android.*`, `softwareDecoder`), float PCM asked for (but `audio/raw`, a FLAC the extractor decodes
    itself), its output read in the encoding it names (`PcmEncoding`; one caracole doesn't read refused). Trimmed here,
    never by the codec: where the format names `encoder-delay` and `encoder-padding` the framework's codecs may trim
    them themselves (this emulator's do), so caracole takes both keys out of the codec's format and trims (`Trim`, its
    counts made the output's rate's at its first format, `Trim.at`: rescaled exactly, else the stated delay): an MP4 to
    its one media edit exactly, a fragmented one with no edit it takes (none, or a segment of 0) to its fragments'
    length, its priming kept (no box names it), as the computer's remux of it decodes (one whose fragments can't be
    read, a download cut short, refused:
    `fragmentsKeep`), an Ogg to its last page's granule less Opus's pre-skip (`Ogg`), an MP3 by the decoder's own 529
    samples (`DROPS_MP3_DELAY`, the decoders measured, any other refused: a LAME tag's delay after them, a headerless
    file's whole by a `silentFrame` first), else the delay and padding stated. Its loop is `CodecLoop` (plain code
    behind `CodecPort` and `SamplePort`: a decoder that stops is given up, a rate or a channel count that changes
    partway refused; `CodecLoopTest` on the JVM). `Mixdown.mono`, numpy's float32 mean of the channels, an array's or a
    file's. `DecoderTest` (`device-test.sh --ml`) holds it to vectors/autochords/decode.jsonl, every threshold its
    meta's `gates`: the lossless files sample for sample (a 24-bit FLAC, which Android gives as 16-bit, by the 16-bit
    gate), the lossy ones at offset 0 and SNR ≥ 60 dB whole and each second, every file's frames the computer's and its
    stated length within 2 samples (yt-dlp's two fragmented shapes, `decode-frag.m4a` and `decode-dash.m4a`, against the
    computer's remux of each: tests/fixtures/autochords/README.md); android/README.md says what it doesn't cover.
  - The whole hearing (E9), in a process of its own: `MlService` (`:ml`'s manifest, `android:process=":ml"`, not
    exported, the debug build's alone; one hearing a process, the process ended once its client lets go, a `CANCEL`
    or the unbind stopping it at its next chunk) runs `Pipeline.hear(audio, work, say)`, the computer's path step for
    step (tests/helpers/autochords_reference.py): `Decoder`, `Mixdown`, libsoxr HQ to 22,050 Hz through its stream
    where the file is at another rate (soxr's own length, beat_this's; BTC reads librosa's `ceil(n · ratio)` of it,
    `Stages.btcSamples`; beat_this's own float64 resample on the computer: the same samples at 22,050 Hz, float32's
    last bits else), then `:autochords`' `Stages` (`chords`, `beats`) over the memory-mapped pcm, no array holding the
    song. One model at a time (`Pipeline.Graphs`, `OrtGraphs`), BTC's first. Checkpoints (`:autochords`'
    `Checkpoints`, `stateDir/cache/autochords/<sha16>-c<contract>/`: `pcm.json`, `pcm.f32` (deleted once the beats
    are kept), `chords.json` (Harte labels, before common names), `beats.json`, `heard.json`), each written to a
    `.part`, forced to the disk and renamed, the folder then forced too (`Checkpoints.syncFolder` on a JVM, `Os.fsync`
    in `:ml`; quiet where refused); one that won't parse, or a pcm shorter than its meta, is made again;
    what a cut-off stage left anywhere under the folder is swept as a hearing starts. `MlChordModels` is
    `ChordModels` in the main process: `ready()` says its `device` reasons first (the app's `deviceProblem`, §8.1:
    Android 13, an ABI it carries, `LEAST_MEMORY` 5 GiB of `totalMem`, "6 GB" as phones are sold; none for the bench
    and the tests), then its `installed` judge (the app's: `ModelFiles.installed` of `stateDir/models/c1/`), or with
    none the three files (BTC's graph and weights, beat_this fp16) by models.json's sizes and SHA-256, hashed once a
    process (the bench's folder, device-test.sh's push); `runtime` is `OrtModels.RUNTIME`. `hear` asks `ready()`,
    then (`guarded`, `HearingGuardTest` on the JVM) refuses under the battery floor (`HeatRules.start` over its
    `gauge`, before any process), takes the one turn of the app's processes (`turn`, an flock of `files/chords.lock`:
    a job's hearing and the Chords bench's, which bind the same `:ml`, never at once; `BUSY` in words) and holds
    `caracole:chords`'s partial wake lock (its 10 minutes begun again each step and minute), both let go on every
    path and what it throws thrown as itself; waits for an earlier `:ml` to end (`awaitGone`: 10 s, then refused in
    words, `STILL_ENDING`), binds the service, sends paths over a
    `Messenger` (`MlProtocol`), polls its replies a second at a time calling `waiting`, cancels on its way out
    unanswered (the unbind ending `:ml` at its next chunk), and reads a dead process as `ChordsUnavailable`
    (`MlChordModels.DIED`). With `forgetHeard` (the app's) a song's checkpoints go once it is heard and its process
    gone; a hearing that fails keeps them for Try again, and `sweepOld` takes those a day old as the app starts; a
    bug in the process is an IllegalStateException "a bug in
    caracole: …", an OutOfMemoryError said as one, an IOException too (`MlProtocol.NO_ROOM` for a full disk, else
    `CANT_WRITE`). A cancel is asked in the decode's, the mixdown's and the resample's loops and at each reading of a
    heat waited out, as before each chunk. `HeatRules` (Heat.kt, the design's §3.4 table over a
    `Heat.Reading`, `HeatGauge` behind it, `HeatTest` on the JVM): 4 threads, 2 at moderate, headroom ≥ 0.85 or
    Battery Saver; severe waits before a stage (10 s polls, 5 minutes at most); critical stops at the next window batch
    or chunk; under 15 % and not charging refused. `Caracole.phone` refuses to start in the `:ml` process, by its name
    (`MODELS_PROCESS`, the app's `MlProcessTest` holding it to the manifest and `MlProtocol`). `PipelineCheckpointsTest`
    (JVM, the graphs faked) holds the checkpoints; `PipelineTest` (`device-test.sh --ml`) hears each committed clip
    and models.jsonl's `hearing` files (44.1 kHz stereo MP3, 48 kHz stereo AAC) through the process against
    `gates.end_to_end` (WCSR of the Harte labels, beats and downbeats F after the 5 s trim; the clips' frames the
    computer's argmax but at its margins, as many frames; each model's input the computer's length), kills `:ml`
    mid-hearing (`ChordsUnavailable`, this process still answering, the next hearing from `chords.json`), and checks
    every decode file's pcm length. `EndToEnd` is that gate as code (`Gates.of` a meta's `gates.end_to_end`, `Hearing`
    a `hearing` record, `score`, where the frames part, `overAll`: every file passing each gate, each score's least
    and its mean by length; `EndToEndTest` on the JVM). `ParityRunTest` (`device-test.sh --data DIR`: the folder's
    files pushed to `/data/local/tmp/caracole-data`, removed however the run ends; skipped with no `-e data`) runs it
    over songs outside the repository, the owner's, against autochords_reference's `--hearings`, each stage's time
    (`Pipeline.STAGES`: decode, mixdown, resample, chords, beats, told by `hear`'s `timed`, `MlProtocol.STAGES` and
    `STAGE_NANOS` in its DONE, `MlChordModels.lastStagesNanos`), `:ml`'s peak and its `RssAnon`/`RssFile` at the
    highest RSS (`PEAK_ANON_KB`, `PEAK_FILE_KB`, `lastPeakSplitKb`), the platform's encoder delay and padding and the
    decoder's trim; each song's copy and checkpoints removed in a `finally` and an `@After`, and the EXIT trap clears
    `:ml`'s test APK's data after a `--data` run.
- `:autochords` (plain JVM, stage B1): the front ends of the chords from audio, `frontend.Soxr`, `Cqt` and `Mel`;
  `Pcm`, a WAV's or an AIFF's PCM read as libsndfile reads it as float32 (`format`, then `read` a block at a time; a
  header cut short or absurd `Pcm.Unreadable`), `PcmTest` holding it to decode.jsonl's lossless files sample for
  sample; `Mp4`, `MpegHeader` and `Ogg`, what a container's boxes, first frame and last page say of its length as
  mutagen and FFmpeg read them (`ContainerLengthTest`, to the bit against decode.jsonl; an MP4's edit that runs past
  its media ends with the media, `keptFrames`, as FFmpeg's does: bounded by the sample table's total, else `mdhd`'s
  positive duration, never in a fragmented file (`mvex`) nor by a length of 0; an edit of no length is none; a
  fragmented file's `fragments`, its `moof`s' samples timed from the first `tfdt` as FFmpeg times them).
  `Cqt.logFeatures(y)` is btc.py's `cqt_features` (`[frames, 144]`, its 10 s chunks and tail rule), each chunk
  frontend.json's steps replayed: a resample by `Soxr` (librosa's length fix to `ceil(n · ratio)` and its √ratio
  scale on top, the samples kept float32), an octave's STFT in librosa 1.0's centred framing (`Stft.librosa`: only
  the slices its first and last frames read padded, numpy's reflection) times its sparse basis; `Mel.logMel(y)` is
  beat_this's `LogMelSpect` (`[1 + n / 441, 128]`, `Stft.torch`'s framing). `Fft`, radix 2 on doubles; the STFTs,
  sums and logs are float64, rounded to float32 once. `CqtTest` and `MelTest` hold them to frontend.jsonl by its
  gate; the area `autochords` (testFixtures' `AutochordsReplays`: soxr.jsonl and frontend.jsonl, the WAVs read as
  soundfile reads them) runs on the device too (`device-test.sh --area autochords`, :ml's libsoxr). `Soxr`, libsoxr 0.1.3
  over JNI (`resample(x, from, to)`, rates finite and over 0: caracole_soxr.c, python-soxr's `soxr.resample` of a
  contiguous 1-D float32 array at HQ, its `csoxr_split_ch` path), held by `SoxrTest` to vectors/autochords/soxr.jsonl
  within 1e-6, its lengths equal. libsoxr is vendored in autochords/native/soxr/ (LGPL-2.1+; nixpkgs' source, its
  `arm64-check.patch` and caracole's `aarch64.patch` applied: NEON on arm64, so the phone runs cr32s, the SIMD engine
  the vectors are made with on x86_64, where upstream's aarch64 build, python-soxr's there too, is scalar), built by the
  host's cmake and gcc (`hostSoxr`, its folder the tests' `java.library.path`) with the CMakeLists the NDK builds in
  `:ml`. `SoxrArm64Test` runs the NDK's static arm64 build of it (`arm64SoxrDriver`, soxr_driver.c) under
  qemu-aarch64 (the shell's `qemu-user`) over every record: NEON's cr32s the same bits as the vectors, the scalar cr32
  (`SOXR_USE_SIMD=0`) within 6e-7; skipped, saying why, without the NDK or qemu. No arm64 device is a test bed.
  Around the models, exactly as the computer (E8): `Labels` (btc.py's `vocabulary`, `commonName`, `spellForKey`,
  `framesToSegments`, `time`: `round(…, 3)` and the builtin sum ported, as `:autochords` depends on no `:core`; its
  tables labels.json's), `ChordSegment`, `Peaks.of` (beat_this's minimal postprocessor), `Chunks.split` and
  `aggregate` (1500 frames, border 6, `avoid_short_end`, `keep_first`) and `Scores` (`wcsr(ref, est, "majmin" |
  "tetrads")` over BTC's Harte labels, never common names, its sums numpy's pairwise ones, so mir_eval's to the bit;
  `beatF`, `f_measure` alone, and `trimBeats`; its tables scores.json's); `LabelsTest`, `PeaksTest`, `ChunksTest` and
  `ScoresTest` replay labels, peaks, chunks and scores.jsonl, which the area's replay holds on the device too.
  `ChordModels` (`ready()`, `hear(audio, onStep, waiting)`, `runtime`; viewer.autochords', named here by typealias),
  `AudioUnreadable`, `ChordsUnavailable`, `Heard` (the
  design's §4.4 `heard`: contract 1, the stated duration, `recognize`'s chords, beats, downbeats; `json`, `read` of
  that contract alone), `Labels.recognized` (`recognize`'s common names, a run joined), `Checkpoints` and `Stages`
  (`resample`, `chords`, `beats` over files, through `ChordsGraph` and `BeatsGraph`; their buffers fixed by the rates
  and the models: `Soxr.resample(file, …)`, libsoxr's stream, the one-shot's output sample for sample, SoxrTest and
  SoxrArm64Test; `Mel.logMel(n, sample, from, until)`, the whole signal's frames bit for bit, MelTest); `HeardTest`
  (recognized over models.jsonl's argmax gives its segments; checkpoints that won't parse), `StagesTest` (each
  model's length) and `StagesHeapTest` (15 minutes at 48 kHz heard in a 40 MB heap, where the old one-call resample
  runs out of memory).
- `:youtube` (Android library, stage Y0 of the phone-youtube design): yt-dlp under Chaquopy's Python, the engine and
  its process; an `implementation` of both builds since Y5.1, the release's Python, Chaquopy's assets and `libqjs.so`
  for arm64-v8a alone (`releaseYoutubeAbis`, `DropPythonAbis`). Every piece is `youtube/pins.json`'s (Chaquopy 17.2.0,
  its plugin from Maven Central in settings.gradle.kts; Python 3.13; the yt-dlp and yt-dlp-ejs wheels by URL and
  SHA-256; QuickJS-NG's source by its tag's commit and the NAR hash of its tree, never GitHub's generated archive),
  which android/flake.nix reads: the wheels fetched fixed-output into `CARACOLE_YTDLP_WHEELS`, QuickJS-NG's tree
  (`fetchFromGitHub`) into `CARACOLE_QUICKJS_SRC`, `python3.13` on PATH as Chaquopy's `buildPython`, a build without any
  of them failing, naming it (in `checkEngine`, which `:youtube`'s Chaquopy, CMake and test tasks run first, so another
  module builds without them); pip `--no-index --no-deps` from that folder alone. `caracole_ytdlp.py`: `version()`,
  `run(argv, out_path, err_path)` (`yt_dlp.main`, `sys.stdout` and `sys.stderr` line-buffered into the files, never fds
  1 and 2; one run a process; `SystemExit` its status, any other Exception its traceback in the err file and 1, never
  raised). `qjs`, QuickJS-NG's command (MIT), is youtube/native/CMakeLists.txt's: upstream's `qjs_exe` sources (`gen/`'s
  committed bytecode, no host `qjsc` step) by the NDK for both ABIs, libsoxr's reproducibility flags, 16 KB pages, a PIE
  executable named `libqjs.so`, run from the app's native library folder (`Qjs.path(context)`), which needs
  `useLegacyPackaging`, every variant's since Y5.1 (app/build.gradle.kts, and the module's test APK): every native
  library then compressed in the APK and extracted at install (the release 55.6 MB installed on arm64, Chaquopy's
  first-start copy of its assets, about 14 MB, on top: android/README.md's Release); yt-dlp is told of it
  alone (`--no-js-runtimes --js-runtimes quickjs:<path>`), runs it with `--script FILE` and `--help` (its version), each
  piped. `PinsTest` (JVM) holds the wheels to the pins, yt-dlp-ejs to the version yt-dlp's `METADATA` requires and
  `CARACOLE_QUICKJS_SRC` to the tag; `GlueTest` (JVM) runs the glue with the shell's python3.13 over the wheels;
  `YtDlpVersionTest` (its own test APK, `YoutubeTestRunner`: `caracole.network=loopback`; `device-test.sh --youtube`)
  Python started, `version()` the pins', yt-dlp's `--version` alone, an exception out of `main` its traceback and 1, and
  none of the standard library's modules the design leaves out (Chaquopy packages none of them). `QjsTest` (the same
  APK): qjs executable there, its `--version` the tag, a script run, and yt-dlp's `-v` (no URL: its header, exit 2)
  naming `quickjs-ng-<version>` among its runtimes. release-check.sh: the release holds Python for arm64-v8a alone
  (`libpython*`, `libchaquopy_java.so`, `lib*_python.so` and `lib*_chaquopy.so`, classes under `com/chaquo/`,
  `assets/chaquopy/`; none of them, and no Chaquopy asset, for x86_64), `:youtube`'s classes, `YtDlpService`,
  `GateService` and the `:youtube` process in its manifest, `lib/arm64-v8a/libqjs.so` alone, none of the YouTube bench,
  `extractNativeLibs="true"` with every native library compressed, and as many notices under
  `assets/licenses/youtube/` as copyLicences wrote (NoticesTest's `NOTICES`, the APKs held to them by `apkScan`); the
  debug APK the control of each.
  `android/scripts/bump-ytdlp.sh [--older] [VERSION]`, the owner's alone (the design's §7): PyPI's JSON of yt-dlp
  (VERSION's, leading zeros dropped as PyPI's, else the latest) and of the yt-dlp-ejs its wheel's `Requires-Dist`
  names, each wheel's URL `https://files.pythonhosted.org/…/<its file name>` alone (the loopback fake's own host for
  the tests), `nix-prefetch-url`ed and held to PyPI's SHA-256 and its `METADATA`, then pins.json's `ytdlp` and `ejs`
  rewritten (synced, renamed) and the steps left printed; a version not on PyPI, yanked or older than the pin (but
  with `--older`), a wheel elsewhere or of other bytes, or an answer of another shape refused, "pins.json is as it
  was"; tests/test_bump_ytdlp.py runs it against a fake PyPI on loopback (`CARACOLE_PYPI`) and a stand-in
  `nix-prefetch-url`.
  - The process (the design's §3.2): `YtDlpService` in `:youtube` takes one request a process (`TAKEN`, process-wide;
    a second refused and the process ended), each answer carrying its run's id: `argv`, and `network`, exactly
    `LOOPBACK` or `NETWORK` (`HostGate.Mode`'s names, the main process's `caracole.network` sent by the client: the
    `:youtube` process has no test runner and reads no property; anything else refused). It runs nothing once its
    client let go (still bound? before Python, the check and the run), makes the environment `Env`'s alone (the glue's
    `environ`: `HOME` `filesDir/youtube-home`, `TMPDIR` `cacheDir/youtube-tmp` swept before and after, `XDG_*` there,
    `LANG`, `PATH`; no proxy variable), and runs the argv only through the glue's `refusal`, an allowlist: read by
    yt-dlp's own option parser (an alias as what it expands to), it must be one of youtube.json's `phone_argv`
    templates as that parser reads them (`GlueRules`: the templates, their placeholders and targets through
    `YouTubeData`, the search's one count `search_results`, the gate's `PROXY_PATTERN` and `LOOPBACK_NAMES` from
    `HostGate`, and the run's own two folders, `RunFolders`, which the request names and the service checks: in the
    app's storage, no link from there down): each option a template sets with its value or a value its placeholder's check
    passes, every other at the parser's default; under LOOPBACK the
    tests' forms too (`_TEST_FORMS`: `--version`, `--no-check-certificates`, `-v`, KillTest's one `--exec`). It kills
    its process once unbound. `YtDlpClient(context, mode).run(argv, timeoutS, onLine, waiting, folders): Ran`
    (`killed`, `timedOut`) binds it `BIND_AUTO_CREATE | BIND_IMPORTANT`, one run at a time in the process and across
    the app's processes (a `FileChannel` lock on `filesDir/youtube-run.lock` held for the whole run; one it can't take,
    `YtDlpNotStarted` "another run is going", nothing killed or started), each run its own stop
    (`cancel()`, `close()`, a run still waiting its turn included), follows its stderr from `cacheDir/youtube-run/`,
    redacts every gate-shaped address (`PROXY_PATTERN`, whatever option spelled it) from every line, the tail and the
    stdout (`Redact`), kills its pid on a stop (waiting for
    STARTED, else finding `:youtube` by its name; Android then kills the process's cgroup, qjs with it: KillTest;
    never a process-group kill, the uid's processes sharing zygote's), and waits until it is gone before the next;
    `YtDlpStopped` for a process gone unasked, `YtDlpNotStarted` for none started, `Refused` in the glue's words.
    `GateService`, in the main process, gives another process of the app a `HostGate` (`Mode.of(caracole.network)`
    there, or a test's `modeOf` seam: a test never clears that property; rule YOUTUBE), its `proxyArg` and its log over
    a Messenger (`GateService.Client`, each ask matched to its
    answer); nothing it is asked throws on its thread; a client's gates close with its close or its process's death,
    each gate's death recipient unlinked as it closes.
    No argv, so no secret, is logged on either side. `YtDlpServiceTest`, `KillTest`, `GateServiceTest` and
    `AcrossProcessesTest` (`device-test.sh --youtube`), `GlueRefusalTest` (JVM): the downloads through the gate, every refusal, the secret
    in no logcat line, a stop of every kind that leaves no process of the uid but the main one.
    The debug build's YouTube bench (android/README.md, "The YouTube bench"): `YouTubeBenchActivity` in `:ytbench`
    (app/src/debug, never Python there), Settings' row by class name, one session a process, started by a tap alone on
    the network (an intent's `go` under loopback only, never from Recents); its session `BenchRun` drives
    `YtDlpClient` itself, not core's runner (stamped lines, process timings, PSS, an observing gate, loopback
    targets), and holds the terms on the runner's records through the main process's `YouTubeBenchLedger`
    (`DbLedger`): each run RESERVED before its gate opens (one write: provider on, no cooldown, under its budget, 50,
    in 24 h by kv
    `ytbench:runs` and `events` unless `DbLedger.DAY_CAP_LIFTED`, the owner's word of 2026-11-27 (Politeness), its
    stamp kept; given back only for a run that never started), its `events` row
    written in a `finally`, Pace.pauseAfterLastRequest for the first pause, a block's strike and the session's stop,
    the gate's `stopped` bucket an error; the kill check on a gate that reaches 127.0.0.1 alone (GateService
    `OPEN_LOOPBACK`: LOOPBACK narrowed to HostGate's `KILL_CHECK_HOSTS`, never 10.0.2.2) on every phone, none of the
    day's runs spent; a line read less its quotes (`BenchRun.unquoted`), a search no video fits said with the artist
    and title it looked for (`noFitWords`), no second search; its report `BenchReport.of`/`summary` (BenchReportTest,
    YouTubeBenchTest: its `budget`'s `lifted` the switch's, a report without it held to the cap it kept, its `of`; its
    `uid_counts` "loopback too", TrafficStats' uid bytes counting yt-dlp's loopback legs to the gate twice and the
    gate's network leg once, about 3.1 x the gate's bytes), Gate Y0's verdict of the owner's reports `python -m
    tests.helpers.ytbench_gate` (test_ytbench_gate.py: the controller's ruling of 2026-11-27, three songs on mobile data
    with Start and a warm download, no observed session or second day needed, a session lost to the network counted
    for nothing and a song the network failed listed for nothing, a block or a failing song holding the gate until a
    later day's clean session on mobile data clears it (§3.8's trigger on Wi-Fi on two days uncleared), the warm
    download one on mobile data, the uid's bytes explained by the gate's three legs over the idle sessions alone, a
    session not idle set aside from them and named; its one shape tests/fixtures/ytbench/sample.json,
    which BenchReportTest holds to `BenchReport.of`); an observing gate only for an
    ask naming `:ytbench` and never under loopback (GateService
    `OPEN_OBSERVING`; HostGate's OBSERVE reaches no address that isn't public), `-v` under the network only by the
    request's `verbose` leave.
  - The engine (Y1.5): `PhoneDeps.youtube: YouTubeEngine?` (core.youtube: `ready()`, `process()`, `gate()`, `qjs`,
    `cacheDir`), `:youtube`'s `YtDlpEngine` in both builds (`PhoneYouTube`, src/main), null on a phone whose primary
    ABI the APK carries no Python for (`BuildConfig.YOUTUBE_ABIS`: the release's arm64-v8a alone); a device test's process in its place while
    `Caracole.youtubeForTests` is set (the engine's gate, readiness and folder kept: YouTubeEndToEndTest's yt-dlp of
    the committed clip, `device-test.sh --models --sites chords YouTubeEndToEndTest`: Ready, "chords over the lyrics",
    requests LRCLIB's and its own, the audio gone after). Settings' YouTube audio row (server's `YouTubeRow`, the
    design's §7, `BuildConfig.YTDLP_VERSION` pins.json's): no row without an engine (an x86_64 phone of the release),
    whatever `youtubeProblem` says; else "Off (the computer's settings)", "Needs the chord models", "Cooling down
    until …", "Out of date: …" (kv `youtube-outdated` of this version), or "On · yt-dlp 2026.11.23 · N runs in the last
    24 hours" (core.youtube's `DayBudget.runs`, the phone's day's one count: a rolling 24 hours of `events` of `youtube`
    that ran, ok, error or blocked, never budget; no limit said); a read that fails said in the row and logged;
    YouTubeRowTest on the JVM.
    `process()` is a `ProcessYtDlp`, core's `YtDlpProcess` over `YtDlpClient`, a client of its own a run, closed with
    it: the argv the runner built, its folders read off the templates; `Ran` its exit, stdout and stderr (its first 64
    KiB, then the client's tail); `NotStarted` for nothing sent (no bind, a refusal, another process's run, a stop
    before its turn); cut off, thrown as it is (`YtDlpStopped`, a `close` or `cancel` a CancellationException, an
    interrupt an InterruptedException, the process killed first), for the runner to count and log. `gate()` a
    `GateService.gate()`, opened in the main process in the app's one mode (`GateService.gatesMode`), closed by the
    runner after each run. One run at a time with the bench's (the client's turn and file lock: a run while `:ytbench`
    runs one is `NotStarted`, "another run is going"). The client refuses (`Refused`, `NOT_OUR_GATE`) a gate-shaped
    `--proxy` that is no open gate of the app's (`HostGate.isOpen` here, `GateService` `IS_OPEN` from another process)
    before it binds, and stops a run whose thread is interrupted as `cancel` does. `YtDlpEngineTest` (`device-test.sh
    --youtube`): the real runner's download of the host's clip, its argv the template filled, the gate's log 10.0.2.2
    alone, one `events` row; a redirect to a host the gate refuses, `GateRefused` in the data's words, no strike; the
    turn held, nothing started; an interrupt and a close mid-download, cut off and counted; after each no process,
    thread, open gate or run file left, and the secret nowhere.
- Milestones 1–6 are built (docs/android_port.md's status, "Built: milestones 4 to 6"), each route a module of its
  own:
  - `server/routes/Stubs.kt` keeps `GET /lookup` alone, answering "…: not on the phone yet." (409), for good, as the
    library page's search does the lookup page's work; a sheet from a pasted video, its panel and a search's suggested
    video are `YouTubeRoutes`';
  - no declaration is left a lane's stub (`TODO("lane <id>")`); a later round that adds one names its lane so, in a
    file that lane owns;
  - the lookup reaches `PhoneRender` and `SongbookPagesImpl` through their `seam`, the real ones in `Phone`;
    `SongPages.NONE` and `SongbookPages.NONE`, a caracole that makes no page, are what the corpus's lookup replays
    run with, as get.py's words for one (`NO_PDFS`) are recorded.
- Building a `Phone` queues nothing: `Phone.start`, which the app calls once it has wired the queue's `onBusy`, queues
  the render job when the phone owes pages, and a take that owes some queues it after the sync, never inside it.
- `core.catalogues` (core/catalogues/) is the one place that knows GitHub's API: `Names` reads a catalogue file's name
  (catalogues.py's, held by vectors/catalogues/), `CatalogueSource` lists the release, `choose` picks the newest `uploaded`
  file of this app's schema, `download` streams it through `GZIPInputStream` into `stateDir/cache/catalogues/`, checks
  GitHub's SHA-256 and a cap of 20 times its size or 64 MiB, the larger, and says why it can't (a newer or older schema only, no release,
  the hour's share spent, no room). server/lookups' `CataloguesRunner` merges it (`IndexTransfer.merge`), kv
  `catalogues:imported`, saying each step (`MergeProgress.words` through `Paced`), the lookups queued meanwhile let
  go first once GitHub's list is read and once the file is in (`yieldToQueued`), never inside the merge's write; a metered network's stop waits for the go-ahead alone
  (`PhoneKinds` CATALOGUES' `otherwise`, its `formerly` words still a wait); the file a killed import left swept as
  the phone starts (`CataloguesRunner.sweep`). The app's Settings row and first-start offer are native
  (`SiteCatalogues`), the shared library page untouched.
- `core.models` (core/models/), the chord models on core.catalogues' code (`download(gzip = false)`, exact sizes;
  `CatalogueSource.Api`'s `tag`): `ModelFiles.carried()`, models.json's `Pins` or null (on the classpath of the
  debug build's `:ml` alone, as BTC's graph: `:core` ships neither; its tests read both), the one probe of a build
  without them; `read()` (and every default of the pins) requires them, `ModelsNotCarried` else; `installed(dir)` (a stat of each file
  against the `manifest.json` written last: no hash), `verify(dir)` (every byte hashed), `sweep`;
  `ModelsSource.fetch(http, into, onProgress)`: `into` the `Pins.folder`, `stateDir/models/c<contract>/`, written beside it
  (`.c1-<16 hex>.part`, each file fsynced, the graph copied from the app) and renamed into place, the old one put
  aside (`.old`) and deleted (a lone `.old` a kill left is put back first); one fetch at a time, the caller's
  guarantee; every refusal a `ModelsError` (or `Limited`) leaving it as it was, the files it had downloaded and
  checked kept beside it (`.c1.kept`, hashed again by the next fetch); a Content-Length other than the pin's refused
  before its body; no room for twice the download and `MARGIN`, nothing asked. ModelsSourceTest over FakeGitHub; ModelFilesTest the authors' real file
  (`CARACOLE_BTC_WEIGHTS`, android/flake.nix's), skipped without it.
- server/lookups' `ModelsRunner`, `caracole models [--metered-ok]` (`Phone.models`, `commands["models"]`): the
  download as a job of PhoneKinds' `MODELS` kind (`spec()`, key `models:`, the go-ahead's `models:go`, `join` false:
  a request while one waits or runs answered by that one; the queue's one worker and nothing else calling `fetch`
  are its "one fetch at a time"), modelled on `CataloguesRunner`: its one stage says "Asking GitHub for the chord
  models…", "Downloading the chord models · 21 of 55 MB" (its done and total the stage's progress too) and "Checking
  the chord models…" through `Paced`, then "Chord models ready · 55 MB"; a folder installed whole asks nothing; the
  lookups queued meanwhile let go first before and after `fetch`, never between its requests; a metered network's
  stop the catalogues' own (`otherwise`, a wait), a `Limited` a wait too in its own words (the kind's `pauses`), kept
  in kv `models:not-before`; any other refusal "Not downloaded: WHY". `PhoneDeps.models` (a `ModelsSource`, this
  build's `ModelFiles.carried()` pins) is null in a build that carries none (the release's): the job is offered
  all the same and fails "Not downloaded: This build carries no chord models.", `ready()` and `remove()` say so, with
  no request. `ready()` (null, or why not) is the one answer to whether they are here: the files judge
  (`ModelFiles.installed`), never kv `models:installed`, which is a note; `folder()` where they are. `remove()`
  deletes `stateDir/models/` whole (every contract's folder, `.c*.kept`, `.part`, `.old`), no link followed, then kv
  `models:installed`, refused while a job of `USES` (the download; the chords job joins it) waits or runs; `sweep()`
  as the phone starts (ModelFiles.sweep, only beside a folder that is there: a lone `.old` is the next fetch's to put
  back). `bytes()` every file's size, `toDownload()` what a download would ask for now (ModelsSource.toDownload: the
  app's graph and a file found whole beside the folder in `.c*.kept` never counted), the metered stop's size and
  Settings' questions'. ModelsRunnerTest over FakeGitHub, ModelsTest on the device.
- The app's Settings › Chords from audio (`ChordModelsRow`, SettingsActivity's row): its line from `bytes()`,
  `ready()`, `Phone.chordsProblem()` (ChordModels.phoneProblem, MlChordModels' device check: what keeps the phone
  from chords whatever the models' files) and the newest models job ("Not downloaded · 55 MB", "Downloading · 21 of 55 MB", "Ready · 55 MB on the phone", "Not
  downloaded: why", "Waiting for your go-ahead (a metered network)", the job's own metered line, there being no
  `models:asking` record); Download asks §6's question with `toDownload()`, then a metered network's ("You're on a
  metered network. Download 55 MB anyway?", `Caracole.metered` now), then queues `spec(meteredOk)`; Remove asks, then
  `remove()`, its refusal said under the row; the debug Chords bench the section's last button. ChordModelsRowTest on
  the JVM; SettingsChordsTest on the device, `phone.models` asking a GitHub on loopback (`Caracole.modelsForTests`,
  CaracoleTestRunner's `MODELS_PORT` 8746), the real files device-test.sh pushed (`--models`).
- The phone's own job kinds, which Python never queues (render, inbox, backup, restore, catalogues, models), are one table with their
  words, `server/jobs/PhoneKinds.kt`, the phone's alone.
- `app/src/androidTest/` runs on a device or an emulator alone (the device step, below), under `CaracoleTestRunner`:
  `BundledSqliteTest`, `CorpusOnDeviceTest` (one test per corpus area, `core.testing.Replays`,
  `server.testing.ServerReplays` and `viewer.testing.ViewerReplays`; `-e area NAME[,NAME…]` picks some), `NoSitesTest`,
  `LocalServerTest`, `EndToEndTest`, `PinchTest`, `SyncSheetTest`, `ExportImportTest` and `PhoneEndToEndTest`, and
  milestones 4–6's: `ColdSearchTest`, `LookupOfflineTest`, `NoNetworkTest`, `RealTransportOnDeviceTest`,
  `LookupOnDeviceTest` and `PagesOnDeviceTest` (with `--sites`), `PagesServedTest`, `SongbooksOnDeviceTest`,
  `VersionsPageTest`, `GuitarPageTest`, `PrintTest`, `ShareTest`, `ShareLinkTest`, `BackupsTest` and `AlertsTest`;
  and `ModelsTest` (the chord models' job against a GitHub on loopback, with pins of its own).

##### core.http, core.health, core.config

- `core.http` is http.py on the phone, held to Python by `vectors/http/` (tests/test_conformance_http.py), with what
  it reads as data in `data/caracole/http/` (`robots.json`, `ROBOTS_DISALLOW`; `http.json`, http.py's other
  constants; `idna.json`, the idna package's tables and each code point's bidi class):
  - `Urls`: httpx 0.28's URL (`HttpxUrl`: its normalizing and percent-encoding, `withParams` in place of the query, a
    host not ASCII through `Idna`, the idna package's encode and decode), `resolve` its next request's URL (urljoin as
    3.14 has it); a string httpx refuses an `UrlError` named as Python's exception;
  - `Robots.disallows`; `HttpRules` (`stale`, `retryAfter` with email.utils's dates, `isChallenge`, `readOnceMore`);
  - `PoliteClient` and `CachedAnswers`: the cache as http.py lays it out (`HttpCache` under `cacheRoot`, http.py's
    `cache_root`), httpx's request headers (a URL's user and password its basic auth, carried on a redirect as httpx
    carries it), the budget, the pause for given draws, redirects, blocks, LRCLIB's 503, the breaker, each case of
    tests/test_http.py a session of `client.jsonl`; `Response.json()` reads the bytes as `json.loads` does
    (`PyJson.loads(ByteArray)`: a byte that isn't the text's encoding an error, never `text`'s U+FFFD);
  - `RealTransport`: HttpURLConnection, no redirect followed, httpx's header set, a URL httpx won't send refused with
    its UnsupportedProtocol before any socket (ws and wss asked as http and https), gzip and deflate decoded as
    httpx's decoders decode them (zlib's gzip mode: `rules.jsonl`'s `decode`), errors named as httpx's, every host but
    loopback and 10.0.2.2 refused under `caracole.network=loopback` (the host as urlsplit, OkHttp and java.net.URL
    each read it); `RoutedTransport`, a test's sites through the fake sites server (`GET {base}/fetch?url=…`).
  - What the platform does otherwise than httpx, each the owner's to decide (RealTransportChecks pins the second):
    - a connection that fails as the answer is read: the JDK's HttpURLConnection sends the GET once more by itself,
      and Android's OkHttp may on another route, so a site can see two requests for one PoliteClient counted, paced
      and budgeted;
    - Android's OkHttp writes a path's `|` and `^` percent-encoded and its `\` as `/` (httpx sends all three as they
      are; the query is left alone);
    - Android's OkHttp ungzips a body of `Content-Encoding: gzip` itself, a body it can't read failing in its own
      words (DecodingError still);
    - http.py's httpx client keeps the cookies a site sets for the client's life (a run's, a lookup's) and sends them
      back; the phone keeps none.
- core.testing's `Scenarios.replay` replays a scenario record (§3 of the M4-6 plan: the fixture, the cache, the
  answers; the result or what it raised, the requests, the rows, kv, files, events and pauses compared), and
  `RealTransportChecks` the transport against a ServerSocket on loopback (RealTransportTest on the JVM,
  RealTransportOnDeviceTest on the device).
- core.health, health.py's: `Health` (kv `provider:<name>`, read as `get_state` reads it, `PyJson.loads`, strikes
  Python's int of any size by `PyInt`'s rule, a `last_error` that isn't text written back as it was, and written as
  `kv_set_json` writes it; 24 h × 2^(k−1) + 2 h after the k-th block in a row, a running cooldown kept, its strikes
  too; Python's exceptions as the KDoc maps them, which `HealthReplay` checks by class), `EventLog` (each request's
  `events` row, nothing else) and `Strptime` (`strptime("%Y-%m-%dT%H:%M:%SZ")`, CPython 3.14's `_strptime` regex by
  hand; the text written `Stamps.stamp`'s).
- core.lookup's `Pace`, _common.py's lookup pace (`lookup_requests_used`, `lookup_policy`, `requests_today`,
  `within_the_day`, `_last_request`, its kv read as `float()` reads a text, `PyFloat`, and
  `_pause_after_last_request`), and `Clients`, `make_client(..., interactive=True)` over `PoliteClient`: the pause
  after this side's last request drawn before the client's own, kv `http:last_request:<provider>` after each request
  sent, as `f"{time.time():.3f}"` writes it (`PyFormat.fixed`). No lock, ticket or handoff on the phone.
- core.config: `PhoneConfig.read`, kv `phone:settings` over config.json's defaults, each value as config.py would
  hold it or the default (`_delay`, `_count`, the `[match]` and `[rank]` ranges), a provider the phone doesn't know
  passed over, `per_day` the stricter of the two, never lifted (`take` is crossing-phone's).
- Every count, cooldown and record is this side's own. tests/test_conformance_health.py writes vectors/health/ and
  vectors/pace/ (`HealthReplay`, `PaceReplay`).

##### core.html

- The tokenizer (html-tokenizer), `core.html.internal.token`: `Preprocess` (UTF-8 with replacement, CRLF and CR to LF)
  and `Tokenizer`, the WHATWG tokenizer as lexbor 3.1.0 tokenizes for selectolax (its processing instructions, a null
  value for an attribute written with none, an empty doctype identifier a missing one in `CompatMode.of`), driven by
  the tree builder (`switchTo`, `contentFor`, `foreignContent`, asked only once the text before a `<!` came out of
  `next()`); docs/superpowers/specs/2026-11-03-html-parsing.md.
- Held by vectors/html/tokens*.jsonl (tests/test_conformance_html.py: what selectolax's tree shows lexbor's tokenizer
  decided of every fixture page, every page the fake sites build, an edge set and seeded tag soup; never a
  `<template>`'s contents, which selectolax's tree doesn't reach), which `HtmlReplay` reads through `TokensTree`, a
  small tree builder of its own (the active formatting elements reconstructed, the tokenizer's names compared as it
  gives them).
- The tree, nodes and selectors (html-tree), `core.html.internal.tree` and `.select`:
  - `TreeBuilder`, lexbor 3.1.0's tree builder ported insertion mode by insertion mode, with its tables of each tag's
    categories (`Tags`), and lexbor's own readings: `<select>` a scope with no "in select" mode, a token "in table"
    hands to "in body" never processed again, the implied end tags by name in any namespace, `sup` no breakout tag,
    text after a frameset's `</html>` read whole;
  - `Dom.kt`, lexbor's linked nodes, a template's contents a fragment no walk reaches;
  - `Selectors`, lexbor's matching of caracole's selectors: an element once for each selector of a list it matches,
    a node's search finding itself and its combinators reading the whole tree, the HTML attributes whose values match
    without case;
  - `HtmlDoc` and `HtmlNode` as selectolax's tree and nodes (`text`, `children`, `attributes`, `replaceWith`,
    `insertAfter`; a processing instruction's tag `-pi`, selectolax's None, and `iter()` `children(includeText =
    false)`: the spec's "For the site parsers");
  - `TreeBuilder`, `Tags` and `Selectors` ported from lexbor's C, with its copyright, under the vendored
    `core/html/internal/LICENSE-lexbor` (the Apache License 2.0 and lexbor's NOTICE).
- Held by vectors/html/tree*.jsonl and mutations.jsonl (tests/test_conformance_html.py's tree half: every page's
  shape, texts, the parsers' selectors and harptabs.py's `<pre>` read; the tree's edge set; selectors alone; 400 seeded
  tag-soup edits of the fixtures, by digest), which `HtmlTreeReplay` reads, the token vectors through core.html's tree
  too; the spec's one divergence, an input's duplicate `type` in a table, pinned in `TreeTest`.

##### Lookups on the phone

- core.lookup's `Lookup` is get.py's `_Lookup` (`internal/LookupRun.kt`), held to it by vectors/lookup/words, asking
  and after_the_sheet (tests/test_conformance_lookup.py, `LookupReplay`):
  - its stages in get.py's order and labels (`LookupWords.STAGES`), each reported as it starts and ends;
  - the song found, or added (`LibraryStore.add`, the phone's wanted.txt line), the pages picked recorded through
    `OverrideWriters`; a refusal (ignored, a tab of a kind caracole doesn't use, a pick that can't be recorded) the song
    stage failed and the rest skipped;
  - the sheet's order (a LaCuerda pick first, Ultimate Guitar's first pass, LaCuerda when no sheet is kept, asked once
    a lookup), its running detail `SHEET_FROM`; the lyrics put together as `_then` does; what follows the sheet within
    `SHEETS_SHARE`; `_owed`; the sheet readable as `_check_readable` says it; the closing `record_ok` and kv
    `lookup:songs`.
- Each site's stage is its lane's file of core/lookup/sites/, called with a `StageContext` whose `asking` is the
  envelope or `InteractiveAsk.afterTheSheet`. A stage words its site's answer as get.py's work does and every other
  `Asked` through `LookupWords.end`; `LookupWords.NOTHING_TO_ASK` is get.py's None: in the lyrics, Megalobiz's or
  AZLyrics' nothing to ask (`_then` says what the sites before said), anywhere else `done` with no words. A
  `SharedFolder` fails the stage in get.py's words; anything else is a bug, said in its stage and `LookupResult.bug`.
- `InteractiveAsk` is get.py's `_ask`: `_usable`'s words, a block recorded, an error counted, a spent budget worded
  the lookup's, the hour's or kept for sheets; one client a provider a lookup (`Clients.interactive`, at the lookup's
  run or a command's own, `lookup:lacuerda-search:`). A block alerts once (`Alerts.blocked`): on the phone a lookup
  alerts, where the computer's sends none, since the phone has no nightly run to tell.
- What a caracole with no ChordPro, no wanted.txt and no index.html says is get.py's too, recorded in the corpus and
  used by nothing on the computer: `ADDED` (the song stage), `NO_PDFS` (the pdf stage, skipped while `SongPages` is
  `NONE`), `PAGES_MADE` (once the phone makes the song's pages), `LIBRARY_PAGE` (the pages stage). The songbooks stage
  says "not on the phone yet" while `SongbookPages` is `NONE`.
- `Lookup.run` blocks: a runner calls it inside one `Database.writeBlocking` on the queue's worker, in autocommit, so
  each event, block and kv record commits as it happens; a write inside it throws; a queue that stops stops it at its
  next stage.
- server/lookups' runners: `GetRunner` (`caracole get`, its options checked as commands/get.py checks them,
  `LookupLines` and `LookupWords.totals` its output; a refusal or a bug exits 1), `VersionsRunner` (`--keep` and
  `--keep-more` to `VersionsCommands`; `--choose` as get `--tab` at the version's address; `--clear` as `removePin`,
  then get), `LaCuerdaRunner` (`--artist`, `--search` to `LaCuerdaCommands`) and `HarpTabsRunner` (`--artist`).
  - A refused lookup's step ends with `error: Nothing fetched: ….` and a bug's with `error: a bug in caracole: …`
    (the queue writes an `error:` line for every step that fails), where the computer's says the first plainly and
    logs the second; the stage the library page's line reads says the same on both.
- A lookup command (core/lookup/sites/'s `VersionsCommands`, `LaCuerdaCommands`, `HarpTabsCommands`, `UgLinkCommands`)
  runs in `LookupJobs.context`, a `CommandContext` (the whole contract: LookupWords' section on a lookup command):
  - it says its Python's `--progress` events as `LookupWords.progressLine`s (`stageLine`, `songLine`; the queue's
    `JobCommands.progressLine` to the byte, a test checks), its job's events when it reports them
    (`JobCommands.reports`, as web/jobs.py's emit reads them), and its other lines; its last line is the one it
    returns;
  - it asks through `c.asking`, which records a block (and alerts once) and an error: a command never records
    either itself;
  - it records its own good run where its Python does: `Health.recordOk` after `Health.answeredAny` of its run
    (`LookupWords.lookupRunOf(c.now)`, `searchRunId` for LaCuerda's search), or after any request where versions_cmd.py
    counts them; the computer's lane commands count their own client's answers since lane 6
    (`PoliteClient.answered_any`, two lookups of one second sharing a run id there), the phone, one job at a time, its
    run's;
  - `versions --keep` and `--keep-more`: the runner begins the song stage and finds the song, the command says from
    `{"song": …}` on, and at its `pdf` and `pages` running events (versions_cmd.py's: a version kept, pdf then pages;
    any other outcome past its refusals, pages alone) the runner makes the song's pages and ends both stages in the
    phone's words (`NO_PDFS` while `SongPages` is `NONE`, `LIBRARY_PAGE`), the command's own ends of them unsaid
    (`LookupJobs.CommandLines`).

##### Site passes on the phone

- Ultimate Guitar's pages (ug-pages):
  - core.ug's `UgPage`, `UgArtist` and `UgLookup` are ug/page.py, ug/artist.py and ug/lookup.py: the js-store read
    through core.html and PyJson.loads, each field as Python's `float()`, `int()` and `str()` read it
    (internal/pages/`PyValues`: a list's or an object's text its repr), and half of a surrogate pair U+FFFD in every
    string, keys too (ug/page.py's `_whole`, the computer's fix too); `IndexTab` Python's, its label and its url.
  - `ArtistTabs.store`, `keepOnly`, `forget` and `backfill` (from the phone's own cache, `CachedAnswers`) write
    artist_tabs.py's rows; each page a store keeps tabs of is noted (`Reads.note`, site `ug`) for the next push to the
    computer, at the store's own time (`now`) or the read's if later, never moved back: a list stored from an older
    copy in the cache after a push is still sent.
  - A number past a Long (an id) or an Int (a version, a vote count, an artist page's number) is none where Python
    keeps it (the tab unusable, 0, the next number read), and a page nested deeper than `PyJson.MAX_DEPTH` a
    PageParseError: UG writes neither.
  - `UgPagesReplay` (area `ug-pages`) replays vectors/sites/ug_pages*.jsonl and ug_artist*.jsonl
    (tests/test_conformance_ug_pages.py).
- core.ug's `Rank`, `Coverage` and `SheetVersions`: rank.py, coverage.py and sheet_versions.py, Python's numbers and
  lists for the same inputs (versions.py's `complete` and `replaces_sheet` are `Rank`'s).
  - A score is Python's float arithmetic (`prior_mean` the builtin sum's, `Py.fsum`), a ranking a stable sort on
    Python's keys: a float as `==` and `<` compare it, ties on `(version, len(tab_id), tab_id)` in code points.
  - Coverage: its regexes through PyRegex, `str.splitlines` and `split()`, lengths in code points, `partial_ratio`
    as `Fuzz.partialRatioAlignment`, Chinese as pinyin.
  - `SheetVersions` reads the tables with sheet_versions.py's own SQL (`inLibraryOf` in four queries), a kv list's
    items as Python's `str()` makes them, `asData` in Python's member order (a record's `dumps`, json.dumps'
    text, checks it byte for byte).
  - tests/test_conformance_rank.py writes vectors/sites/ug_rank.jsonl, ug_coverage*.jsonl (every fixture sheet
    against every fixture lyrics) and ug_sheet_versions*.jsonl (over a fixture library): `RankReplay`. They are
    a share of the `sites` area every site lane writes: a record only where it can answer otherwise than another
    (a policy by the fields that differ from `RankPolicy()`'s, which its first record gives).
- UG's lookup path for a matched song (ug-fetch-sheet): core.ug's `UgFetch` (`processSong`, `keepVersion`,
  `checkedSince`, `needsArtistPage`), ug/fetch.py's for one song, never its bulk work (no fetch_songs,
  rescore_kept_sheets or handoffs), in internal/fetch/:
  - `Pages`: `_read_page` and its one more fetch past the cache, kv `ug:unreadable:<tab>` (7 days, doubling, 90 at
    most), RobotsClosed neither gone nor unreadable, a 404 a version gone, each page's versions recorded
    (`_check_links`), its artist's page learned (kv `ug:artist_url:`);
  - `Slots`: the groups rated from the lowest unrated id (a slug naming no part first), the pins and the pinned URL,
    the sheet slot (another site's sheet replaced only as `replaces_sheet` says, LaCuerda's you picked never but by a
    pin, a complete one retiring the auto sheet) and the tab slot; `Beside`: the versions kept beside the sheet, beside
    a pin from the cache alone, yours, one text under one name (kv `sheet_versions:same:`);
  - `SongFetch`: `_finish` (status, `ug_dirty`, `ug_checked_at`, kv `ug:blocked:`), `_drop_undone`, `keep_version`'s
    answers; info.json is PhoneRender's (`InfoJson`, as the lookup's pdf stage makes the song's pages): the fetch
    writes none, and a song's `updated_at` is the fetch's time;
  - `ArtistPages`: the artist-page route (ug-fetch-artist's, below).
- The lookup's UG stages (core/lookup/sites/Ug.kt): `UgSheetStage`, the first pass (one versions page, one sheet
  scored, nothing kept beside it, no tab: "tab N from Ultimate Guitar"), `UgStage` the rest ("sheet N · tab M · kept
  beside it: …"), `_ug_ready`'s skips (none for a song the index can't settle whose artist's page is known,
  `ArtistRoute.artistIsKnown`), and what asking came to in `LookupWords.end`'s words; the envelope (InteractiveAsk)
  marks the song owed a fetch (`_owed`), and the frame (LookupRun) asks the ug stage within `after_the_sheet`, and
  LaCuerda after a sheet stage that kept none.
- tests/test_conformance_ug_fetch.py writes vectors/lookup/ug_sheet.jsonl and ug_keep.jsonl, scenario records, and
  ug_sheet_stages.jsonl, get.py's words for the two stages and `_ug_ready`'s answers (`UgFetchReplay`, area
  `ug-fetch`).
- UG's artist pages (ug-fetch-artist): a song the index can't place looked up on its artist's UG page, ug/fetch.py's
  route, in internal/fetch/`ArtistPages` (`processSong` calls it, as `process_song` calls `_artist_page_route`):
  - the page's address: `[artist_url]`, a tab page there read once for the page it links to (kv
    `ug:pasted_tab:<tab>`, or what is wrong with it: `ArtistRoute.pastedPageProblem`), a learned one (kv
    `ug:artist_url:<artist key>`), else `LEARN_TRIES` slugged tabs of the artist read for it;
  - the chords list, then those its filter bar offers (the unfiltered page when a list answers 404, a 404 there a
    page gone), `artistPagesPerKind` pages a kind, 30 days from the cache (a stale copy no answer: BudgetExhausted
    once the budget is spent), every page stored for searches (`ArtistTabs.store`, `Reads.note`d for the computer);
    a block, an error or a page that won't parse raised, never a miss (no `ug:artist_page_checked:`);
  - titles as `_best_title` takes them (`TITLE_MATCH` 90, `TITLE_MARGIN` 8), a `[reject]`ed song out first, the
    match written with step `artist_page`; the lists of a song matched there, or of one whose index tabs hold no
    chords, read as its versions; `ArtistRoute.artistIsKnown` what the UG stages ask first.
- `versions --keep` and `--keep-more` (ug-fetch-artist): core/lookup/sites/`VersionsCommands`, versions_cmd.py's
  `keep` and `keep_more` through a `CommandContext` and the song's `LibraryStore` (the `[block]`, gone and "the
  sheet already" checks, `KeepRefused` its `fail`, exit 1; `keepVersion`; `_stopped`'s words; `Health.recordOk` only
  after a request; keep-more in `SheetVersions.mayKeep`'s rank order through one client, `noteUnkeepable`, "kept N of
  M"), saying its `pdf` and `pages` stages where versions_cmd.py makes the song's pages, its last line returned, which
  lane lookup's VersionsRunner says after them.
- tests/test_conformance_ug_fetch.py writes vectors/lookup/ug_artist.jsonl and commands_versions.jsonl too (the
  same `UgFetchReplay`).
- core.match's `Matcher`: match.py for a lookup's song (`matchAll`, `candidatesOf`; the ladder, `Ladder`; the index
  as it reads it, `IndexView`), each answer Python's for the same index and overrides.
  - Its scores are core.fuzz's: `ratio` and `extract`, `osaDistance` and `extractDistance` (rapidfuzz's OSA, the typo
    route's: the nearest first, then by index), and `tokenSetRatio` (music.py's names); each rounded as
    `round(score, 1)` (`Py.round`), each list sorted in code points, a range's bound U+10FFFF as one code point.
  - `matchAll` writes as `_save` does, through `Versions` (`updateSong`, `markStale`, `refreshStatus`), the candidates
    as json.dumps' text; an index not complete (no `ug:index:built_at`) records no miss and undoes nothing the ladder
    found.
  - `IndexView` loads the artist keys, the title keys and the catch-alls' songs whole only once a step reaches them: a
    song steps 1 and 2 settle loads none (MatcherTest).
  - A stored candidate may name no step (`MatchCandidate.step` null, as match._stored's `c.get("step")`):
    `candidatesOf` gives those that name a UG song.
  - The lookup's match stage (core/lookup/sites/Match.kt, `MatchStage`): `ArtistTabs.backfill` from the lookup's
    cache alone (`StageContext.cacheDir`, which the frame gives every stage whatever asking it passes; its keys made
    current first), then `matchAll` over the song, get.py's words for what it came to.
  - tests/test_conformance_match.py writes vectors/match/ (test_match.py's cases harvested, a few views over keys past
    U+FFFF, a seeded library, the stage), tests/test_conformance_fuzz.py vectors/fuzz/osa*.jsonl and
    token_set.jsonl: `MatchReplay`.
  - MatcherBench (`gradle bench`, 1.5 M rows, its own heap) times one song and its heap; a song that reaches
    title_only loads every title key, about 100 MiB on the JVM, the phone's to measure.
- core.lyrics' `Lrclib`, `Megalobiz` and `AzLyrics`: lyrics.py, megalobiz*.py and azlyrics*.py for a lookup's song,
  and their stages, get.py's `_lrclib`, `_megalobiz` and `_azlyrics` (core/lookup/sites/, its words; lane lookup's
  frame puts them together as `_then` does).
  - An answer read as json.loads reads it (PyJson: a number an int or a float as Python's, `lyrics.internal.PyValues`
    for `isinstance` and `repr`), a length `round()`ed half to even, Megalobiz's stamps as
    `f'{ms % 60000 / 1000:05.2f}'` writes them (PyFormat), AZLyrics' pages by Python's regexes over the text and
    `html.unescape` (PyHtml).
  - LRC's stamps are read in one place, library/internal/LyricsFiles.kt (any decimal digits, a minute as long as
    `int()` reads, as Python's `\d`, `int()` and `float()`, their errors past 4300 digits or a float's range too), for
    `Lyrics.fromRecord` and the files written: `lyrics.txt`,
    `lyrics.lrc` and `lyrics_json` byte for byte.
  - kv `lyrics:failed:`, `megalobiz:checked:` and `azlyrics:checked:` as Python's: an error never a miss, a song
    LRCLIB missed back to pending; Megalobiz's per-day limit is the lookup's client's (`Pace.withinTheDay`); info.json,
    the link back's, is PhoneRender's (`InfoJson`), written as the lookup's pdf stage makes the song's pages.
  - tests/test_conformance_lyrics.py writes vectors/sites/{lrclib,megalobiz,azlyrics}.jsonl (the parsers and pickers
    over tests/fixtures/) and vectors/lookup/ the same (each pass of one song as a scenario record): `LyricsReplay`.
- LaCuerda's pages and search (lacuerda-pages), core.lacuerda:
  - `LaCuerdaPages`, lacuerda.py's pages read as the computer reads them (core.html's tree, PyRegex for its regexes
    over the raw page, Python's str and int on code points): an artist page's songs, their popularity and the
    artist's name, the "aqui llega:" body, a version's sheet in UG markup, an answer of its search (every page cut
    short a `LaCuerdaParseError`), `parseLcd`, `bestAcordesVersion`, `matchTitle`, `looksSpanish`, `searchWords` and
    `searchUrl`; the listings' pages are the nightly run's alone, never read on the phone;
  - `LaCuerda`'s store writers, lacuerda_index.py's `store_songs`, `store_artist_page`, `store_search` and
    `_replace`, each noting the page it wrote (`Reads.note`: "<slug>/", or `busca.php` for an answer with rows, at
    the store's `at`), which index-push sends;
  - `LaCuerdaSearch`, lacuerda_search.py: `queryKey`, `asked`, `answersWell`, `answered`, the failures
    (`recordFailure`, `forgetFailure`, `failed`, `Failure.said`), `searchesUsed`, `gate` (and its /api/search shape,
    `SearchGate.of`, of `answersWell` over the route's own kept hits) and `search`: its one request, the answer
    stored and its kv in one savepoint, the count it states Python's int of any size;
  - tests/test_conformance_lacuerda_lookups.py writes vectors/sites/lacuerda_pages.jsonl and lacuerda_store.jsonl,
    vectors/lookup/lacuerda_gate.jsonl and lacuerda_search.jsonl (`LaCuerdaReplay`, area `lacuerda`).
- LaCuerda's sheets (lacuerda-sheets):
  - `LaCuerdaSheets`, lacuerda_fetch.py for a lookup's songs (`only`): `_to_try` and `mayAsk`, the artist's slugs in
    `_artist_songs`' order (a slug given first, the listings' `artistSlugs`, then `artistSlugCandidates`; a 404 or
    "aqui llega:" moving on), each page cached 30 days (a stale copy no answer once the budget is spent), your pick's
    page, `_record` and `_keep` (`sheet.json` as `json.dumps(indent=2)` and a newline, then `sheet.txt`; no
    savepoint, as Python's), `lacuerda_checked_at`, a shared folder waiting; and `readArtistPage` (its `first`, which
    Python's lacks, asked in place of the name written as a slug). The songs re-keyed first, as `list_songs` does.
    Each page stored is noted for the next push. Python's nightly parts are left out: the popular artists' pages, the
    listings pass, the handoffs, info.json;
  - core.lookup.sites' `LaCuerdaPickStage` and `LaCuerdaStage`: get.py's `lacuerda()` through the stage's asking, its
    words for what the pass came to, and `LookupWords.end`'s for what asking came to;
  - `LaCuerdaCommands`, commands/lyrics.py's `lacuerda --artist` and `--search` (with `progress`, its default, the
    search's `--progress` lines said; the last returned), the cooldown and the gate checked as Python checks them,
    the block and the error recorded by the asking, a good run by `LookupWords.lookupRunOf`'s run, which the runner's
    asking logs under; the search re-keys the songs before `answered`, as `search_library`'s `list_songs` does, and
    stores no cached page first (`backfill_cached`: the phone stores each page as it reads it);
  - tests/test_conformance_lacuerda_lookups.py writes vectors/lookup/lacuerda_sheets.jsonl (the pass, an artist's
    page, and get.py's stage over the record's client alone) and commands_lacuerda.jsonl (through InteractiveAsk, as
    LaCuerdaRunner asks): `LaCuerdaReplay.sheets` and `commands`, each record's `noted` the pages the phone notes.
- A song's lyrics searched under a name typed (lyrics-search, the chords-on-the-phone plan's E29): core.lookup.sites'
  `LyricsSearchCommands`, lyrics_search.py (`search`, `askAnew`, `notNow`, `stopped`, `lastLine`, `notes`, `rowFacts`,
  `askedLine`, `lastSearch`, `keptSearch`, `rowOf`; `lines`, commands/lyrics.py `_lyrics_as`'s), through a
  CommandContext's asking, LRCLIB's get a second ask of its client; its name noted by `OverrideWriters.setLyricsName`,
  kv `lyrics-search:<id>` as Python writes it; run by server/lookups' `LyricsRunner` (`lyrics --song --as`, a lookup:
  `JobCommands.isLookup`, `lyricsSearchSteps`). tests/test_conformance_lyrics_search.py writes
  vectors/lookup/lyrics_search.jsonl, `LyricsSearchReplay` over LookupScenariosReplay's world. A block alerts once, as
  every lookup's on the phone; the audio's length is the line's, its YouTube video's, else its own file's by the
  phone's examiner (`AudioStore.formatAndLength`, LyricsRunner's hook). Its read-back (`lastSearch`, `keptSearch`,
  `rowOf`, `askedLine`) is held by vectors/lookup/lyrics_kept.jsonl.
- A row of that search made the song's lyrics (lyrics-pick, E30): core.lookup.sites' `LyricsPickCommands`,
  lyrics_pick.py's song and lyrics stages (`findSong`, `cachedLrclib`: LRCLIB's record from the search's answers in
  the phone's HTTP cache, no request; `lyrics`: the files, `setLyricsRecord`, then `askAnew` and the song found in one
  savepoint), and server/lookups' `LyricsPickJob` (`lyrics --song --record --progress`, `lyricsPickSteps`, the
  queue's): its chords `Relay.onto` where the auto sheet keeps what was heard, up to date (`autochords_mtime` its
  `audio_mtime`: staged.py's UP_TO_DATE, no model), else the phone's own audio through `ChordModels`
  (`AudioRunner.keepAutoSheet`, the audio job's keep, at the job's stamp), else skipped in lyrics_pick.py's words, and
  where the phone hears no chords now in its own (lyrics_pick.py `PHONE_NOT_HERE`, `PHONE_NOT_DOWNLOADED`: no nightly
  run makes it later); the record noted in the lyrics' savepoint, a failure to note it putting the files back; pdf and
  pages PhoneRender's, which write info.json, so a picked record's `lyrics_from` follows at the pdf stage (a song with
  no sheet: at its next render). tests/test_conformance_lyrics_pick.py writes vectors/lookup/lyrics_pick.jsonl (LyricsRunnerTest).
  `--clear` is `LyricsPickCommands.clearPick` (lyrics_pick.py `clear_pick`, no request; a lyric file that can't be
  removed said in Python's `strerror`, a dangling link removed), then the song's pages; lyrics_pick.jsonl holds its
  clears too (each site's record that gave the lyrics, one that didn't, none, a file that won't go).
- The card's lyrics panel on the phone (E31): server/routes' `LyricsRoutes` (`POST /lyrics/search`, `GET
  /api/lyrics/search`, `POST /lyrics/pick`, `POST /lyrics/clear`, web/lyrics_routes.py's answers and refusals, the
  audio's length by the phone's examiner), `server.lyricsSearch` true (LibraryPage.kt);
  tests/test_conformance_lyrics_routes.py writes vectors/web/lyrics_routes.jsonl; LyricsSearchTest on the emulator
  (`device-test.sh --sites lookups LyricsSearchTest`) searches, lists, takes a record and re-lays the auto sheet.
- harptabs.com (harptabs): core.sites' `HarpTabsFetch` and `HarpTabsPages`, harptabs.py, harptabs_fetch.py for a
  lookup's song and harptabs_index.py's `read_artist`, over the index the computer's sync brings (the phone reads no
  sitemap and makes no artist pass):
  - its pages read as selectolax reads them (core.html), their JSON-LD by `PyJson.loads` (a value's `str()` as
    Python's), their counts by `PyFloat` and `PyInt`, whole as Python's int: one past SQLite's integers is its
    OverflowError only where it is written (`HarpTabsPages.sqliteInteger`), never on a page passed over;
  - a song's candidates, its artist by name forms, the most viewed kept as `harmonica-N.txt` (`Numbering`, `Kept`,
    `Versions`; info.json is PhoneRender's), kv `harptabs:checked:` and `:pick`;
  - an artist page stored (`store_artist_page`, `store_gone`), each noted for the next push (`Reads.note`, site
    `harptabs`, the page's path);
  - the lookup's harptabs stage (`HarpTabsStage`, the rest of what asking came to `LookupWords.end`'s) and
    `caracole harptabs --artist` (`HarpTabsCommands.artist`, its one line, commands/lyrics.py's words), through
    StageContext's and CommandContext's asking;
  - tests/test_conformance_harptabs.py writes vectors/sites/harptabs.jsonl, vectors/lookup/harptabs.jsonl,
    harptabs_artist.jsonl and commands_harptabs.jsonl: `HarpTabsReplay` (asking through `InteractiveAsk` over each
    record's client, each request with caracole's own user agent, the pages noted beside Python's rows).
- gametabs.net (gametabs): core.sites' `GameTabsPages` (gametabs.py's tab and game pages read through core.html,
  `parseTabPage` and `parseGamePage`) and `GameTabsFetch` (gametabs_fetch.py for a lookup's song alone, no sitemap
  or game page read), and the lookup's gametabs stage (core/lookup/sites/GameTabs.kt, get.py's words, the envelope's
  `LookupWords.end`'s).
  - A `data-tab` value as gametabs.py reads it: Python's truth and `str()` of each JSON value, its ints unbounded
    (`BigInteger`), each as the float Python makes of it (the nearest, a tie to the even one, whatever the platform's
    `BigInteger.toDouble` rounds), one too large for a float an OverflowError as `math.isfinite` raises; a version's
    votes are the views as SQLite holds them (64 bits, sqlite3's OverflowError past them).
  - Candidates by game (its slug's key, its page's name) or composer, `CANDIDATES` (4) at most, the most viewed
    first, then by path in code points; the most viewed page that fits kept as `gametab-N.txt`, a pick
    (`[gametabs]`) read alone; kv `gametabs:checked:<id>` and `:pick`, of the lookup's song alone; the game pages'
    title keys made again first (`SiteKeys.gametabsEnsureCurrentKeys`, kv `gametabs:games:keys`), as the computer's
    pass does.
  - tests/test_conformance_gametabs.py writes vectors/sites/gametabs.jsonl (the parsers over tests/fixtures/gametabs,
    helpers/gametabs_site.py's pages and an edge set; `title_key`, `game_forms`, `song_forms`, `fits`) and
    vectors/lookup/gametabs.jsonl (the pass's scenarios, each request with caracole's user agent): `GameTabsReplay`.
- gtptabs.com and MuseScore (tab-files), core.sites' `GtpTabsPages`, `GtpTabsFetch` and `MuseScorePages`: gtptabs.py's,
  gtptabs_fetch.py's and musescore.py's rules for a lookup's song, every regex PyRegex's.
  - `GtpTabsPages.parseArtistPage`: an artist page through core.html's tree, its link text collapsed as `split()`
    does, the size and upload-number regexes Python's.
  - `GtpTabsFetch.gtptabsFiles`: the pass with `refresh_index=False` (the computer's index, no sitemap read), its
    candidates (internal `GtpPass`: by the artist keys, "Last, First" and without hyphens; sorted by (-stars,
    version, id)), artist pages cached 30 days (a stale copy BudgetExhausted), three downloads at most past the
    cache, the file kept as the lowest free `guitar-N` (Kept, Versions, Numbering), kv `gtptabs:checked:` and
    `gtptabs:unusable:`, `PagesNotFiles`; never a replace or a delete; info.json is PhoneRender's.
  - `sniff` reads a Guitar Pro 7 zip's central directory as CPython's zipfile does (internal `ZipNames`: the end
    records, zip64's, cp437 and UTF-8 names, the Unicode Path field), never java.util.zip's stream; inbox-share
    reuses it.
  - `titlePage`, the Requests tab's; `MuseScorePages.songPages`, links from the index alone, with no client.
  - The lookup's gtptabs stage (core/lookup/sites/GtpTabs.kt, `GtpTabsStage`) in get.py's words, the envelope's
    `LookupWords.end`.
  - tests/test_conformance_tab_files.py writes vectors/sites/gtptabs*.jsonl, musescore.jsonl and
    lookup/gtptabs.jsonl (its stage records asked through InteractiveAsk with the records' clients):
    `TabFilesReplay`, area `tab-files`.
- A UG link pasted into the library page's search box (ug-link), the plan docs/superpowers/plans/2026-11-17-ug-link.md:
  - core.ug's `UgUrls.readLink` (ug_urls.py's, its `SPACES`), and `UgLinks`, ug/link.py: `known` (no request: the
    database and the phone's HTTP cache alone), `read` (a tab's page by the fetch's rules, `Pages.readTabPage`, then
    its artist's lists read whole, `ArtistPages.readArtistPage` of no song's over a `ListReading`; a cached tab whose
    artist page wasn't read within 30 days is `auto`, its lists read), `named` (the songs and names a link stands
    for, the routes' and the command's lines alike), `said`, `knownLine`, kv `ug:link-failed` (one of OwnRecords'
    records that gate a request);
  - `caracole ug --link` is core/lookup/sites/`UgLinkCommands` (commands/ug.py), run by server/lookups'
    `UgLinkRunner` in a CommandContext; it asks a tab's page and its artist's lists apart (`UgLinks.readPage`,
    `readLists`), so the envelope records a block or an error of either and tells a block once, as every lookup's on
    the phone (the computer's command tells none), one of the artist's page the read's `stopped`, never the link's
    failure;
  - server/routes' `UgLinkRoutes`, web/ug_link_routes.py: `GET /api/ug/link` and `POST /ug/link` (a job of no song's
    under `JobCommands.UG_LINK`, among `INDEX_READS`, its stages `tab` and `artist`, an artist's link the second
    alone); `/api/search` gives a pasted link no hint, no unseen and no LaCuerda gate (Found's `isLink`);
  - tests/test_conformance_ug_link.py writes vectors/web/ug_link.jsonl (read_link's shapes, both routes over each
    scene, its library folder among its records) and vectors/lookup/commands_ug_link.jsonl (scenario
    records, each page stored noted for the next push): `UgLinkReplay`, area `ug-link`.
- UG's artist directory (ug-directory), the computer's bulk work: the phone reads no listing and makes no pass, and
  takes `ug_directory` (schema 16) with UG's index at a merge.
  - core.index's `Merge` takes it as `_plan_directory` does: a row seen later its listing columns, a page read later
    its read columns, a letter's round of kv `ug:directory:letters` where it got further, no row removed; under a
    sync's clock (`notAfter`) a time the file gives after it is never newer. `newest` reads its seen, read and rounds'
    times. core.ug's `UgDirectory` is its keys (`formsText`, `artistKeyOf`, `ensureCurrentKeys`, kv
    `ug:directory:keys`, made current after a ug merge); OwnRecords keeps `ug:directory:` as an index's progress.
  - core.search's `Search.directoryArtists` (`DirectoryHit`) is search.py's `directory_artists`, and Found's
    `ug_directory` `/api/search`'s (`UgLinks.known`'s state of each artist's page, with no request; none of the
    index's hint or unseen beside it); its Read their page on UG posts `/ug/link` with the row's `url`, `UgLinkRoutes`'
    read of that artist page.
  - vectors/index/ (`IndexReplay`, area `index`), vectors/search/index.jsonl (`SearchReplay`) and
    vectors/web/api_search.jsonl (`WebReplay`).
- YouTube's rules (core.youtube; the phone-YouTube plan's Y1.2), youtube.py's phone half over
  data/caracole/youtube/youtube.json, no flag, pattern, prefix or word of yt-dlp's typed (NoLiteralsTest, HostGate.kt
  read too):
  - `YouTubeData`: `read()`, `argv` (phone_argv: a kind's template, each element filled in one pass, a value never
    read again; its refusals, `Refused`), `searchTarget`, `watchUrl`, `pattern`;
  - `Videos`: `parseSearch`, `parseVideo` and `searchQuery` (PyJson.loads, Python's `str()`, truth and `float()`, an
    `AnswerError` in a ProviderError's words, an int duration too big for a float one too, on both sides; past
    PyJson's depth, its own words, a well-formed answer too, which Python reads: parse.jsonl's `phone` record);
  - `Choose`: `choose` and `ranked` (`_ranked`'s key: tier, title, closeness, official, rank), in code points, names by
    core.keys.Normalize, patterns through PyRegex;
  - `Classify`: `of` (classify), `ofRun` (the exit status first), `OK_EXIT`, `OK`, `GATE` (the runner's, before both);
  - `HostGate.HostRule.YOUTUBE`: youtube.py's `PHONE_GATE` (youtube.json's `gate`: names, suffixes, port, the hosts
    reported apart, those refused by name, the refusal's words); the computer has no gate; `HostGate.isOpen`, this
    process's open gates by port and user; a NETWORK gate refused while `caracole.network` is `loopback` unless it
    names a resolver and a connector of its own (`NETWORK_UNDER_LOOPBACK`);
  - `YtDlp` (Y1.3), youtube.py's `YtDlp` over a `YtDlpProcess` (`Ran`; `NotStarted`, nothing sent): `budget` runs
    (the `budget` event once), `beforeRun`'s refusal (`RunHeldBack`: no process, nothing spent, no event), the pause
    after this side's last run (`Pace.pauseAfterLastRequest`, kv `http:last_request:youtube`) then `_pause`'s, the
    gate's `proxyArg` in every argv, one `events` row a run (`EventLog`, the computer's fields); after a run the
    gate's log first (`GateRefused`, `gate.refusal`'s words, never a block; `gate.stopped`, the gate's acceptor
    ended by a bug, an error in `gate.stopped_said`), then a timeout, the exit status and `Classify.of`:
    `ProviderBlocked` (`Health.recordBlock` at the job's start, every later run refused with no process),
    `VideoUnavailable`, `PassedOver` (a VideoUnavailable), `ExtractorOutdated` (no block); its events the computer's
    for every run; the gate's user and secret in no event, kv, exception or line (`<proxy>` in their place);
    - `YtDlpGate`, a gate a run (`gate: () -> YtDlpGate`), closed once the run's log is read, on every path;
      `YtDlpGate.keptOpen` for one gate a job, which the job closes;
    - a cooldown an earlier job recorded refuses each run before its gate (`ProviderBlocked` in youtube_sheet.py's
      words, youtube.json's `runner.cooling`): no gate, no process, no event, no strike;
    - the runner records a block itself (one strike); a caller never does, and sends the alert;
    - a run cut off by an exception (anything but `NotStarted`) is counted and logged, an `error` event and kv
      `http:last_request:youtube`, then rethrown with no secret: the computer's writes no event there, but Android
      can kill the `:youtube` process mid-run, and the day's budget and the next pause must see it;
    - `HostGate.close` never throws, keeping the caller's interrupt (set again once every thread was waited for);
  - `SearchGate` (Y1.4), youtube_search.py's gates: `gate(cfg, db, query, onScreen, now, routeWhy)` and
    `videoGate` (`found`, `none`, `auto`, `failed`, `spent`, `off`, their words, numbers and keys youtube.json's
    `search`: a query once in 30 days, kv `youtube-search:<key>`; 10 runs named `youtube-search:` an hour in
    `events`; none while `Health.isCooling`; its own failure or 3 within the hour, kv `youtube-search:failed`,
    `recordFailure`; YouTube off in PhoneConfig, or `routeWhy`, the phone's own reason it makes no sheet from a
    video), `suggestion` (/api/search's `youtube`) and `sheetOnScreen`;
  - `Due` (Y3.3): youtube_fetch.py's `phone_due`, `songs(db, overrides, now, paired)`: `songs_for_youtube`'s songs
    (todo.songs_to_buy's rule, core.todo's `Todo.songsToBuy`, which the cards' buy links read too) with no
    `audio_path` and no sheet kept, human or auto; on a paired phone the noted alone (kv `youtube-wanted:<id>`); the
    noted first, failures last;
  - `DayBudget` (Y3.3): the phone's day, `left(db, config, now)`, `PhoneConfig.provider("youtube").budget` less
    `runs`, every yt-dlp run of the last 24 hours (`events` of `youtube` decided ok, error or blocked: asked-now runs
    and the bench's too, a `budget` row none), which Settings' row and the bench's ledger count by; YtDlp's `budget`
    wins over its policy's, the caller's to give (an automatic job's the day's left);
  - `Records` (Y1.4): kv `youtube:<song id>` (`Record`), `load` and `save` as `load_record` and `_save`, the text
    byte for byte (youtube.json's `record`); a removal takes it and `youtube-wanted:<song id>`, the phone's note of a
    song for its automatic pass (songs.py `_PER_SONG_KV`, SongKv.kt), and a restore keeps `youtube-search:`,
    `youtube-outdated` and `phone:youtube-auto` as they are now (OwnRecords);
  - `Thumbs` (Y2.4): youtube_search.py's thumbnail, youtube.json's `thumb` (provider `ytimg`, its address, folder,
    names, limits and frame markers): `fetch` one request through the caller's PoliteClient (robots' rules: `/sb/`
    closed), kept as `<cache>/youtube-thumbs/<id>.jpg` when `checkedJpeg` reads a JPEG, the record of its key said
    `thumb`; `get` and `read` checked again; `SearchGate.kvKey`, `forgetFailure`, `run`;
  - vectors/youtube/argv, classify, parse, choose, runs, gate, record and due.jsonl (`YouTubeReplay`, area `youtube`;
    runs.jsonl the computer's `YtDlp` over FakeYtDlp, replayed over `FakeYtDlpProcess` through a loopback HostGate),
    and video_cmd.jsonl's `checked_jpeg` records (synthetic JPEG heads, seeded edits of them).

##### The Requests tab on the phone

- **Its lines** (server/jobs: `Status`, `Outcomes`, `SongFacts`, `JobViews`, `JobsRoutes`): every job's line, chips
  and outcome as status.py, outcome.py and jobs_routes.view say them, for every kind caracole serve queues and the
  phone's own:
  - a job of commands is read as caracole serve's; one of the phone's own (a run, no command) as caracole serve's of
    the same request (`Shape`): an add's or a removal's stage its one command, a staged one's stages under its title;
  - with no to-do page: status.job_line's `todo=None`, the same words with no link;
  - its song as the library has it now (`SongFacts.songOf`, jobs_routes.song_of: the sheet its card opens, review,
    the picker, ignored and a LaCuerda pick by the phone's overrides, `checked_now` by `ug_checked_at` and the
    artist page's check, read as strptime reads them, `elsewhere` from the local indexes and `Health.isCooling`);
  - what a job over came to worked out once, the queue's one answer (`SongFacts.ended(queue)`, jobs_routes'
    `_ended`), which every route that says a job's line asks, /jobs.json's and the Requests tab's alike;
  - a request queued behind a running job of the phone's own (`JobViews.behind`: a PhoneKinds' kind's, a sync's, an
    index import's, not yielding) says what it waits for, the phone's own, as Python never queues one (`queuedBehind`:
    "Queued · waits for the site catalogues to finish importing (79 %)", "Queued · after backing up the book", "Queued
    · 2 requests ahead, now the sync (Updating the indexes · …)");
  - the catalogues' line never carries the import's count of tabs (every row of GitHub's file, none of the request's):
    its share is the stage's `done` and `total` (`JobContext.progress`, `Stage.done`), data beside the words, left out
    while there is no total;
  - PhoneKinds' kinds (render, inbox, backup, restore, catalogues) say §5.3's table's words, the ones their run filled in as
    their stage's detail (`context.stage(<its stage>, state, PhoneKinds.fill(…))`, done, running or failed; inbox's
    wait a done detail in `otherwise`'s words: `JobViewsTest.thePhonesOwnKindsSayTheirTablesWordsAsTheirRunFilledThemIn`),
    and the phone's index import "Merging the computer's index…", its merge's words after it (a long stage);
  - vectors/web/job_views.jsonl (the phone's own jobs), job_views_kinds.jsonl (every kind of commands in every state,
    every stage a line words running, a sync's, a take's and a merge's commands), outcome.jsonl (the same and each
    site's waits and errors, then the tables of words whole, its `tables` record) and job_views_song_of.jsonl
    (song_of over a small library a record, its fixture), written by tests/test_conformance_sync_routes.py and
    test_conformance_web.py (`JobViewsReplay`, area `job-views`).
- **Its tab** (`server/jobs/Feed.kt`, `server/routes/RequestsRoutes.kt`, `server/page/LibraryPage.kt`): the library
  page's Requests tab as caracole serve's (feed.py, jobs_routes.py, library_page.py):
  - the tab and its panel are library_page's `_requests_tab` and `_requests_panel`, exported as they are into
    data/caracole/page/requests.json (`RequestsTab`), the tab counting `ServerControls.active`;
  - `GET /requests.json` (the page's script alone, `?open=N,M`) is `Feed.feed` over the queue's snapshot: each job's
    line `JobViews.line` (its song's facts through `SongFacts.ended`, the cache /jobs.json shares, its songbook's page
    `JobsRoutes.songbookPage`), each one over `Outcomes.outcome`, the running one's `Outcomes.steps`, and the songs
    that wait for a pick (review_routes.picks_waiting: a review with candidates, `SongFacts.hasCandidates`, or a song
    the index didn't match, `search`), read apart from the lines as caracole serve reads them;
  - a database that can't be read (`RequestsRoutes.unreadable`, Python's `(sqlite3.Error, OSError)`: SQLite's own
    error, a file's, a database too new) leaves the lines saying only how the jobs went, or no picks; anything else is
    a bug, the request's error;
  - `Feed.feed` takes the outcomes and chips as `Outcome` and `Chip`, and works out one not given from the job, as
    feed.py does (an outcome from its line, the running one's chips with no facts);
  - a request of the phone's own that said something as it ran (`JobContext.say` with no step: what a sync, pressed
    or unattended, or a file's import took and gave, then its units left as they were, `SyncRoutes.said`, one
    implementation for all three) has one more step in its Output, `Feed.SAID` ("What it said"), its lines those
    words, the phone's alone: feed.py has none (a command's Output is its step's own, the comparison a line a
    difference, `_report`, `_file_report`, unbounded). A unit taken or given is said by its label as compared
    (`SyncOutcome.compared`), else its id, in commands/peer.py's words (`DONE`, `ASKED_AGAIN`, `CONFLICT_SETTLED`,
    `done_line`, `done_lines`: the lines `caracole peer sync`, `pull`, `take` and `import` print without `--progress`,
    filtered alike, `_Said.flush`), from data/caracole/sync/said.json (core.sync's `SyncSaid`, vectors/sync/said.jsonl,
    tests/test_conformance_sync_said.py): "Took Radiohead - Creep", "Gave songbook Campfire", a removal named as a
    tombstone's label names one ("Took Oasis - Wonderwall (removed)", `peer_sync.REMOVED_LABEL`), a tombstone gone
    there, its song asked for again ("Took Oasis - Wonderwall (asked for again)"), a tombstone going with its song
    said by the song's line alone, a conflict settled "…: changed on both sides" (the verb says whose side came: Took
    the other's, Gave this one's); at most `DONE_MOST` (20) a way, then
    "Took … and 312 more", so a first sync's entry stays small. A unit left is said by its label as compared
    (`SyncOutcome.labels`), else its id, in
    commands/peer.py's words, which caracole serve's sync prints in its step's Output (`LEFT`, `left_line`,
    `SyncRoutes.leftLine`): "Left as it was: Oasis - Wonderwall: changed here since compared"; a conflict the
    unattended sync left "…: changed on both sides: tap Sync to choose" (`CONFLICT_LEFT`), never as a failure;
  - the times are the phone's zone's, named as Python's `%Z` names them, tzdata's abbreviations (CET and CEST), from
    requests.json's `zones` (`ZoneNames`: every zone's labels of letters by offset and since when, else the offset's
    number, `-03`, `+0545`), never java.time's or ICU's "GMT+01:00"; month names the C locale's;
  - `POST /jobs/again` is jobs_routes.again over `JobQueue.again`, its view the job as the queue has it now (one the
    worker started already runs, WebApp.job_view), its refusals caracole serve's words, but a request
    of the phone's own read back from the history, with nothing left to run (`JobNotRepeatable`): 409, the phone's
    words (`RequestsRoutes.NOT_REPEATABLE`);
  - vectors/web/requests.jsonl (feed.py's answer byte for byte under UTC and Europe/Madrid, `_ordinal`, `_ago`,
    `stamps.shown(local=True)` in zones of letters and numbers either side of a change of clocks, the tab for a
    count, feed.py's words) and requests.json, written by tests/test_conformance_requests.py (`RequestsReplay`, area
    `requests`), with library_page.json's pages whole, the tab in them.

##### The computer's settings on the phone

- A sync's agree stage takes the computer's settings from the state it reads again there (`PeerState.settings`, `GET
  /api/peer/state`'s `settings`; a member that isn't an object is none), inside the agreement's write:
  `SyncEngine.takeSettings`, then `PhoneConfig.take`, the document whole as kv `phone:settings`, as `kv_set_json`
  writes one, replacing the last. A state with none (an older computer) leaves it as it was; a sync that stops before
  agree takes none.
- `PhoneConfig.read` lays it over config.json's defaults, value by value as config.py would hold it (`[rank]`'s
  `line_match` and `prior_votes` numbers, 82.5 too, so `RankPolicy`'s are Doubles; a provider the phone doesn't know
  passed over). Assembly reads it for each lookup's clients and the cards, and the library's `name` for every page
  of the phone's (`AppConfig.libraryName`, ShareRoutes', GuitarRoutes' and the choices' pages: `LibraryName.phone`),
  which names it after caracole's, with the Phone badge.
- It is no unit: a take changes no unit's digest and no other record (SettingsTest), and the phone sends no settings
  back. Nothing of either side's politeness crosses (Two caracoles, each its own politeness, below).
- `SettingsReplay` (area `settings`) replays vectors/sync/settings.jsonl (each caracole.toml's document taken, then
  read as config.py holds it) and settings_take.jsonl (the take rule by rule), each take through `PeerState.read` and
  `SyncEngine.takeSettings`.

##### Syncing on the phone

- **The rules** are peer_sync.py's, replayed (`SyncReplay`, area `sync`): `Compare`'s kept answers (`keptOf`,
  `recordKept`, `mergedKept`, `compare(kept=)`, `recordAgreement` and `recordTaken` dropping each agreed unit's, the
  base written with a `"kept"` only when it holds one; `PeerState.kept`, the state's `kept`) and `Scope`'s parts
  (`PARTS`, `partOf`, `listedSongs` through `Songbooks.entryKeys`, `inScope`, `changeOf`, `namesOf`):
  vectors/sync/kept.jsonl and scope.jsonl.
- **When the phone agrees**: its take stage records what it took as agreed in the take's own write, right after
  `Take.applyUnits` (`SyncEngine.agreeTaken`, `Compare.recordTaken` at the computer's `now` as compared), and its
  agree stage records what the two then hold alike; so a sync that stops after its take (the give refused or cut off,
  the agree's read of the computer failing, the job cancelled) leaves what it took agreed, and a later change on the
  computer alone is the computer's (SyncEngineTest's "what a sync took stays agreed …"). The computer, which took
  nothing, records nothing; the sync still fails. A kill between the take's last unit and that record (one library
  read and one kv write) leaves those units unrecorded, as before: alike on both, they read as no difference, and
  the next sync's agree records them, unless the computer changes one meanwhile. An import records the same way in
  its take's write (`SyncFiles.recordTaken`, with the file's caracole at its `made`, of the units the file speaks for;
  none for an index export), so one cancelled or killed in its mirror stage leaves what it took agreed, and the same
  file compared again offers the rest (ImportTest's "an import cancelled in its mirror stage …").
- **The song keys' rules** (peer_sync.py's): `PeerClient.state` refuses a computer whose state names other rules
  (`PeerState.keyVersion`, `Units.otherKeys`: an `OtherKeys`, a PeerError, in `Units.OTHER_KEYS`' words), so
  `compare`, `tested` and `apply`'s compare stage stop before any change (SyncRoutes: 409); Sync on Wi-Fi's probe
  (`Syncs.run`, the unattended sync's first read) ends as a failed outcome in those words on the bar, never the
  silence of no caracole answering (any other PeerError or SyncError there); `Give.document` and `SyncFiles.export`
  say the phone's (`key_version`, Normalize.KEY_VERSION), and `SyncFiles.read` refuses a file of other rules
  (`FileError.OTHER_KEYS`, SyncFileRoutes: 409). A computer or a file that names none is read as before.
- **The engine's comparison** (`SyncEngine.compare`) carries, beside its differences, its `kind` (`"computer"` or
  `"file"`), the parts the other side `holds`, the merged `base` and `kept` answers it compared against, the songs
  either side's songbooks `listed` (each songbook difference's document asked of the computer once,
  `Scope.listedOn`), each songbook difference's two documents (`songbooks`) and the indexes (`indexes`,
  `IndexWaiting`: below; a file's, each site whose newest read differs); its hash is of the differences unscoped.
  `documents` gives a unit's two documents (a file's none of a unit it left out or of a part it doesn't hold,
  `FileSource.says`) and `tested` what the computer holds (its state read once, nothing changed).
- **The indexes a sync takes** (`SyncEngine.newerThere`, the index stage's rule and its comparison's): each site whose
  stamp in the computer's state is later than both kv `sync:index:<computer id>` (what the phone took of that computer
  last) and kv `index:merged` (core.index's `MergedIndexes`: each site's newest read of the whole exports the phone
  merged, read over each file as its merge read it, `Merged.newest`, a site dated after the merge's `notAfter` left
  out; written by a sync's own merge, a file's indexes, the site catalogues and an index import, the later kept), never
  by the phone's own newest, which its lookups' reads move. So a sync after the catalogues or a file of the computer's
  downloads only what the computer read since. The comparison lists those (`newer` "there") and each site whose pages
  Reads noted for the next push ("here"), a site of both twice, so the Sync sheet says what the Sync does: where
  sync_routes._waiting compares newest reads, the phone answers otherwise (vectors/web/sync_routes.jsonl's scene holds
  both records, so the two answers agree).
- **Only the part it doesn't hold** of each site taken (SyncEngine.merge): `POST /peer/index/newer` with core.index's
  `Have` document (the phone's record of each sitemap but its `checked_at`, and `since`, kv `sync:cut:<computer id>`,
  `Have.CUT_KEY`: the computer's own `exported_at` of the last partial export of the cut asked that the phone merged,
  recorded only when that time is within the merge's clock bound (below), kept apart from `sync:index:`, whose stamps the phone's own pushed pages move: a page the computer read meanwhile is
  later than the cut, so it comes whatever the push did); a computer that answers 404 or 405 (older) or 413 (a
  document too large) the whole, any other refusal the stage's failure. The document is held to Python's by
  vectors/index/have.jsonl (`IndexReplay.have`, byte for byte; tests/test_conformance_index.py feeds each to
  `read_have` and to an export of the same database, which leaves out every sitemap that has validators). Once merged, the file's META `partial` is checked to be the cut asked for
  (`Have.mismatch`: every site, its `since`, nothing left out the phone lacks) and no sitemap it left out held
  otherwise (`Merged.unheld`), else the stage fails in "… isn't the part asked for" and nothing is recorded (its merge
  lost no row); else `sync:index:` and `index:merged` (the file's newest, a part's no later than the whole's) move
  on, true as after a whole export: the phone holds every row the computer held as of it. `sync:cut:` moves on only
  for a partial export of the cut asked whose `exported_at` is no later than the merge's `notAfter`: never from a
  whole export (an older computer notes no arrivals, so rows it merged with old times before its update would fall
  below that cut; the first part after the update is uncut, once), nor past the bound (a row the merge passed over
  for being dated after it would fall below the cut).
- **A computer of another schema** (its state's `schema`, `PeerState.schema`, read as an integer, none else): none
  taken and none of the pages read here given (`SyncEngine.indexesSkipped`, the index stage skipped in
  `INDEXES_NEWER`'s or `INDEXES_OLDER`'s words before anything is downloaded or pushed, the notes kept), the
  comparison listing no index and saying why (`Comparison.indexesSkipped`, `indexes_skipped`, the sheet's Site
  indexes); a state with none (a computer older than the member) asked as before. A merge's refusal names its file
  ("The computer's index export", "The file": `namingFileAs`), never its copy's path, and no class name.
- **The pages the phone's lookups read** (Reads), pushed at the index stage's end (`POST /peer/index`): their notes
  forgotten only once the computer's request that merges them (its `caracole index merge`) ends done; kept when it ends
  otherwise (the stage failed, "… didn't merge them: its Journal entry N ended failed.") or still goes at the wait's
  end (10 minutes), for the next push, which a merge there takes to the same rows. Once done, each site's stamp there
  (`GET /api/sync/indexes`) that those pages alone explain (`SyncEngine.explained`: a time no later than the newest
  page pushed of it, the computer's stamp just before the push one the phone held) goes into kv `sync:index:<computer
  id>`, so the next sync downloads no site's whole index for the phone's own pages; a stamp later than them, or one the
  phone lacked before the push (its download failed), is the computer's own reading, which the next sync takes.
- **`apply(c, choices, prefer, parts, conflicts)`**: only the differences of `parts` are taken, given or left
  (`Scope.inScope`: a part left out is never read as a removal, a song a songbook lists comes along with the
  songbooks); Library unticked skips the mirror stage, Site indexes unticked the index stage, each saying so. No stage
  is added to a network sync. `Conflicts.ASK` refuses a conflict settled neither way before any change;
  `Conflicts.LEAVE`, the unattended sync's, leaves it (`UNSETTLED`) and never refuses.
- **Its stages say how far** (`Paced`): the index stage "The computer is copying its indexes…", "Downloading the
  computer's indexes · 120 of 274 MB" (`PeerClient.index`'s `onBytes`, by Content-Length; none, "· 3.4 MB so far"),
  the merge's `MergeProgress.words`, "Tidying the database…"; a file's "Copying the file's indexes out…" first. Its
  hooks take a words callback: `mirrorRefresh: suspend (address, say) -> Unit` (Assembly's: `MirrorSync.sync`'s
  progress, "120 of 640 pages") and `pagesFromFile: (SyncFile, taken, say) -> Unit` (`SyncFileRoutes.pagesFromFile`:
  `Mirror.takeLayer`'s `progress`, "12 of 40 pages kept").
- **A song's overrides entries taken** are read back inside its unit's savepoint, as `put_song_entries` reads them, an
  entry the reader refuses leaving the unit in Python's words; a `[version]` kept by its key and a `[harmonica]`
  reading by the viewer's checks, which core reaches through `OverrideChecks` (the engine's `checks`: Assembly's
  `OVERRIDE_CHECKS`, `Versions.keyVersion` and `HarpTabs.checkSpec`).
- **What it says it did** (`SyncRoutes.said`, the job's Output's step of what it said, `Feed.SAID`): a sync's, pressed or
  unattended, and an import's units taken and given, a line each by name, from what it really did
  (`SyncOutcome.taken` and `given`: a unit left is said as left alone; a file gives none, its "keep mine" taking
  nothing), then its units left ("The Requests tab on the phone" above; SyncSaidReplayTest, SyncRoutesTest,
  SyncFileRoutesTest).
- **A removal beside its song** (peer_sync's rule): `Compare.answeredByItsSong` takes out of the take each
  `removed/` unit whose song is given (a sync) or kept (an import, its answer kept beside the song's); one whose
  song's difference is left is left `Take.SONG_HERE`, never counted taken. A song the take respells is given at its
  digest as the take ended (`Applied.respelledDigests`, measured in the take's write).
- **An import** (`compareFile`, then `apply` of its comparison) is a sync with a `.caracole` file (core.sync.file,
  peer_file.py's port: `SyncFiles`, `SyncFile`, `FileSource`, `FileError` in its words, vectors/sync/file.jsonl), in
  `FILE_STAGES` (check, take, mirror, agree, index): the file read and refused whole before anything changes (another
  format, songs keyed by other rules, this library's own export, one no newer than the last sync with its caracole,
  one that can't be read whole), compared within the parts it holds
  (a part it lacks is never read as a removal), taken from as from the computer, the units taken handed to the
  `pagesFromFile` hook, the agreement kept with the file's caracole at its `made` for the units it speaks for, each
  "keep mine" remembered (`SyncFiles.recordImport`), its indexes merged; it gives nothing back.
  - Its zip is read by `Zip`, CPython 3.14's zipfile by hand (the end records, zip64's too, the central directory,
    names in UTF-8 or cp437, each member's local header, its data stored or inflated, its CRC-32 at its end), never
    java.util.zip.ZipFile, which Android refuses at open for a name with `..` or a name twice (ZipPathValidator),
    where peer_file says which member is wrong: file.jsonl's zips made by hand hold it to Python's, on the device too.
  - Its JSON members are read as `json.loads(bytes)` reads them (`SyncFiles.json`: json.detect_encoding's UTF-8,
    UTF-16 or UTF-32, lone surrogates passed).
- **The report** (`SyncOutcome.report`, the sync redesign's §3.5): with whom (`with`: name, kind, address), when,
  its parts, and each index taken or given, its first table's rows (`TabCounts`) before and after, `new` (after −
  before) and `checked` (the rows of the sitemaps and listing pages its merge took, `Merged.checked`, index_transfer's
  `SiteMerge.checked`, by the statements' own counts: no scan), commands/peer.py's `_taken_entries` and
  `_give_indexes` alike: a taken one around its merge here; a given one on the computer (`GET /api/sync/indexes`,
  `PeerClient.indexes`) before the push and after its merge job, its `checked` null (that answer doesn't say it), none
  from a computer that doesn't count them. `checked` is the rows of the sitemaps taken, read new or not, for UG and
  the sitemap sites, and for LaCuerda's artist pages and search the rows inserted, new by construction. While it
  merges the computer's indexes or a file's, a site the phone held rows of says what is newer there and the rows
  checked (`MergeProgress.Updating(held, there)`, index_transfer.MergeWords' `held` and `there` alike, `peer sync`'s and
  `peer import`'s: "Ultimate Guitar · 3 sitemaps newer on the computer · 50,000 of 117,701 tabs checked", "… newer in
  the file …"), "Importing" kept for the catalogues and a site whose table was empty.
- A phone's own export writes the file `SyncFiles.export` makes (its indexes every site's whole, `IndexFile`, as
  `caracole index export` writes them, which SyncReplay compares with Python's as data; its pages through a
  `PageSource`, server/routes/sync/MirrorPages.kt: the mirror's and its layers' pages of each unit at the digest the
  phone holds, the computer's first, and for its start page the phone's own library page's data, every card it shows,
  `MirrorPages.startPage`, so that a song taken from a file opens its sheet on a phone the export goes on to).
- **A file's pages, a layer of the mirror** (mirror/Layers.kt, `Mirror.takeLayer`, the engine's `pagesFromFile`,
  `SyncFileRoutes.pagesFromFile`): an import keeps the pages its file held of the units it took, and the file's start
  page, in `mirror/layers/<the file's caracole's id>/` (a list and blobs, each checked by its SHA-256 as it is
  written; a page the file lacks or holds otherwise than listed leaves the layer as it was), one layer a caracole, the
  newest taken first; then every layer is cut to what `PhoneGate` still serves (a unit the phone changed or removed
  since loses its pages, a layer left with none goes).
  - `pageFor` serves the computer's page while its unit is as the phone holds it, else the newest layer's of that same
    unit at that path (never a page of another unit at a path the computer gives one), else the computer's answer; a
    layer's start page is never served, and the computer's mirror sync (`cleanUp`) never touches a layer.
  - A file is anyone's to make, so a layer serves no header the file gave (`LayerPolicy`): a kind caracole serves alone
    (a page, a PDF, text, JSON, a download; any other is never kept), caracole serve's Content-Type for it, the
    phone's `nosniff` and Referrer-Policy, and a page only in a sandbox (where the file's `sandbox` holds
    `allow-scripts` and `allow-downloads` alone, as viewer_csp's, a viewer's policy the phone writes, keeping of the
    file's only its scripts' and stylesheets' hashes, nothing loaded or connected to; else `LayerPolicy.NOTHING`, one
    that runs and loads nothing): never `allow-same-origin`, which would give a file's page the phone server's origin,
    its form token and every write. A unit's page is kept only right in its folder here (`PhoneGate.folderOf`: a
    song's `Artist/Title`, a songbook's `_songbooks/<folder>`). An export carries the layer's headers on, never the
    file's.
  - The phone's page makes every card of its songs itself (server/page's PhonePageData, library_page.song_cards'
    port, vectors/web/cards_full.jsonl), linking the pages of a song's folder `pageFor` serves, a layer's too, and
    saying what no sync carries (exports, a PDF's move, the sites' misses, a purchase) as the computer's card does
    for a song the computer listed a file of at the digest the phone holds. MirrorPageData's own cards (M2–M3's: a
    layer's card read as untrusted, `fromFile`, else the minimal card) are for a page with no library to make them of.
  - Layers are kept until a unit changes or the app's data is cleared; `storageBytes` counts them.
- **Export and Import a file** (server/routes/SyncFileRoutes.kt, web/sync_file_routes.py's routes on the phone:
  `GET /api/sync/sizes`, `POST /sync/export`, `GET /api/sync/export`, `POST /sync/import/open`, `/part`, `/compare`,
  `/drop`; vectors/web/sync_file_routes.jsonl, `WebReplay.syncFileRoutes`, area `web`):
  - an export (`routes/sync/Exports.kt`) is made through the database's writer (its indexes' attached file) into
    `stateDir/cache/peer/export-<16 hex>.caracole` (0700, 0600), one at a time, and sent once: taken out of the
    exports' names, its name deleted as the server opens it (`Body.FromFile`'s `once`, `open()`), one never asked for
    swept an hour after, one taken that no server opened 10 minutes after, and every one an earlier start left cleared
    as the phone starts (`Exports.clear`); a HEAD is 405;
  - an import's file (`routes/sync/Imports.kt`, peer_import.py's) is staged part by part in
    `stateDir/peer/import-<16 hex>/` (0700: `file.caracole`, `open.json`, 0600), one at a time, each hold the job's
    or a comparison's alone (one process: an in-process hold, no flock), let go as another is opened once whole or
    stopped, dropped by the page's Cancel, swept an hour after;
  - its comparison is the engine's `compareFile`, answered as `POST /sync/compare`'s (`peer.kind` `"file"`, its
    `made`, no address, the indexes it read more recently alone); SyncRoutes' `POST /sync/apply` hands a file's
    comparison to it (`SyncRoutes.files`, `FileSyncs`), which compares the file again and queues the import: kind
    `sync` under `import:<id>`, "Sync with a file from <name>", `FILE_STAGES`, the folder deleted once it ends;
  - the phone's App reads a `json` or `bytes` route's body as web/app.py does (`Route.body`, `DocumentAnswer`: the form
    token in its header, its content type, its limit, JSON by PyJson.loads); the routes declare Python's kinds and
    limits (the vectors' `limits`).
  - Where the phone answers otherwise: `indexes` of `GET /api/sync/sizes` is null, its bundled SQLite having no
    dbstat (peer_file.indexes_size's None), and an index export's comparison names no index newer in it.
- What the phone says otherwise: the report leaves out a site whose merge moved its progress records alone (no row
  taken, its count the same), as IndexTransfer's `Merged` says what changed of the merge whole (`SyncEngine.taken`).

##### :viewer

- Its assets and data, `ViewerAssets` and `ViewerData`, and music theory (theory):
  - `viewer.theory` is viewer/theory.py (`Chord`, `Key`, `Theory`, Python's parameter names), its tables and
    patterns read from `data/caracole/viewer/theory.json`, which tests/test_conformance_viewer_theory.py writes from
    the module, never retyped; `Chord` a class with a data class's members, so that its `tones` are a frozen copy as
    Python's frozenset is, and every list handed out a copy (TheoryTest mutates them).
  - `ViewerAssets` reads viewer/'s files as page.py does (strict UTF-8) and names each page kind's (`Page`, held by
    vectors/viewer/theory_assets.jsonl); `ViewerData.table(module)` reads `data/caracole/viewer/<module>.json`
    (viewer_corpus.py `data_json`'s format), which shares its classpath folder with viewer/'s assets: no module's
    data is named `voicings*.json`.
  - tests/helpers/viewer_corpus.py is the seeded inputs every M5 generator reads (its docstring), the same in every
    process; an edit there, or to a string literal of tests/test_viewer_theory.py (the theory vectors read them),
    regenerates the corpus.
- A sheet read, ChordPro and a song's key (sheet-keys): `viewer.sheet`'s `Sheets` (viewer/sheet.py: `parse`,
  `directive`, `written`, `isLegend`, `isLegendLine`, `preambleSection`, `splitPreamble`, `bars`), `SheetView`
  (page.py's reading functions that hold no HTML, below the page, so that a version's and the harp's reading need no
  page: `shown`, `drawnLines`, `writtenTexts`, `peek`, `places`, `played`, `songKey` and `viewerKey`, `givenShapes`
  and `shapesOf`), `ChordPro` (chordpro.py, with render.py's `chordProText`, `asLatin` and `needsFontFile` and
  ug/page.py's `decodeTwice`) and `MusicKeys` (keys.py: `sheetKey`, `sheetKeys`, `songKey` and `letterAlone` over the
  phone's `files` and `versions` as core.library reads them, `Kept.keptFiles` and `Versions.get`, each file read only
  as a regular file, never through a link; `SongKey`).
  - Their constants and patterns exported from the modules by tests/test_conformance_viewer_sheet.py into
    data/caracole/viewer/sheet.json, a member a module, never retyped; Python's lines, whitespace and lengths
    throughout (str.splitlines, str.isspace, code points, a chord's column a display column), never Kotlin's trim or
    lines.
  - Every answer held by vectors/viewer/sheet, chordpro and musickeys (`SheetReplay`, the `sheet` area), a sheet's
    derived lists by their digest; estimate_key's sums Python's (`Py.fsum`), its correlation compared to the bit.
  - Their inputs include every string literal of tests/test_viewer_sheet.py, test_viewer_preamble.py,
    test_chordpro.py and test_keys.py (`SHEET_LITERALS`, `CHORDPRO_LITERALS`, `KEYS_LITERALS`): an edit to one
    regenerates the corpus.
  - Where Kotlin holds less than Python: a `{capo}` or a sheet.json capo past an Int is none; and as in Python, a
    solfège name sre's IGNORECASE reads but no table holds (`[ch]ſol[/ch]`) raises.
- Voicings, instruments, the harmonica and the winds (shapes-harp-winds): `viewer.shapes`' `Voicings` (chords-db's
  fingerings from viewer/'s own voicings.json and voicings-ukulele.json, a legend's and a `{define}`'s shapes,
  `voicingKeys`, `sheetShapes`) and `Instruments` (`INSTRUMENTS`, easy keys, each one's shapes of a chord, a page's
  `voicings` and `instruments`), `viewer.harp`'s `Harp` (the layout, the chords a harp plays, the ranking in one
  place, the tables, `holeNote`, `holeTables`) and `viewer.winds`' `Winds`.
  - Their constants exported from the modules by tests/test_conformance_viewer_shapes.py: data/caracole/viewer/
    instruments.json (voicings.py's patterns too, viewer/voicings.json being chords-db's), harp.json (harmony's
    pentatonic boxes too) and winds.json (harmony's `_BASS_DEGREES` too: a chord's tones in harmony's order).
  - Every answer held by vectors/viewer/voicings, instruments, harp_* and winds (`ShapesReplay`, the `shapes` area),
    a page's objects in Python's order too (a kept answer's `sha256`).
- Pinyin with tones, OpenCC and hanzi (chinese):
  - core.pinyin's data is pypinyin's in Style.TONE alone (data/caracole/pinyin/, `symbols.txt` its tone marks):
    `Pinyin.lazyPinyin(text, errors, style)` (`DEFAULT`, `IGNORE`, `EMPTY_EACH`; `TONE`, `NORMAL`), NORMAL derived as
    pypinyin's `to_normal` (`Pinyin.normal`), which M1's NORMAL vectors guard, vectors/pinyin/tone.jsonl the TONE.
  - `viewer.chinese.OpenCC` is OpenCC's algorithm as hanzi.py runs `t2s`, `tw2s` and `s2tw` without tofu-risk
    dictionaries: normalization, mmseg, the chain, groups by `short_circuit` and `union`, an IDS written whole, a
    segment ending at a NUL. Its configs are the package's as shipped (data/caracole/hanzi/opencc.json, with
    `opencc.__version__`, 1.4.0) and its dictionaries the package's opencc_dict dumps (`hanzi/<Name>.txt`): an OpenCC
    bump regenerates them, and OpenCCTest names the version it ports.
  - `Hanzi` and `ViewerPinyin` are hanzi.py's and pinyin.py's, in code points (pinyin.py's constants from
    `viewer/pinyin.json`); hanzi.py's `chordpro` is the computer's PDFs' alone. tests/test_conformance_viewer_chinese.py
    writes their data and vectors (viewer/opencc, hanzi, pinyin_page), each also read back from the data alone.
- Harmony (harmony): `viewer.harmony.Harmony`, harmony.py's chord half: `numeral` (`Numeral.text`), `relation`,
  `family`, `explain` (the numeral's tooltip line), `glossary`, `chordTones`, `soloScale`, `keyScale`, `pentatonic`
  and `goesTo` (`_goes_to`), each read as `_read` reads the chord with the one it goes to (`HarmonyChords`, function for
  function, its words harmony.py's own), its tables harmony.py's exported to data/caracole/viewer/harmony.json
  (tests/test_conformance_viewer_harmony.py, `vectors/viewer/harmony_chords.jsonl`, HarmonyReplay); its progressions
  and tables (harmony-progressions):
  - `progressions`, `progressionKey`, `nameOf`, `readTyped` (each of a list or of a string typed) and `catalogue`
    (`catalogue_keys`), `HarmonyProgressions` function for function (`_fold`, `_passes`, `_varies`, `_whole`, `_rows`,
    `_contained`, `_ending`, public for the replay), CATALOGUE, `_LOOPS` and its other tables and patterns exported to
    harmony.json too, a key's turn chosen by code point as Python compares str;
  - `HarmonyTables.tables`, harmony_tables.py's, each object in Python's insertion order (a chord's reading the one most
    of its places have, the first seen in a tie), so that `PyJson.dumps` writes `json.dumps`' bytes;
  - `vectors/viewer/harmony_progressions.jsonl` and `harmony_tables.jsonl` (a table's members by their SHA-256, a few
    kept whole).
- A sheet's versions and progressions (version-progressions): `viewer.version`'s `Versions`, viewer/version.py's page
  side function for function, and render.py's `own_version` (`ownVersion`); `apply_version`, a sheet's ChordPro for
  chordpro's PDF of a version, is the computer's alone.
  - `fromQuery` and `query`, a version as the viewer's address reads and writes it (Python's parse_qsl, JavaScript's
    Number(), URLSearchParams' bytes); `playedKey`, `forInstrument`, `label` and `playedLabel`; `settingProblem` in
    Python's words and reprs, of any value a form or a file gives; `inSetting`; `keyVersion` (an
    IllegalArgumentException with key_version's words, which `Overrides.read` and `OverrideWriters.addVersion` take as
    their check), `inKey`, `entry` and `KeyVersion.query` and `label`, byte for byte, as `[version]` is in a song's
    sync unit.
  - `viewer.progressions`' `Progressions`, progressions.py's: `record` (kv `render:progressions:<song id>`, json.dumps'
    text, written only when what json.loads reads there changed), `forget`, `library`, `read`, `songsWith` (the
    library's keys as they are: it re-keys none), `catalogue`, `label`, `keyWords`, which /api/search's `progression`
    reads (Found.kt).
  - Their constants and patterns exported to data/caracole/viewer/version.json (`version` and `progressions`) by
    tests/test_conformance_viewer_version.py, which writes vectors/viewer/version.jsonl and progressions.jsonl
    (`VersionReplay`, the `version` area), a batch's answers by a 16-digit digest where the viewer area is short of
    room.
  - Where Kotlin holds less than Python: a chord's index, a shape's number or a swap's root or bass past an Int, in an
    address, is dropped, and a record's song id past a Long is none.
- A harmonica tab read (harptab-read): `viewer.harptab`, harptab.py's reading half, Q for Q:
  - `Notation`, `Symbol` and the presets as data (data/caracole/viewer/harptab.json, every constant and pattern of
    harptab.py, written by tests/test_conformance_viewer_harptab.py), each notation compiled at run time into its
    tokenizer (`Tokens`, `_alt`'s order and `re.escape`'s rules, through core.py.PyRegex);
  - `HarpTabs.scan` and its passes (Scanner.kt), its columns Python's code points (`Group.col`, `digit`, `end`), the
    text UTF-16 while it runs; a notation that folds reads a symbol as its tokenizer's IGNORECASE does
    (`Notation.meaning`: an "ı" or an "İ" is its "i", `PyRegex.ignoreCase`); the legends (`legend`, `meaning`,
    `entry`); the candidates, `weighed` (Python's builtin sum, Py.fsum), `read` and `readings`; a pin's `checkSpec`
    (Python's words and its reprs), `pinned` and `specOf`; `said`, `Reading.standard`; Python's `expandtabs`,
    `swapcase` (a capital sigma by its context) and `_fold_accents` (`HarpTabText`).
  - `Scan`, `Reading`, `Prepared` and `Weighed` are the seam harptab-layout builds `parse` on.
  - `HarptabReplay` (area `harptab`) replays vectors/viewer/harptab_read.jsonl: each fixture tab, the tests' literals
    and drawn tabs in every notation, their candidates, scores, scans (whole or by digest), readings and pins, each
    pin's tab read as it says (`read(notation=)`).
- A harmonica tab laid out (harptab-layout): `HarpTabs.parse`, harptab.py's layout half, giving Python's `Tab`:
  - Layout.kt: each line's kind, the tabber's notes, the sections, a row's words under it or above it (`above`), a
    section's name beside a row or sung (`isLabel(besideRow=)`), prose and later verses, `namedKey`, `Row.trusted`,
    `Tab.readable` and `missed`;
  - Align.kt: `syllableStarts` and `align`, which answers the row with its parts (Python's sets them in place), the
    cuts weighed as `_cuts` weighs them (`math.comb` exact, the costs summed as Python's builtin sum, Py.fsum), every
    column a code point;
  - `HarptabReplay` replays vectors/viewer/harptab_layout.jsonl too: each tab of harptab_read's records and drawn
    ones, parsed and read as another reading's pin says (layout/'s small tabs whole, the rest by digest, for the
    viewer's budget), its rows' parts as lengths, its lines and words, `align` on drawn rows, and `_cuts` on drawn
    words, on ties that each of its numbers decides (`TIED_CUTS`) and on MAX_CUTS's edges.
- The sheet page (pages): `viewer.pages.SheetPage` is viewer/page.py's builder, byte for byte: `build(ViewerInputs)`
  writes `build_viewer`'s page (the data's members in Python's order, `names` kept in its place; the policy of each
  inlined file's hash, `ViewerAssets.Page.SHEET`), `viewerCsp` its header, and the frame book.py and harptab_page.py
  reuse, under Python's names (`page`, `readSong`, `songHtml`, `sheetHtml`, `preambleHtml`, `sectionHtml`, `factsHtml`,
  `footer`, `namesTable`, `zhAttr`, `artistLine`, `pdfLine`, `words`, `CONTROLS`, `LIBRARY_PAGE`).
  - `build` takes the song's `timed` lyrics (`ViewerInputs.timed`, Lyrics.syncedLines' `(seconds, text)`) and puts
    their match to the lines it draws (`SheetView.drawnLines`) last in its data, `sung`, `[ms, n or null]` each:
    `viewer.sung.Sung` is sung.py's (`lineKey`: Normalize.romanize then `nameWords`; `lines`: the longest monotone
    match by Fuzz.ratio, a time PyFormat.roundHalfEven's), its numbers page.json's `sung` (`PageConstants.SUNG_*`).
  - Its HTML and constants are page.py's, data/caracole/viewer/page.json, which tests/test_conformance_viewer_pages.py
    writes from the module (`_CONTROLS`, `_SHEET_CONTROLS`, `_VERSIONS`…, chords-db's notice, `_META_POLICY` run over
    a page's bytes read as Latin-1); its icon page/icon.json's; `build_version` is Python's alone.
  - `PagesReplay` (area `pages`): vectors/viewer/pages_parts.jsonl (the frame, function by function, and sung.py's
    `line_key` and `sung_lines`, SungTest its cases by hand), pages-1.jsonl to pages-6.jsonl (every corpus sheet's
    page with every option, as digests: the page, its body, each data member, its names) and page_whole.json (a small
    page whole, the files it inlines by name).
  - A page record is the generator's `page_out` and `PagesReplay.out`: `sha256` and `size` of the whole page, `body`
    and `names` as their SHA-256's first 16 hex digits, `data` one string of `member=digest` in the data's order (8 hex
    digits each), so that it pins the members' order too; another lane's page records take that shape.
  - Printed, every viewer page is in the light palette with a 15 mm margin: viewer.css's dark palette is the screen's
    alone, under `@media screen`, both for the system's dark (`:root:not([data-theme="light"])`) and for Dark chosen (`:root[data-theme="dark"]`, written twice: test_viewer_theme.py), `@media print` sets `color-scheme: light` and `@page`
    the margin, which Android's print framework gives a WebView's page none of (tests/test_viewer_print.py, in
    Chromium's print emulation).
- A harmonica tab's page (harmonica-page): `viewer.pages.HarmonicaPage`, harptab_page.py's builder, byte for byte:
  `build` writes `build_harmonica_viewer`'s page on SheetPage's frame (`page`, `namesTable`, `isChinese`, `zhAttr`,
  `artistLine`, `words`, `LIBRARY_PAGE`, PageConstants' `VERSIONS` and `VERSION_LIST`; `ViewerAssets.Page.HARMONICA`),
  its data's members in Python's order (`groups` and `rows` filled as the tab is written, `versions` and `kinds` after
  `overlay`, SongPass's `renderHarmonica` passing them as render.py does), and its parts under Python's names (`overlayData`, `harpLines`, `readAs`, `footer`, `a`); and
  `viewer.harpfit.HarpFit`, harpfit.py: `pitch`, `words`, `sheetLines`, `recordFit` (PySequence.SequenceMatcher, the
  fits by share then harp), `choose` and `Choice.tabsHarp`, and render.py's `_tab_harps` as `tabHarps` (each
  `HarmonicaTab` a kept tab as render.py reads it; one it can't read, a refused pin among them, gives no harp), the
  harps a sheet's viewers start on (`harpTabs`).
  - Its constants are data/caracole/viewer/harmonica_page.json (harpfit.py's, and harptab_page.py's `_BAR`,
    `_BAR_RAW`, `_PILL`, `_SAID`…), written by tests/test_conformance_viewer_harmonica.py; its numbers as Python
    writes them (`round(q, 2)` a PyJson float; `{share:.0%}`, `{views/1000:.0f}k`, `{views/1e6:.1f}M`,
    `{rating:.1f}★` and `({q:.2f})` through PyFormat), a fact counted only where Python's `isinstance` takes it.
  - `HarmonicaPageReplay` (area `harmonica-page`): vectors/viewer/harpfit.jsonl (pitch, words, a sheet's sung lines,
    each tab's fit and choices, `_tab_harps`), harmonica_pages.jsonl (the parts, and every page as digests: the page,
    its header, tab, foot and bar, each data member, the overlay's two) and harmonica_pages_whole.jsonl (a small page
    whole, the files it inlines by name); the texts that are no fixture in harpfit_texts.jsonl.
- An auto sheet laid out (autochords-sheet): `viewer.autochords`, autochords/merge.py and align.py, function for
  function, the sheet's text byte for byte:
  - `Lrc.parse` and `parseWords` (`LrcLine`, `WordStart`) are merge.py's own LRC reader (`parse_lrc`,
    `parse_lrc_words`), never core's LyricsFiles (lyrics.py's): its patterns through PyRegex, a stamp's numbers
    `int()` and `float()` of any script's digits (PyInt, PyFloat), int()'s ValueError and a float's OverflowError
    raised as Python raises them;
  - `AutoSheet` (`build`, `snapToBeats`, `youtubeCredit`, `withPlainLyrics`, which PlainLyrics calls; internal,
    the vectors' too, `beatGrid`, `barStarts`, `wordStart`, `onWords`, `chordLine`): Python's `round`, `int()`, `statistics.median`, `bisect`, `max` and `min`
    (the first of those tied) and stable sorts by `<` (0.0 and -0.0 tied); lengths and indexes in code points, a chord
    line's columns ChordPro.displayColumns', a word's letters PyUnicode.category's;
  - `Align` (`lyricsOffset`, `Alignment`, `shiftedLrc`; internal `scored`, every candidate's `Fit` before rounding):
    `statistics.fmean` math.fsum's (`Py.mathFsum`, CPython's partials), the builtin sum `Py.fsum`, `why` and the
    stamps PyFormat's, float `divmod` CPython's, a stamp's minutes unbounded;
  - `ChordSegment`'s one home: `:autochords` names it by a typealias (it depends on `:viewer`, never the other way);
  - both modules' constants and patterns are data/caracole/viewer/autochords.json; tests/test_conformance_autochords.py
    writes it and vectors/autochords-sheet/merge.jsonl and align.jsonl (the tests' own calls, both test files'
    literals, characters past the BMP, round()'s ties, seeded hearings, each alignment's fits by digest,
    `math.fsum`), which `AutochordsReplay` (area `autochords-sheet`) replays.
- The sheet half and its re-lay (autochords-sheet): `viewer.autochords`' `Heard`, `SheetHalf` and `Relay`,
  autochords/sheet.py and sheet_lyrics.py's re-lay, so a sheet made on either device re-lays the same on both:
  - `Heard` (sheet.Heard, its one home: `:autochords` and `:ml` name it by a typealias; `duration` null where the file
    names none): `record` and `json` heard_record's, each float as Python's repr (PyJson.float), `read` and `of`
    read_heard's, as strict (an object; `contract` a number equal to 1, never a bool; `duration` there; chords
    `[number, number, text]`; a number an int or a float, NaN and the infinities as json.loads reads them, never a bool,
    a text or an int no float holds), anything else an IllegalArgumentException; the chords COMMON names, as stored;
  - `SheetHalf` (`make`: make_sheet, the song's stored lyrics given; `raw`: raw_of, its members in raw_of's order, the
    side's `Maker` given; `syncedFor`, `Timed.note`, `syncedKey`, `songLyricsKey`, `widerLines`), its constants
    sheet.py's and transcript.py's (autochords.json's `sheet`, `transcript`);
  - `Relay` (`due`: relay_due's reasons word for word; `relay`, RELAY_KEEPS kept; `relaysHere`, `madeByAnother` by kv
    `sync:id`, `notedIn`, `notedOf` over transcript.py's kv as the computer reads it; `onto`: relay_onto_sheets, one
    query for its candidates, no file read for a sheet not due, the raw and the sheet in one savepoint, info.json
    after, an unreadable `heard` left as it is; `Relayed`: the songs re-laid and those that failed, with why, as
    PhoneRender words a song's failure, a bug's "a bug in caracole: …"), every constant read from the data;
  - tests/test_conformance_autochords.py writes vectors/autochords-sheet/sheet.jsonl (make_sheet and raw_of over named
    hearings, float corners among them, × lyrics of each kind, Chinese, past the BMP, a YouTube credit, a transcript,
    nothing sung, three makers; read_heard's every refusal; relay_due's every reason and relay over raws make_sheet
    wrote; relays_here, made_by_another, Timed.note) and relay.jsonl (relay_onto_sheets over a library, three steps,
    the last writing nothing): `AutochordsReplay.sheet` and `relay`, SheetHalfTest and RelayTest.
- The phone's own pages, `PhoneRender` (phone-render): render.py's page path with no PDF, for the songs no mirror
  page serves at their unit's digest (`owed`: kv `render:<id>:phone`'s `unit` and `build` not now's), each pass
  render_all's for the song (`SongPass`: the kept versions' pages, each sheet's .cho and page, an auto sheet's beside
  the human one with no export and none of its shapes and swaps, the harmonica tabs' pages whatever came of the
  sheets, with HarpFit.tabHarps, a viewer's `guitar` from GuitarFiles, inbox.guitar_files' port, and its `kinds`,
  `_kinds_data`'s, each source's name from `page/empty_library.json`'s `icons`, `PhoneRender.sourceName`, and the
  song's timed lyrics, `_timed_lyrics`' read once a song, `lyricsFromJson` then `Lyrics.syncedLines`, none for lyrics
  it can't read, given every page of its sheets and versions), after
  `PlainLyrics` (sheet_lyrics.py, a sheet that keeps no `heard` alone), then `Relay.onto` (render_all's order:
  whoever made the sheet, whether the mirror serves the song or not, as phone_render.py's reference does; a re-lay
  moves the song's unit, its pages then the phone's; a song whose re-lay failed is in `RenderStats.failed`, its pages
  made from the sheet it has; both counted in `RenderStats.given`, render.RenderStats'), and `OwnVersions`
  (own_versions_upgraded); render.jsonl's `relaid` case holds each auto version's raw text by digest, so a phone that
  puts plain lyrics on a heard sheet fails it. Two differences, on purpose: the phone has no log, so a re-lay that
  failed by IO or a `SharedFolder` is in `RenderStats.failed` too (Python's `errors` holds bugs alone, the rest
  logged), and the lookup's pdf stage then says "failed" in the re-lay's words, its pages made (get.py says "made":
  its `render_all` passes no `errors=`); a song the mirror serves gets its
  progressions, script and info.json alone, the phone's own pages of it forgotten.
  - `WrittenPages`: kv `render:files:<id>` as render.py records it, each entry's `unit` the song unit's digest it was
    made at (Units.digestOf: an entry no pass wrote or found as written keeps its own); kv `render:<id>:phone`
    (`unit`, `build`, `script`, which `chineseSongs` reads for the cards, the phone making no PDF record); a songbook's
    kv `songbook:<folder>`.
  - `InfoJson` is library.write_info, its `render` null whatever kv `render:<id>` holds; `RenderBuild` is the app's
    version and, on the phone, the APK's `classes*.dex` and `caracole/` entries by name, size and CRC-32, so every
    APK whose code or tables changed makes the pages again (elsewhere each viewer asset and runtime data file the
    pages read, hashed, each listed and held to its folder by PhoneRenderTest).
  - `render` is the lookup's pdf stage (in its write, its `between` never the queue's), its failed detail render.py's
    log line, the phone's alone; `renderStale` the render job's, a write a song, `between` two
    (JobContext.yieldToQueued: PhoneRenderJobTest on the real queue), passing over a song a lookup made meanwhile, then
    kv `phone:render-build`; a song's pass that fails, on a bug too ("a bug in caracole"), costs the others nothing
    and is stamped all the same.
  - `stale` is the start's, one query (a song this build never made, or kv `phone:render-build` not this build's);
    `afterSync` reads every song's digest, inside the sync's job, and `owe`s (that kv forgotten) what moved, as a change
    on the phone that makes no page of its song does.
  - tests/helpers/phone_render.py is the reference (render_all with `_render_sheet_pdf`, `_render_traditional` and
    `_remake_exports` making nothing, `_write_viewer` linking no PDF, `_drop_human_outputs` the phone's and no PDF's
    record read, whatever PDFs the library holds; then the phone's records and info.json);
    tests/test_conformance_viewer_render.py writes vectors/viewer/render.jsonl (fixture libraries and steps: renders, a
    file dropped, one deleted), which `RenderReplay` (area `render`) replays: the names, each pass's info.json and
    units, and every step whole.

##### The phone's written pages

- `LibraryFiles` serves a page the phone wrote (a sheet's viewer, a kept version's, a harmonica tab's, a songbook's in
  `_songbooks/<folder>/`) as app.py's `_written_page` does, before the mirror's:
  - while it is the bytes WrittenPages recorded (`render:files:<id>` among the songs whose folder it is in, of those
    with a record; `songbook:<folder>`), read once, of a recorded size and SHA-256, and its unit (the song's, or the
    songbook's, `WrittenPages.songbookUnit`) is still at the digest it was made at (each entry's `unit`);
  - with `SheetPage.viewerCsp` of those very bytes (its `_NOTHING` sandbox for a page with no policy) and
    `frame-ancestors 'none'`;
  - otherwise the mirror's through PhoneGate, else a message page: 409 for a unit moved since its page was made (the
    phone's sheet.txt linked), 404 Not sent, by the page's kind, for one changed on disk;
  - a .cho it wrote the same way, as text (LibraryFilesTest).
- Its checks are made on the path, then the file is opened with no link followed and its bytes checked: the library
  is the app's own folder, which nothing but the app writes.
- `PhoneRender.afterSync`, after a take: the pages the take superseded forgotten (`forgetSuperseded`: each deleted
  while it is as written, its record's entry with it), a song's or a songbook's made at a digest its unit has moved
  from where the mirror now serves it at its digest, and a songbook's whose folder no songbook has any more; a moved
  song's page the mirror doesn't serve stays, never served, for the render job to make again.
- A removal takes the phone's written pages by their records: each `render:files:<id>` entry naming the `unit` it was
  made at, as removal.py takes a version's or a tab's page (the phone makes no PDF, so no render record names them); a
  record render.py wrote names no unit and keeps removal.py's answer (RemovalWrittenTest).
- A take that moves or respells a song's folder deletes the phone's pages of it still as written rather than moving
  them (`Removal.phonesWritten`, SongTake), so no page is left there unrecorded and a removal after it empties the
  folder (RemovalWrittenTest).
- PagesServedTest opens one in the WebView: its own policy and an opaque origin, refused once changed on disk or once
  its song's unit moves.

##### Songbooks, versions and printing on the phone

- Songbooks, their entries and the Songbooks tab (songbook-writers, songbook-entries, songbook-routes):
  - core.songbooks' `Songbooks`: songbook.py's names, entries and writers over phone_songbooks
    (vectors/songbook/writers*.jsonl);
  - server/songbooks/`SongbookEntries` (songbook.py's entries, where each plays, `songs_to_get`, `with_capo`,
    `on_instrument`), `SongbookPagesImpl` (render_songbooks: each songbook's songbook.html alone, kv
    `songbook:<folder>`, no PDF nor .cho) and server/page/`SongbookSection` (the Songbooks tab's data, the page's and
    `/jobs.json`'s: PageRoutes puts it in place of the mirror's); a song whose pages are the computer's plays from the
    mirror's .cho of it (`SongbookEntries.sheetOf`); vectors/songbook/entries.jsonl and tab.jsonl;
  - the Songbooks tab's forms, server/routes/SongbookRoutes.kt: each `/songbook/*` form queued as its `caracole
    songbook` command under web/songbooks.py's key (`songbook\u001f` and the command's words; a setting's, its songbook
    and song first; Get the missing songs' render, the last lookup it follows), refused in songbook_routes.py's words
    before anything is queued (a mirror's card, a negative id: "isn't in the library any more");
    - Get the missing songs: one lookup a song (`get --no-songbooks`, SongbookEntries.songsToGet: none of a song whose
      sheet the phone or the mirror keeps) with room left for the songbook's `songbook render` after them;
    - Add a song: a song of the library's add alone, else its lookup (LookupForms.lookupRequest, whose `caracole get`
      adds it) and the add, `JobQueue.submitAll`, both or neither;
    - vectors/songbook/routes.jsonl (tests/test_conformance_songbook_routes.py, SongbookRoutesReplay): each form's
      answer, its jobs' views, and the queue's jobs, scenario by scenario;
  - the songbook runner, server/songbooks/SongbookRunner.kt: commands/songbook.py's make, add, remove, move, set,
    rename, delete and render through Songbooks in one write, a song found as the command finds one (its "Artist -
    Title", else a search one song answers well), then the songbook made again through `PhoneParts.songbooks`
    (SongbookPagesImpl), and what `_render` says of it (the songs it names missing, the files it wrote);
    - its lines and exit statuses are the command's: vectors/songbook/routes_runner.jsonl (commands/songbook.py through
      CliRunner over the tab's library, render_songbooks making nothing) and the songbooks after;
    - a message of several lines is its `error:` line, then the others; a songbook whose page can't be made is a
      `warning:` line and exit 1 with no `error:` line (typer.Exit(1): `CommandExit` with no words, which the queue
      writes none for), so the Requests tab says "Making the songbook failed." as caracole serve's does;
  - area songbook-tab (SongbookTabReplay, the routes' replays with it); SongbooksOnDeviceTest drives the tab in the
    WebView (Select's Make songbook, a song's chip, the songbook's Phone page).
- A sheet's versions and a harmonica tab's readings chosen on the phone (versions-harmonica): server/routes'
  `VersionsRoutes` and `HarmonicaRoutes`, their pages server/pages' (`VersionsPage`, `HarmonicaPage`, `Choices`).
  - `GET /versions`, `POST /versions/choose`, `/keep`, `/clear` (versions_routes.py; Fetch them, `/versions/keep-more`,
    is LookupRoutes'), and `GET /harmonica`, `POST /harmonica/pin`, `/clear` (harmonica_routes.py).
  - Each page the server's own with no script (the message pages' style and policy), reached from the sandboxed
    viewer by a plain GET (a top-level navigation: the launch's cookie is Lax), its forms posting with the form token
    (Assembly gives both modules `deps.csrf`), one that follows a request reloading every 10 s; its words, refusals
    and jobs Python's.
  - A viewer is the phone's when the phone recorded writing it (kv `render:files:<id>`, WrittenPages): a computer's
    page the mirror serves names no sheet (404), as LookupRoutes' keep-more by sheet.
  - Each post a job: under the song's key, the `versions` runner (VersionsRunner, joined as jobs.py's `_pick`); or
    under jobs.READING, the `harmonica` runner (HarmonicaRunner: harmonica_cmd.py's pin, clear and list, the pin
    checked by `HarpTabs.checkSpec` and written by `OverrideWriters.addHarmonica`, then the song rendered again
    through `PhoneParts.pages`).
  - vectors/web/versions_routes.jsonl and harmonica_routes.jsonl (tests/test_conformance_choices.py: a library a
    scene; every page whole but its stylesheet, every post's job, `caracole harmonica`'s runs), `ChoicesReplay`
    (area `choices`).
- Export PDF and Make this my version (export-print): `ExportRoutes`' `GET /export.pdf`, export_routes.py's checks
  and refusals in its words, answering `{name, label}` (download_names' name, `ExportSheet.label`) in place of a PDF.
  - A viewer is the library's where the phone recorded writing it (`WrittenPages.written`, render.written_file's kv
    `render:files:<id>`) or the mirror holds it under the song's unit (`ExportRoutes.mirrorOf`, the cards' mirror),
    the computer's pages being most of what the phone shows (PhoneRender forgets its own of a song the mirror serves).
  - `Exports` and `ExportSheet` (server/routes/ExportSheet.kt) are render.py's export half: `export_version`,
    `export_query`, `export_traditional`, `export_viewer`, `export_sheet` over `_export_source`; its sheet is the one
    the phone's viewer shows, its ChordPro PhoneRender's `.cho` byte for byte (ExportRoutesTest).
  - Making no PDF, the phone names any version the viewer's code can read, where caracole serve refuses one whose PDF
    can't be made (500).
  - `mine=1` (a GET, never a HEAD) queues `render --song=… --version=… --mine` under `export:<key>:<version>:mine`:
    the phone's one write with no form token (ExportRoutesTest posts every other without it). `RenderRunner` writes
    `ExportSheet.kept` through `OverrideWriters.addVersion` (checked by `Versions.keyVersion`), then makes the song's
    pages (PhoneParts.pages, PhoneRender: a song the mirror served gets the phone's own, its unit's digest moved) and
    the songbooks (PhoneParts.songbooks) again; plain `render`, each song in a write of its own, the queued lookups
    let go between two; `--version` alone, a PDF beside the sheet, is the computer's.
  - The app's `Printer`: the server asked in-process (`ask`, as LocalFiles asks), then `PrintManager.print(name,
    web.createPrintDocumentAdapter(name), A4)` on the WebView shown, on the UI thread; nothing kept. PrintTest, on an
    emulator alone (it stops the print spooler), checks the job, a link the page follows through MainActivity's hook,
    and runs the WebView's adapter as the print spooler would (android.print's `PrintedPdf`, the callbacks'
    constructors being that package's): an A4 PDF.
  - vectors/web/export.jsonl, tests/test_conformance_export.py (caracole serve's route, `version_pdf` giving the label
    alone, checked against `_export_text`'s; a message's library folder `{library}`, a reader's own words on a file
    left out, `prefix`), `ExportReplay` (area `export`).

##### An uncertain match reviewed on the phone

- server's `ReviewRoutes` is review_routes.py:
  - `GET /review?song=ID`, the picker's page (the Journal's Pick, a song not found's Search the
    index), pages.picker_form's markup in the message page's frame and policy (`MessagePage.html`: no script);
  - `POST /review`, its answer and the card's picker's: `caracole review --song=… --pick=…` (or `--none --seen=…`)
    queued under the song's key, never joined (`join` false), refused while the song's own request waits or runs;
  - a pick with Fetch ticked is looked up after it by `caracole get` (the lookup Fetch now queues), in place of
    caracole serve's `caracole fetch --song` and `render --song`, which the phone hasn't: its line, while the review
    runs, the lookup's first stage's, as status.py says it of a job with a lookup ("Finding the song…");
  - the page's form token is Assembly's (`ReviewRoutes(parts, csrf)`, no default), so its Pick posts as the card's.
- server/lookups' `ReviewRunner` is commands/library.py's `_answer`, in one savepoint: `Review.accept` (`[match]`, and
  `[alias]` when `writesAlias`) or `Review.reject` (the candidates seen, else every one listed, under `[reject]`),
  `review` false, then `Matcher.matchAll` over the song and, after an `[alias]`, every song with that artist among its
  artists; its lines caracole review's but `Wrote …` (the phone writes no _todo.md or index.html).
- `Review` is review.py's rules: `searchCandidates` (core.search's `searchIndex`, less the song's `[reject]`),
  `writesAlias`, `accept` and `reject`, and, as the cards' `Choices` ports them (library-cards), `candidatesOf`,
  `ref`, `stepWords` and the picker's choices (library_page.review_choices).
- vectors/web/review.jsonl (tests/test_conformance_review.py, `ReviewReplay`, area `review`) holds both routes, the
  rules, the command over a copy of a library, the job's line after it and a pick with Fetch it now's lines as it
  runs; ReviewRoutesTest the phone whole (its page's form posted, a pick refused while the song's request runs).

##### Guitar Pro on the phone

- server.guitar's `AlphaTabBundle` is web/alphatab.py (`bundle`, `fontFace`, `load`), `GuitarPage` web/guitar_page.py
  (`style`, `script`, `policy`, `build`, top.py's header) and routes/GuitarRoutes.kt web/guitar_routes.py: `GET
  /guitar?file=` and `GET /assets/alphatab/<name>`, caracole serve's answers (its `parse_qs`, strict and four fields at
  most; a file the phone's `files` records alone; Power Tab; past 8 MiB; a link at any step; the sheet viewer its
  folder holds), held by vectors/web/guitar.jsonl (tests/test_conformance_guitar.py, `GuitarReplay`, area `guitar`).
- :core's `GuitarFiles.of` is inbox.guitar_files, phone-render's port, the one the render, the cards, the set lists
  and the page read: N `int()`'s of any script's digits, ordered and labelled by the whole number (`wholeNumber`; an
  Int `number`, `Int.MAX_VALUE` past one, a name caracole never writes), past 4300 digits Python's ValueError.
- **The bundle in the APK**: app/alphatab.gradle.kts makes it from `CARACOLE_ALPHATAB_DIR` (android/flake.nix,
  ../nix/alphatab.nix) as `bundle` does:
  - the asset `alphatab/<name>`, beside `alphatab/licenses/` (MPL-2.0, OFL, Apache-2.0);
  - its name, integrity and CSP sources as the Java resource `caracole/web/alphatab.json`, which
    `AlphaTabBundle.installed` reads;
  - one task a variant, wired through the Android Gradle plugin's variant API reached dynamically (a script plugin
    sees none of its classes);
  - without the variable the build fails, naming it: never an APK without the bundle.
- **`AlphaTabAssets.answer`**, MainActivity's `shouldInterceptRequest`'s first: the sandboxed page's request for the
  bundle carries no launch cookie, so the app answers `GET /assets/alphatab/<name>` of the server's exact origin
  (127.0.0.1 at its port, once it listens) from its assets, with guitar_routes.asset's headers and app.py's
  (`Access-Control-Allow-Origin: *`, the script being CORS with its integrity; `text/javascript; charset=utf-8`; kept
  for good), any other name there 404; the server's own route answers only a bundle whose bytes it holds (the JVM's
  tests).
- `ServerControls.guitar` is `GuitarRoutes.available()` (the APK's bundle there), so the served library page opens a
  card's `guitarPage`; mirror's `Links` routes `/guitar?file=` as a page, a download of it the file.
- Beyond caracole serve:
  - a path the phone's library records no Guitar Pro file at, that the mirror lists as a file (a song only the
    computer's pages copied), is a 303 to the file, which the app hands to another app as before (the mirror reached
    through `PhoneParts.cards`, PhoneParts naming none);
  - a file past 8 MiB is refused before it is read, never held whole to be refused.
- Tests: server.guitar's GuitarPageTest (the vector, the APK's bundle as named, the mirror's 303); the app's
  AlphaTabAssetsTest (the build's resource is the port's bundle of the same files); androidTest's GuitarPageTest (the
  APK's bytes Python's, the licences, and the page in the WebView: drawn, the font's stylesheet allowed by its hash, the
  synthesizer ready, Play and Stop, Download handed off).

##### A song shared to the app

- A music app's Share of a song is `ShareLinkActivity`'s (SEND of text/plain alone, its own intent filter; files are
  ShareActivity's): its extras logged under `caracole-share` (`SharedLink.said`), then the library screen loads
  `GET /share` with them (`SharedLink.page`; MainActivity takes a share page alone from an intent, and Cancel,
  `/share/cancel`, as `leaveShare`: the history before the share, the sender in front).
- core.share's `SharedText.read`, the one place that knows each app's words, before read_names: the app (package,
  link host, words), the first link, each app's shape (`SHAPES`: Deezer's, Shazam's, SoundCloud's… as "Artist -
  Title"), else the text less its links and an app's name, with no request. tests/fixtures/share/shares.jsonl holds
  each app's shapes and where they were found (SharedTextTest).
- A text that names no song but a link of Apple Music's, Spotify's, TIDAL's, YouTube's or YouTube Music's is read by
  asking its service once, the owner's choice of 2026-11-10 (Politeness, "A shared link read by asking its service
  once"):
  - core.share's `ShareLinks.of`: what the link is, with no request (a song's id, a short link, or an album, a
    playlist, an artist… that names no song, said so); `answer`, what the service's answer names (Apple's lookup,
    Spotify's and TIDAL's track page, YouTube's oEmbed: a video's title and channel, read by read_names as a pasted
    video's), a page that won't parse a `ShareParseError`, never a miss;
  - `ShareAsk`: off, the cache's answer with no request and no write, else one ask through the lookup's envelope
    (`InteractiveAsk`, run `lookup:share:…`) inside one write (server's `ShareReader`), its words one line;
  - ShareLinksTest and ShareAskTest, over the services' answers to caracole of 2026-11-10 (tests/fixtures/itunes/,
    spotify/, tidal/, youtube/).
- server's `ShareRoutes` is the phone's own page, which caracole serve has none of:
  - the names through `SongNames.readNames` (a link's service's, "Read from Spotify's page: …"), searched as
    `/api/search` searches (`SearchRoutes.answer`);
  - its rows on one line a song (`SongLine`, as mergeSites), the best (`best`, else the names' identity);
  - Fetch the library page's `POST /lookup`, Open, Edit (`GET /share?artist=&title=`), in the message page's frame
    and policy (`MessagePage.html`: no script).
  - A `GET /share` asks a link's service by itself only when the browser says no other site sent it there
    (`ShareRoutes.asks`: `Sec-Fetch-Site` `none`, the app's own loadUrl of a share, or `same-origin`, a link of
    caracole's pages), the owner's choice of 2026-11-15; else (cross-site, same-site, or no header) the cache's answer
    alone, or Read the link, a form that posts the share again to `POST /share` with the form token, which asks once.
    So no other site's page makes the phone ask a service or write (the one write with no token stays `mine=1`).
  - A YouTube video shared (its link's id, `OverrideUrls.videoIdFromUrl`; through Edit as `youtube`): Make its sheet
    from this video (the phone-youtube design's §5.2, `SharePage.MAKE`), a form posting the library page's `POST
    /request` with `artist`, `title`, `youtube` and the form token (YouTubeRoutes' `youtube --sheet --url` queued),
    where `YouTubeRoutes.whyNotFromVideo` offers it: the route ready (`Phone.youtubeProblem`, then a cooldown), the
    names read, the song not ignored, with no human sheet and no audio of its own; first and the page's main button
    where no site has the song's sheet (`SongLine.sheetOnSites`), else second to Fetch. Otherwise no button and one
    hint, the route's words ("No sheets from YouTube here: …", "… already has a sheet.", `NO_NAMES`). Nothing
    downloads before the owner presses it, a share by mistake spends no run; the names come of oEmbed still, the
    page's one request, and Edit's names are the ones the sheet is made under.
- ShareRoutesTest and SharedLinkTest on the JVM, ShareLinkTest on the device (the WebView's loadUrl of a share and a
  link of caracole's page both ask by themselves; a YouTube video's button or its hint).

##### Files shared to the app

- `ShareActivity`: SEND and SEND_MULTIPLE of the manifest's stream types (never VIEW or text/plain); a share of mixed
  types, `*/*`, `application/*` or `audio/*`, offers caracole too, as Android matches a wildcard type against any type
  a filter names, and each file of a kind it keeps nothing of is answered Not filed (ShareTest pins both). Each file of
  EXTRA_STREAM (else the share's ClipData), one at a time, read whole while the share's grant holds, at most
  `InboxShare.MAX_BYTES` (64 MiB), with its display name and type, and staged and queued before the next is read, each
  its own line; only a `content:` address (`ShareActivity.refused`: a `file:` one could name caracole's own files, which
  its process may open; its own FileProvider shares the cache's `handoff/` alone). Then finished, and a toast of each
  file's line, the Requests tab's (`ShareActivity.told`, ShareTest's).
- An audio file (`AudioShare.isAudio`: an audio type but MIDI's, the manifest's 13 of §8.2 among them, or an audio
  extension under a type that says nothing) shared alone is no inbox file: its stream read once into an upload
  (`AudioRoutes.stageShared`: the store swept, `AudioStore.stage` a chunk at a time, never held whole; refused before a
  byte is read where `Phone.audioProblem` says why), then the library screen opens `GET /share/audio?upload=ID`
  (ShareRoutes', `AudioSharePage`, the message page's frame, no script: the file, the guess, the library's song and its
  sheet, words heard on the computer said, Make sheet the library page's `POST /audio`, Cancel `POST
  /share/audio/cancel`, the upload dropped then `/share/cancel`, which the app takes as leaving the share); where no
  sheet is made, `?name=` and why, naming Settings; each audio file of a share of several "Share one audio file at a
  time." (ShareAudioTest, AudioSharePageTest). The page's file input that asks for audio (the "+") opens the picker on
  the audio types (`FileChooser`, `AudioShare.chooser`).
- server's `InboxShare.share`: the file's name (core.inbox's `InboxFolder.nameFor`: its display name's last part, an
  extension from its bytes, `GtpTabsFetch.sniff`, or its type when it has none inbox.py files), staged in
  `stateDir/inbox/` (`InboxFolder`: one file a name, " (2)" before a second's extension, which parse_download_name
  drops; regular files alone, no link followed), and its filing queued, a job of PhoneKinds' inbox kind keyed
  `inbox:<name>`, run by the inbox runner (`InboxRunner`, `caracole inbox -- NAME`, as the job's own run, so its
  stage `file` says PhoneKinds' words: a command's stage events would be its output lines). A name with no
  extension inbox.py files is never staged.
- core.inbox's `Inbox.file`: inbox.py's filing of one `_inbox/` entry, in one Database.write: `parseDownloadName`;
  `match`, by identity key, then `MusicNames` (music.Names: Fuzz.ratio and tokenSetRatio) at 90 among the songs not
  ignored, a title alone only when one song fits; `_place`'s numbering (core.library's `Numbering`) and the song's
  `inbox` version; `Kept.keepFile`; `_copies` and `_again`, a lost copy put back by its bytes, a duplicate where the
  library holds one (`Inbox.held` names it), left waiting where its place holds other bytes now (`Inbox.changed` names
  it: the job fails "Not filed: … whose place holds other bytes now, and nothing is replaced", the file staged still,
  as inbox.py leaves it in `_inbox/`). MusicXML's header is never read on the phone: a score is placed by its name
  alone (the plan's §11, Q12).
- A file no song fits waits: `InboxRetry`, the phone's afterJob, queues each waiting file that fits now
  (`Inbox.fits`, read only, every song's names made once a pass, `Inbox.Candidates`) after a job that ran of kind sync,
  song or add, and after the process's first job whatever its kind (a share whose job the process's end cut short:
  Try again can't repeat a run of the phone's own), and drops after any job the files that waited 30 days
  (`InboxFolder.sweep`). A filing that failed (a `SharedFolder`, an IOException) is remembered (`InboxFolder.failed`,
  `stateDir/inbox/.failed/<name>`) and tried again after a sync, else a day on (`InboxRetry.AFTER_FAILURE`), never
  after every lookup. A file kept or put back has its song's pages made again (`PhoneParts.pages`).
- vectors/inbox/ (tests/test_conformance_inbox.py, `InboxReplay`, area `inbox`): names.jsonl (parse_download_name
  over every download name tests/test_inbox.py writes and more, music.Names' forms and scores), match.jsonl
  (`_match`), file.jsonl (one file filed over file_fixture_library.jsonl: what it came to, the rows and files it
  wrote); none filed by a MusicXML header.
- InboxTest and InboxRunnerTest on the JVM, ShareTest on the device.

##### An audio file given to the phone

- core.library's `AudioStore(stateDir, examiner)` is audio_store.py (`stateDir/audio/`, 0700, each file 0600), its
  constants, name patterns (PyRegex), record and marker members and every refusal's words and status data,
  data/caracole/library/audio_store.json (tests/test_conformance_audio_store.py): `sniff`, `displayName`, `stage`,
  `staged`, `gone`, `drop`, `sweep`, `marked`, `keep`, `adopt`, `uploaded`, `givenName`, `tidy`, `keptIn`,
  `givenFile`, `namedByAnother`, function for function, the marker written before the data's move and the record
  let go once the row names the kept file; one in-process lock (`held`), `named` called under it, never a database
  write under it (`keep`, `adopt` and `tidy`, inside a job's write, take none).
- Where it departs: `stage(input, name, named)` spools a stream into `.upload-<id>.part` (the phone's own name, which
  `sweep` lets go an hour after its last write), its SHA-256 streamed, refused as soon as it is known: NOT_AUDIO once
  its first `HEAD` bytes are in (a non-audio body past `AUDIO_MAX` is NOT_AUDIO here, TOO_BIG on the computer), at
  the first byte past `AUDIO_MAX`, NO_ROOM every MiB once the free bytes and those of the staged uploads it may let go
  (listed again at each check) are under the spooled ones and `ROOM` (needed for Python's check to pass: it refuses
  nothing Python takes; so an early NO_ROOM comes before TOO_BIG, TOO_LONG and the examiner's NOT_AUDIO, which Python
  says first); then
  exactly, under the lock after the others go (the free bytes with the spooled ones counted free, under twice them and
  `ROOM`: Python's check before its write). A refusal leaves the stream unread and open (the route drains or closes
  it); a read of 0 bytes is a broken stream, an IOException. `keep(db, song, staged)` moves a staged upload alone (a
  file of your own's copy is the computer's). `:core` reads no audio: the app's `Examiner` gives a
  file's length and tags (an MP3's its frames' count, mpeg_frames.py's, wherever not 0; each tag's values in music.py's
  key order; an M4A with no sound track thrown), the store judging the rest (the format the bytes said, a length over
  0 and finite, `MAX_SECONDS`, music._first's stripped tag); whatever it throws a refusal, but an IOException of a
  file kept on the disk.
- A removal deletes the song's given file, none another song's row names (`LibraryStore(libraryDir, audioDir)`,
  `Removal.uploadedAudio`, `Result.audioDeleted`), and its question says so in removal.py's words
  (`AudioStore.REMOVAL_GOES`, `REMOVAL_BRIEF`); the re-keying merge keeps a file given (`Rekey.givenAudio`,
  songs._given_audio: the later `audio_mtime`, kv `audio:name:` with it).
- vectors/library/audio_store.jsonl (`AudioStoreReplay`, area `audio-store`): sniff and its two tests over every head
  test_audio_store.py builds and edges, the shown name, the patterns' matches, kept names, the record's and marker's
  texts and reads, `given_file` over trees, and `merge`; AudioStoreTest (each of a cut-off keep's states, a stage of
  100 MiB under an allocation bound) and LibraryRoutesTest's removal.

##### A sheet from an audio file on the phone

- server/lookups' `AudioRunner`, `caracole audio --progress --upload=ID --song="A - T"` (`commands["audio"]`,
  `JobCommands.audioSheetSteps`, key `audio:<song key>`), audio_sheet.py's job on the queue's worker, its stages,
  lines and outcome the computer's (Status, Outcomes' `AUDIO_STEPS`), its words audio_sheet.py's, youtube_sheet.py's,
  staged.py's, transcript.py's and commands/audio.py's from data/caracole/library/audio_sheet.json
  (tests/test_conformance_audio_sheet.py). Before any stage, as the command: `Phone.audioProblem()`
  (`AudioRunner.problemOf`, the one answer for the job and E24's routes: no `PhoneDeps.chords`, `LibraryPage.
  AUDIO_PROBLEM`; the models not installed, `ModelsRunner.ready()`, "the chord models aren't downloaded (Settings ›
  Chords from audio)"; else `ChordModels.ready()`'s own words) refuses "caracole makes no sheet from an audio file
  here: …", exit 1; the upload read as the command reads it (its staged record, or the kept file its marker names),
  the store's refusal exit 2 (400) or 1, the disk's "can't read the upload: …" exit 1. `--song` is required: the
  routes always give it.
- song (found or `LibraryStore.add` with the file's album and length, get.py's `ADDED`; refused ignored or with a
  human sheet), audio (`AudioStore.keep`, `adopt` by the marker, "has this file's audio already" once done), lyrics
  (core.lookup's `Lookup.lyrics`: the lookup's three stages alone, LRCLIB and Megalobiz asked with the audio's length,
  `StageContext.length`, at the lookup pace and in get.py's words, where the computer's job asks at the bulk pace in
  youtube_sheet.py's: by design), vocals and words skipped (a site's words or verdict, `SITES_ANSWERED`, in the
  offer's words, "not transcribed: its lyrics are found"; else, missing or pending after a site's error, "not
  transcribed here: the phone hears no words", `transcript.PHONE`; "no vocals"),
  chords, pdf and pages (get.py's `NO_PDFS`/`PAGES_MADE`, `LIBRARY_PAGE`, staged.py re-exporting them).
- chords: the queued lookups go first (`yieldToQueued`), the song read again and still the job's (not ignored, no
  human sheet, its `audio_path` the file kept, else a refusal that ends the job); a sheet already made of this audio
  is up to date or re-laid (`Relay.onto`); else `ChordModels.hear` holding no write, `yieldToQueued` every second;
  read again; then in one write `SheetHalf.make` and run.py's `_keep` (the song's one auto version, `refreshStatus`,
  info.json, `autochords_mtime` last; info.json failing after the keep fails the stage "the sheet was kept (…), but
  its info.json couldn't be written", `autochords_mtime` set, so it isn't heard again, and pdf, pages and the readable
  sheet go by the sheet kept, never by the chords stage's state), the maker the phone's (`made_on` "phone", kv
  `sync:id`, `ModelsRunner.names()`, models.json's names, `ChordModels.runtime`, kv `audio:name:`, the file's sha16).
  Failures: `AudioUnreadable` "audio the phone can't read: …", `ChordsUnavailable` in its words, a bug laying out "a
  bug in caracole: …"; each exit 1, nothing recorded against the song (no `autochords:failed:`: the phone tries again
  at Try again).
- The queue's yield passes over a lookup of the running job's own song (`JobCommands.songOfJob`, jobs.song_of_job:
  a song never has two jobs running): it waits for the job's end. `ModelsRunner.USES` holds `audio:`, so the models'
  remove is refused while a sheet waits or runs; the hearing itself holds the files (`ModelsRunner.holding`, a read
  lock that `remove` must take for writing, AudioRunner's `hold`) and asks `Phone.audioProblem()` again under it, so
  a remove after the job was queued fails its chords "the chord models aren't downloaded …". What `waiting` throws
  (the queue's stop) propagates through `hear` as itself, never as `ChordsUnavailable`: the job ends as the queue's
  stop, its audio kept, no sheet. `ChordModels.forget(audio)`, once the sheet is kept and never before: `:ml`'s
  checkpoints go then (MlChordModels, `forgetHeard`; the sheet kept only once its `autochords_mtime` is written, the
  keep's last write), so a keep that fails leaves them and Try again hears nothing again; `forget` never throws (what
  letting go throws logged, the folder left); a job refused after a whole hearing (the song got a human sheet
  meanwhile) never calls it, so its folder waits for the day-old sweep and MlChordModels' entry of it stays for the
  process's life; the start's sweep (`sweepOld`) takes those a day old under the hearings' one turn, none while it is
  held.
- `ChordModels`, `AudioUnreadable` and `ChordsUnavailable` live in :viewer's viewer.autochords (`:autochords` names
  them by typealias): :server, which the release ships, never depends on `:autochords`, whose `caracole/autochords/`
  data release-check.sh keeps out of the release.
- The phone notes no transcript or nothing-sung verdict of its own: `Relay.notedOf` of its own audio is the empty
  `Noted`, which is `notedIn` of a phone-made raw (it holds neither), so the computer's re-lay of a phone-made sheet
  is the phone's.
- The app's chords (E22): `PhoneDeps.chords` is `PhoneChords.of` (src/ml's, both builds of the ml shell: `:ml`'s
  `MlChordModels` over the folder the models' job installs, `forgetHeard`, the device's reasons with this APK's ABIs,
  `BuildConfig.ML_ABIS`; src/noMl's, a build without `:ml`: null, and `audioProblem()` says auto-chords isn't on the
  phone); `PhoneDeps.models` is its default (`ModelFiles.carried()`: `:ml`'s pins). `PhoneChords.sweep` after
  `Phone.start`, a failure logged (`guarded`). A device test sets `PhoneChords.anyPhoneHearsForTests` (the emulator's
  2 GB) and `Caracole.examinerForTests`.
  ChordsEndToEndTest (`device-test.sh --models --sites chords
  ChordsEndToEndTest`; `--models` pushes the models with none of `:ml`'s classes) installs the pushed models through
  the models' job (copied into `stateDir/models/.c1.kept/`, hashed again by `ModelsSource.fetch`, nothing asked, the
  real manifest written), stages hearing.mp3 through `Phone.audio`, queues its job on the real queue against
  fake_sites' `chords` (LRCLIB timing the clip's song): Ready, "chords over the lyrics", the sheet's `heard` back to
  Harte labels at B1's WCSR and beats F against models.jsonl's hearing, LRCLIB's requests alone, the maker's members,
  the checkpoints gone; `:ml` killed mid-job (long.wav) fails the chords in `DIED`'s words, the library page
  answering; and `hear`'s contract on the real process (what `waiting` throws, as itself; `BUSY`).
- `Phone.audio` (`AudioStore(stateDir, PhoneDeps.examiner)`, by default `NO_EXAMINER`, which reads no file); `tidy`
  runs as the phone starts and after a sync's take, a write of its own, never under `held`.
- The app's examiner, `PhoneExaminer`, a build with `:ml`'s (src/ml, beside `:autochords`, an implementation then;
  src/noMl's refuses every file, its routes refusing first anyway): its length `:autochords`' `AudioLengths` by
  the format the store gives (a spool has no extension): an MP3's `MpegFrames` count (mpeg_frames.py's port) where
  its first frame names none, else `MpegHeader`'s; an M4A's sound track's `mdhd` (`Mp4.Track.sound`: none with no
  sound track, refused); FLAC's STREAMINFO; `Ogg`; `Pcm`. Its tags Android's (MediaMetadataRetriever: artist, then
  album artist, title, album; none where it can't read them). A known divergence, kept: a WAV's and an AIFF's ID3
  chunk, which mutagen reads on the computer, Android doesn't, so their guess comes from the file's name (the
  dialog's fields are editable). AudioLengthsTest holds each length to the computer's store's over
  vectors/web/audio_routes.jsonl's `examine` records, to the bit; AudioRoutesOnDeviceTest the real one.
- server/routes' `AudioRoutes(parts, store, problem)`, web/audio_routes.py's three routes: `POST /audio/upload`
  (`Route(spool = true)`: App hands its answer the body as a stream, a test's bytes wrapped, refused 413 by its
  Content-Length past the limit; LocalServer streams it from the socket, never whole in the heap, 413 in server.py's
  words before reading a body past it, a body ended short of its Content-Length a 400 in server.py's words ("That
  body is shorter than it said it was."), never a whole upload, and an answer that left it unread says `Connection:
  close`, CIO dropping the rest, never reading it as a request; a chunked one past the limit is drained uncapped,
  behind the launch secret), `POST /audio`, `POST /audio/drop`, in their words and statuses (the store's
  refusals; `NOT_HERE` with `Phone.audioProblem()`'s reason; a song with a sheet or ignored; `WAITS`); the store's
  `held` from what Make sheet and a drop read of the queue to what they change, an upload's `named`
  (`JobCommands.uploadsNamed`, jobs.uploads_named) read under it; `sweep` at each upload; the route closes the
  stream on every end. A song by name is the job's to add (the phone writes no wanted.txt, so its note is none).
  `namesOf` is audio_sheet.names_of (`bareName`: pathlib's stem, music.py's track number). `server.audio`
  (`ServerControls.audio`, `Phone.audioProblem()`): `audio_member`'s shape, `ok` true with `AUDIO_MAX` and
  `too_big` where it is null. vectors/web/audio_routes.jsonl (tests/test_conformance_audio_routes.py, area `web`; each step's `keys` its
  answer's members in Python's order, `out` being written with sorted keys):
  each route over scenes of one library (a sheet, ignored, a purchase, YouTube's audio, a file given), the computer's
  reader's reads recorded for the phone's fake examiner, the routes' limits, `audio_member` where it makes sheets,
  and `examine` over the fixtures; `WebReplay.audioRoutes` (AudioRoutesReplay), AudioRoutesTest, LibraryPageTest,
  LocalServerTest's spooled bodies.
- vectors/lookup/audio_sheet.jsonl (`AudioSheetReplay`, area `audio-sheet`): Python's job with fake models over the
  fake lyrics sites, replayed through AudioRunner with a fake ChordModels answering the record's `heard`; compared
  apart: the lyrics stage's words, a failing hearing's chords words, the events' runs, the pauses, the maker's side,
  the kv the phone never writes, and `provider:lrclib` where LRCLIB errs (the lookup's envelope records the error, the
  job's bulk pass none); and a phone-made sheet re-laid alike on both sides. AudioRunnerTest through the
  real queue.

##### A sheet from a YouTube video on the phone

- server/lookups' `YouTubeSheetRunner`, `caracole youtube --sheet --progress [--url=URL] --song="A - T"`
  (`commands["youtube"]`, key `youtube:<song key>`), youtube_sheet.py's job: `StagedSheet`, the stages it shares with
  `AudioRunner` (song, lyrics, vocals, words, chords, pdf, pages: one class, `AudioRunner` and it its subclasses), its
  audio stage youtube_fetch.py's `_one` for the song; its words youtube_sheet.py's constants from
  data/caracole/library/youtube_sheet.json (tests/test_conformance_youtube_sheet.py), the rest audio_sheet.json's.
  Before any stage `Phone.youtubeProblem()` (`YouTubeSheetRunner.problemOf`: YouTube off in the computer's settings,
  `AudioRunner.problemOf`'s reasons, no `PhoneDeps.youtube`, `YouTubeEngine.ready()`) refuses "caracole makes no sheet
  from YouTube here: …", exit 1.
- song: found or added (a song by name added with the album and length its request named, `JobSpec.song` read as
  `JobContext.adds`, never the argv, as wanted.txt's line keeps them on the computer: `_the_song(album=,
  duration_ms=)`, so LRCLIB is asked with that length), refused with audio of its own (an upload of `AudioStore`'s, or an `audio_path` that isn't its
  `youtube:` record's: `_still_ours`) or `[youtube]` "none" with no video given; `--url` noted under `[youtube]`
  (`OverrideWriters.addYoutube`, overrides.py's `add_youtube`, vectors/library/overrides_writes.jsonl).
- audio: `YouTubeAudio.sweep` first; the video's audio kept already, done; the song's auto sheet made here of the
  very video asked for (its version's `raw.youtube.id` the pasted video, else the record's downloaded pick), done in
  the same words, no yt-dlp and no model: the chords stage finds it up to date or lays it out again over new words
  (`StagedSheet.madeOfThisAudio`), as Python's second run does with the audio it keeps (the controller's ruling of
  2026-11-27: the phone let the audio go, a re-lay needs none); cooling, skipped in the runner's words;
  else through core.youtube's `YtDlp` over the engine's process (its budget PhoneConfig's `youtube`, the product's,
  never the bench's lifted cap; its pauses; one run at a time; a block recorded by the runner alone, the job sending
  `Alerts.blocked`), the database reached a write a touch (`YtDlp.Writes`), its pauses and its process's wait
  (`YouTubeSheetRunner.Yielding`, the run on a thread of its own) letting the queued lookups go first each second; the
  pasted video, else the search's pick (`Choose.choose` past `skip`), into `cache/youtube/.part-<id>-…/`, then moved to
  `<id>-<video>.m4a` and linked. A video that can't be had (unavailable, or `PassedOver`: no m4a stream) is unusable
  pasted and into `skip` searched, the stage failed; a run never started (`NotSent`: the bench's run going) a wait in
  the phone's words, counted against nothing; yt-dlp out of date (`ExtractorOutdated`) or the gate's refusal
  (`GateRefused`), a host's problem, the stage failed in their words, a wait, counted against nothing; any other error
  counted against the video (the data's `network` pattern aside), given up at `give_up_after`; a stop of the queue closes the process (`ProcessYtDlp.close`) and keeps
  nothing. A download the decoder refuses fails the chords "audio the phone can't read: …".
- chords as `AudioRunner`'s, credited to the video (`AutoSheet.youtubeCredit`), the version's `raw.youtube` and
  `url` the video's, the maker the phone's with no `audio_name`; the decoded length said beside yt-dlp's (the job's
  Output and the `caracole.youtube` log). The sheet kept, the pages stage lets the audio go (`YouTubeAudio.letGo`:
  file, `audio_path`, `audio_mtime`, the record's `audio`); else it stays `YouTubeAudio.KEPT_FOR` (3 days), swept at
  the next job and as the phone starts (a file a song links that its record doesn't name aged by its own time); its
  folder `stateDir/cache/youtube/`, the app's files folder, not Android's cacheDir, which may be cleared under a job
  whose song still links it: the sweep and the let-go are what keep it small; a removal deletes it
  (`LibraryStore.youtubeDir`, removal.py's `youtube_audio`).
- vectors/lookup/youtube_sheet.jsonl (`YouTubeSheetReplay`, area `youtube-sheet`): Python's job over FakeYtDlp, fake
  models and the fake lyrics sites, replayed through the runner with a `Plan` of the record's yt-dlp (its runs
  compared) and `at_yield` written at the chords' yield alone; compared apart: AudioSheetReplay's, plus
  `http:last_request:youtube`, and, where the sheet was kept, the phone's let-go applied to Python's after-state;
  the done line's requests (`out.sent`, commands/youtube.py's `sent_words`); no model run where Python's sheet was up
  to date. Its records hold the error ladder (a network error, a counted one, a third failure pasted and searched) and
  the same job again on the phone's own state after the let-go (`let_go`), Python's second run its answer.
  YouTubeSheetRunnerTest through the real queue; YouTubeAudioTest the sweep and the removal.
- server/lookups' `YouTubeVideoRunner`, `caracole youtube --video=URL|ID [--progress]` (commands/youtube.py's `_video`
  and `_thumbnail`; `YouTubeRunners` sends `--video` to it, every other `youtube` line to the sheet's), a job of no
  song's: a link that names no video exits 2; `SearchGate.videoGate` first (read within 30 days, YouTube off in the
  computer's settings in the computer's words, `Phone.youtubeProblem()`, cooling, the hour's 10, a failure lately),
  then one yt-dlp run (budget 1, run `youtube-search:video:<id>:<time>`, `Yielding`, a write a touch), its record
  kept and its failure forgotten (a block the runner's, its alert the job's; an error `Health.recordError` and
  `recordFailure`; `NotSent` counted against nothing), then the thumbnail through `Clients.named` (the provider's own
  policy and the run's name, as `make_client`'s bulk client: `ytimg`'s budget 20, no pause), its own block, cooldown
  and alert. Its words youtube.json's `video_cmd` (commands/youtube.py's constants). vectors/youtube/video_cmd.jsonl
  (`YouTubeVideoReplay`, area `youtube-video`): the command over FakeYtDlp and a fake i.ytimg.com, replayed with the
  record's answers; apart, `http:last_request:`, `songs:key_version` and the events' times. Its run's ladder and the
  thumbnail are `YouTubeAsk`'s, which the search's shares.
- server/lookups' `YouTubeSearchRunner`, `caracole youtube --search=QUERY [--progress]` (commands/youtube.py's
  `_search`; `YouTubeRunners` sends `--search` to it, and refuses it with `--video`, exit 2), a job of no song's: the
  query's words joined by one space; no word, or `Phone.youtubeProblem()`, not searched; `SearchGate.gate` first
  (searched within 30 days, cooling, the hour's 10 shared with the pasted videos' reads, a failure lately, and, the
  phone's own, a metered network: `heldBack`, the gate's `off` in `YouTubeSearchRunner.METERED`'s words, "waiting
  for Wi-Fi"), then one `ytsearch1:` run (`YouTubeAsk.ask`: budget 1, run `youtube-search:<time>`, the network
  checked again as its `beforeRun`, a run held back counted against nothing), its first video that isn't live kept
  under `youtube-search:<key>` with the query (or none), then its thumbnail. Its words youtube.json's `search_cmd`
  and `video_cmd`. vectors/youtube/search_cmd.jsonl (`YouTubeSearchReplay`, area `youtube-search`), replayed as the
  video's.
- server/routes' `YouTubeRoutes`, web/youtube_routes.py on the phone: `POST /youtube` (`youtube --sheet --progress
  --url=… --song=…` queued under `youtube:<key>`, a song by its id and `identity` or by name, the job adding one the
  library hasn't, its album and length on the spec (`JobSpec.song`): no wanted.txt, so no note; asked again while it
  waits, that job the answer), `POST /request` with `youtube` handed to it by LibraryRoutes,
  `GET /api/youtube/video` (no request: the gate, the video read, the name guessed by `SongNames.readNames`, the
  library's song by its record, its `[youtube]` or the name), `POST /youtube/video` (`youtube --video` queued under
  `youtube-search:video:<id>` when `auto`), `POST /youtube/search` (`youtube --search` queued under
  `youtube-search:<key>` when its gate, its sheet on the screen read as /api/search reads it, says `auto`: 429 on a
  metered network, "Not now: waiting for Wi-Fi."), `GET /youtube/thumb/<id>.jpg` (`Thumbs.read`, a policy that runs
  nothing); /api/search's `youtube` (Found, `SearchRoutes.YouTubeAsked`: `Phone.youtubeProblem()` and the network,
  read before the search's own read; `names` read with the suggested video's title and channel, `SongNames.readNames`'
  `video`, song_names.py's rule 5), whose row library.js draws and which sends nothing; refused as caracole serve
  refuses, `Phone.youtubeProblem()` its reason ("No sheets from YouTube here:
  …"); form routes, so App's cross-origin check and token hold. `server.youtube` `{ok, why, off}` and the request
  form's YouTube field where ok (`ServerControls.youtube`: `Phone.youtubeOffered()`, the design's §5.6, YouTube
  cooling down after the problem's reasons, `YouTubeRoutes.COOLING`), its line "its lyrics from the lyrics sites"
  (library_page.py's `_request_form(hears=)`: the lyrics heard from the video only where `server.transcribe.ok`,
  never on the phone, whose `transcribe.why` is "No lyrics site has its words. The computer hears them from its own
  audio of this song.", `LibraryPage.TRANSCRIBE_PROBLEM`; library.js says so in Make sheet's title too). vectors/web/youtube_routes.jsonl (`WebReplay.youtubeRoutes`,
  YouTubeRoutesReplay: each answer's member order too, the song the job adds against wanted.txt's line there),
  library_page.json's cases with `youtube` (the field drawn, a why).

##### Alerts and backups on the phone

- **Alerts** (the app's `AndroidAlerts`, core.health's `Alerts`, Caracole's from the phone's start), notifications on
  the `alerts` channel:
  - `blocked`: InteractiveAsk's block of a lookup, once a lookup, titled as `_common.alert_block` titles ntfy's
    ("caracole: <provider name> blocked", `LookupWords.NAMES`), with the cooldown's end; once a cooldown, the cooldown
    posted kept in the app's preferences (`AndroidAlerts.PREFS`), so a second block of the same cooldown posts none. On
    the computer a lookup sends none; the phone has no nightly run to tell;
  - `failed`: a job that failed (Assembly's `afterJob`, through `JobQueue.onEnd`) while no screen of the app's is
    started (the activities' lifecycle; one started before the alerts were made counts by the process's importance
    until a screen stops), titled by the job's display, its text its line (`JobViews.line`);
  - nothing posted without the right to notify (`areNotificationsEnabled`); AlertsTest on the device.
- **Backups** (core.backup, `Backups`): the take's backup made public, with labels (`by-hand`, `daily`,
  `before-sync`), the newest `KEEP` (3) of each label, SQLite's quick check before a copy takes an old one's place, none
  made without twice the room (`freeSpace`), `stateDir/backups/<label>-<UTC time>.sqlite`:
  - the library's tables (`BackupTables.TABLES`: songs, versions, files, removed, kv and the phone's), the index tables
    empty, and the library's kept files by SHA-256 in `stateDir/backups/blobs/`, each read once and checked as it is
    copied, shared between backups and gone with the last that names it (`sweep`); a file that can't be read or no
    longer holds its row's bytes is never kept as them (`Backup.missing` counts those a backup lacks, its job's line
    says so), and a blob that can't be written makes no backup;
  - `Take.backupBeforeSync(db, stateDir, now, store)` is the `before-sync` one, its store required, so every take keeps
    the files too (an older app's before-sync copies hold the tables alone);
  - `exportTo`: one zip of the copy and `blobs/<sha256>`, `exportName` its name, refused for a backup that lacks a
    blob; a backup being exported is never rotated out nor its blobs swept until it ends;
  - `restore(database, lib, file)`: in one write, this side's own records read (`OwnRecords.document`), the tables put
    back exactly, and those records written over them (`OwnRecords.putBack`), one savepoint; then each kept file whose
    bytes its file doesn't hold written from its blob, each kept file of before that the backup doesn't name deleted
    while it holds its row's bytes, each song's lyrics files as its row has them (`Restored`: written, removed);
  - refused whole, nothing changed, unless every kept file the backup names is held by its file now or by its blob,
    checked by its SHA-256 (`NotRestorable`), and every path of the rows is a place in the library (no link); a write
    that fails after the tables came back is `PartlyRestored` ("restore it again"), so no restore leaves a row naming
    bytes no file holds;
  - `OwnRecords`: what a restore keeps as it is now (Politeness's "Two caracoles, each its own politeness"): `provider:`,
    `http:last_request:`, the global records that gate a request (`lacuerda:search:`, `lacuerda:search-failed`,
    `gtptabs:unusable:`, `ug:artist_url:`, `ug:pasted_tab:`, `ug:unreadable:`, `youtube-search:`,
    `youtube-outdated`, `phone:youtube-auto`), `sync:` (so a
    restored library is the phone's change at the next sync: §11 Q11's default), `phone:settings`, `phone:schema`, the
    index push's notes and every index's progress records, what the whole exports it merged read (`index:merged`,
    which a sync asks the computer by), the site catalogues' (`catalogues:`: the file the index
    tables took last, GitHub's ask-again time, a download waiting for a go-ahead, the offer made: a restore never
    touches those tables, so a tap after one says Up to date exactly when they hold the newest file), the chord
    models' (`models:`: what was installed, a note beside files no backup holds and a restore never touches, and
    GitHub's ask-again time), and each song's
    records that gate a request (`SONGS`:
    `megalobiz:checked:` and the other 30-day checks, `ug:artist_page_checked:`) by the song's identity key; the rest
    of kv, and the songs' own columns, are the library's;
  - BackupsTest on the JVM.
- **The jobs**: server/lookups' `BackupRunner`, `backup --label LABEL` and `backup --restore NAME` (a name in
  `stateDir/backups/` alone), run as jobs of the phone's own (`backup(label)`, `restore(backup)`: PhoneKinds' backup
  and restore kinds, their words JobViews'), so on the queue's one worker, never beside a lookup's write; a restore
  owes every page again in its savepoint (`owePages`: each `render:<id>:phone` and `phone:render-build` forgotten),
  and the app then reloads the mirror, forgets the search's answers and queues the render job, after one done or one
  failed once its tables came back (`BackupsActivity.afterRestore`; a restore run again from the Requests tab leaves
  them to the next start's render job). Meanwhile written-pages' gating serves none of the phone's pages whose bytes or
  unit the restored records no longer match, a songbook's as a song's, until the render job makes them again, its
  songbooks' through `SongbookPagesImpl.renderOwn` (BackupRunnerTest).
- **The app**: `BackupsActivity` (Settings' Backups row): the list, Back up now, Export… through
  `ACTION_CREATE_DOCUMENT` (`application/zip`), Restore… asked first; `BackupWorker`, the daily backup, a periodic
  WorkManager job while the phone is idle and its battery isn't low, which queues the backup and waits for it, kept
  scheduled by `AndroidAlerts` at each start (the one start-time hook the app gives this lane). BackupsTest on the
  device.

tests/conformance/ is the corpus between the two (its README): `data/caracole/` the phone's runtime data (a resource
root of `:core`), `vectors/` what the Kotlin tests compare with, both written by `tests/test_conformance_*.py` through
helpers/corpus.py.

#### The phone agrees with the computer to the byte

- What the Kotlin side ports, Python states as data in the conformance corpus
  (docs/superpowers/specs/2026-11-03-conformance-corpus.md): each `tests/test_conformance_<area>.py` builds its file
  and `helpers.corpus.check`s it against the committed one. Never edit one by hand; regenerate:
  `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_*.py`.
- A change to normalize, search, peer_sync, the schema, library_assets, status.py or outcome.py regenerates the corpus
  in the same commit, and `nix develop ./android -c gradle -p android test` passes before it merges. When a Kotlin
  test breaks on it, the change doesn't merge: it is conformance drift, the Kotlin side's to follow first (the drift
  protocol, in the spec).
- A `SCHEMA_VERSION` or `KEY_VERSION` bump moves the phone in lockstep: migrations.json regenerated,
  `Database.SCHEMA_VERSION` and `Normalize.KEY_VERSION` bumped, `LibraryStore.ensureCurrentKeys` re-keying as
  `songs.ensure_current_keys` does, and `phone_overrides` from each entry's written name, as overrides.py keys it
  at a load.
- `:core`, `:viewer`, `:server` and `:autochords` never call a JDK or ICU text API (case, normalization, `Character` classes,
  `java.util.regex`'s own `\w` or `\s`, `Collator`): their Unicode is not Python's, and on Android it varies by
  device. They use `core.py` and its tables, held by the shared check `core.testing.ForbiddenApis` (each module's
  `ForbiddenApiTest`; an M1–3 file a later lane ports may be allowed by name, with that lane, until it does: none
  is today).
- The `autochords` area is the one whose generator needs another shell: its models' half runs, checks and is
  regenerated in `.#autochords` alone (`CARACOLE_CORPUS=write nix develop .#autochords -c pytest -q -n 0 -m
  autochords tests/test_conformance_autochords_models.py`); the default shell checks its clips and skips the rest.
  Its model outputs are bit for bit on a CPU of its meta's `cpu_capability`, and elsewhere within the gates its
  models.jsonl's meta holds. On the device it runs in the ml shell alone (`device-test.sh --area autochords`, whose
  libsoxr is `:ml`'s). The other chords-from-audio areas, `autochords-sheet`, `audio-store`, `audio-sheet` and
  `lyrics-search`, are the default shell's on both sides.
- What the JVM can't show, the device does: `CorpusOnDeviceTest` answers every record of the `unicode`, `keys`,
  `pinyin`, `fuzz` and `canonical` vectors under Android's runtime and ICU-backed regex (it found ICU reading a `\G`
  inside a lookaround otherwise than the JDK: py/PyRe.kt's guard after an empty match uses no `\G`).

## Development

### Running the tests

- **Fast loop**: `nix develop -c pytest -q -m "not slow"` (about 45 s, 90 s while other suites share the machine)
  while you work, and the whole suite, `nix develop -c pytest -q` (about 170 s, 275 s shared), before a commit.
- Always through `nix develop`: its pytest has pytest-xdist, which spreads the suite over the cores; a pytest without
  it runs the whole suite in one process, for minutes.

```
nix develop        # Python 3.14 with the dependencies, pytest, pytest-xdist, chordpro, ruff, sqlite3
caracole --help    # in either shell: the checkout's src/ (PYTHONPATH), no rebuild after an edit
pytest -q                         # the whole suite, from the repo root, on up to 12 cores
pytest -q -m "not slow"           # the quick loop, under a minute
pytest -q -m "not slow" --lf -x   # what failed last time, stopping at the first failure
pytest -q tests/test_fetch.py     # given paths, pytest runs them in one process
nix develop .#autochords -c pytest -m autochords   # the model tests
nix develop ./android -c gradle -p android test    # the Android side: :mirror, :core, :server, :app, :e2e on the JVM
nix develop ./android#ml -c gradle -p android test # the same and :ml (the runtime built from source: once a machine)
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py   # the phone and the computer synced
```

- `python -m tests.helpers.big_library measure [--songs N] [--src PATH] [--runs N] [--out FILE]` (in `nix develop`, from
  the repository's root): a library of 2,000 songs built with no request (tests/helpers/big_library.py) and index.html's
  numbers on a phone (390 x 844, touch, CPU 4x slower) as JSON: the page drawn, the scroll's frames, a card opened, a
  letter typed; `--src` builds the page with another checkout's `src/`; `build DIR [--songs N]` builds the library
  alone and prints its index.html's path, to open as a file. The spec's "Measurements before building" holds the table
  the long-lists stage is judged by.
- tests/test_android_e2e.py, marked `android_e2e` and `slow`, is skipped unless `CARACOLE_ANDROID_E2E=1`: the goal's
  scenario (docs/android_port.md), a computer built by tests/helpers/e2e_library.py with no request and real `caracole
  serve` processes, the phone android/e2e's `PhoneScenarioTest` on the JVM, a Gradle run a phase. Its last phases
  (12, 13) are one song's sheet from audio between the two: the phone's audio job makes it chords-only
  (`RecordedChordModels`: the corpus's hearing of hearing.mp3 for that clip, the models installed by the phone's own
  job from test pins, nothing asked), a sync gives it, the computer's `caracole autochords` (stub model packages that
  raise, `Computer.without_models`) leaves it `MADE_ELSEWHERE` beside a purchase, the song's lyrics come and its
  render re-lays it, maker kept; the phone takes it, its own render re-lays nothing, and a third comparison is empty:
  no conflict, one `auto` version, one digest.
- **The device step**, the one place an emulator runs, through device-test.sh's pool of emulators, each one caller at a
  time, each stopped again by the run that started it (android/README.md, "Try it on an emulator"; "Leave nothing
  running", below):
  `nix develop ./android#emulator`, the AVD made once (`avdmanager` writes it under `~/.config/.android/avd`: give
  `ANDROID_AVD_HOME` that folder), `emulator -avd caracole -gpu host` with `LD_LIBRARY_PATH=/run/opengl-driver/lib`
  (and `QT_QPA_PLATFORM=xcb` on Wayland), a computer of its own for each test that changes the phone's library
  (`nix develop -c python -m tests.helpers.e2e_library serve DIR PORT --address 127.0.0.1`, the emulator's
  `http://10.0.2.2:PORT`), `adb shell pm clear io.github.danielhp95.caracole.debug` between them, and each class alone
  with `adb -s emulator-5554 shell am instrument -w -e class io.github.danielhp95.caracole.CLASS [-e server …]
  io.github.danielhp95.caracole.debug.test/io.github.danielhp95.caracole.CaracoleTestRunner`.

- Given no paths, pytest runs on pytest-xdist workers (conftest.py: `-n auto`, at most 12, fewer on a busy machine:
  the cores its load leaves, 2 at least, so suites run at once share it; `--dist worksteal`).
- `-n 0` runs it in one process, as `--pdb`, `--trace`, `-s` and `-m autochords` do.
- `slow` marks a test that starts a browser (`helpers.browser.in_chromium`), chordpro or the models
  (`@pytest.mark.chordpro` and `autochords` add `slow`) or another process: mark a new one too.
- The whole suite stays the gate before a commit.
- tmp_path is in /dev/shm, and stays on disk with `--basetemp` or `PYTEST_DEBUG_TEMPROOT`, or when /dev/shm is noexec
  or has less than 1 GB free (a container's).

### Browser tests

- A test that opens a page in Chromium is marked `@in_chromium` (or has it as its module's `pytestmark`,
  `helpers.browser.CHROMIUM_MARKS`): slow, and skipped without Chromium.
- One that opens a page unmarked fails (`helpers.browser.require_in_chromium`).
- It opens pages through:
  - helpers/browser.py, `dump_dom` (the DOM once the page's script ran, its timers on virtual time, in one Chromium
    per process and a fresh context per page) or `Browser` (a page on real time, to type, press keys, click and touch,
    in a browser context of its own of another Chromium the process's Browsers share, `_Driven`);
  - or helpers/chromium.py, for a page whose policy refuses a test's script.
- None of them resolves a host name (`helpers.browser.NO_LOOKUPS`), and the other browser helpers in tests/helpers/
  build on them.
- A test that drives a page on real time (`Browser`) waits for the state it needs, never a fixed time: its workers
  share the machine with eleven others.
  - `Browser.wait`: an expression that throws while the page still loads is not true yet; once the page has loaded,
    it raises at once.
  - After a step that loads the page again (a reload, a songbook's next song), it waits for the new document, not the
    one before it (`window.before`, as `Browser.open` does for an address).
- The library page caracole serve serves asks /jobs.json every 1.5 s and counts Remove's five seconds:
  - `WebApp(timers=...)` shortens both for such a test (test_web_page.py's `QUICK`);
  - and caracole serve never sets it, so the page users get carries no timers (`WebControls.timers`).

### Programs and models the tests need

- Both shells set `CARACOLE_CJK_FONT` to the packages' font, `CARACOLE_PDF_FONTS` to their PDF fonts
  (nix/pdf-fonts.nix), and `CARACOLE_ALPHATAB_DIR` to alphaTab (nix/alphatab.nix).
- `.#autochords` adds torch, beat-this, librosa, openai-whisper and onnx, and for the tests alone onnxruntime and
  mir-eval (its image tests off: their baselines fail against this nixpkgs' matplotlib), and sets `CARACOLE_BTC_WEIGHTS` and
  `CARACOLE_BEAT_CHECKPOINT` to the files nix/autochords.nix fetches, and `CARACOLE_WHISPER_MODEL` and
  `CARACOLE_DEMUCS_MODEL` to Whisper large-v3 and HTDemucs (about 3.1 GB, fetched on a first build); both
  auto-chords shells put `demucs` on PATH: `.#autochords` the `cpu` build of demucs-rs (backend fixed at compile
  time; 712 s for a 149 s song), `.#autochords-cuda` nixpkgs' own wgpu build (the GPU, about 35 s). The suite points
  `CARACOLE_DEMUCS_BIN` at no program (tests/conftest.py), as it does yt-dlp's.
- `.#autochords-cuda` is that on `pkgsCuda` (flake.nix): a second nixpkgs whose python takes torch, torchaudio,
  torchvision and triton from the `-bin` packages, package-wide (one dependency on the CPU torch and buildEnv meets two
  torch builds). The unfree CUDA packages it admits are `cudaUnfree`, a list found by evaluating, not
  `allowUnfree`; a new torch-bin dependency that refuses to evaluate for its license is one more name there.
  torchaudio-bin does not bring torchcodec, so it is listed in the extra. `packages.autochords-cuda` is the package.
  The shell sets `CARACOLE_TORCH_CUDA=1`, as that package's wrapper does (`nix/`, package.nix's `cudaTorch`).
- Tests that need a real program or model skip without it:

| Needs | Tests | Set by |
|---|---|---|
| `chordpro` on PATH, or `CARACOLE_CHORDPRO_BIN` | the tests marked `chordpro`: real PDFs | both shells |
| `CARACOLE_CJK_FONT`: one `.ttf` or `.otf` with CJK glyphs | Chinese PDFs | both shells |
| `CARACOLE_PDF_FONTS`: Adwaita's four files (`helpers.fonts.PDF_FONTS`) | the real PDFs in Adwaita Sans (test_render.py, test_render_all.py, test_songbook_render.py: their fonts, and the glyphs embedded), the two-column estimates in its widths, test_pdf_fonts.py's Adwaita test | both shells |
| `CARACOLE_ALPHATAB_DIR`: alphaTab's three files (`helpers.guitar.alphatab_dir`) | test_web_guitar_browser.py: the Guitar Pro page in Chromium | both shells |
| `pdftotext` on PATH, or `CARACOLE_PDFTOTEXT` | the PDFs' text in test_render_all.py (fewer checks without it, no skip) | neither: `nix shell --inputs-from . nixpkgs#poppler-utils` |
| torch, librosa, beat_this, and `CARACOLE_BTC_WEIGHTS` with `CARACOLE_BEAT_CHECKPOINT`, or `CARACOLE_MODELS_DIR` (searched for `btc_model_large_voca.pt` and `final0.ckpt`) | the tests marked `autochords` | `.#autochords` |
| those and onnx, onnxruntime and mir_eval | test_autochords_export.py's and test_conformance_autochords_models.py's tests marked `autochords` | `.#autochords` |
| `CARACOLE_BTC_MAJMIN_WEIGHTS`, or `btc_model.pt` under `CARACOLE_MODELS_DIR` | `test_the_major_minor_model_loads_too` | neither |
| `ffmpeg` on PATH | `test_btc_reads_aac_from_the_itunes_store` | neither |
| `chromium` on PATH | the tests marked `@in_chromium` (Browser tests, above): the pages caracole writes and serves, in a real browser | neither |

### Before a change is done

```
nix develop -c pytest -q
nix develop .#autochords -c pytest -m autochords   # when auto-chords is touched
nix develop ./android -c gradle -p android test    # when android/ or the corpus is touched
nix develop ./android#ml -c gradle -p android test # when :ml, the chords' debug sources or the runtime are touched
CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py   # when sync, android/ or the corpus is
android/scripts/release-check.sh   # android/'s native code or packaging: the release's exclusions, native-check.sh
nix flake check
```

- `nix flake check`'s package build runs the suite on a tree of pyproject.toml, README.md, LICENSE, src/ and tests/
  alone: a test that reads docs/ or android/ skips there (test_nix_package.py, test_android_termux.py,
  test_canonical.py).

- `nix flake check` builds three checks:
  - `package` and `autochords` each run the suite (minus the tests marked `autochords`), then check that the installed
    package is src/ file for file (the suite imports caracole from src/, so a data file left out of the wheel shows
    only there: a new asset folder goes inside src/caracole/) and check the wrapped `caracole`;
  - `module` evaluates small NixOS systems against nix/module-check.nix, loads their caracole.toml with config.py and
    parses their units' command lines with caracole's own CLI (a command or option a unit names, renamed or removed,
    fails it).
- One at a time: `nix build`, `nix build .#autochords`, `nix build .#checks.x86_64-linux.module`.

### Traps

- The flake sees only files git tracks: `git add` a new file before a Nix build.
- The package builds from pyproject.toml, README.md, LICENSE, src/ and tests/ alone, in a sandbox without network
  (test_nix_package.py skips itself there). A subprocess test keeps the inherited PYTHONPATH
  (`conftest.subprocess_pythonpath`): the dependencies arrive on it.
- A dependency is listed three times: pyproject.toml, flake.nix (`runtimeDeps` or `autochordsDeps`) and
  nix/package.nix.
  - It comes from nixpkgs: no pip, uv or PyPI pins.
  - Every third-party module src/ imports is listed, even one another dependency brings (click with typer);
    auto-chords' modules may import the extra's.
  - test_nix_package.py checks both.
- The version is in pyproject.toml and src/caracole/__init__.py; the package check compares `caracole --version` with
  pyproject's, and test_cli.py expects "caracole 0.1.0".
- A Nix file may set only `CARACOLE_*` variables the source reads (test_nix_package.py). A unit setting changes
  together with its expectation in nix/module-check.nix.
- docs/deploy.md's Ubuntu part pins by hand what Nix pins:
  - its constraints.txt is the package's versions in flake.lock's nixpkgs;
  - its CPython and deno are nixpkgs' too;
  - and its SHA-256s are nix/'s (alphaTab's and the model files', which test_nix_package.py checks, and the fonts
    nix/pdf-fonts.py makes).
  - A commit that moves flake.lock or nix/ moves deploy.md with it.
- `ruff check --select E4,E7,E9,F src tests` is clean; ruff's default rules and `ruff format --check` are not. Don't
  reformat code you aren't changing.
- Every pytest-xdist worker collects the suite itself and must find the same test ids: parametrize with nothing that
  changes between processes, such as a zip's clock-dated entries (helpers/zips.py `dated_entry`), random values or a
  set's order.

## How work is done here

- Test first: a test that fails (on the missing name or an assertion), then the code.
- **Never a live request in a test**: not to ultimate-guitar.com, lrclib.net, megalobiz.com, azlyrics.com,
  lacuerda.net, gtptabs.com, musescore.com or YouTube.
  - Give `PoliteClient` an `httpx.MockTransport` as `transport=`.
  - CLI tests monkeypatch `caracole.commands._common.transport_for` (and `_common.sleep`).
  - Pipeline tests pass `Services` with fake clients (`FakeGtpTabs.client` and `FakeMuseScore.client` make real ones).
  - YouTube tests run `FakeYtDlp` as `ytdlp_bin`, never a real yt-dlp: conftest.py points `CARACOLE_YTDLP_BIN` at no
    program for every test, so a command reading the real environment in `nix develop .#autochords` (torch, the model
    paths, yt-dlp on PATH) finds the route off.
  - Nothing blocks the network for the whole suite; only the package build's sandbox has none.
- **A Kotlin test never reaches the network**: every Gradle `Test` task sets `caracole.network=loopback`, under which
  `core.http.RealTransport` refuses any host but loopback and the emulator's `10.0.2.2`; the app's instrumentation
  runner, `CaracoleTestRunner`, sets it too, before `Application.onCreate`, and makes `Caracole.sitesForTests` a
  transport that refuses every site unless a test sets another. `PhoneDeps.transport` has no default: every `Phone` a
  test builds names its transport.
- **The device**: a lane's device tests run only through `android/scripts/device-test.sh` (`--area NAME` for a
  corpus area, `--app` for the app's classes, `--ml` for `:ml`'s ModelParityTest, DecoderTest and PipelineTest and the
  app's ChordsBenchTest, `--models` the models alone pushed and named to the classes (`-e models`), `--youtube` for
  `:youtube`'s YtDlpVersionTest, `CLASS[=DIR]` for its own;
  `--tcpdump FILE` the gate on caracole's own uids, iptables and ip6tables owner rules counting what the debug app and
  the test APKs send to any host but 10.0.2.2 or loopback, a control sent as the app before and after the classes each counted on its own (the counters read just before each), the chain still first in OUTPUT; it proves nothing those uids sent left, not what another
  uid sends for them (a name lookup through Android's resolver among it); the emulator's whole capture beside it as
  evidence, Wi-Fi off, each stray endpoint with its socket's uid, a failure only when it is caracole's; what goes to or from the emulator's DNS, 10.0.2.3, under a heading of its own, listed, not attributed),
  which builds first, then takes the first free emulator of a pool (`CARACOLE_EMULATORS`, 3 by default, the owner's
  choice of 2026-11-10: emulator-5554, -5556, -5558, each one caller at a time) and holds its lock (emulator-5554's
  `${CARACOLE_EMULATOR_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/caracole-emulator.lock}`, the others' the same name with their
  port) while it installs and runs, and starts that emulator if it isn't up (each read-only, so several run on the one
  AVD). It builds `--ml`, `--models`, `--data` and the corpus's `autochords` area in the `ml` shell (the debug build
  with `:ml`), every other run in the default one.
- **Leave nothing running**, the owner's rule of 2026-11-27: "Ensure that emulators are properly killed when using them
  for testing or development. same thing for gradle biuld and adb servers."
  - device-test.sh stops, as it ends on any path (a pass, a failure, an interrupt, a reader gone: an EXIT trap that
    ignores them), the emulator it started (`adb emu kill`, its process session waited for
    `CARACOLE_EMULATOR_STOP_WAIT` s, 60 by default, then killed), while it still holds that emulator's lock, so no
    caller takes a dying one; one up already is someone else's and is left up; `--keep-emulator` (or
    `CARACOLE_KEEP_EMULATOR=1`) keeps the one it started, to look at it.
    It stops the adb server it started once adb lists no device at all and no other caller holds a pool emulator,
    never one running before it nor while a phone is attached (tests/test_device_scripts.py). No adb it runs inherits
    the lock, and each adb call of a stop is bounded (`CARACOLE_ADB_TIMEOUT`, 10 s; no answer, then the kill). An
    emulator left by a run that was SIGKILLed, or by a script older than this, reads as someone else's to every later
    caller and stays up until stop-all.sh runs.
  - `android/scripts/stop-all.sh`, at a task's end: every pool emulator whose lock is free (one another caller holds
    is left), and the adb server only when no device is listed, in any state, and no caller holds a pool lock, a line
    for each thing stopped or left (a reader gone, `| head`, cuts none of it short); this user's processes alone,
    matched by their own name and arguments. Gradle only
    with `--gradle`: `gradle --stop` stops every daemon of that version for the user, other worktrees' running builds
    among them, so it refuses while `gradle --status` calls any daemon busy (or fails, or can't say; the check and
    the stop aren't atomic); without it, it says how many run, each stopping by itself after two idle minutes.
  - android/gradle.properties' `org.gradle.daemon.idletimeout` is two minutes: a task's builds still reuse the daemon,
    and none lingers after; the Kotlin compile daemon ends with the Gradle daemon that used it.
- **The owner's phone** gets a debug build only through `android/scripts/phone-install.sh` (`-s SERIAL`, `--launch`):
  `adb install -r --user 0` of `io.github.danielhp95.caracole.debug` alone, so the phone's other user and F-Droid's
  `io.github.danielhp95.caracole` are never touched; no test runs on it.
- **Big data sets** (more than a few thousand rows) run only in a `*Bench` class of the gated `bench` task
  (`nix develop ./android -c gradle -p android bench`: a 3 GiB heap, one fork), never in `test`, which excludes them.
- `load_config` takes `env=`, and unit tests pass it. CLI tests read the real environment: clear what could leak in,
  as `OUTSIDE_SETTINGS` does in test_commands_sources.py.
- **Heavy imports** stay inside the command function: `cli.build_app` imports every module in commands/ on every
  start, and the default package has no torch.
  - `test_commands_index_match.py::test_registering_the_commands_imports_neither_the_matcher_nor_the_index` fails
    when importing `caracole.cli` loads rapidfuzz, `caracole.match` or `caracole.ug`; the
    `test_registering_the_command*` tests of fetch, lyrics, sources, autochords, youtube and transcribe do the same
    (transcribe's: no whisper, torch or librosa).
  - httpx, with the rich and pygments it brings, is a third of a start: http.py imports it inside the functions that
    use it, and `_common` makes its client class on first use (`_locked_client`).
  - `test_commands_index_match.py::test_a_command_that_sends_no_request_imports_no_http_client` fails when importing
    `caracole.cli` and reading a `[youtube]` entry (youtube_urls.py) loads httpx, rich, `caracole.http` or
    `caracole.youtube`.
  - music.py imports mutagen in `read_audio` alone, and lyrics.py (`expected_seconds`) in `_matches`: inbox.py, which
    the pages import, scores names with its `Names`, and audio_store.py and commands/audio.py read a file's tags
    inside the functions that read one (`test_audio_store.py::test_the_store_imports_no_tag_reader`,
    `test_commands_audio.py::test_registering_the_command_imports_no_tag_reader_or_model`,
    `test_music.py::test_the_pages_load_no_tag_reader`,
    `::test_the_inbox_loads_no_http_client`).
  - viewer/pinyin.py imports pypinyin in `_read` alone, and viewer/hanzi.py OpenCC in `_converter`: a page of a sheet
    with no Chinese loads neither (`test_viewer_pinyin.py::test_pypinyin_is_loaded_only_for_a_sheet_with_chinese`,
    `test_viewer_hanzi.py::test_opencc_is_loaded_only_for_a_sheet_with_chinese`).
- Branch from `main`, the default branch: each piece of work on a branch of its own, merged into `main` once it passes
  (`caracole-v1`, the default until 2026-10-27, is retired).
- Conventional commits, scoped by area: `fix(fetch): …`, `feat(lacuerda): …`, `test(commands): …`, `docs: …`,
  `build(nix): …`.
- No Claude or AI attribution anywhere: no Co-Authored-By trailer or "Generated with" line, in commits, code or docs.
- Keep docs/usage.md, docs/deploy.md and docs/install.md in step with behaviour (commands, options, defaults, files,
  messages) in the same commit; no test checks them.

## Invariants

Each names where it is enforced. Don't weaken one to make a test pass.

### Politeness

Politeness (http.py, health.py, commands/_common.py), at two paces (`config.ProviderPolicy`; `_common.make_client`
picks one).

#### Bulk work

- The nightly run (its index refresh and UG's artist directory included), `caracole index build` and every command
  but `caracole get`, `caracole versions`, `caracole lacuerda --artist` and `--search`, `caracole harptabs --artist`,
  `caracole ug --link`, `caracole lyrics --song --as` and `caracole lyrics --song --pick | --record`.
- Budgets per run (`config.DEFAULT_PROVIDERS`):
  - `ug` 60, and UG's artist directory a budget of its own, `[ug_directory].budget` (25,000; below);
  - `lrclib` 200;
  - `megalobiz` 60 (a search and a record a song, `megalobiz_fetch.py`; and never more than its `per_day`, 900 a UTC
    day, every run's, command's and lookup's together, counted in `events`: `_common.within_the_day`, under its API's
    1,000 a day);
  - `azlyrics` none (`config.NO_BUDGET`, the owner's choice of 2026-10-30, the one site with none: two requests a
    song, only for a song with no lyrics, each once in 30 days; a lookup keeps its own limits);
  - `lacuerda` 30 (its sheets first, then its listings of every artist, then, once those are read whole, the pages of
    its most popular artists not read in 30 days, `lacuerda_fetch.POPULAR_PAGES` (10) at most);
  - `gtptabs` 20;
  - `musescore` 10;
  - `harptabs` 20 requests (its sitemap, then a song's candidates, `harptabs_fetch.CANDIDATES` (8) at most, then, once
    the library has a song, artist pages with what is left, `harptabs_index.artist_pass`);
  - `gametabs` 20 requests (its sitemap index and six children, then a song's candidates, `gametabs_fetch.CANDIDATES`
    (4) at most, then, once the library has a song, game pages with what is left, `gametabs_index.game_pass`);
  - `ireal` 20 requests (its sitemap index and six children and the curated playlist, once in 30 days, then a song's
    candidates, `ireal_fetch.CANDIDATES` (3) thread pages at most, then, once the library has a song, the jazz forum's
    page and its playlists with what is left, `ireal_index.playlist_pass`);
  - `youtube` 50 yt-dlp runs (6 until 2026-11-27: the owner's choice that day, "increase youtube's song request maximum to 50
    (not 6)");
  - `ytimg` 20 requests (YouTube's image host: the thumbnail of a video suggested for a search, one image a video,
    youtube_search.py).
- `caracole index build`: at least 100 (`BUILD_BUDGET`, commands/index.py); and `caracole harptabs --index` and
  `caracole gametabs --index` their `--budget`, `BUILD_BUDGET` by default.
- Then `BudgetExhausted`.
- Between any two requests to a provider, a random pause from its `delay`, each a quarter of what it was before
  2026-11-03, the owner's choice that day ("wait times divided by 4"; the budgets and limits are as they were):
  - 2.5–5 s for UG, LaCuerda, gtptabs.com, MuseScore, harptabs.com and iReal Pro's forum (which asks no pace);
  - 0.25–0.5 s for LRCLIB;
  - 0.5–1 s for Megalobiz (0.5–0.75 s a lookup's): its API allows 30 a minute, which caracole can now go past, by
    the owner's choice (a 429 is a block, as at any site);
  - 0.25 s for gametabs.net (its robots.txt's `Crawl-delay` asks 5 s: caracole waits less, by the owner's choice);
  - none for `ytimg`: the owner's choice of 2026-10-29, a thumbnail comes right after its search, YouTube's
    3.75–7.5 s between yt-dlp runs and its last request never holding it back;
  - none for `azlyrics`, the owner's choice of 2026-10-30, at either pace.
- Everything else below binds both.

#### UG's artist directory, read at the owner's pace

- The owner's choice of 2026-11-17, in their words: "Build it, first full read, I want it to last 1h. Read every
  letter every 30 days. Second pass, all of them. Budget, enough so that I read everything in 1h. Ignore the
  politeness for this." Asked which reads the hour covers, the owner chose both: the listings and the whole second
  pass (docs/superpowers/specs/2026-11-17-ug-artist-directory-design.md, "The owner's decisions").
- So this pass alone (ug/directory.py, `caracole ug --directory`, the nightly `ug-directory` step) departs from one
  request at a time per provider, the bulk pace and UG's budget of 60: `[ug_directory]` (config.py
  `DirectoryPolicy`) gives it `concurrency` 6 requests in flight, a `delay` of [0, 0] and a `budget` of 25,000 of its
  own, about 20,000 requests in an hour, about five a second (http.py `ParallelClient`, `_common.directory_client`).
  They are caracole.toml settings, never sent to the phone (politeness.py's `settings_document` gives a lookup's
  settings alone).
- What still holds there: robots.txt (`/bands/` and `/artist/` alone, both open to `*`); caracole's own user agent;
  every 200 and 404 cached; each request an event of provider `ug` and `http:last_request:ug` moved on, in the
  caller's thread; errors never misses (a listing page cut short or unparseable an error, the pass going on from it
  the next time, never dropping an artist); a 403, a 429 or a challenge stops every worker at once (nothing more
  begun, those in flight waited for), records the block (one cooldown of `ug`, so the fetch and lookups cool too) and
  sends one alert, nothing retried around it; the lock handed to a waiting lookup between two batches, with no request
  in flight (`between`), so a lookup never waits for the hour; database writes on one connection in one thread (the
  workers fetch; the caller parses, stores and records); Ctrl-C or a stop leaves no worker running.

#### An interactive lookup

- An interactive lookup is one of:
  - `caracole get`, one song asked for just now (caracole serve's lookups run it);
  - `caracole versions --keep`, one tab page asked for now, and `--keep-more`, as many as one lookup's budget lets
    (`--choose` and `--clear` run get);
  - `caracole lacuerda --artist`, one artist's page (an artist's Songs);
  - `caracole harptabs --artist`, one artist's page (an artist's Songs, once in 30 days);
  - `caracole ug --link`, a UG page pasted into the library page's box: a tab's page, then its artist's lists, or an
    artist's lists (ug/link.py), each list page 30 days from the cache;
  - `caracole lacuerda --search`, one query of LaCuerda's search (one request);
  - `caracole lyrics --song --as`, what the three lyrics sites list under a name typed (lyrics_search.py, 2–4
    requests, one client a site);
  - and `caracole lyrics --song --pick | --record`, a row of that search made its lyrics (lyrics_pick.py, 0 or 1
    request), under the lock as asked for now, as `versions --keep`.
- `caracole lacuerda --search`:
  - a query at most once in 30 days, kv `lacuerda:search:<key>`, its words' key in alphabetical order;
  - none once your library or LaCuerda's index answers it well, `lacuerda_search.answered`, checked again after the
    cached artist pages are stored;
  - those the pages send by themselves, `--auto`:
    - at most `lacuerda_search.SEARCHES_PER_HOUR` (20) in the last hour, counted in `events` under runs named
      `lookup:lacuerda-search:…`, within `lookup_per_hour`;
    - and none of a query whose search failed within the hour, nor any once three did, kv `lacuerda:search-failed`:
      an answer caracole can't read is never asked again by every page that shows the query.
- Its clients are `make_client(..., interactive=True)`:
  - a random gap from `lookup_delay` (default 0.125–0.375 s, the owner's quarter of 2026-11-03; `[0, 0]` allowed)
    between two requests to a provider;
  - a budget of `lookup_requests` (6) requests to it for the song;
  - and at most `lookup_per_hour` (60) for every lookup of the last hour together (`_common.lookup_policy`, counting
    the `events` of runs named `lookup:…`), read again after each turn (`_LockedClient` in the lane: the hour, the
    day, and after the sheet its `reserve`), so two lookups at once never pass it together: what the other spent
    in its turn cuts the next request, which is never sent, one `budget` event
    (`test_commands_lane.py::test_after_a_turn_a_lookups_client_keeps_to_what_the_hour_and_the_day_leave`,
    `::test_after_the_sheet_a_turn_keeps_the_reserve_for_sheets`, `::test_the_hour_holds_for_two_lookups`).
- What follows the sheet, which the nightly run would do anyway (get.py's `ug` stage, LaCuerda for a song with a
  sheet), spends only what leaves `get.SHEETS_SHARE` (half) of that hour's requests for sheets
  (`_Lookup.after_the_sheet`), its client's `reserve` that share after a turn too; a turn's cut is said as kept for
  sheets only where the reserve made it (`kept_back`: the budget would be more without it), the hour spent whole as
  the hour's (`test_get.py::test_after_a_turn_what_follows_the_sheet_says_what_cut_it`,
  `test_commands_lane.py::test_a_turn_after_which_the_hour_is_spent_whole_is_no_reserve_kept_for_sheets`).
- Then `BudgetExhausted`: the rest waits for the nightly run.
- Nothing else is looser for a lookup, and a lookup never runs yt-dlp.

#### A shared link read by asking its service once

- The owner's choice of 2026-11-10: a link shared to the phone whose text names no song (core.share's `SharedText`)
  is read by asking its service once, one request a shared link, at a lookup's pace and nothing looser (core.share's
  `ShareLinks`, `ShareAsk`):
  - Apple Music: `itunes.apple.com/lookup?id=…&country=…`, provider `itunes` (Apple documents about 20 calls a minute
    for it);
  - Spotify: the track's page, `open.spotify.com/track/<id>`, provider `spotify`, which names the artist to
    caracole's own user agent (checked by hand on 2026-11-10; its oEmbed names the title alone, and is unasked);
  - TIDAL: the track's page, `tidal.com/track/<id>`, provider `tidal`;
  - YouTube and YouTube Music: YouTube's oEmbed, `www.youtube.com/oembed?url=…&format=json`, provider
    `youtube-oembed`, never yt-dlp's `youtube`.
- Each asks the one URL the link's id names: one request, or two for a short link (`spotify.link`,
  `spotify.app.link`, `tidal.link`), whose redirect, to another site, is its answer (a redirect whose status the
  caller accepts is never followed: http.py and core.http alike, client.jsonl's session). An album's, a playlist's or
  an artist's link names no song, said with no request. Deezer's shares carry their names (its API's robots.txt is
  closed: never asked); a Navidrome or Subsonic server's link is never asked.
- Their policies (config.py, `SHARE_PROVIDERS`): no budget, no bulk work (no run or command of the computer asks
  them, pipeline.py and the to-do page's health leave them out), `lookup_requests` what a share needs (1, Spotify's
  and TIDAL's 2), within `lookup_per_hour` with every lookup's (run `lookup:share:…`), at `lookup_delay`.
- Each is switchable (`config.SWITCHABLE`, `enabled = false`, which the phone takes from the computer at a sync), on
  by default.
- The cache's answer is read first, with no request (a short link's hop, which the HTTP cache never keeps, kept beside it once
  the link was read, `ShareAsk.hops`); a block cools the service down and alerts once, an error is
  counted, and the page says either in one line, Edit open: never "this link names no song" for an error.
- The share's page asks by itself only when the app or caracole's own page opened it (`Sec-Fetch-Site` none or
  same-origin); any other page's link gets its Read the link, posted with the form token (ShareRoutes.asks).
- Nothing is sent to a tab site before Fetch.

#### Either pace

- One request at a time per provider (a synchronous client, and the lock below; two lookups at once pass the lock
  between two requests, a lane client's turn coming at the start of its pause before each request but its first,
  and after one its pause runs from the other's last request and a block the other met stops it:
  `test_commands_lane.py::test_two_lookups_requests_alternate_and_a_site_sees_one_at_a_time`,
  `::test_one_lookups_block_stops_the_other_before_its_next_request`), redirect hops included; UG's artist
  directory alone has several in flight, the owner's choice above.
- A request answered with a redirect is a request sent, followed or not: `_common._SENT` and `Pace.SENT` count its
  `redirect` event in the hour's, the day's and `http:last_request:`.
- A connection that fails before any byte is sent (`httpx.ConnectError`: no address, no route) is tried again only
  by bulk work, within `_common.CONNECT_PATIENCE` (60 s) a client (`PoliteClient(connect_patience=)`): a run that
  starts as the laptop wakes, before its Wi-Fi has an address. A retry is the same request; nothing that may have
  reached the site is ever tried again.
- `PoliteClient` paces its own requests, and `_common._pause_after_last_request` its first after the last one any
  caracole sent (kv `http:last_request:<provider>`, to the fraction of a second, else `events`), as bulk work's client
  paces its next one once its process let a lookup go first (`_LockedClient._after_a_lookup`).
- The gap between two requests is the pace's alone: no robots.txt `Crawl-delay` adds to it (gametabs.net's asks 5 s;
  the owner chose, on 2026-10-28, that caracole does not keep it), nor an API's own rate (Megalobiz's 30 a minute;
  the owner chose, on 2026-11-03, the wait times divided by 4, quicker than that). The Sites tab says so of both
  (sites.py `CRAWL_DELAY_ASKED`, `API_PACE_ASKED`).

#### Two caracoles, each its own politeness

- A phone and a computer each keep their own limits, request counts (`events`), cooldowns, pace
  (`http:last_request:`) and the kv records that gate a request, and nothing of them crosses at a sync: the owner's
  choice of 2026-11-03 ("Don't do the polite request across 2 devices";
  docs/superpowers/specs/2026-11-03-politeness-crossing.md).
- So two caracoles at one address may together send a site more than either one's limits; each keeps every rule
  here on its own, and the phone looks songs up at the lookup pace alone, but for an automatic YouTube job's lyrics
  stage, which asks at the bulk pace and budget (The one exception is YouTube, on the phone too): each provider's own
  `budget` and `delay` (`Clients.bulk`, `InteractiveAsk(bulk=)`), under run `youtube-auto:<UTC>:<song id>` (`JobSpec
  .automatic`, `StagedSheet.AUTO_RUN`), so never within `lookup_per_hour`, and still within Megalobiz's `per_day`
  (server's AutomaticPaceTest).
- What the phone takes from the computer is its settings (provider switches, lookup settings, `[match]`, `[rank]`, the
  user agent, the library's name: `GET /api/peer/state`'s `settings`, politeness.py `settings_document`, which the
  phone keeps as kv `phone:settings`), never its politeness.

#### The site catalogues, published for a phone with no computer

- The owner's choices of 2026-11-24 (plan_host_index.md, "Decided"): the laptop's service writes a gzip of every site
  index each week (`caracole index publish`, catalogues.py, no network, no lock, no secret); the owner's own user service
  uploads it to the GitHub release `indexes` of this repo with their `gh` login (nix/publish-indexes.sh, `publish-indexes
  DIR`); the Android app downloads it with one tap (Settings, and a first-start offer when no computer is set) and merges
  it as a sync's index stage does. The public file leaves out the database's path and LaCuerda's search rows
  (`index_transfer.PUBLIC_OMIT`), and keeps the artist pages read.
- The phone asks GitHub's REST API, never `github.com/…/releases/download/…`, whose path github.com's robots.txt closes:
  `api.github.com/repos/Danielhp95/caracole/releases/tags/indexes` (the files, their states and digests), then the
  chosen asset's address, redirected to `release-assets.githubusercontent.com`, a redirect to any other host refused.
  Two requests a download, at a tap, with caracole's own user agent; a 403 or 429 with no requests left is kept (kv
  `catalogues:not-before`) and nothing is asked before it (one more than two hours ahead of the clock passed over,
  `Catalogues.MOST_AHEAD`, `holdBack`), the job failing in `Limited`'s words, where the chord models' job waits. No
  exception to robots.txt is made.
- The upload script keeps the release a prerelease (made one, or marked one, at each run: `/releases/latest` never
  answers a prerelease, and the phone reads the tag), and uploads again a file GitHub lists with no digest, which
  can't be checked, once it is deleted; one listed otherwise than the sidecar says is never replaced. `caracole index
  publish` refuses a clock that reads earlier than the last file's minute, `--force` or not, and the Keep rule
  prunes by the higher of the uploader's schema and the newest one the names hold (catalogues.py, above).
- "caracole itself sends it nowhere" (the exports above) stays true: caracole writes the public file and never
  uploads it; the owner's user service does.

#### The chord models, downloaded at a tap

- The design's §6 (android-autochords): the phone's chords from audio need two models' files it downloads once, at
  a tap, on core.catalogues' code (core.models' `ModelsSource`), with caracole's own user agent: beat_this's float16
  graph, converted here and re-hosted in this repo's GitHub release `models` (a prerelease, as `indexes`; beat_this is
  MIT, "code and published weights"), and BTC's checkpoint, never re-hosted: its authors' own file, unchanged, from
  their repository (jayg996/BTC-ISMIR19 at nix/autochords.nix's commit), beside the APK's BTC graph, which reads it
  at its offsets. The release is published by the owner, never by caracole ("caracole itself sends it nowhere").
- Three requests a download, all to api.github.com: `/repos/Danielhp95/caracole/releases/tags/models` (the release
  listed), its asset's address (`Accept: application/octet-stream`, its one redirect followed to
  `release-assets.githubusercontent.com` alone, any other host refused, as the catalogues' hop: by the computer's
  rule a redirect answered is a request sent, so four exchanges), and `/repos/jayg996/BTC-ISMIR19/git/blobs/<sha>`
  (`Accept: application/vnd.github.raw+json`, answered by the API itself, a redirect refused). A file already there
  whole is asked for again never; an install whole, nothing at all. A 403 or 429 with no requests left is the
  catalogues' `Limited`, its time (`until`) handed back for the caller to keep; a plain 403 (GitHub's secondary
  limit, a block) "Try again later", never a file gone. Each file exactly its pinned size and SHA-256
  (data/caracole/autochords/models.json), or nothing installed.
- robots.txt, checked by hand on 2026-11-27: api.github.com and release-assets.githubusercontent.com answer 404, no
  rules (tests/fixtures/github/); github.com's, which closes `/*/releases/download/`, is never asked.
- A download is a job of the phone's own (server/lookups' `ModelsRunner`), queued by a tap alone: never by itself, one
  at a time. A `Limited` keeps GitHub's time in kv `models:not-before`, and nothing is asked before it (one more than
  two hours ahead of the clock passed over, `Catalogues.MOST_AHEAD`): the job ends as a wait in `Limited`'s
  words. On a metered network it asks nothing and waits for the go-ahead given in Settings, as the catalogues do
  (`--metered-ok`, a job of its own key). Once the folder is judged whole, kv `models:installed` (`{"contract",
  "files", "bytes", "when"}`, kv_set_json's text) notes it; both records are the phone's own, kept by a restore
  (OwnRecords' `models:`).

#### Turning a provider off

- Only a provider in `config.SWITCHABLE` (`megalobiz`, `azlyrics`, `gtptabs`, `musescore`, `harptabs`, `gametabs`,
  `ireal`, `youtube`, `ytimg`, and a shared link's `itunes`, `spotify`, `tidal`, `youtube-oembed`) can be turned off
  (`enabled = false`): then it gets no client and its step is skipped (`ytimg` off: a suggested video's row without
  its thumbnail; a shared link's service off: the phone's share page says so, and asks it nothing).

#### Blocks

- A 403, a 429 or a challenge page raises `ProviderBlocked`:
  - the client sends nothing more that run;
  - `health.record_block` cools the provider down for 24 h × 2^(k−1) + 2 h after the k-th block in a row (so the next
    nightly run is always skipped);
  - one ntfy alert goes out for the first block of a streak alone (`health.alerts`: k == 1, the owner's choice of
    2026-11-15), never one a song, titled with `logs.provider_name` (the run's step, or `_common.alert_block` in a
    command, `caracole fetch --song` from serve's review page too; a lookup sends none); the blocks after it are
    said on the summary and the pages alone;
  - from the third in a row (`health.STREAK`) the Sites tab and the to-do page's health table say the site keeps
    blocking caracole, and how to turn a switchable one off (sites.py `keeps_blocking_words`, `status_of`);
  - and nothing retries or works around it (no proxies).
- A block a lookup met while bulk work let it go first is that work's too: its client sends nothing more
  (`_LockedClient._after_a_lookup`), and `record_block` adds no strike for a cooldown that began after its caller did,
  as `record_ok` clears none
  (`test_commands_common.py::test_bulk_work_sends_nothing_more_to_a_site_that_blocked_a_lookup_it_let_go_first`).
  So is one the other lookup in the lane met at its turn: one block, one strike
  (`test_commands_lane.py::test_one_lookups_block_stops_the_other_before_its_next_request`).

#### robots.txt

- No URL robots.txt closes is asked for, or followed to (`http.ROBOTS_DISALLOW`, `robots_disallows`):
  - not UG's `/search.php` (matching is local, against the sitemap index), `/tab/download`, `/tab/print?` or
    `/download/public/`;
  - nor gtptabs.com's `/ru/` (half of its sitemaps), `/search/` or `/storage/` (an artist's "Download all" archive);
  - nor musescore.com's `/api/jmuse`, `/score/*/download/*`, `/sheetmusic?` (its search) or `/oembed/*`;
  - nor harptabs.com's `/search`, `/api/` or `/*?*_rsc=`;
  - nor gametabs.net's `/api/`, `/tabs?*` (its filters) or `/preparing-tab-file-download` (every attachment, behind a
    login);
  - nor azlyrics.com's `/search/`, `/suggest/`, `/song/` or `/lyricsdb/` (tests/fixtures/azlyrics/robots.txt);
  - nor forums.irealpro.com's `/search/`, `/login/`, `/register/`, `/members/`, `/whats-new/`, `/misc/`, `/find-new/` or
    `/account/` (tests/fixtures/ireal/robots.txt, 2026-11-18);
  - nor i.ytimg.com's `/sb/`;
  - nor, for a link shared to the phone, itunes.apple.com's `/*/lookup?`, `/search*` and `/WebObjects/*`,
    open.spotify.com's `/embed/`, `/download/` and `/local/`, spotify.link's and spotify.app.link's `/_r/`, or
    www.youtube.com's `/results`, `/youtubei/`, `/api/` and the rest of its `User-agent: *` group (tidal.com's and
    tidal.link's close nothing).
- A rule's `$` ends it (`/*.php$`).
- A host's rules are the `User-agent: *` group of its live robots.txt (tests/fixtures/gtptabs/,
  tests/fixtures/musescore/robots.txt, tests/fixtures/harptabs/robots.txt, tests/fixtures/gametabs/robots.txt and
  tests/fixtures/youtube/ytimg-robots.txt, checked by hand on 2026-10-29; tests/fixtures/itunes/, spotify/, tidal/
  and youtube/www-robots.txt on 2026-11-10).
- LaCuerda's robots.txt is empty, and so are LRCLIB's and Megalobiz's API hosts' (none; megalobiz.com's, whose favicon
  caracole asks, closes only accounts and editors: tests/fixtures/megalobiz/robots.txt).

#### A search asks no site

- A search (`caracole search`, `/api/search`) reads the local indexes alone, `lacuerda_index` among them, asks no site
  and takes no lock (`test_web_app.py::test_a_search_asks_no_site_and_takes_no_lock`).
- iReal Pro's forum's threads its sitemaps name are found by their names alone (`search.search_ireal_threads`), with
  no request: a thread is read only by the Fetch the owner presses on its line, a lookup with its `[ireal]` pick
  (`test_web_app.py::test_the_search_gives_irealpros_threads_known_by_their_names_alone_guessed_by_the_query`).
- The exceptions are YouTube's first video for a search, under YouTube's exception below, and LaCuerda's own search
  (`/busca.php`, lacuerda_search.py):
  - sent as a queued job at the lookup pace (`caracole lacuerda --search`), one request;
  - only when the query has settled and its gate allows (`lacuerda_search.gate`, read with no request):
    - a word of four letters;
    - neither your library nor LaCuerda's index answering it well already;
    - not asked within 30 days;
    - no cooldown;
    - the hour's lookups;
    - no failure within the hour;
  - or by hand (its button, or Enter while the gate says `auto` or `button`);
  - at most 20 an hour sent by the pages by themselves within `lookup_per_hour`;
  - each query kept 30 days (kv and the HTTP cache).
- An artist's songs come from their page, read at most once in 30 days.

#### The one exception is YouTube

- The one exception is YouTube, the owner's explicit choice for their own songs (a handful a night at first; up to 25
  since 2026-11-27, the budget's 50 runs): its robots.txt closes `/results` and `/youtubei/` to crawlers, and yt-dlp
  uses both, against its terms too.
- Provider `youtube` (youtube.py) is the one place caracole runs yt-dlp, and only on these terms, for:
  - a song with no human sheet (`todo.songs_to_buy`);
  - or one the owner names with the video to take (`caracole youtube --song`, and its `--sheet`, which the library
    page's sheet from a YouTube video queues as a command: the owner chooses the video and starts it from the page; a
    song with no human sheet, not ignored, no purchase linked, `youtube_sheet.py`);
  - or the first video of a search on the served library page, the owner's explicit choice of 2026-10-29
    (`youtube_search.py`, `caracole youtube --search`, a queued job, never `caracole get`):
    - metadata alone (`ytsearch1:`, `--flat-playlist --dump-single-json`, the query after `--`, `make_youtube`'s
      pauses and lock);
    - its thumbnail from `i.ytimg.com/vi/<id>/hqdefault.jpg` (a `PoliteClient` of provider `ytimg`, right after the
      search with no pause, one request, cached forever, its own cooldown and alert, so that a block of either never
      cools the other, kept in `cache_dir` once `checked_jpeg` reads a JPEG);
    - only for a query with no sheet on the sites;
    - a query once in 30 days (kv `youtube-search:<key>`, which keeps the video for the page);
    - at most `SEARCHES_PER_HOUR` (10) an hour (`events`, runs named `youtube-search:`);
    - none while YouTube cools down, none of a query that failed within the hour, none for the hour once three did;
    - on the phone the same, on its own records, and none sent by itself on a metered network (the gate's `off`,
      "waiting for Wi-Fi", the network checked again before the run): a search's suggested video goes on an
      unmetered network alone;
  - or the metadata of a video pasted into that box, the owner's explicit choice of 2026-10-29
    (`caracole youtube --video`, `youtube_search.read_video`):
    - `--skip-download --flat-playlist --dump-single-json` of the video's plain address after `--`, never a download;
    - under the same gate keyed `video:<id>`, the hour's 10 shared with the searches;
    - its thumbnail as theirs.
- And only where auto-chords can make chords of it (`youtube_fetch.route_problem`: the packages, both model files,
  yt-dlp; the default package never runs it).
- How it runs:
  - within the budget, one run at a time;
  - a pause from `delay` (3.75–7.5 s) between two runs (`YtDlp._pause`, and `_common._pause_after_last_request` via
    `make_youtube`), and yt-dlp's own pauses inside one (`--sleep-requests 0.5`, `--sleep-interval 2.5` to
    `--max-sleep-interval 5` before a download), each a quarter of what it was before 2026-11-03, the owner's choice;
  - `--retries 0`;
  - audio alone (`-x`), never a playlist, the song's name after `--`, arguments a list and never a shell;
  - no cookies, login, config files, plugins (PO-token providers among them) or remote code (`--ignore-config`,
    `--no-cookies`, `--no-cookies-from-browser`, `--no-plugin-dirs`, `--no-remote-components`);
  - an environment of its own (`ytdlp_env`: what a program needs, no `CARACOLE_*` variable);
  - a stop or Ctrl-C stops its process group too;
  - a bot check, an HTTP 429 or 403, a rate limit or a captcha is `ProviderBlocked`, honoured like any block
    (tests/test_youtube.py).
- The debug build's YouTube bench (android/README.md, "The YouTube bench"), a few songs by hand on the owner's phone,
  keeps these terms on the phone's records, but for one: its cap of YouTube's budget (50 yt-dlp runs in any 24 hours,
  6 before 2026-11-27) is lifted while the feature is developed, the owner's choice of 2026-11-27 ("ignore the run
  limits while developing this feature. as connection is patchy"; `DbLedger.DAY_CAP_LIFTED`, `false` puts it back):
  the run count alone, every run still reserved, counted and reported; the pause, one run and one session at a time, a
  block and its cooldown, no retry, the provider's switch, the gate's hosts and three songs a session stay. Nothing
  else's budget changes (`YtDlp`'s, PhoneConfig's `youtube`, the computer's).
- **On the phone too**, the owner's choice of 2026-11-26, answering the YouTube-on-Android study's seven questions: "1.
  yes, 2. yes. 3. automatic is okay, 4 It's okay 5. acceptable, 6. I would 7. I don't want to go further with "ask the
  computer route"". The exception holds on the phone on the computer's terms: the same arguments and block patterns,
  read from the corpus's `data/caracole/youtube/youtube.json` (never retyped), and the same budget and pauses, counted
  on the phone apart (Two caracoles, each its own politeness, below). yt-dlp, its challenge scripts and QuickJS-NG are
  pinned in the APK (`android/youtube/pins.json`) and run in the app's `:youtube` process, in both builds, the release's
  on an arm64 phone alone (an x86_64 one says "this phone's caracole has no yt-dlp"); nothing updates itself, and a fix
  comes with a caracole release (`android/scripts/bump-ytdlp.sh`). yt-dlp presents itself as its default clients do (an
  official app's: a TV's, a Vision Pro's); nothing solves BotGuard or mints a PO token. Every run is given the app's
  loopback gate (`HostGate`) as its `--proxy` and is refused without it (`YtDlpService`); the gate allows YouTube's own
  hosts and refuses Google's attestation host by name, and the app's bytes are measured against the gate's: a check and
  a measurement, not a wall. Audio alone is chosen by format (`-f bestaudio[ext=m4a]`), with no FFmpeg. A pasted video's
  title and thumbnail are read as it is pasted (`YouTubeVideoRunner`); nothing is downloaded before the owner asks, for
  a video pasted, shared or named on a card (`YouTubeRoutes`, `YouTubeSheetRunner`), on any network, but by the
  automatic pass below.
- The phone takes audio by itself ("automatic is okay"; and of its default: "1. yes and allow that setting"): at most
  the provider's budget (50) of yt-dlp runs in any 24 hours, every run of the phone's counted (`DayBudget`: `events`
  and the runs reserved before their gate opens, the bench's too, as one set); only on an unmetered network, checked
  before each run (`YouTubeSearchRunner.METERED`, "waiting for Wi-Fi", the song left noted), and while the battery
  isn't low; only for a song with no sheet at all whose sites were asked (`Due.songs`); only once the chord models are
  on it. After a lookup that left its song "Not on the sites" (kv `youtube-wanted:<id>`, `Phone.onNoSheet`; on a
  paired phone, those songs alone), and daily while charging on a phone that has not synced with a computer in 14 days
  (`YouTubeAuto.paired`, the app's `YouTubeWorker`: `youtube-soon`, `youtube-daily`); a pass stops at 8 minutes, at
  fewer than 2 runs left, at a block or at out of date: two runs yt-dlp can't read (classify's `outdated`) on two
  different videos within 24 hours set kv `youtube-outdated` `{version, at, reason}` for the app's yt-dlp
  (`core.youtube.Outdated`, `youtube-outdated:hits`; a pass-over never notes one), until that version changes or 7
  days pass, said in Settings, the job's audio stage and outcome ("YouTube changed what yt-dlp 2026.11.23 reads:
  caracole's next release brings a fix") and one alert a version; a job asked for now still runs, warning first. Its jobs are `JobSpec.automatic`: their budget the day's runs
  left, quiet (`Job.quiet`: no failed alert; a block's alert still once a cooldown), and their lyrics stage at the
  bulk pace and budget, under a run of its own (`youtube-auto:`), never within `lookup_per_hour`. Settings' switch
  "Find audio on YouTube by itself" (kv `phone:youtube-auto`, on by default) turns the pass alone off. A sheet from a
  video you paste or share is asked for now, on any network. No route asks the computer to do it.
- YouTube's oEmbed for a link shared to the phone (provider `youtube-oembed`, the owner's choice of 2026-11-10) is no
  yt-dlp run and no part of this exception: one request a video, robots.txt honoured (its `/oembed` is open).
- Everything else keeps honouring robots.txt; widen nothing here without the owner, and copy it to no other site.

#### iReal Pro's forum, the owner's choice

- The owner's go of 2026-11-18, after a probe and a smoke test (22 requests, caracole's own user agent, 6 s apart, no
  block): "Go for adding ireal forum as a new source", for jazz standards, "as ultimate guitar and la-cuerda are not
  great with them".
- Its terms (`/help/terms/`) say nothing of bots, scraping or reading: "You retain copyright over the Content", and no
  one may "submit or link to any Content which … risks copyright infringement"; no `/ai.txt` or `/llms.txt`. So it is
  no exception; caracole keeps every rule above there, its robots.txt (no Crawl-delay) among them.
- Provider `ireal` (ireal.py, ireal_fetch.py, ireal_index.py) keeps a chart as the sheet of the songs of wanted.txt and a
  lookup's song alone, the sheet sites having none: never a thread for a song nobody asked for, and its playlists'
  thread pages, which robots.txt allows, read for their charts' titles and composers, each once in 30 days, never a
  mirror. Never its search, its members' pages, its attachments or a login.
- The iReal Pro app is paid; the forum's charts are free to anyone, and caracole draws its own chord grid, none of the
  app's paid parts (its backing tracks, its playback): no paywall is worked around.

#### The second exception: a site whose terms forbid automated access, where the owner chose it

- A site's terms against bots, scrapers or copying do not stop caracole at a site the owner chose, named below with
  its terms; the owner's rule, for any site they name here.
- Everything else above binds caracole there, as at every site:
  - robots.txt honoured (its disallowed paths; its `Crawl-delay` is not kept);
  - caracole's own user agent;
  - the paces and budgets;
  - one request at a time;
  - never a login, a file behind one, or an API robots.txt closes;
  - a 403, a 429 or a challenge a block (`ProviderBlocked`, the cooldown, one alert);
  - and nothing worked around (no other user agent, cookies, login, proxies, API keys or captcha).
- The exception is what is kept, never how it is asked for.
- A site joins it by the owner's choice alone, never by analogy.

##### harptabs.com

- Its site terms (2004) say no one may "use, copy, or distribute any portion" of it, and its API's terms ask that its
  tabs not be bulk-mirrored, yet caracole keeps tabs from it.
- Provider `harptabs` (harptabs.py, harptabs_fetch.py) keeps them for the songs of wanted.txt and a lookup's song:
  - never a tab page for a song nobody asked for and never a mirror (its sitemap, then the pages of a song's
    candidates, `CANDIDATES` at most, each read once and cached);
  - one tab a song, privately, in the library;
  - robots.txt honoured (it closes `/search`, `/api/`, `/*?*_rsc=` and more);
  - the bulk pace and budget above, a lookup's at the lookup pace.
- Its artist pages, which robots.txt allows, are read for the names of their tabs alone, never a tab, so that a
  search finds its tabs by artist as UG's index does, the owner's ask (harptabs_index.py: every artist the sitemap
  lists, once in 30 days, at the bulk pace and within a budget; an artist's Songs, one page at the lookup pace).
- An artist's tabs past the 30 a page renders are the site's API's, which caracole never asks for.
- caracole sends harptabs.com its own user agent, as every site
  (`test_harptabs_fetch.py::test_caracole_asks_with_its_own_user_agent`): asked by hand on 2026-10-27 (robots.txt,
  the sitemap and two tab pages: all 200, the sitemap after one Cloudflare 530, an error), it answers it.
- A block there is any site's (`test_pipeline.py::test_a_harptabs_block_cools_it_down_and_marks_no_song`).
- An export (`caracole peer export`, the Sync tab's Export, the phone's) holds what this site gave too, to share as the
  owner likes: the owner's choice of 2026-11-03 ("ignore the privacy, share everything"); caracole itself sends it
  nowhere.

##### gametabs.net

- Its terms (updated 2026-05-25) forbid "Using automated means (bots, scrapers, etc.) to access or collect data from
  the Service without Our express written permission"; the owner chose to read it anyway on 2026-10-28, knowing
  them.
- Its robots.txt allows tab and game pages and the sitemaps, closes `/api/`, `/tabs?*`, the pages behind a login
  (`/preparing-tab-file-download`, every attachment's download, among them) and more, and asks a `Crawl-delay` of
  5 s, which caracole does not keep: its pace is four requests a second (`config.DEFAULT_PROVIDERS`, a quarter of a
  second apart since the owner's choice of 2026-11-03), far quicker than it asks.
- Provider `gametabs` (gametabs.py, gametabs_fetch.py, gametabs_index.py) keeps the text tab each tab page shows to
  anyone, never an attachment (Guitar Pro, MIDI, PDF: a login's), for the songs of wanted.txt and a lookup's song
  alone:
  - never a tab page for a song nobody asked for and never a mirror (its sitemaps, then the pages of a song's
    candidates, `CANDIDATES` at most, each read once and cached);
  - one tab a song, privately, in the library.
- Its game pages, which robots.txt allows (`?page=N` too, which its sitemap lists), are read for each tab's
  composers and instruments alone, never a tab, so that a song is found by its composer, the owner's ask
  (gametabs_index.py: every page the sitemaps list, once in 30 days, at the bulk pace and within a budget).
- Asked by hand on 2026-10-28 with caracole's own user agent (robots.txt, the sitemap index, a child, three game
  pages and two tab pages), it answered each with 200 from a plain nginx; caracole asks it so
  (`test_gametabs_fetch.py::test_caracole_asks_with_its_own_user_agent`).
- A block there is any site's (`test_pipeline.py::test_a_gametabs_block_cools_it_down_and_marks_no_song`).
- An export (`caracole peer export`, the Sync tab's Export, the phone's) holds what this site gave too, to share as the
  owner likes: the owner's choice of 2026-11-03 ("ignore the privacy, share everything"); caracole itself sends it
  nowhere.

##### azlyrics.com

- Each lyrics page says, in a comment above the text, "Usage of azlyrics.com content by any third-party lyrics
  provider is prohibited by our licensing agreement", and it has no terms page caracole found (its `/copyright.html`
  is a DMCA policy, silent on bots); the owner chose to read it anyway on 2026-10-30, knowing that notice.
- Its robots.txt allows artist and lyrics pages and closes its search, so that provider `azlyrics` (azlyrics.py,
  azlyrics_fetch.py) keeps the plain lyrics of the songs of wanted.txt and a lookup's song alone:
  - only where LRCLIB and Megalobiz left none;
  - reached from the artist's page by their name: two requests a song, each cached, no letter page, no index, never
    a mirror;
  - privately in the library, with a link back to the page wherever caracole credits them.
- No pause and no budget, the owner's choice (Bulk work, above).
- caracole sends it its own user agent (`test_azlyrics_fetch.py::test_caracole_asks_with_its_own_user_agent`).
- Its block page is a 200, which `http.is_challenge` knows by its words and the client never caches
  (`test_azlyrics_fetch.py::test_its_block_page_is_never_kept_in_the_cache`), a block as at any site
  (`test_pipeline.py::test_an_azlyrics_block_cools_it_down_and_marks_no_song`).
- An export (`caracole peer export`, the Sync tab's Export, the phone's) holds what this site gave too, to share as the
  owner likes: the owner's choice of 2026-11-03 ("ignore the privacy, share everything"); caracole itself sends it
  nowhere.

##### Spotify and TIDAL, for a link shared to the phone

- Spotify's User Guidelines forbid "crawling" or "scraping", "whether manually or by automated means, or otherwise
  using any automated means (including bots, scrapers, and spiders), to view, access or collect information", and
  TIDAL's Content Guidelines, part of its terms, say the same in the same words (both as a web search quoted them on
  2026-11-10); the owner chose on 2026-11-10 that the phone reads one of their track pages for a link shared to it
  (A shared link read by asking its service once, above), and, told these terms the same day, kept both on ("don't
  turn tidal and spotify off").
- One page a shared link (its short link's hop besides), at a lookup's pace, robots.txt honoured (both open their
  track pages), cached; only the song's two names are read of it, for the share page and a lookup the owner taps.
- Apple's lookup is its documented public API and YouTube's oEmbed a public endpoint for any client; YouTube's terms
  forbid automated access but for search engines by its robots.txt, with its permission or as the law permits, so
  its oEmbed is asked by the same choice of the owner's, one request a video.

#### The cache

- Every accepted 200 and 404 is cached forever, in `cache_dir/http/<provider>/`.

### Errors are never misses

- A block, a spent budget, an HTTP or network error, or a page that won't parse (`PageParseError`,
  `GtpTabsParseError`, `LaCuerdaParseError`, `LrclibParseError`, `MegalobizParseError`, `AzLyricsParseError`,
  `HarpTabsParseError`, `GameTabsParseError`) never makes a song not found, its lyrics missing or its Guitar Pro file
  or harmonica tab a miss: the song waits for the next run.
  - http.py, pipeline.py, provider_pass.py, ug/fetch.py, lyrics.py, megalobiz_fetch.py, azlyrics_fetch.py,
    lacuerda_fetch.py, gtptabs_fetch.py, harptabs_fetch.py, gametabs_fetch.py.
  - `test_pipeline.py::test_ug_block_cools_down_and_never_marks_not_found`,
    `test_fetch.py::test_parse_error_is_not_a_miss`, `test_gtptabs_fetch.py::test_a_spent_budget_is_no_miss`.
- A cached answer that won't parse is asked for once more, past the cache, before it is an error, so a bad night isn't
  replayed every night after: `http.read_once_more` for LRCLIB, LaCuerda, harptabs.com, gametabs.net and gtptabs.com,
  ug/fetch.py's `_get_page` for UG
  (`test_lyrics_pending.py::test_a_cached_answer_that_isnt_json_is_asked_for_once_more`).
- LRCLIB's 503 is its ServerOverloaded, busy, never a miss:
  - `PoliteClient` asks once more after its `Retry-After` (seconds or a date, 30 s at most, within the budget and the
    pace; a host of `http.RETRY_AFTER_503` alone);
  - and a second 503, or one without it, is an error
    (`test_lyrics_pending.py::test_a_503_from_get_is_an_error_and_the_song_waits_never_missing`).
- A song's lyrics are missing only once every site asked answered a miss:
  - LRCLIB's miss;
  - then Megalobiz's (a search with no result that fits, or a record gone, 404), which asks again after 30 days; an
    error, a block or a spent budget there (`provider_pass.each_song`'s `on_cut`) puts a song LRCLIB missed back to
    pending, and a song LRCLIB failed on is never missing whatever Megalobiz answers (`test_megalobiz_fetch.py::test_an_error_on_a_song_lrclib_missed_puts_it_back_to_pending`);
  - AZLyrics the same way, after Megalobiz, its miss a 404 or a page that doesn't list the song
    (`test_azlyrics_fetch.py::test_an_error_on_a_song_the_others_missed_puts_it_back_to_pending`).
- On gtptabs.com only an artist page that answered without a candidate is a miss, asked about again after 30 days.
- On harptabs.com only candidates that all answered, none by the song's artist (or gone, 404), asked about again after
  30 days (harptabs_fetch.py, `test_harptabs_fetch.py::test_a_page_that_wont_parse_is_an_error_never_a_miss`).
- On gametabs.net only candidates that all answered, none whose page is the song's title of its game or composer (or
  gone, 404), asked about again after 30 days (gametabs_fetch.py,
  `test_gametabs_fetch.py::test_a_page_that_wont_parse_is_an_error_never_a_miss`); and of its game pages only one that
  answers 404 loses its tabs (gametabs_index.py).
- On iReal Pro's forum only candidates that all answered, none holding a chart that is the song's (or gone, 404),
  asked about again after 30 days (ireal_fetch.py,
  `test_ireal_fetch.py::test_a_page_that_wont_parse_is_an_error_never_a_miss`); and of its playlists only a page that
  answers 404 loses its charts (ireal_index.py).
- On YouTube only a search that answered without a video that fits (youtube_fetch.py,
  `test_youtube_fetch.py::test_an_error_is_no_miss_and_the_song_waits_for_the_next_run`).
- Of LaCuerda's listings only a page that answers 404 loses its artists, never one that errs or won't parse
  (`test_lacuerda_index.py::test_a_page_that_wont_parse_is_an_error_and_its_artists_stay`).
- A page of LaCuerda's search its server cut short (its table or list not closed, its script's arrays missing or
  disagreeing, fewer rows than it counts) is a `LaCuerdaParseError`, never "no results":
  - it records nothing asked (`test_lacuerda.py::test_an_answer_cut_short_is_a_parse_error_never_no_results`);
  - only the failure that keeps the pages from sending it by themselves for an hour
    (`test_commands_lyrics.py::test_lacuerda_search_that_failed_isnt_sent_by_the_page_again_within_the_hour_but_by_hand_it_is`).
- A block or a spent budget exits 0; a bug exits 1, which fires the unit's ntfy alert.

### Slugged tabs only at their slugged URL

- **Slugged tabs only at their slugged URL**, as UG answers 404 for them at `/tab/{id}`: the index keeps each tab's
  sitemap path (`ug_index.path`), from which ug/page.py `page_url` and ug/lookup.py `IndexTab.url` and `tab_url_for`
  build it.
- **Bare-id tabs** (a tenth of UG's, and every tab of an artist with an accented or non-Latin name) are found on the
  artist's UG page (ug/artist.py, the `artist_page` route in ug/fetch.py; every list read kept for searches,
  ug/artist_tabs.py), `/artist/<name>_<id>` or `/artist/<id>` (`overrides.artist_page_address`):
  - its URL from `[artist_url]`, or learned from a tab page into kv `ug:artist_url:<artist key>`, or named by UG's
    artist directory (ug/directory.py `artist_page_for`);
  - an `[artist_url]` tab page is read once, through the run's client, for the page it links to: kv
    `ug:pasted_tab:<tab id>`;
  - one that won't parse waits as any tab page does, kv `ug:unreadable:<tab id>`.
- `test_fetch.py::test_slugged_tabs_fetched_at_their_slugged_url`,
  `::test_bare_id_chords_of_a_matched_song_come_from_its_artist_page`, tests/test_live_banma.py.

### Guitar Pro: gtptabs.com's downloads and the inbox, never Ultimate Guitar's

- The index keeps UG's chords, text tabs and ukulele chords alone (ug/sitemap.py `KEEP_TYPES`): a Guitar Pro or Power
  Tab file's tab is counted by type and left out, so no song matches one and no page, search, count or link shows one
  (`test_index.py::test_guitar_pro_and_power_tab_files_are_counted_by_type_and_left_out`).
- ug/page.py gives UG's `Pro` and `Power` types no kind (`KINDS`: chords, tabs, ukulele), so ug/fetch.py never rates,
  records or picks such a version, never reads an artist page's lists of them, and a `[pin]` of one pins nothing
  (`test_fetch.py::test_a_pin_ultimate_guitar_answers_with_a_guitar_pro_page_pins_nothing`,
  `::test_artist_page_kinds_fill_the_tab_slot_and_its_guitar_pro_lists_are_never_read`).
- `caracole get --tab` refuses a page whose address names another type before writing anything
  (`test_get.py::test_a_page_of_another_type_asked_for_as_the_tab_is_refused_and_nothing_is_written`).
- inbox.py files what the user drops into `_inbox/` by its name, for any song not ignored, as the song's lowest free
  `guitar-N`, under its own `inbox` version of the file's kind (`test_inbox.py::test_files_into_song_by_name`).
- Official and non-public versions are never used.
- gtptabs_fetch.py downloads from `/tabs/download/{id}.html` alone, never logged in:
  - one file for a song with no Guitar Pro or Power Tab file in `files` (filed or downloaded, deleted since or not);
  - and keeps it only when `gtptabs.sniff` reads a Guitar Pro or Power Tab header: as the lowest `guitar-N` no file
    holds (`inbox.guitar_number`), with its version (provider `gtptabs`).
  - It never replaces or deletes a file (`test_gtptabs_fetch.py::test_a_song_with_a_guitar_pro_file_gets_no_other`,
    `::test_a_number_a_file_in_the_folder_holds_is_never_reused`).

### MuseScore is links and the inbox

- musescore_fetch.py asks MuseScore for its song sitemaps alone: never a song page, a score, a download or
  `/api/jmuse`, and never logged in (`test_musescore_fetch.py::test_caracole_asks_for_the_sitemaps_alone`).
- Its Cloudflare challenge is a block like a 403, and the to-do page then says plainly that MuseScore is blocking
  caracole, even with no page to list (`todo._musescore_pages`).
- Every match is on the title alone, a possible match (`musescore.song_pages`).
- inbox.py files what the user downloads (`SCORE_EXTENSIONS`) as `score-N.<ext>`, never as `sheet.pdf`, under the
  song's one `inbox` version of kind `score`.
- A MusicXML header is read with `musicxml.header`, up to the part list only.

### Chinese is compared as pinyin

- Chinese is compared as pinyin (`normalize.romanize`, with pypinyin) in match.py, coverage.py, music.py, search.py,
  library_page.py, ug/fetch.py, ug/artist_tabs.py (its forms) and lacuerda_index.py (whose keys are pinyin).
- Identity keys also fold Traditional characters to Simplified.
- Where a name caracole didn't write meets yours (UG's artist pages and slugs, LaCuerda's listings, purchases' tags,
  downloads), it is compared by `normalize.name_forms`, which also gives the parts of a name in two scripts ("Song
  Dongye (宋冬野)"); forms are for comparing and never make a key.
- **A key changed**: a change to `clean_title`, `slug_key` or `identity_key` that can change a key bumps
  `normalize.KEY_VERSION`: `songs.ensure_current_keys`, run before songs are looked up, listed or added, then re-keys
  them once and merges those that now share a key.
  - It re-keys `songs` and the tombstones of removed songs (`removed`, `songs._rekey_removed`) only.
  - `ug_index` keys change when a sitemap is parsed again.
  - The keys of a table site_index.py fills (`gtptabs_index`, `musescore_index`, `harptabs_index`, `gametabs_index`)
    at its next refresh, which parses every sitemap again, an unchanged one from the cache
    (`test_gtptabs_fetch.py::test_new_keys_read_the_sitemaps_again_even_when_they_are_unchanged`).
  - `harptabs_index`'s, after a change to how harptabs.py keys a slug alone (`harptabs.joined`: a tab's
    `can-t-help-…` is `cant-help-…`), from the paths it holds, with no request, before the step, a lookup or the
    artist pages' pass (`harptabs_fetch.ensure_current_keys`, `ROW_KEYS`).
  - `lacuerda_index` keys are made again from the names it stores, with no request
    (`lacuerda_index.ensure_current_keys`, at its next refresh or store).
  - So are `ug_artist_tabs`' keys and forms (`artist_tabs.ensure_current_keys`, at its next store or backfill, which
    the match step and every lookup call).
  - And `gametabs_game_tabs`' title keys from their titles (`gametabs_index.ensure_current_keys`, before the step, a
    lookup or a game pass), and `ireal_charts`' from theirs (`ireal_index.ensure_current_keys`, before a pass or a
    store); `ireal_index`'s are its sitemaps', made again with them.
- Name new per-song kv keys `<prefix><song id>` (or `<prefix><song id>:<more>`) and add the prefix to
  `songs._PER_SONG_KV`, so a merge or a removal deletes them (`songs.delete_song_kv`).

### A removed song stays removed until you ask for it again

- `caracole remove` (removal.py):
  - takes the song's lines out of wanted.txt first, and stops before anything else when the file can't be read;
  - then, in one savepoint, leaves its tombstone (`songs.mark_removed`: table `removed`, its key, name and source ids)
    and deletes its record (versions and files cascade), its per-song kv and its lines' `wanted:first_seen:`;
  - then the files caracole wrote.
- `songs.upsert_song`, the one way a song is added, is given wanted.txt lines alone (`caracole add`, the web page, a
  line typed):
  - a line for a removed song asks for it again, so its tombstone (found by source id or by key) goes and the song
    comes back new;
  - or the line finds the song of that key the library has (after a re-keying).
- Nothing else may create a song
  (`test_removal.py::test_the_next_sync_brings_nothing_back_until_you_ask_for_the_song_again`,
  `test_songs.py::test_a_wanted_line_brings_a_removed_song_back_as_new`).

### Schema changes go through db.py

- Bump `SCHEMA_VERSION` and add the script to `_MIGRATIONS`.
- A trigger states no conflict clause: an upsert's `DO UPDATE` aborts on a conflict in any trigger it fires, whatever
  `OR IGNORE` says, so a trigger looks up what it would repeat (schema 14,
  `test_index.py::test_a_tab_renamed_to_a_new_key_of_words_the_index_knows_is_stored`).
- `_migrate` copies an existing database to `caracole.sqlite.v<N>.bak` (`VACUUM INTO`, under a name of its own, then
  renamed), then runs each script in one `BEGIN IMMEDIATE` transaction with its `PRAGMA user_version` (a script never
  begins or commits one itself).
- One connection migrates at a time, of every thread and process (an flock on `caracole.sqlite.migrating`, the version
  read again under it:
  `test_db.py::test_connections_opened_at_once_migrate_once_and_each_opens_the_database`).
- A newer database raises `DatabaseTooNew`, and `_common.open_db` exits 2 (tests/test_db.py).
- Writes that apply whole or not at all go in `db.savepoint(conn, name)`, which nests in a caller's: the connection is
  in autocommit mode, where `with conn:` opens no transaction
  (`test_db.py::test_a_savepoint_undoes_its_whole_block_and_nests`, tests/test_versions.py).

### overrides.toml and songbooks.toml

- **overrides.toml** is written only through the `add_*` functions of overrides.py: tomlkit, so the user's comments
  and layout survive, then `library.write_atomic`.
- It is read only as a regular file (`test_overrides.py::test_writers_preserve_comments_and_roundtrip`).
- So is **songbooks.toml**, through the writers of songbook.py (`make_songbook`, `add_to_songbook`, ...): a file that
  won't parse is a `SongbookFileError`, which stops the songbooks and nothing else
  (`test_songbook.py::test_writers_keep_comments_and_layout`,
  `test_songbook_render.py::test_a_broken_songbooks_file_is_an_error_that_stops_nothing_else`).

### The library is synced

- Syncthing and every device can write to it.
- Read a file there with `library.read_regular` (or `open_regular`: no symbolic link followed, regular files only):
  - `dir_fd=` for a name in a folder opened without following a link, as inbox.py reads `_inbox/`;
  - `read_text` for its text, any failure the caller's error naming the file, as overrides.py and songbook.py read
    theirs;
  - `read_json` for its JSON, where whatever a device wrote is a ValueError at worst, never the RecursionError that
    would stop a pass over every song, as it is an `OverridesError` or a `SongbookFileError` in overrides.toml or
    songbooks.toml.
- Write one with `library.write_atomic`: a random temporary name opened exclusively, then a rename. Never `mkstemp`,
  whose mode 0600 hides files from Syncthing.
- Nothing private or bulky goes there: the database, the lock, caracole serve's request history (`requests.jsonl`,
  0600), the HTTP cache, the audio taken from YouTube (`cache_dir/youtube/`, youtube_fetch.py) and the audio files you
  give caracole (`state_dir/audio/`, audio_store.py) stay in `state_dir` and `cache_dir`, and chordpro works on a copy
  in a 0700 folder under the cache (render.py).
  tests/test_library_safety.py.
- A removal deletes only what caracole wrote in the song's folder, by name, through descriptors opened with
  `O_NOFOLLOW` from the library down, and names everything it leaves:
  - `removal._caracoles`: kept files, the outputs of a kept sheet (its Traditional PDF among them) or of a render
    record, its exports, a version's or a harmonica tab's page `render:files:` records, LRCLIB's lyrics, info.json;
  - it never touches Music/, and deletes the song's audio taken from YouTube from the cache and the audio file you
    gave it from `state_dir/audio/` (tests/test_removal.py).

### One caracole at a time

- `_common.exclusive` holds an flock on `state_dir/caracole.lock`, re-entrant within a process, and the clients of
  `make_client` and the yt-dlp runner of `make_youtube` hold it until closed.
- Every command that asks UG, LRCLIB, LaCuerda, gtptabs.com, MuseScore or YouTube for pages or writes the library
  takes it.
- `search`, `match --dry-run`, `index stats`, `remove --list`, `songbook list`, `songbook show`, `versions` (the list
  alone), `backup --list`, `index export` and `peer export` (one read transaction each) only read and never wait.
- `add` writes its wanted.txt line first, and a `--lacuerda` pick (overrides.toml is in the library) only once it holds
  the lock, failing when the lock file can't be opened
  (`test_commands_sources.py::test_add_with_lacuerda_writes_no_pick_without_caracoles_lock`).
- `review` and `remove` take it only after their questions (commands/library.py, commands/remove.py), so the nightly
  run never waits for an answer (`test_commands_lock.py::test_review_never_holds_the_lock_while_it_waits_for_you`,
  `::test_remove_never_holds_the_lock_while_it_asks`).

#### A lookup never waits behind a whole nightly run, and still never writes beside it

- `exclusive(..., interactive=True)` announces it in `state_dir/caracole.lock.waiting/`:
  - a file per waiting process, touched every `TICKET_BEAT` s while it tries for the lock, and dropped once it holds
    it;
  - one its process left, or untouched for `TICKET_STALE` s, a lookup killed while it waited, no longer counts.
- Lookups take the lock in the lane (`exclusive(..., lane=True)`, which implies `interactive`): `caracole get`
  (get.py `_Lookup.run`), `ug --link` (commands/ug.py `_read`), `lacuerda --search` and `--artist`, `harptabs
  --artist` and `lyrics --song --as` (commands/lyrics.py), the six
  (`test_commands_lock.py::test_lookups_take_the_lock_in_the_lane_what_the_owner_asked_for_now_as_a_lookup_and_bulk_work_neither`):
  - a shared flock of `state_dir/caracole.lock.lane` (`LANE_NAME`) from before they ask for the lock until they let
    go of it (`_release`), so a lookup run in a process that goes on, or whose acquire was interrupted, leaves it;
  - their tickets named `lane.<time.time_ns(), 20 digits>.<pid>` (`LANE_TICKET`), taken oldest first, a ticket
    trying for the lock only at the head of the lane (`lane_tickets`: a dead one dropped at once, a stale one passed
    over), one deleted from under its lookup made again under its own name, in its place;
  - their turns (`pass_turn`): a lane process holding the lock, at a turn point (a lane client's pause before each
    request but its first, and between two of a lookup's stages), in no transaction, when a lane ticket waits,
    writes its own (the newest), lets go, takes the lock back when its ticket heads the lane, writes its record back
    and counts a handoff (`handoffs()`), so whatever reads again after a handoff reads again after a turn; killed or
    interrupted as it waits, it leaves no ticket and writes no record, and the next in the lane takes the lock;
  - `caracole get` passes a turn before each stage (`_Lookup._turn`, never inside one), and after a turn, there or in
    a client's pause, reads overrides.toml and its song again (`_Lookup.handed`, `overrides_since`), so its
    index.html shows a tab the other pinned; its good run is what its own clients were answered
    (`PoliteClient.answered_any`), never another lookup's errors under the same second's run id
    (`test_get.py::test_a_lookup_passes_a_turn_before_each_stage_never_inside_one`,
    `::test_after_a_turn_a_lookup_reads_overrides_and_its_song_again`,
    `::test_a_lookups_good_run_is_its_own_clients_not_another_lookups_of_the_same_second`); a song that left the book
    at a turn (another caracole took it out, or merged it into one of the same name) ends it as a refusal, its song
    stage saying so and the stages left skipped, never a bug (`_Lookup._left`,
    `::test_a_song_that_left_the_book_at_a_turn_ends_the_lookup_in_its_song_stages_words`);
  - `ug --link` passes a turn between a tab's page and its artist's lists (its `stage` callback, as the artist stage
    starts after a tab's), and reads overrides.toml again after it (`overrides_since`); the others only in their
    client's pauses. What each reads before a request and writes after it: LaCuerda's search checks its gate (asked,
    answered, the hour, a failure, the hour's automatic searches) and sends its one request, its client's first, in
    one turn; `ug --link`'s `known` decides only before its first request, and kv `ug:link-failed` is read and written
    after its last, with no turn between; `lacuerda --artist` and `harptabs --artist` store each page as they read it.
    Each one's good run is its own client's (`PoliteClient.answered_any`)
    (`test_commands_ug.py::test_a_ug_link_takes_a_turn_between_its_tab_page_and_its_artists_lists`,
    `::test_a_ug_links_good_run_is_its_own_clients`,
    `test_commands_lyrics.py::test_a_lacuerda_search_checks_its_gate_and_sends_in_one_turn`,
    `::test_a_lacuerda_artist_pages_good_run_is_its_own_clients`,
    `test_commands_harptabs.py::test_an_artist_pages_good_run_is_its_own_clients`);
  - two lookups of one song, one from a terminal beside serve's, interleave their writes to it by turns (serve never
    runs two jobs of a song): accepted (the spec's part 3);
  - a caracole that isn't in the lane, once it has the lock, lets go of it while the lane holds anyone and waits for
    it to empty, holding nothing (`_lane_empty`, `_wait_lane_empty`; asked now, announced, polling); a lock its
    process holds already is taken again of the outer one's kind;
  - a waiting lookup's `on_wait` is told whom it waits for after `WAIT_SAID` (1 s), its warning at once
    (test_commands_lane.py).
- `caracole versions --keep`, `--keep-more` and `--clear` (which writes overrides.toml under it) wait so too, and
  `--choose` through get; so do `caracole lyrics --song --pick`, `--record` and `--clear` (lyrics_pick.py).
- So does everything else caracole serve queues that the owner asked for just now, so a lookup queued behind it in
  serve's one-at-a-time queue never waits behind the whole run either: `add`, `remove`, `review`, `fetch --song`,
  `render --song`, `youtube --song` (`--sheet`, `--none`), `youtube --search` and `--video`, `transcribe` and `audio`
  (`test_commands_lock.py::test_lookups_take_the_lock_in_the_lane_what_the_owner_asked_for_now_as_a_lookup_and_bulk_work_neither`,
  `test_commands_audio.py::test_it_takes_the_lock_as_asked_for_now`,
  `test_web_jobs.py::test_a_lookup_queued_behind_an_add_never_waits_behind_the_whole_nightly_run`).
  - A process holding the lock as asked for now hands it to the lane's lookups alone (`hand_over`), at its hand-over
    points (a yt-dlp pause, a YouTube sheet, an audio file's sheet and a transcription before each of vocals, words
    and chords (`test_transcribe_job.py::test_the_lock_goes_to_a_waiting_lookup_before_each_long_stage`,
    `test_youtube_sheet.py::test_the_lock_goes_to_a_waiting_lookup_before_vocals_words_and_chords`), `fetch --song`'s
    pauses, `peer sync --push`'s wait for each push's take but the last: `commands/peer.py` `_handing_over`, a poll
    a second, so the lock goes a second at most without a hand-over point there), taking the gate only if it is free
    (held, it is the bulk work that let it in), and waits with a ticket
    of its own, written before it lets go, to
    take it back once the lane is empty; so bulk work that let it in gives it back at its next pause
    (`test_commands_lane.py::test_a_queue_job_lets_a_lookup_go_first_in_its_pause_and_gets_the_lock_back`,
    `::test_a_nightly_run_that_let_a_queue_job_in_gives_it_back_at_its_next_pause`). Another caracole asked for now
    usually waits for its end: one waiting while this one is away (a terminal's `caracole remove`, a `caracole-admin`
    command) may take the lock first once the lane is empty, as tickets outside the lane keep no order.
  - The phone has no lock and no nightly run, so its queue needs none of this.
- Every changing `caracole songbook` command (make, add, remove, move, set, rename, delete, render:
  commands/songbook.py) waits the same way, as a songbook is asked for now
  (`test_commands_songbook.py::test_a_change_waits_for_the_nightly_run_as_a_lookup_does_never_for_its_whole_run`).

#### Bulk work hands the lock over

- Bulk work hands the lock over (`_common.hand_over`, never inside a transaction): it lets go of the flock, takes it
  back last, once the lane is empty and no lookup waits (`HANDOFF_TAKE` bounding only a ticket nobody takes, never
  the lane's work: `test_commands_lane.py::test_the_nightly_run_takes_the_lock_back_only_once_the_lane_is_empty`),
  counts the handoff (`_common.handoffs()`), and goes on.
- That count is how everything below learns a lookup went first (a client's block and pace checks, the re-reads of
  songs and overrides.toml): it is the one way to let go of the lock mid-work.
- It hands it to lookups alone: meanwhile it holds the flock of `state_dir/caracole.lock.handoff`, and a caracole that
  isn't a lookup lets go of a lock it took during a handoff and waits for it to end (`_common._take_outside_handoffs`),
  so a `caracole-admin` command waiting for the run takes the lock after it, never in its middle
  (`test_commands_common.py::test_the_nightly_run_hands_the_lock_to_a_lookup_alone_never_to_another_command_waiting`).
- No deadlock: bulk work alone blocks holding a flock, its gate: on the lane's flock (`_wait_lane_empty`, the lane's
  work, however long), and then on the lock once the lane is empty. What the owner asked for now tries the gate
  without waiting, a lane lookup polls for the lock, and a `caracole-admin` command holds nothing while it waits.
- It does so in two places:
  - Its clients, and the yt-dlp runner of `make_youtube` between two runs, spend each pause looking for a waiting
    lookup (every `HANDOFF_SLICE` s), then pause a whole `delay` again
    (`test_commands_common.py::test_the_youtube_steps_pauses_hand_the_lock_to_a_waiting_lookup_too`).
  - Work that sends no request does it between two songs (a `between` callback): `autochords_pending`
    (commands/autochords.py) and `render_all` (pipeline.py's render step, commands/render.py).
  - UG's artist directory's client, which has no pause, between two batches of its requests, none in flight
    (ug/directory.py, the client's `between`: a block the lookup met is its too).
- A bulk caller holding state across a handoff re-reads it after one:
  - ug/fetch.py `fetch_songs` reads each song and overrides.toml again (`_Handoffs`; a song a lookup fetched mid-turn
    is fetched again next run);
  - lacuerda_fetch.py `lacuerda_sheets` reads each song and overrides.toml again and passes over a song no longer to
    try (`_Lookups`; after a handoff within a song's turn, it records what LaCuerda answered only for a song still to
    try with the pick the turn asked for:
    `test_lacuerda_fetch.py::test_a_tab_a_lookup_pinned_during_the_songs_own_turn_is_never_replaced`);
  - gtptabs_fetch.py checks a song still has no file before its turn;
  - every pass through provider_pass.py (LRCLIB, Megalobiz, AZLyrics, gtptabs.com, harptabs.com, gametabs.net,
    YouTube) reads each song again just before its turn (`as_now`), passing over one removed or no longer due
    (`test_megalobiz_fetch.py::test_a_song_a_sync_removed_in_the_passs_pause_is_passed_over`,
    `test_youtube_fetch.py::test_a_song_a_lookup_kept_a_human_sheet_for_in_the_passs_pause_is_left_alone`), and the
    three lyrics passes `[lyrics]` too (lyrics.py `Turns`), keeping an answer of a turn a pick or a clear came in only
    for a song still asked so;
  - and `autochords_pending` and `render_all` read each song after and overrides.toml again;
  - what comes after reads overrides.toml again too (`_common.overrides_since`): the run's next steps,
    `StepContext.read_overrides_again`; the songbooks and pages of `caracole render` and `autochords`; the pages of
    `caracole fetch`, `youtube`, `icons` and commands/lyrics.py's `_provider_pass`.
  - `test_lacuerda_fetch.py::test_a_tab_a_lookup_pinned_during_an_earlier_step_is_never_replaced_by_lacuerda`,
    `test_commands_common.py::test_the_nightly_run_hands_the_lock_to_a_lookup_during_its_pause`,
    `test_autochords_run.py::test_a_lookup_waiting_for_the_lock_takes_it_between_two_songs`.

#### `serve` never takes it

- It reads like `search` and appends to wanted.txt like `add`, and runs every other change as a `caracole` command in
  a child process, since the lock is re-entrant within a process and its threads would share it: one at a time in the
  queue, and up to `LANE` lookups beside it, which take turns with the lock (web/jobs.py; `CaracoleRunner` keeps a
  process a running command, and `JobQueue.stop` ends them all, each request `INTERRUPTED`, a command asked after it
  starting none).
- A removal too, `caracole remove --yes`, once the line's five seconds with Undo are over (the library page's script;
  without it, a page of its own), having asked what goes (`removal.plan_removal`, which only reads, and
  `removal.brief`); its job's song key is `remove:<key>` (`jobs.REMOVING`), so it never joins the song's add or fetch.
- Beyond wanted.txt, the one thing it writes is its own request history, `state_dir/requests.jsonl`
  (web/history.py), no table of caracole.sqlite:
  - a file no command reads or writes, whose one writer is caracole serve's queue, under the queue's own lock
    (`JobQueue._save`), so it needs caracole's lock no more than wanted.txt does, and the database keeps its rule that
    every change to it is a caracole command's;
  - a line a request appended in one write as it changes;
  - written again whole (a temporary file, synced, renamed over it) when it starts and when it grows past three lines
    a request kept or `MAX_BYTES`;
  - a line it can't read skipped;
  - the last `jobs.KEEP` (100) requests of `DAYS` (30) read back, the next ids after theirs, one that waited or ran
    then `INTERRUPTED`, as is one the server ends as it stops (`JobQueue.stop`): over, Try again queues it
    (test_web_history.py).
- It also writes, for the phone's sync alone, and nothing else: a push's staging folder (`state_dir/peer/push-<id>/`,
  0700, its files checked by their SHA-256, deleted once `caracole peer take` is over or an hour after, or a push never
  sent at once, dropped by its pusher, `POST /peer/push/drop`, or let go of as its sender opens another); a
  temporary index export for `GET /api/peer/index` and `POST /peer/index/newer`'s part of it (`cache_dir/peer/`,
  `index-<16 hex>.sqlite`, one read transaction, no lock, one at a time, deleted once open to be sent; one a killed
  process left swept an hour after, with `peer_push.sweep_copies`' copies, as the next one is made); and the index
  pages a phone's lookups read, `POST /peer/index`'s export of them
  (`state_dir/peer/index-<16 hex>.sqlite`, 0600, at most `peer_push.INDEX_OPEN` waiting, read before its 202 as an
  export of pages alone of this caracole's version, `index_transfer.check_pages`, deleted when it isn't, then
  `caracole index merge --delete --progress` queued, which deletes it once merged or refused (the phone forgets those
  pages only once that request ends done), and `--delete` deletes a refused file of that staging alone, never one
  named by hand; one an hour old no waiting request names is swept, `peer_push.sweep_indexes`).
- And for Export and Import a file (sync_file_routes.py), nothing else: an export's file
  (`cache_dir/peer/export-<16 hex>.caracole`, 0600, one made at a time, its units from one read transaction and its
  indexes from one of their own, no lock; one waits to be sent at most, the one before it deleted as the next is made;
  deleted once it is open to be sent, or an hour after if never asked, a part a killed process left swept only while
  no export is made); and a file to import's staging folder (`state_dir/peer/import-<16 hex>/`, peer_import.py:
  0700, its `file.caracole` and `open.json` 0600, one at a time, each part 8 MiB at most and the next one, 8 GiB in
  all), deleted once its import has taken it with nothing left, refused at its comparison or its import (it can't be
  read whole, another format, this library's own export, its songs keyed by other rules, a document of it unreadable,
  nothing newer in it), dropped (`POST /sync/import/drop`), let go as another is opened when no request names it and
  it is whole or its upload stopped (`peer_import.let_go`, `STOPPED`), or an hour after its last part, unless an
  import holds it; every other end of an import keeps it, its hold let go and its hour run from that end
  (`peer_import.kept`), for the page's Compare again: `STALE`, a `--choose` of no difference, a unit left, its indexes
  not merged, this library unreadable, a "Go on?" answered no, a bug.
- And for a sheet from an audio file (audio_routes.py), nothing else: an upload staged in `state_dir/audio/`
  (audio_store.py: 0700, `.upload-<16 hex><ext>` and its `.upload-<id>.json` 0600, one no job names at a time, 128 MiB
  at most), which `caracole audio --upload` moves into place as the song's audio, dropped (`POST /audio/drop`), let go
  as another is staged, or swept an hour after unless a waiting or running job names it; nothing is served back from
  the folder. Everything else stays a queued command's.
- The copies of the indexes the queued `peer sync` and `peer import` work on are theirs, in `cache_dir/peer/`
  (`sync-indexes-`, `give-indexes-`, `import-indexes-<12 hex>.sqlite`, an export's `.part` and SQLite's `-journal`,
  `-wal` and `-shm` beside them): deleted once merged or given, and, one a killed command left, swept an hour after
  its last write (`peer_push.sweep_copies`: those names alone, regular files, no link followed) as either command
  starts and as `GET /api/peer/index` comes, never while its command holds it (`peer_push.holding_copy`, an flock
  from the end of its download, its export or its copy out of the file until its merge or upload is over, gone
  with a killed process).

### wanted.txt is the one source of songs

- `sources.sync_sources` syncs it alone, and a song's album, duration, ISRC and variant are what its line says now,
  kept in its record alone (`songs.upsert_song`;
  `test_songs.py::test_a_song_keeps_what_its_line_says_in_its_own_record_alone`).
- wanted.py's writers: `append_wanted` (a line added), `remove_wanted` (a song's lines taken out) and
  `retime_wanted`, autochords/remeasure.py's alone: a song's length rewritten on each of its lines that is byte for
  byte what `format_line` writes with the length caracole once guessed for an MP3 that names none (`caracole audio`'s
  line, or a hand-typed one the very same), the rest of the file as it was; it reports only the lines it wrote. So
  the re-check, once, may correct a line's length, and the record follows it as from any line; the song's sync unit
  then changes and goes to the other side at the next sync.
