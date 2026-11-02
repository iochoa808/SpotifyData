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

### The schedule is not reliable, and that costs plays

GitHub's `schedule` event is best-effort. Measured on this repository, it fires
**4–5 times a day whatever the cron says** — a single hourly entry did no better
than the 2-hourly one it replaced — and on 2 November 2026 it went quiet for
**15.9 hours** before resuming unprompted, with the workflow active and no
GitHub incident.

That matters because the gap between runs is the only protection there is.
Against this account's own history:

| Gap between runs | Busiest window | vs the ~50-play ceiling |
|---|---|---|
| 2 hours | 47 plays | safe, barely |
| **3 hours** | **64 plays** | **loses ~14** |
| 5 hours | 101 plays | loses ~51 |

This is not theoretical: **65 commits in the history added exactly 45–60 plays**,
which is the signature of a full window with older plays already scrolled out.

Four cron entries across the hour improve the odds and nothing more. A
dependable interval has to come from outside Actions.

### External scheduler

The workflow accepts a `repository_dispatch` event of type `collect`, so any
external timer can fire it:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_PAT" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/iochoa808/SpotifyData/dispatches \
  -d '{"event_type":"collect"}'
```

`scripts/trigger-collection.sh` wraps that with useful error messages — run it
once locally to confirm the token works before handing it to a scheduler:

```bash
GITHUB_PAT=github_pat_... ./scripts/trigger-collection.sh
```

A success is **HTTP 204** with no body.

**The token.** Create a *fine-grained* token at
[Settings → Personal access tokens](https://github.com/settings/personal-access-tokens/new):

| Setting | Value |
|---|---|
| Repository access | Only select repositories → `SpotifyData` |
| Permissions | Repository permissions → **Contents: Read and write** |
| Expiration | Set one, and diarise the renewal |

Contents write is the only permission the dispatches endpoint needs. The token
can push to this repository, so treat it as a password: put it only in the
scheduler's secret field, never in the repo, and never in a commit. An expired
token fails closed — collection falls back to GitHub's unreliable schedule
rather than breaking — so renewal is the thing to watch.

**The scheduler.** Anything that can POST on a timer works. A hosted cron
service (cron-job.org and similar) needs: the URL above, method `POST`, the
three headers, the JSON body, and an interval of 30 minutes or better. Keep it
under two hours; the table above is why.

A local timer is the alternative if this machine is usually on, and needs no
token at all — it can run `src/main.py` directly and push. Both sources can
collect at once safely: it has happened twice, and git reconciled both without
duplicates, because `played_at` is the primary key and the CSVs merge as text.

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
