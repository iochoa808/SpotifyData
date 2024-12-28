import sqlite3

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row

c = conn.cursor()

c.execute("""CREATE TABLE songs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                album_id TEXT,
                duration_ms INTEGER,
                explicit INTEGER,
                isrc TEXT,
                popularity INTEGER,
                track_number INTEGER,
                FOREIGN KEY(album_id) REFERENCES albums(id)
                )""")

c.execute("""CREATE TABLE albums (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                release_date INTEGER,
                popularity INTEGER
                )""")

c.execute("""CREATE TABLE artists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                genres TEXT,
                popularity INTEGER
                )""")

c.execute("""CREATE TABLE playlists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                collaborative INTEGER,
                owner_id TEXT,
                FOREIGN KEY(owner_id) REFERENCES users(id)
                )""")

c.execute("""CREATE TABLE users (
                id TEXT PRIMARY KEY
                name TEXT NOT NULL)""")

c.execute("""CREATE TABLE album_artists  (
                album_id TEXT,
                artist_id TEXT,
                PRIMARY KEY (album_id, artist_id),
                FOREIGN KEY (album_id) REFERENCES albums(id),
                FOREIGN KEY (artist_id) REFERENCES artists(id)
                )""")

c.execute("""CREATE TABLE song_artists (
                song_id TEXT,
                artist_id TEXT,
                PRIMARY KEY (song_id, artist_id),
                FOREIGN KEY (song_id) REFERENCES songs(id),
                FOREIGN KEY (artist_id) REFERENCES artists(id)
                )""")

c.execute("""CREATE TABLE album_tracks (
                album_id TEXT,
                track_id TEXT,
                PRIMARY KEY (album_id, track_id),
                FOREIGN KEY (album_id) REFERENCES album(id),
                FOREIGN KEY (track_id) REFERENCES song(id)
                )""")

conn.commit()


def insert_song(song):
    with conn:
        c.execute(
            "INSERT INTO songs VALUES (:id, :name, :album_id, :duration_ms, :explicit, :isrc, :popularity, :track_number)",
            {'id': song.id, 'name': song.name,
             'album_id': song.album_id, 'duration_ms': song.duration_ms,
             'explicit': song.explicit, 'isrc': song.isrc,
             'popularity': song.popularity, 'track_number': song.track_number})

        for artist in song.artists_id:
            c.execute("INSERT INTO song_artists VALUES (:song_id, :artist_id)",
                      {'song_id': song.id, 'artist_id': artist})


def getSong(id):
    c.execute("SELECT * FROM songs WHERE id=:id", {'id': id})
    song = dict(c.fetchone())
    c.execute("SELECT artist_id FROM song_artists WHERE song_id=:song_id",
              {'song_id': id})
    artists = [row['artist_id'] for row in c.fetchall()]
    song.update({'artists_id': artists})
    return song


#insert_song(Song('0mfHN9LcAPidSI3JCPqYml'))
#insert_song(Song('6Oryv6qqkDSi0opyTi7gvJ'))

#mySong = getSong('6Oryv6qqkDSi0opyTi7gvJ')


