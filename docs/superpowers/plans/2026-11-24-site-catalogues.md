# Site Catalogues Without a Computer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The laptop adds a gzip index export to the fixed GitHub release `indexes` each week; a phone with no
computer downloads the one of its schema at a tap and merges it, so it searches every site offline.

**Architecture:** `caracole index publish` writes the public file (an index export, cleaned, gzip -9, a sidecar of
its SHA-256 and rows); a shell script uploads it, checks GitHub's digest and prunes; the phone's
`core.catalogues` lists the release, picks its schema's newest file, streams it through `GZIPInputStream`, checks it
and hands it to the merge a sync already uses, as a phone job of its own kind.

**Tech Stack:** Python 3.14 (typer, sqlite3, gzip), bash + `gh`, Nix (module, flake package), Kotlin (`:core`,
`:server`, `:app`), `java.util.zip`.

**Spec:** `plan_host_index.md` (read it first: its "Decided" section settled this plan's three switches).

## The three switches

The spec leaves three decisions to the owner. This plan builds both sides where they differ in code, behind one
named switch each, and each task says which switch it reads. Settling a switch is a one-line change plus deleting
the losing branch and its tests (Task 9).

| Switch | Where it lives | Values | Default while open |
|---|---|---|---|
| **S1: how the phone asks** | `CatalogueSource` (Kotlin, Task 5), chosen in `Assembly` | `Api` (api.github.com release listing) / `Download` (`releases/download/indexes/indexes.json` manifest) | `Api` |
| **S2: what the public file leaves out** | `index_transfer.PUBLIC_OMIT` (Python, Task 1) | a tuple of `Omit` rules | the spec's: `source` meta, LaCuerda `busca.php` rows |
| **S3: who uploads** | `nix/publish-indexes.sh`'s auth (Task 3), the module option (Task 4) | `gh` login of the user running it / `GH_TOKEN_FILE` read by a system unit | `gh` login, user timer |

S1 is the only switch that changes the shape of what is published: `Download` also needs `indexes.json` and its
rename swap (spec "Plan B"). Tasks 2 and 3 write the manifest entry and the swap behind `--manifest`, so both
sides are tested; the phone's `Download` source reads it.

## Global Constraints

- Release tag `indexes`, marked not latest (`--latest=false`); never `releases/latest`.
- File name `indexes-s<schema>-<yyyymmdd>T<hhmm>Z.sqlite.gz`, UTC, e.g. `indexes-s17-20261124T0312Z.sqlite.gz`.
  A name is uploaded once; nothing is replaced in place, no `--clobber`.
- Every site of `index_transfer.SITES`: ug, lacuerda, gtptabs, musescore, harptabs, gametabs.
- gzip -9 with `mtime=0` and no file name in the header; the phone reads it with `java.util.zip.GZIPInputStream`.
  No new Gradle or Python dependency.
- Keep: of each schema its newest file for 180 days; of the publishing schema also the one before it.
- The phone: caracole's user agent; https only; a redirect followed only to `release-assets.githubusercontent.com`
  (S1 Api) or `objects.githubusercontent.com`/`release-assets.githubusercontent.com` (S1 Download); no tab site.
- Unpacked bytes capped at 20 × the `.gz` size; room needed before download: 23 × the `.gz` size (spec estimate,
  re-measured in Task 0 and stored as `Catalogues.ROOM_FACTOR`).
- caracole reads no secret; the module loads no credential unless S3 is set to the token file.
- AGENTS.md rules hold: test first; never a live request in a test (Python `httpx.MockTransport`/fake `gh`;
  Kotlin `caracole.network=loopback`, every client calls `RealTransport.refuseUnderTests(url)` before a socket);
  docs in the same commit as behaviour; corpus regenerated with any change the Kotlin side ports.

## Review Focus

1. **A release with a half-uploaded file** (`state: "starter"`/`"new"`): the phone must pass over it, never
   download it. Test in Task 5 (`passesOverAFileNotUploaded`).
2. **The phone's clock or GitHub's list ordering**: "newest" must come from the file name's stamp, never list
   order or `created_at`. Test in Task 5 (`newestIsByTheNamesStampNotTheListsOrder`).
3. **A schema with no file but an older one present, and a newer one present**: the words must say the newer
   case when both exist (update the app wins over "on their way"). Test in Task 5 (`aNewerSchemaIsSaidBeforeAnOlderOne`).
4. **A merge that fails after the download**: the downloaded file is deleted and `catalogues:imported` is not
   written, so the next tap tries again. Test in Task 6 (`aRefusedMergeLeavesNothingImported`).
5. **The laptop publishing twice in a minute** (a retry by hand): the second name collides; `publish` must refuse
   an existing name and the script must refuse an asset name that exists, never overwrite. Tests in Task 2
   (`test_publish_refuses_a_name_that_exists`) and Task 3 (`an_existing_name_is_refused`).

---

### Task 0: Measure (no code)

**Files:** none committed but the spec's numbers.

- [ ] **Step 1:** `sudo caracole-admin index export /var/lib/caracole/m.sqlite`, then `gzip -9 -n -k`; note both
      sizes and each site's rows (the command prints them).
- [ ] **Step 2:** Copy the `.sqlite` to the phone; Settings › Import a file; note the import's time, free space
      lowest during it (`adb shell df /data` every second), and `stateDir` size after.
- [ ] **Step 3:** Write the three numbers into `plan_host_index.md`'s "What was measured", replace "Estimated" with
      "Measured", and set `ROOM_FACTOR` (Task 5) to `ceil(lowest free used / gz bytes)`.
- [ ] **Step 4:** Commit: `docs: the site catalogues' sizes, measured on the service and the phone`.

---

### Task 1: The public export (S2)

**Files:**
- Modify: `src/caracole/index_transfer.py` (add `Omit`, `PUBLIC_OMIT`, `export(..., omit=)`)
- Test: `tests/test_index_transfer.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Omit: table: str; where: str` (an SQL condition on that table's rows;
    `table == META` with `where` naming a key drops that meta key).
  - `PUBLIC_OMIT: tuple[Omit, ...] = (Omit(META, "key = 'source'"), Omit("lacuerda_index", "page = 'busca.php'"))`
    — **S2 lives here**: to keep a thing, remove its rule; to drop UG artist pages, add
    `Omit("ug_artist_tabs", "1")`.
  - `export(conn, path, sites=None, *, now, pages=None, omit: Sequence[Omit] = ()) -> Exported` — rows matching an
    `Omit` are deleted from the written file before its rename, then `VACUUM`; `Exported.rows` counts after.
  - `omit` with `pages` is a `TransferError("an export of pages omits nothing")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_public_export_holds_no_source_and_no_lacuerda_search_rows(conn, tmp_path):
    seed_lacuerda(conn, [("a/x", "a/"), ("b/y", "busca.php")])   # helper beside the file's others: (path, page)
    out = index_transfer.export(conn, tmp_path / "p.sqlite", now=NOW, omit=index_transfer.PUBLIC_OMIT)
    f = sqlite3.connect(out.path)
    assert "source" not in dict(f.execute("SELECT key, value FROM caracole_export"))
    assert [r[0] for r in f.execute("SELECT path FROM lacuerda_index")] == ["a/x"]
    assert out.rows["lacuerda_index"] == 1

def test_an_export_of_pages_omits_nothing(conn, tmp_path):
    with pytest.raises(index_transfer.TransferError, match="omits nothing"):
        index_transfer.export(conn, tmp_path / "p.sqlite", now=NOW, pages={"lacuerda": ["a/"]},
                              omit=index_transfer.PUBLIC_OMIT)

def test_a_public_export_merges_as_any_export(conn, other_conn, tmp_path, cfg):
    out = index_transfer.export(conn, tmp_path / "p.sqlite", now=NOW, omit=index_transfer.PUBLIC_OMIT)
    assert index_transfer.merge(other_conn, out.path, state_dir=cfg.state_dir, now=NOW).sites
```

(`other_conn`: a second migrated database; use the fixture the file's merge tests already use.)

- [ ] **Step 2:** `nix develop -c pytest -q tests/test_index_transfer.py -k "public or omits"` → FAIL (`omit`
      unexpected keyword).
- [ ] **Step 3:** Implement `Omit`, `PUBLIC_OMIT`, `export(omit=)`. Apply the deletes on the `.part` file after
      `_write_export`, inside the same `try`, then `VACUUM`; table names come only from `Omit`, never input.
- [ ] **Step 4:** Run the file → PASS; `nix develop -c pytest -q -m "not slow"` → PASS.
- [ ] **Step 5:** Commit: `feat(index): an export that omits what a public copy shouldn't hold`.

---

### Task 2: `caracole index publish DIR`

**Files:**
- Create: `src/caracole/catalogues.py` (the file's name, its gzip, its sidecar, the manifest; standard library
  alone; no import of httpx)
- Modify: `src/caracole/commands/index.py` (the command)
- Test: `tests/test_catalogues.py`, `tests/test_commands_index.py`
- Create: `tests/test_conformance_catalogues.py` → `tests/conformance/vectors/catalogues/names.jsonl`
- Modify: `docs/usage.md` (the command)

**Interfaces:**
- Consumes: `index_transfer.export(..., omit=PUBLIC_OMIT)` (Task 1).
- Produces (`caracole.catalogues`):
  - `PREFIX = "indexes"`; `name_for(schema: int, at: datetime) -> str` →
    `"indexes-s17-20261124T0312Z.sqlite.gz"`.
  - `read_name(name: str) -> Named | None`, `@dataclass(frozen=True) class Named: schema: int; at: datetime`;
    None for any other name (`.next`, `.json`, `indexes2-…`, a bad stamp).
  - `@dataclass(frozen=True) class Published: name: str; schema: int; made: str; bytes: int; raw_bytes: int;
    sha256: str; rows: dict[str, int]` with `as_json() -> dict` (keys: `file, schema, made, bytes, raw_bytes,
    sha256, sites`), `sites` being each site's first table's rows.
  - `publish(conn, folder: Path, *, now: datetime, last: Published | None) -> Published`: export to a temp file in
    `folder`, `PRAGMA quick_check`, gzip -9 `mtime=0` streaming 1 MiB chunks while hashing, rename into place,
    write `published.json` (`as_json()`), delete the folder's older `indexes-*.sqlite.gz`. Refuses
    (`PublishError`, nothing left behind):
    - the name exists in `folder`;
    - `ug:index:built_at` absent ("UG's index isn't built whole yet");
    - any site's rows below 0.9 × `last`'s for that site ("<site> holds 9,100 rows, a tenth fewer than the
      last file's 12,000: --force publishes it").
  - `published(folder) -> Published | None` reads `published.json`.
  - `manifest_with(manifest: dict | None, new: Published, *, keep_days=180, now) -> dict` (S1 `Download` only):
    `{"format": 1, "files": [...]}`, the new entry first, the kept ones by the Keep rule.
  - `kept(names: Iterable[str], *, schema: int, now: datetime, keep_days=180) -> set[str]`: the Keep rule, one
    function the script (via `caracole index publish --kept`) and `manifest_with` share.
- Command: `caracole index publish DIR [--force] [--manifest FILE] [--kept NAME...]`
  - `load_cfg(ctx, builds_index="index publish")` (refused on a machine whose service has another database).
  - No lock (one read transaction, as export).
  - Prints the file's path, size and rows; exit 1 on `PublishError`.
  - `--manifest FILE`: reads FILE if it exists, writes `manifest_with(...)` to `FILE.next` beside it.
  - `--kept NAME...`: prints, one a line, the names of NAMEs to delete under the Keep rule; no export.

- [ ] **Step 1: Write the failing tests** (`tests/test_catalogues.py`)

```python
def test_a_name_holds_the_schema_and_the_minute():
    at = datetime(2026, 11, 24, 3, 12, 40, tzinfo=UTC)
    assert catalogues.name_for(17, at) == "indexes-s17-20261124T0312Z.sqlite.gz"
    assert catalogues.read_name("indexes-s17-20261124T0312Z.sqlite.gz") == catalogues.Named(17, at.replace(second=0))

@pytest.mark.parametrize("name", ["indexes.json", "indexes-s17-20261124T0312Z.sqlite.gz.next",
                                  "indexes2-s17-20261124T0312Z.sqlite.gz", "indexes-s17-20261340T0312Z.sqlite.gz",
                                  "indexes-sx-20261124T0312Z.sqlite.gz"])
def test_other_names_are_none(name):
    assert catalogues.read_name(name) is None

def test_publish_writes_a_gzip_that_unpacks_to_a_mergeable_export(conn_with_index, tmp_path):
    p = catalogues.publish(conn_with_index, tmp_path, now=NOW, last=None)
    data = (tmp_path / p.name).read_bytes()
    assert data[4:8] == b"\0\0\0\0"                       # mtime 0
    assert hashlib.sha256(data).hexdigest() == p.sha256
    assert len(gzip.decompress(data)) == p.raw_bytes
    assert json.loads((tmp_path / "published.json").read_text())["file"] == p.name

def test_publish_refuses_a_name_that_exists(conn_with_index, tmp_path):
    catalogues.publish(conn_with_index, tmp_path, now=NOW, last=None)
    with pytest.raises(catalogues.PublishError, match="exists"):
        catalogues.publish(conn_with_index, tmp_path, now=NOW, last=None)

def test_publish_refuses_an_index_not_built_whole(conn, tmp_path): ...       # no ug:index:built_at → "built whole"
def test_publish_refuses_a_tenth_fewer_rows_unless_forced(conn_with_index, tmp_path): ...
def test_publish_keeps_only_its_newest_file_in_the_folder(conn_with_index, tmp_path): ...

def test_the_keep_rule():
    names = [catalogues.name_for(17, d(2026, 11, 24)), catalogues.name_for(17, d(2026, 11, 17)),
             catalogues.name_for(17, d(2026, 11, 10)), catalogues.name_for(16, d(2026, 11, 3)),
             catalogues.name_for(15, d(2026, 4, 1)), "indexes.json"]
    assert catalogues.kept(names, schema=17, now=d(2026, 11, 24)) == set(names[:2] + [names[3], "indexes.json"])

def test_a_manifest_lists_the_new_file_first_and_the_kept_ones(): ...       # manifest_with over a two-entry manifest
```

Command tests in `tests/test_commands_index.py`: `test_index_publish_prints_the_file_and_its_rows`,
`test_index_publish_exits_1_and_leaves_no_file_when_refused`, `test_index_publish_is_refused_beside_the_service`
(service marker pointing elsewhere, as the `index build` refusal test does), `test_index_publish_kept_prints_what_to_delete`.

Conformance (`tests/test_conformance_catalogues.py`): writes `vectors/catalogues/names.jsonl`, each record
`{"name": …, "schema": int|null, "at": "…Z"|null}` for the names above and ~20 more (every month's end, leap day,
`T2359Z`), plus `{"kept": {...inputs}, "out": [...]}` records for the Keep rule; `helpers.corpus.check`.

- [ ] **Step 2:** `nix develop -c pytest -q tests/test_catalogues.py tests/test_commands_index.py -k publish` → FAIL.
- [ ] **Step 3:** Implement `caracole/catalogues.py` and the command as the Interfaces say. The command imports
      `caracole.catalogues` inside its function (Heavy imports rule).
- [ ] **Step 4:** Run those tests → PASS; `CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_catalogues.py`,
      then without `write` → PASS; the quick loop → PASS.
- [ ] **Step 5:** docs/usage.md: `index publish` under the index commands (what it writes, its refusals,
      `--force`, `--manifest`, `--kept`).
- [ ] **Step 6:** Commit: `feat(index): caracole index publish, the public catalogue file`.

---

### Task 3: `nix/publish-indexes.sh` (S1 manifest, S3 auth)

**Files:**
- Create: `nix/publish-indexes.sh`, `nix/publish-indexes.nix` (a `writeShellApplication` with `gh`, `jq`,
  `coreutils`, the caracole package on PATH)
- Modify: `flake.nix` (`packages.publish-indexes`)
- Test: `tests/test_publish_indexes.py` (runs the script with a fake `gh` on PATH; skips where bash or jq is missing)
- Create: `tests/helpers/fake_gh.py` (a `gh` executable over a JSON state file: `release view --json assets`,
  `release create`, `release upload`, `release delete-asset`, `api -X PATCH …/assets/<id> -f name=`; failure
  injection by env `FAKE_GH_FAIL=<subcommand>:<n>`)

**Interfaces:**
- Consumes: `caracole index publish --kept` (Task 2); the folder's `published.json`.
- Usage: `publish-indexes [--manifest] DIR`
  - `REPO` defaults to `Danielhp95/caracole`, `TAG` to `indexes`.
  - **S3**: if `GH_TOKEN_FILE` is set, `GH_TOKEN=$(cat "$GH_TOKEN_FILE")`; else `gh`'s own login
    (the owner's user unit sets `GH_TOKEN` from `gh auth token` for their account; see Task 4).
  - Steps, each failing the script (exit 1) with a line saying which:
    1. release exists, else `gh release create indexes --latest=false --title "Site catalogues" --notes …`;
    2. delete every asset whose `state` isn't `uploaded`;
    3. the file of `published.json` already listed as `uploaded` with the same size and digest: exit 0, "already
       published"; listed otherwise: exit 1, "a different file of that name is there";
    4. `gh release upload indexes DIR/<file>` (no `--clobber`);
    5. read the asset back: `size == bytes` and `digest == "sha256:"+sha256`, else delete it, exit 1;
    6. with `--manifest` (**S1 Download**): `caracole index publish --manifest`'s `indexes.json.next` uploaded;
       rename `indexes.json` → `indexes.json.prev`; rename `indexes.json.next` → `indexes.json`; delete
       `indexes.json.prev`. Step 2 also: when `indexes.json` is missing and `.prev` is there, rename it back first;
       a leftover `.next` is deleted;
    7. delete what `caracole index publish --kept <every asset name>` prints.

- [ ] **Step 1: Write the failing tests** (`tests/test_publish_indexes.py`, each from a fake release state)

`test_a_first_publish_makes_the_release_not_latest_and_uploads`, `test_a_half_upload_left_behind_is_deleted_first`,
`test_an_existing_name_is_refused` (different size there → exit 1, nothing deleted),
`test_the_same_file_again_is_already_published`, `test_a_digest_that_differs_is_deleted_and_fails`,
`test_pruning_deletes_only_what_the_keep_rule_names`, `test_a_failed_upload_leaves_last_weeks_file_listed`
(`FAKE_GH_FAIL=upload:1`), and for `--manifest`: `test_the_manifest_is_swapped_by_two_renames`,
`test_a_run_dead_between_the_renames_is_mended_by_the_next` (`FAKE_GH_FAIL=api:2`, then a clean run: `indexes.json`
there, no `.prev`/`.next`), `test_a_token_file_is_used_when_named` (fake gh records `GH_TOKEN`).

- [ ] **Step 2:** `nix develop -c pytest -q tests/test_publish_indexes.py` → FAIL (no script).
- [ ] **Step 3:** Write the script (`set -euo pipefail`; `jq` for every JSON read; every name passed as an argument,
      never through a shell string) and the Nix package.
- [ ] **Step 4:** Tests → PASS; `git add` the new files; `nix build .#publish-indexes` → builds; `nix flake check`
      → PASS (test_nix_package.py: no unknown `CARACOLE_*` variable).
- [ ] **Step 5:** Commit: `build(nix): publish-indexes, the catalogues' upload, checked and pruned`.

---

### Task 4: Timers (S3)

**Files:**
- Modify: `nix/module.nix` (`services.caracole.publish`), `nix/module-check.nix`
- Modify: `docs/deploy.md` (NixOS: the option; Ubuntu: "no timer; run `caracole index publish` and
  `publish-indexes` by hand")
- Outside this repo: the owner's own configuration (the user unit that uploads)

**Interfaces:**
- `services.caracole.publish.enable` (bool, default false), `.folder` (default `"${dataDir}/publish"`),
  `.calendar` (default `"Sun 05:00"`), `.tokenFile` (null or path; **S3 token side**).
  - Always: `caracole-publish.service` (oneshot, the units' `sandbox` and `identity`, `PrivateNetwork = true`,
    `ReadWritePaths` + the folder) running `caracole --config … index publish <folder>`; its timer; tmpfiles makes
    the folder `2750 caracole:caracole`; OnFailure the units' ntfy alert.
  - `tokenFile` set: `caracole-publish-upload.service` after it (network, `LoadCredential=gh:<tokenFile>`,
    `GH_TOKEN_FILE=%d/gh`) running `publish-indexes <folder>`. Null: no upload unit, and the folder is the owner's
    user timer's to upload (S3 default).
- The owner's configuration (S3 default): a systemd user service that sets `GH_TOKEN` from `gh auth token` and
  runs `publish-indexes /var/lib/caracole/publish`, started as the publish writes `published.json` (docs/deploy.md).

- [ ] **Step 1: Write the failing checks** in `nix/module-check.nix`: a system with `publish.enable = true` has the
      unit, its command line parses with caracole's CLI (the check's existing parser), `PrivateNetwork` true, no
      `LoadCredential`; one with `tokenFile` has the upload unit with `LoadCredential`; one without `publish` has
      neither.
- [ ] **Step 2:** `nix build .#checks.x86_64-linux.module` → FAIL.
- [ ] **Step 3:** Implement the option. dataDir mode `:0710` already lets group members through; the folder is
      `2750`, so the owner (group `caracole`) reads it.
- [ ] **Step 4:** Module check → PASS; `nix flake check` → PASS.
- [ ] **Step 5:** docs/deploy.md in the same commit. Commit: `feat(nix): a weekly publish of the site catalogues`.
- [ ] **Step 6 (the owner's configuration, after caracole's push):** the user unit; `nix flake update caracole`; switch; run both
      by hand once; open `https://github.com/Danielhp95/caracole/releases/tag/indexes`.

---

### Task 5: The phone's catalogue source (S1)

**Files:**
- Create: `android/core/src/main/kotlin/io/github/danielhp95/caracole/core/catalogues/Names.kt`
  (`read_name`'s port), `Release.kt` (listing, choice, words), `Download.kt` (stream, gunzip, hash, caps),
  `Catalogues.kt` (constants)
- Test: `android/core/src/test/kotlin/io/github/danielhp95/caracole/core/catalogues/NamesTest.kt`, `ReleaseTest.kt`,
  `DownloadTest.kt` (a `com.sun.net.httpserver.HttpServer` on loopback as fake GitHub)
- Modify: `core.testing.Replays` (area `catalogues`, replaying `vectors/catalogues/names.jsonl`)

**Interfaces:**
- Consumes: `vectors/catalogues/names.jsonl` (Task 2); `RealTransport.refuseUnderTests(url)`.
- Produces:
  - `object Catalogues { const val REPO = "Danielhp95/caracole"; const val TAG = "indexes";
    const val CAP_FACTOR = 20; const val ROOM_FACTOR = 23 /* Task 0 */; const val IMPORTED = "catalogues:imported";
    const val NOT_BEFORE = "catalogues:not-before" }`
  - `object Names { fun read(name: String): Named? }`, `data class Named(val schema: Int, val at: Instant)`.
  - `data class Listed(val name: String, val bytes: Long, val sha256: String, val uploaded: Boolean, val url: String)`
  - `sealed interface CatalogueSource { fun list(): List<Listed> }` — **S1**:
    - `class Api(http: Http, base: URI = URI("https://api.github.com"))`: `GET /repos/{REPO}/releases/tags/{TAG}`
      with `Accept: application/vnd.github+json`; `uploaded = state == "uploaded"`; `sha256` from `digest`
      (`sha256:` stripped; an asset with no digest is not `uploaded`); `url` = the asset's API `url`, fetched
      with `Accept: application/octet-stream`; 404 → `NoRelease`; 403/429 with `x-ratelimit-remaining: 0` →
      `Limited(until = x-ratelimit-reset)`.
    - `class Download(http: Http, base: URI = URI("https://github.com"))`: `GET /{REPO}/releases/download/{TAG}/indexes.json`,
      on 404 once `indexes.json.prev`, then `NoRelease`; every entry `uploaded = true`; `url` =
      `…/download/indexes/<file>`.
  - `sealed interface Choice { data class Take(val file: Listed, val named: Named) : Choice;
    data class UpToDate(val name: String); data class Newer(val schema: Int); data class Older(val schema: Int);
    object None }`
  - `fun choose(listed: List<Listed>, schema: Int, imported: String?): Choice` — of `uploaded` files whose name
    reads, this schema's newest **by `Named.at`**; else `Newer(max)` if any schema > ours, else `Older(max)`,
    else `None`; `UpToDate` when the newest is `imported`.
  - `fun words(choice: Choice): String?` — the spec's sentences verbatim:
    `"The published catalogues are for a newer caracole (schema 18). Update the app."`,
    `"The published catalogues are for an older caracole (schema 16). New ones are on their way."`,
    null for `Take` and `UpToDate` (the job's kind words them). `fun date(named: Named): String` →
    `"24 Nov 2026"` (`d MMM yyyy`, English month names from a table, never a `java.text` locale).
  - `class Fetched(val file: File, val raw: Long)`; `fun download(http: Http, file: Listed, to: File, onProgress:
    (Long) -> Unit): Fetched` — follows at most one redirect, only to the hosts in Global Constraints (else
    `CatalogueError("GitHub sent the download to <host>; nothing was downloaded.")`); hashes the `.gz` bytes as
    they come, unpacks through `GZIPInputStream` to `to`, stops past `CAP_FACTOR × file.bytes`
    (`"The file unpacks to more than it should; nothing was imported."`), checks the digest
    (`"The download isn't the file GitHub listed. Try again."`), deletes `to` on any failure.
  - `class CatalogueError(message: String) : Exception(message)`; `NoRelease`, `Limited(val until: Instant)` its
    subclasses, with words `"No catalogues are published yet."` and `"Try again after 14:05"` +
    `" — GitHub has answered this network's share of requests for the hour."`.
  - The streamed GET is `mirror.Http`'s `get` (it already streams, follows no redirect and takes headers); it gains
    no new behaviour, but every call here goes through a `URI` the source built and is checked by
    `RealTransport.refuseUnderTests` first.

- [ ] **Step 1: Write the failing tests**

```kotlin
// ReleaseTest
@Test fun passesOverAFileNotUploaded() {
    val c = choose(listOf(listed("indexes-s17-20261124T0312Z.sqlite.gz", uploaded = false),
                          listed("indexes-s17-20261117T0310Z.sqlite.gz")), 17, null)
    assertEquals("indexes-s17-20261117T0310Z.sqlite.gz", (c as Choice.Take).file.name)
}
@Test fun newestIsByTheNamesStampNotTheListsOrder() { /* older first, newer second, then reversed: same Take */ }
@Test fun aNewerSchemaIsSaidBeforeAnOlderOne() {
    assertEquals(Choice.Newer(18), choose(listOf(listed("indexes-s18-…"), listed("indexes-s16-…")), 17, null))
}
@Test fun theSameFileAsLastTimeIsUpToDate() { … }
@Test fun otherNamesAreIgnored() { /* indexes.json, .next, indexes2-… → None */ }
@Test fun theWordsAreTheSpecs() { assertEquals("The published catalogues are for a newer caracole (schema 18). Update the app.", words(Choice.Newer(18))) }
// Api against the fake server: a listing → Listed with sha256 stripped; 404 → NoRelease;
// 403 + x-ratelimit-remaining 0 + reset 1795537517 → Limited(Instant.ofEpochSecond(1795537517)).
// Download source: indexes.json 404 then .prev 200 → its files.
// DownloadTest: a good file → Fetched(raw = its bytes) and `to` holds the export;
// a redirect to evil.example → CatalogueError, `to` absent; a wrong digest → error, `to` absent;
// a gzip cut short → error; a gzip of 1 KB that unpacks to 30 KB with bytes=1 KB → cap error.
```

- [ ] **Step 2:** `nix develop ./android -c gradle -p android :core:test --tests '*catalogues*'` → FAIL.
- [ ] **Step 3:** Implement as the Interfaces say; JSON through `core.json`'s reader (never `org.json`); dates
      through `core.py`/`Stamps`, no `java.text` locale.
- [ ] **Step 4:** Tests → PASS; `gradle -p android test` → PASS (ForbiddenApiTest included).
- [ ] **Step 5:** Commit: `feat(android): the site catalogues' release read and downloaded, either source`.

---

### Task 6: The phone's `catalogues` job

**Files:**
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/jobs/PhoneKinds.kt`
- Create: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/lookups/CataloguesRunner.kt`
- Modify: `android/server/src/main/kotlin/io/github/danielhp95/caracole/server/Assembly.kt` (register the runner;
  **S1**: `val source: CatalogueSource = CatalogueSource.Api(http)`)
- Test: `android/server/src/test/kotlin/.../lookups/CataloguesRunnerTest.kt`, `JobViewsTest.kt`

**Interfaces:**
- Consumes: Task 5's `CatalogueSource`, `choose`, `words`, `download`; `IndexTransfer.merge(db, file, now,
  notAfter =)`; `TabCounts.of`; the database's `checkpoint()`; the search's answers' cache (as the restore forgets it).
- Produces:
  - `PhoneKinds.CATALOGUES = Kind("catalogues", "catalogues:", "Download the site catalogues", "The site catalogues",
    "catalogues" to "Catalogues", "{doing}", "Catalogues of {date}", "Not imported: {why}",
    otherwise = "Up to date: the catalogues of {date}")`, added to `ALL`.
  - `class CataloguesRunner(val parts: PhoneParts, val source: CatalogueSource, private val clock: () -> Instant)`
    with `fun spec(meteredOk: Boolean): JobSpec` (key `catalogues:`, one at a time; args `["catalogues"]` or
    `["catalogues", "--metered-ok"]`) and `override suspend fun run(args, context)`:
    1. `kv[NOT_BEFORE]` in the future → fail with `Limited`'s words, no request;
    2. `source.list()`; `choose(…, Database.SCHEMA_VERSION, kv[IMPORTED])`; `Newer`/`Older`/`None` → fail with
       `words`; `UpToDate` → done `otherwise` with `date(named)`;
    2b. on a metered network without `--metered-ok`: done `otherwise`-free with detail
       `"52 MB to download: waiting for Wi-Fi or your go-ahead"` and the size in kv `catalogues:asking`
       (`{"name", "bytes"}`), which Task 7's question reads; nothing downloaded;
    3. free space of `stateDir` < `ROOM_FACTOR × bytes` → fail `"The import needs about 1.2 GB free; the phone has
       700 MB."` (`SizeLabel`'s units);
    4. `download` into `stateDir/cache/catalogues/<name>.sqlite`, stage detail `"Downloading · 31 of 52 MB"`;
    5. in one `database.write`: `IndexTransfer.merge(db, file, now, notAfter = clock())`; then sites in the file's
       `caracole_export.sites` that `Sites.named` doesn't know → appended to the done line: `" It also holds
       iReal Pro's, which this version doesn't read. Update the app to search it."` (title from the file's site
       name as-is when unknown); `kv[IMPORTED] = name` **only after the merge succeeds**;
    6. checkpoint, forget the search's answers, delete the file (in `finally`, always);
    7. `Limited` caught anywhere → `kv[NOT_BEFORE] = until`.

- [ ] **Step 1: Write the failing tests** (`CataloguesRunnerTest`, a fake `CatalogueSource` and a fake download
      server, a fresh `Phone` database)

`importsTheNewestOfItsSchemaAndSaysItsDate`, `upToDateDownloadsNothing`, `aNewerSchemaFailsInTheSpecsWords`,
`aRefusedMergeLeavesNothingImported` (a file whose `caracole_export.schema` is 16 named `-s17-` → job failed with
the merge's words, `kv[IMPORTED]` null, the cache folder empty), `aSiteItDoesntKnowIsImportedAndSaid`,
`noRoomFailsBeforeAnyDownload` (the fake server saw no request for the file), `limitedIsKeptAndNothingIsAskedBeforeIt`,
`theFileIsDeletedWhateverCameOfIt`, `aMeteredNetworkStopsBeforeTheDownloadAndSaysTheSize`. `JobViewsTest`: the kind's lines running, done, otherwise and failed.

- [ ] **Step 2:** `gradle -p android :server:test --tests '*Catalogues*' --tests '*JobViews*'` → FAIL.
- [ ] **Step 3:** Implement; regenerate nothing on the Python side (the kind is the phone's own, as backup's).
- [ ] **Step 4:** `gradle -p android test` → PASS.
- [ ] **Step 5:** Commit: `feat(android): a job that downloads and imports the site catalogues`.

---

### Task 7: The app's offer

**Files:**
- Modify: `android/app/src/main/kotlin/io/github/danielhp95/caracole/SettingsActivity.kt`, its layout
  `res/layout/activity_settings.xml`, `res/values/strings.xml`
- Modify: `OpeningScreen.kt` (first start)
- Test: `android/app/src/androidTest/.../CataloguesTest.kt` (device, through `android/scripts/device-test.sh`)

**Interfaces:**
- Consumes: `CataloguesRunner.spec()` queued as BackupsActivity queues a backup (`phone.queue.submit(spec)`);
  `IndexTransfer.newest(db)` for the date shown; kv `catalogues:asking` (Task 6, step 2b).
- Settings: a row "Site catalogues" with `"Of 3 Nov 2026 · 3 weeks old"` (the newest of `newest(db)`; `"None yet"`
  without) and a button **Download the site catalogues**. No request until it is tapped. The tap queues
  `spec(meteredOk = false)`; on a metered network (`ConnectivityManager.isActiveNetworkMetered`) the job stops at
  step 2b, and the app then asks `"52 MB over mobile data?"` from `catalogues:asking`; Yes queues
  `spec(meteredOk = true)`.
- First start: when no computer is set and `TabCounts.of(db)` is all zero, once (kv `catalogues:offered`), the
  card of the companion page: title `"Search the sites offline?"`, text, `"52 MB to download · about 450 MB on the
  phone"` from the listing, **Download** / **Not now**.

- [ ] **Step 1: Write the failing device test** `CataloguesTest`: with a fake GitHub served by the test's
      computer process (`tests.helpers.e2e_library serve` gains `--catalogues DIR`, serving the API shape over a
      published file) and `Catalogues` base URIs pointed at `10.0.2.2:PORT` by the test runner's arguments: the
      first-start card shows, Download imports, Settings then shows the date, a second tap says Up to date.
- [ ] **Step 2:** `android/scripts/device-test.sh io.github.danielhp95.caracole.CataloguesTest=…` → FAIL.
- [ ] **Step 3:** Implement the row, the question and the card; strings in `strings.xml`.
- [ ] **Step 4:** Device test → PASS; `gradle -p android test` → PASS.
- [ ] **Step 5:** Commit: `feat(android): download the site catalogues from Settings and the first start`.

---

### Task 8: Docs and AGENTS.md

**Files:** `docs/phone.md`, `android/README.md`, `docs/sources.md`, `AGENTS.md`, `plan_host_index.md`

- [ ] **Step 1:** phone.md: "Without a computer: Settings › Download the site catalogues", what it downloads, its
      size, how often it's refreshed. android/README.md's Release: "after a schema bump, run the publish once before
      releasing the APK".
- [ ] **Step 2:** sources.md: the catalogues are published weekly, what they hold and leave out (S2's rules).
- [ ] **Step 3:** AGENTS.md: `catalogues.py` in the shared modules table; `index publish` among the commands and
      under `service.py`'s `builds_index` words; Politeness: **S1 Api** — "the phone asks api.github.com, two
      requests a download, at a tap"; **S1 Download** — the owner's exception for
      `github.com/Danielhp95/caracole/releases/download/indexes/` under "The one exception is YouTube"'s neighbour;
      the exports' "caracole itself sends it nowhere" kept, with "the owner's publish timer uploads the public
      file"; android/'s `core.catalogues` and the `catalogues` kind.
- [ ] **Step 4:** `nix develop -c pytest -q` → PASS (the whole suite). Commit: `docs: the site catalogues without a computer`.

---

### Task 9: Settle the switches (when the owner decides)

For each decided switch, in one commit each:

- **S1 = Api:** delete `CatalogueSource.Download`, its tests, `--manifest` (Task 2), step 6 of the script and its
  tests, `manifest_with`. **S1 = Download:** delete `CatalogueSource.Api` and its tests; Assembly picks
  `Download`; the script's `--manifest` becomes the default; AGENTS.md's exception written.
- **S2:** edit `PUBLIC_OMIT`; its test names what is kept and left out; sources.md says the same.
- **S3 = user timer:** delete `publish.tokenFile` and the upload unit and their checks. **S3 = token file:**
  delete the owner's user unit; deploy.md says how to make the token.
- Then `nix develop -c pytest -q`, `gradle -p android test`, `nix flake check` → PASS; commit
  `refactor: the site catalogues' <switch> settled`.

---

## Self-review

- Spec coverage: the file (T1–2), the release and Keep (T2–3), publishing both timers and refusals (T2–4), the
  phone's ask, choice, room, download, checks, merge and words (T5–6), Settings and first start (T7), schemas and
  new sites (T5 `choose`, T6 unknown sites), docs (T8), measuring (T0), Plan B (S1 Download in T2/T3/T5).
  Deferred by the spec, not built: resume with Range, merging another schema with matching columns.
- Names used across tasks: `PUBLIC_OMIT`, `Published`, `kept`, `name_for`/`Names.read`, `CatalogueSource`,
  `choose`, `words`, `date`, `download`, `CataloguesRunner.spec(meteredOk)`, `PhoneKinds.CATALOGUES`, kv
  `catalogues:imported`, `catalogues:not-before`, `catalogues:asking`, `catalogues:offered`.
