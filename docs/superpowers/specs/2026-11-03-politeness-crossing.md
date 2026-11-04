# Two caracoles' politeness, and what crosses between them

docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, §4, as the owner settled it on 2026-11-03. Lanes
crossing-computer (the computer's side), crossing-phone (the phone's) and index-push.

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

`GET /api/peer/state` gains a `settings` member (`politeness.settings_document`; readers ignore unknown keys, so the
sync's FORMAT does not move for it):

```json
"settings": {"name": "<caracole.toml's name or null>", "user_agent": "…",
             "providers": {"<provider>": {"enabled": true, "lookup_delay": [0.125, 0.375], "lookup_requests": 6,
                                          "lookup_per_hour": 60, "per_day": null}},
             "match": {"accept": 90, "margin": 8, "review": 75, "artist_gate": 90},
             "rank": {"coverage_threshold": 0.8, "line_match": 85, "prior_votes": 10, "scored_sheets": 3,
                      "label_penalty": 0.5, "variant_bonus": 0.25}}
```

- `providers`: every provider of the computer's config, its switch and its lookup settings (a lookup's alone: the
  phone never does bulk work).
- `match` and `rank`: the computer's `[match]` and `[rank]`, since a match decision is in the song unit's digest and
  the phone must match with the computer's thresholds.
- `user_agent`: caracole.toml's, else `config.DEFAULT_USER_AGENT`: sites see caracole's own user agent from the phone
  too.

The phone keeps it as kv `phone:settings` (PyJson text), taken in the sync's agree stage (`PhoneConfig.take`), and
`PhoneConfig.read(db)` lays it over `data/caracole/config/config.json`'s defaults (config.py's, written by
`tests/test_conformance_config.py`). The phone never sends settings back.

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
