# Plan: the site catalogues for phones with no computer

Goal: someone installs caracole from F-Droid and gets offline search without running caracole on a
computer. Visual companion: https://claude.ai/artifact/6UYpwC1MuigC6CDBJ8TQt2

Revised 2026-11-24, after checking the first plan against the code, GitHub's API and its robots.txt, and
once more after the owner's three decisions below. What the review changed is listed at the end.

## Decided (2026-11-24)

1. **How the phone asks GitHub: its REST API.** github.com's robots.txt closes `/*/*/download/*`, which
   matches `releases/download/indexes/…`, and AGENTS.md allows no such URL but YouTube's. `api.github.com`
   and the host it redirects a download to have no robots.txt. The API's list of the release's files is the
   manifest, so there is no manifest and no swap. Its cost: GitHub answers an address 60 requests an hour
   without a login, shared with every other app behind that address; a download takes 2.
2. **What of your own use the file shows.** The public file leaves out the database's path
   (`caracole_export.source`, and any path of this machine is refused) and what LaCuerda's search answered
   you (`lacuerda_index` rows of page `busca.php`). It keeps the artist pages caracole read (UG's,
   LaCuerda's): they find a bare-id tab, and UG's directory pass reads every bare artist's page anyway.
3. **Who uploads.** The owner's own user, with a systemd user timer and the `gh` login they already have. No
   token file, no upload unit, no agenix; the module still loads no credential.

## Decided (owner, 2026-11-24)

- Published on GitHub, in this repo, in one fixed release, tag `indexes`. Never `releases/latest`.
- Every site the export carries: UG, LaCuerda, gtptabs.com, MuseScore, harptabs.com, gametabs.net
  (`index_transfer.SITES`; iReal Pro's index is the computer's alone).
- gzip, read by Android's own `java.util.zip.GZIPInputStream`: no new dependency.
- No `--clobber`: no file a phone may be reading is replaced in place.
- The schema in the file's name and in the file, so the phone says plainly when a file isn't for it.

## Don't bundle them in the APK

- The laptop's database is 426 MB, most of it the site indexes.
- The F-Droid repo is `docs/fdroid/` on GitHub Pages, in git: no file over 100 MB, no site over 1 GB.
- The indexes go stale in weeks; bundling means an app release for every refresh.

## What was measured (a copy of the Oct 30 local database, not the service's)

- `index export` already leaves out the FTS tables and secondary indexes, and the phone's merge fills them
  through the triggers: no `--no-fts`, no rebuild step. `--site` exists.
- Six sites, 1.37 M UG rows: 170 MB raw, **52 MB gzip -9** (zstd -19: 37 MB, with a library).
- The phone merges 300,000 rows in 7.6 s (docs/android_port.md): the whole index in about half a minute.
- Estimated on the phone; Task 0's measurements are pending: about 450 MB kept (the database with its FTS tables), about
  1.2 GB free while it imports (the unpacked file, the database, its WAL). A first sync with a computer costs
  the same today.
- The repo has no release yet, and its APKs are in `docs/fdroid/`, so nothing else uses the releases.

## The file

`indexes-s<schema>-<UTC time>.sqlite.gz`, as `indexes-s17-20261124T0312Z.sqlite.gz`: an index export of every
site, less what "Decided" 2 leaves out, vacuumed, `PRAGMA quick_check`ed, gzip -9 with no time in its header.
A name is used once. The schema is in the name and in `caracole_export.schema`, which the merge already checks.

## The release

```
indexes  (a tag and its release, marked not latest, kept for good)
├─ indexes-s17-20261124T0312Z.sqlite.gz   this week's
├─ indexes-s17-20261117T0310Z.sqlite.gz   the one before, a week more
└─ indexes-s16-20261103T0309Z.sqlite.gz   the last of an older schema, for apps not updated yet
```

- Files are only added and deleted, never renamed or replaced. A phone sees a file only once GitHub holds it
  whole (`state: uploaded`), with the SHA-256 GitHub computed (`digest`).
- Kept: of each schema the newest file for 180 days; of the laptop's schema the one before it too.
- The repo's "immutable releases" setting stays off: it forbids adding a file to a published release.

## Publishing, on the laptop

Two timers, weekly, since the database is the service's and the login is yours.

1. **The service's** (nix/module.nix, `services.caracole.publish.enable`, off by default; user `caracole`, the
   units' sandbox, no network): `caracole index publish /var/lib/caracole/publish`.
   - One read transaction, no lock, as `index export`.
   - Refused, exit 1 (the unit's ntfy alert), when UG's index isn't built whole, or when a site holds a tenth
     fewer rows than the last file made (`published.json` in that folder: the last file's name, SHA-256 and
     rows; `--force` for a real shrink).
   - Refused on a machine whose service has another database (`builds_index`'s rule, `--home` aside): never
     the home folders' stale index by mistake.
   - The folder is mode 2750, group `caracole` (you are in it); it keeps the newest file alone.
   - caracole uploads nothing and reads no secret.
2. **Yours** (nix_config, a systemd user timer; the script in this repo, `nix/publish-indexes.sh`, a flake
   package, tested against a fake `gh`):
   1. delete from the release any file not `uploaded` (what a failed run left);
   2. `gh release upload indexes FILE`, which refuses a name that exists; the release made first if missing
      (`--latest=false`);
   3. read the file's entry back: its size and `digest` are the local file's, else delete it and exit 1;
   4. delete what "Kept" no longer keeps.

A failure anywhere leaves the release listing only whole files, the last good one among them. There is no
moment when a phone finds nothing.

After a schema bump: update the laptop's service and run both by hand once, before releasing the app
(android/README.md's Release steps), so a new app finds a file of its schema.

## The phone

- **Where it asks** (core.catalogues, the one place that knows GitHub's API):
  1. `GET https://api.github.com/repos/Danielhp95/caracole/releases/tags/indexes`: the files' names, sizes,
     states and digests;
  2. `GET …/releases/assets/<id>` with `Accept: application/octet-stream`, which redirects to
     `release-assets.githubusercontent.com`; a redirect to any other host is refused.
  caracole's user agent, https only, never a tab site. A 403 or 429 with no requests left says when to try
  again (`x-ratelimit-reset`) and is kept (kv `catalogues:not-before`), so the app doesn't ask before then.
- **A streamed GET** in core.http: `RealTransport` reads a body whole into memory. Kept to loopback under
  `caracole.network=loopback`, as every transport.
- **The job** (PhoneKinds `catalogues`, one stage, in the foreground service, one at a time):
  1. the release's files; of those named as above and `uploaded`, the newest of this app's schema;
  2. the same as the last one imported (kv `catalogues:imported`): "Up to date", nothing downloaded;
  3. room checked first: about 23 times the download (measured in step 1);
  4. streamed through `GZIPInputStream` into `stateDir/cache/catalogues/`, the `.gz` bytes hashed as they
     come; stopped past 20 times the download's size (a file that unpacks without end);
  5. the SHA-256 is GitHub's `digest`, and gzip's own check passes;
  6. `IndexTransfer.merge`, as a sync's index stage calls it (its clock as `notAfter`), then the WAL
     checkpointed, the search's answers forgotten, the file deleted.
- **What it says when it can't**, each before anything is downloaded where it can:
  - only newer schemas: "The published catalogues are for a newer caracole (schema 18): update the app.";
  - only older ones: "The published catalogues are for an older caracole (schema 16): new ones are on
    their way.";
  - the file's own schema isn't its name's: "This file is for schema 16; this app reads 17. Nothing was
    imported." (the merge's refusal);
  - a site in the file this app doesn't know (read from `caracole_export.sites`): imported, and said: "It
    also holds iReal Pro's, which this version doesn't read. Update the app to search it.";
  - no room, no release yet, GitHub's hourly share spent, a download that doesn't check out.
- **Where it shows** (native, `:app`; the shared library page is untouched):
  - Settings: "Site catalogues · of 24 Nov 2026 (3 weeks old)" and **Download the site catalogues**. No
    request until it is tapped;
  - first start, with no computer set and no index: asked once, with the sizes ("52 MB to download, about
    450 MB on the phone"); asked again before a download on mobile data.
- A second download merges only what is newer. Fetch still asks the sites from the phone, as now.

## Schemas, and new sites

- **The schema moves often** (17 in five weeks), and the merge takes its own schema alone. So the release
  keeps each schema's last file: an app that isn't updated keeps finding its own, and only goes stale.
- **A new site with new tables** bumps the schema: the case above.
- **A site added to the export with no bump**: the merge passes over a site it doesn't know; the phone now
  says so.
- **A site gone from the file**: the phone keeps its rows; a merge removes none.
- **The export's own layout changing** (`FORMAT`, 1 since the start): a new name, `indexes2-…`, so old apps
  don't download a file they can't read.
- Later, not now: a file of another schema whose tables have this app's columns could merge (the columns
  check exists). The rule is held by the corpus on both sides, so it is a change of its own.

## Known limits

- **`KEY_VERSION`**: a file keyed by another normalizer merges, as at a sync today; the phone makes again the
  keys it can. `ug_index`'s come from the laptop's sitemaps.
- **Trust** is GitHub's account and TLS, as for the APK. The merge reads the file as anyone's (tables alone,
  no trusted function). A file someone else put there could give wrong addresses, nothing more.
- **No resume**: a download cut short starts again. Later, with Range.
- **F-Droid**: the repo is ours. The download is data, at a tap, so the rule on downloaded binaries doesn't
  apply. On the official F-Droid a NonFreeNet label for GitHub is possible.

## Steps

1. Measure, with no new code: `sudo caracole-admin index export`, gzip -9; then Import a file (`.sqlite`) on
   the phone: time, room while it imports, room kept.
2. `caracole index publish DIR` (commands/index.py; its rules in index_transfer.py), with tests; the names
   as a conformance vector (`vectors/index/`), which the Kotlin name reader replays.
3. `nix/publish-indexes.sh` and its test with a fake `gh`: a failed upload left behind, a digest that
   differs, the pruning.
4. nix/module.nix: `publish.enable`, its timer and folder; module-check.nix; nix_config: your timer.
5. Phone: core.http's streamed GET; core.catalogues (names, the API's answer, the download, the checks),
   tested against a fake GitHub on loopback: no release, a file half uploaded, each schema case, hourly
   share spent, a redirect elsewhere, a wrong digest, a file cut short, one that unpacks without end,
   another schema inside, a site it doesn't know, no room.
6. Phone: the `catalogues` kind and its words (JobViewsTest), its runner, Settings' row, the first-start
   question; a device test through device-test.sh.
7. Docs, in the same commits: usage.md (`index publish`), phone.md and android/README.md (catalogues without
   a computer; the Release step), sources.md (the catalogues are published; what they hold), deploy.md (the
   timer, or that Ubuntu has none), AGENTS.md (Politeness: the phone asks api.github.com at a tap; the
   exports' "caracole itself sends it nowhere" stays true, the owner's timer publishes; the module's publish
   unit; android/'s new parts).
8. The first publish by hand; the download from a phone with no computer set.

## What the review changed

- The phone asks GitHub's API, not `releases/download`: robots.txt, and no manifest to swap. The first plan's
  swap could leave no manifest for a week if a run died between its two renames.
- The public file leaves out the database's path and your LaCuerda searches.
- No token: your `gh` login in a user timer; the service's timer only writes the file.
- `index publish` refuses the wrong database, an index not built whole, and a sudden shrink.
- Each schema's last file is kept 180 days, since the schema moves often.
- The phone checks room first, caps what it unpacks, and says which sites it passed over.
- One stage in PhoneKinds, as its other kinds; the offer is native, the shared page untouched.
- Stamps to the minute in names, so two publishes in a day don't collide.
