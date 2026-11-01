# SpotifyData

A personal listening-history archive. A GitHub Actions job polls Spotify's
recently-played endpoint every hour and commits what it finds, so the history
accumulates in git instead of expiring.

It exists because the API remembers almost nothing: **Spotify retains only
about 50 recent plays**. Anything not collected within the hour is gone for
good. That single fact drives most of the design decisions below.

Currently **56,286 plays** spanning **2024-12-14 to 2026-11-01**.

## How it works

```
Spotify API
     │  hourly, .github/workflows/python-script.yml
     ▼
 collector  ──writes──▶  data/*.csv      append-only · committed · system of record
                              │
                              │  python src/database.py build   (~4s)
                              ▼
                         spotify.db      normalised · gitignored · derived
                              │
                              ▼
                         analysis
```

The CSVs are the system of record, not the database. They are append-only, they
diff readably, and — the deciding reason — **git can merge them**. When two
sides collect independently, a text conflict keeps both sides' rows; a binary
`.db` conflict keeps one and discards the other. That is not hypothetical: it
happened during the 2026 recovery, and 28 plays survived only because the
canonical store was text.

The database is a derived read model, rebuilt from scratch each time. Nothing in
the collection path reads it, so a mistake there cannot cost a play.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp src/.env.example src/.env        # then fill in the three values
.venv/bin/python src/auth_catch.py  # mint a REFRESH_TOKEN (opens a consent link)
.venv/bin/python src/main.py        # collect
```

`src/auth_catch.py` runs a throwaway server on port 8888 to catch Spotify's
OAuth redirect, so there is nothing to copy by hand. The redirect URI it uses
must be registered **verbatim** in the
[app dashboard](https://developer.spotify.com/dashboard); Spotify rejects
`localhost`, so use `http://127.0.0.1:8888/callback`.

### Secrets

| Name | Where | From |
|---|---|---|
| `CLIENT_ID` | `src/.env` and repo secrets | app dashboard |
| `CLIENT_SECRET` | `src/.env` and repo secrets | app dashboard |
| `REFRESH_TOKEN` | `src/.env` and repo secrets | `src/auth_catch.py` |

`src/.env` is gitignored. A refresh token does not expire on a timer but **is
revoked by a password change or by removing app access** at
`spotify.com/account/apps` — which is exactly what broke this project for 98
days in 2026.

### Database and tests

```bash
.venv/bin/python src/database.py build     # rebuild spotify.db from the CSVs
.venv/bin/python src/database.py verify    # foreign keys + row counts vs CSVs
.venv/bin/python src/database.py stats
python3 -m unittest discover -s tests      # 67 tests, stdlib only, no credentials
```

## Data

### `data/*.csv` — the system of record

| File | Key | Notes |
|---|---|---|
| `recently_played.csv` | `id` — UTC epoch seconds | one row per play |
| `songs.csv` | `id` | `artists_id` is a stringified list |
| `albums.csv` | `id` | `tracks`, `images` stringified lists |
| `artists.csv` | `id` | `genres`, `images` stringified lists |
| `playlists.csv` | `id` | editorial playlists are not stored |

File order is append order, not sorted — the last line is not reliably the
newest play. Use `MAX(played_at)`.

### `spotify.db` — the derived model

Lists become real tables: `song_artists`, `album_artists`, `album_tracks`,
`artist_genres`, `artist_images`, `album_images`, `playlist_images`. Two views,
`play_artists` and `plays_detail`, cover most questions without writing joins.

Three relations carry **no foreign key**, each for a measured reason documented
in `src/database.py`:

- `album_tracks.track_id` — albums list every track; only played tracks are
  stored, so most point at tracks we don't have.
- `album_artists.artist_id` — some albums credit artists never fetched.
- `plays.context_id` — polymorphic, and most playlist contexts are editorial
  playlists skipped by design.

`release_date` is `TEXT` because Spotify returns three precisions (`2020`,
`2020-04`, `2020-04-10`); a `DATE` column would invent January 1st.

### Provenance: `plays_detail.source`

| Source | Plays | Has context | Has popularity |
|---|---|---|---|
| `api` | 51,095 | yes | yes |
| `import` | 5,191 | no | no |

Plays recovered from a bulk export have no playlist context and no popularity
at play time, so both columns are empty rather than guessed. **Any analysis
that uses context or popularity should filter on `source`** instead of
averaging the two regimes together.

## Backfilling from a Spotify export

`src/import_history.py` imports plays the collector never saw, from a GDPR
**"Extended streaming history"** export (request it under Privacy Settings; it
takes a few weeks and is *not* the fast basic export, which lacks track IDs).

```bash
.venv/bin/python src/import_history.py --zip my_spotify_data.zip \
    --since 2026-07-20 --until 2026-10-27 --dry-run
```

Rules it follows, all for the sake of keeping imported plays comparable to
collected ones:

- Plays under 30s are dropped; the API only ever reported plays past that.
- Deduplication allows 15 seconds of drift. The export's `ts` and the API's
  `played_at` were verified to mean the same thing, agreeing exactly for most
  of 50,212 cross-checked plays and within 3 seconds for the rest.
- A timestamp already owned by a different track is skipped and reported, never
  nudged — `played_at` is the primary key, and moving one invents a play time.

> **The export contains an IP address, device platform and country for every
> play, and this repository is public.** The zip is gitignored and only the
> timestamp, track id, track name and `ms_played` are ever read from it. Keep it
> that way.

### Not done: nine years of pre-2024 history

The same export covers **2015-06 onward — 186,490 importable plays over 2,484
days**, roughly 3.3× the current dataset. It is deliberately **not** imported.

```bash
# available, not run:
.venv/bin/python src/import_history.py --zip my_spotify_data.zip \
    --since 2015-01-01 --until 2024-12-14
```

The reasons to think before running it:

- **It changes what the dataset is**, rather than repairing it. Nine years of
  bulk-export history would sit beside two years of purpose-built collection at
  a different fidelity.
- **None of it has playlist context.** Coverage would fall from **91% of plays
  to 21%** (playlist context specifically, from 69% to 16%), weakening every
  "where do I listen from" question — the most distinctive thing this archive
  can answer.
- **No popularity at play time**, so trend analysis over that span is unavailable.
- It needs **23,419 track lookups** — roughly 469 track requests plus albums and
  artists, so a few thousand API calls and some tens of minutes.

The repaired 2026 outage was different: that was 90 days of genuinely missing
rows inside the collection period, so filling it restored the record rather than
redefining it.

A smaller, clearly worthwhile version of this remains open: **23–26 October
2026** is still empty, because the export was generated before the collector
came back. A fresh export would close those three days.

## Operations

Two workflows:

- **`python-script.yml`** — hourly collection. Runs the tests, collects, then
  commits and pushes with a concurrency guard and rebase-and-retry. **Raises a
  GitHub issue on failure**, which is the lesson of the 2026 outage: the broken
  token cost one click to fix, while the 98 days of unnoticed silence cost
  history that cannot be recovered.
- **`publish-database.yml`** — weekly, and manually dispatchable. Builds and
  verifies the database and uploads it as an artifact. Kept off the hourly path
  so collection stays a seven-second job.

Scheduled workflows are disabled by GitHub after 60 days without repository
activity. Successful runs commit, and commits reset that timer, so this only
becomes a problem once collection is already broken.

## Layout

```
src/main.py              entry point: collect and store recent plays
src/Classes.py           Song, Album, Artist, Playlist, PlayedSong
src/Spotify.py           authenticated client
src/ReadWrite.py         CSV read/write with a cached key set
src/utils.py             timestamps, batching, nested lookups
src/database.py          schema and builder for the derived database
src/auth_catch.py        one-shot refresh-token minter
src/import_history.py    backfill from a GDPR export
src/migrate_data0.py     one-shot import of the original 2024 schema
tests/                   67 stdlib-only tests
data/                    the CSVs — system of record
data0/                   the original schema, fully migrated into data/
```

Original reference:
<https://github.com/AzeemIdrisi/TweetifyMusic/blob/main/tweetifymusic.py>
