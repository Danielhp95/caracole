# Two caracoles' politeness, and what crosses between them

docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, §4, as the owner settled it on 2026-11-03. Lanes
crossing-computer (the computer's side), crossing-phone (the phone's) and index-push.

Status: built (milestone 4, 2026-11-10), as this spec says, and nothing more:

- the settings document, `politeness.settings_document` in `GET /api/peer/state`'s `settings`, taken by the phone's
  sync in its agree stage (`SyncEngine.takeSettings`, `PhoneConfig.take`) and read for each lookup's clients, the
  cards and the pages' name (`PhoneConfig.read`); vectors/sync/settings.jsonl and settings_take.jsonl;
- the index push: `core.index.Reads`, the sync's index stage, `POST /peer/index` and `caracole index merge --delete
  --progress`;
- no politeness crossing: no schema change (15), no health document, no `POST /peer/health`. The end to end holds
  it (tests/test_android_e2e.py, steps 10 and 14): a 403 cools Ultimate Guitar on the phone alone, and the
  computer's `events`, pace, health and lookup records are the same before and after each sync. A restore on the
  phone keeps its own politeness records as they are (core.backup's `OwnRecords`).

## Each caracole's politeness is its own

The owner's choice ("Don't share between devices", then "Don't do the polite request across 2 devices"): a phone and
a computer each keep their own limits, request counts (`events`), cooldowns (`provider:<name>`), pace
(`http:last_request:<provider>`) and the kv records that gate a request (LaCuerda's searches and their failures,
Megalobiz's day, the 30-day checked records, `ug:artist_url:`, `ug:pasted_tab:`), entirely to themselves. Nothing of
them crosses at a sync, either way:

- no schema change: `events` has no origin, and the schema stays 15;
- no health document, no `POST /peer/health`, no `caracole peer health`;
- a block met on one side cools that side alone.

So two caracoles at one address may together send a site more than either one's limits (each its `lookup_per_hour`,
Megalobiz's `per_day`, LaCuerda's 20 searches an hour). Each still keeps every Politeness and "Errors are never
misses" invariant of AGENTS.md on its own, with caracole's own user agent. The phone looks songs up at the lookup pace
alone, so it adds little.

## Settings (computer to phone)

`GET /api/peer/state` gains a `settings` member (`politeness.settings_document(cfg)`, web/peer_routes.py; readers
ignore unknown keys, so the sync's FORMAT does not move for it, and a computer syncing with another passes over it):

```json
"settings": {"name": "<caracole.toml's name or null>", "user_agent": "…",
             "providers": {"<provider>": {"enabled": true, "lookup_delay": [0.125, 0.375], "lookup_requests": 6,
                                          "lookup_per_hour": 60, "per_day": null}},
             "match": {"accept": 90, "margin": 8, "review": 75, "artist_gate": 90},
             "rank": {"coverage_threshold": 0.8, "line_match": 85, "prior_votes": 10, "scored_sheets": 3,
                      "label_penalty": 0.5, "variant_bonus": 0.25}}
```

Its members, in this order, each value as config.py holds it:

- `name`: caracole.toml's `name`, a string, or null when it names none (`Config.library_name` then falls back to the
  computer's folder, and the phone's folder is its own: it keeps its own name).
- `user_agent`: caracole.toml's, else `config.DEFAULT_USER_AGENT`: sites see caracole's own user agent from the phone
  too.
- `providers`: every provider of the computer's config, in config.py's order (`DEFAULT_PROVIDERS`), each with its
  switch and a lookup's settings alone, `politeness.LOOKUP_FIELDS`: `enabled` (a boolean; true for a provider
  caracole.toml can't turn off), `lookup_delay` (`[min, max]` seconds, two floats: `[0.0, 0.0]` for caracole.toml's
  `[0, 0]`), `lookup_requests` and `lookup_per_hour` (integers), `per_day` (an integer or null; caracole.toml can't
  set it). Never a run's `budget` or `delay`: the phone never does bulk work.
- `match` and `rank`: the computer's `[match]` and `[rank]`, every field in `MatchPolicy`'s and `RankPolicy`'s
  order, since a match decision is in the song unit's digest and the phone must match with the computer's
  thresholds. A number is as config.py holds it: the defaults' as `MatchPolicy` and `RankPolicy` write them
  (`accept` 90, an integer, though the field is a float), and caracole.toml's as it gave them, an integer or a float
  for every field but `scored_sheets` (a whole number): `line_match = 82.5` and `prior_votes = 2.5` too, though
  their defaults are integers, and `coverage_threshold = 1`, an integer.

Never a folder, a program (`chordpro_bin`, `ytdlp_bin`), ntfy's topic or anything of the computer's own politeness.

The phone keeps it as kv `phone:settings` (PyJson text), taken in the sync's agree stage (`PhoneConfig.take`), and
`PhoneConfig.read(db)` lays it over `data/caracole/config/config.json`'s defaults (config.py's, written by
`tests/test_conformance_config.py`): each provider the phone knows takes the document's five fields and keeps its
defaults' `budget` and `delay`; `user_agent`, `match`, `rank` and `name` are the document's. A provider the document
names that the phone doesn't know (a newer computer's) is passed over, and one it doesn't name (an older computer's)
keeps its defaults. A state with no `settings` leaves `phone:settings` as it was. The phone never sends settings back.

The vectors are `tests/conformance/vectors/sync/settings.jsonl` (tests/test_conformance_sync.py): for each
caracole.toml of `SETTINGS` (`args[0]`, its text), `out` the document, and `phone` what `PhoneConfig.read` answers once
it is taken, in config.json's shape (its `switchable` aside) with `name`, made from the config, never the document.
What no caracole.toml can show, since a computer's document always names every provider of its config, is
`tests/conformance/vectors/sync/settings_take.jsonl`: the take rule by rule (`SETTINGS_TAKES`, each record's `case`),
`args` `[kept, settings]` (the kv `phone:settings` before, a document or null, and the state's `settings`, null when
the state has none), `out` `{kept, read}` (the kv after: the document as given, unknown providers and all, or the one
kept when the state gives none; and what `PhoneConfig.read` answers then, in `phone`'s shape). Its cases: nothing
taken yet; a state with no settings keeps the last take; a second take replaces the first whole; a newer computer's
provider is passed over; a provider an older computer's document doesn't name keeps the defaults, never an earlier
take's. Its `out` is `phone_takes`', this rule as a model, which a test holds to `phone` on every document of
settings.jsonl.

## The phone's index reads go to the computer

The pages the phone's lookups store in an index (UG's artist pages, LaCuerda's artist pages and search rows,
harptabs.com's artist pages) are noted as they are stored (`core.index.Reads`, kv `phone:read:<site>:<page>`), and the
sync's index stage, after the computer's newer indexes are merged, exports those noted since the last push to that
computer (`phone:pushed:<peer id>`) as `index_transfer.export(pages=)` does and posts them:

- `POST /peer/index` (body `bytes`, at most 64 MiB, the form token), staged as `state_dir/peer/index-<16 hex>.sqlite`,
  and `caracole index merge FILE --delete --progress` queued (web/jobs.py `index_merge_job`, a job of no song's, its
  one stage `merge`), answering `202 {"job": N}`;
- merged by index_transfer's rules: a LaCuerda page or search row the computer already has stays the computer's.

What stays each side's own besides politeness: the HTTP cache, `run:last`, every `*:keys` record.
