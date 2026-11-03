-- The phone's own tables, beside caracole's schema (PRAGMA user_version stays caracole's): what overrides.toml and
-- songbooks.toml hold on the computer, since a sync moves units, not files. Hand-written, not generated. Version 1:
-- core.db.PhoneSchema runs it with kv phone:schema = '1' in one BEGIN IMMEDIATE, and helpers.corpus.replay_fixture
-- the same. Its readers drop each comment and split the rest at semicolons, so no comment holds one.
CREATE TABLE phone_overrides (
  tbl TEXT NOT NULL,      -- match, pin, transpose, reject, youtube, lacuerda, harptabs, gametabs, azlyrics, version, harmonica, ignore, alias, artist_url, block
  key TEXT NOT NULL,      -- identity key (song tables), slug_key(artist) (alias, artist_url), the tab id (block)
  written TEXT NOT NULL,  -- the name as overrides.toml would write it: "Artist - Title", the artist's name, the tab id
  value TEXT NOT NULL,    -- C(value): the value exactly as overrides.song_entries yields it (canonical JSON)
  PRIMARY KEY (tbl, key));
CREATE TABLE phone_songbooks (
  key TEXT PRIMARY KEY,   -- songbook.name_key(name): NFC, whitespace collapsed, casefold
  name TEXT NOT NULL,
  songs TEXT NOT NULL,    -- C([[entry text, parts], ...]) as peer_sync.songbook_value
  position INTEGER NOT NULL);
