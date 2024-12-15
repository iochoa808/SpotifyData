from Spotify import sp
import ReadWrite as rw
import utils


class Song:
    file_path = "songs.csv"

    def __init__(self, new_id="", queryDict=None):
        # Initialize queryDict as an empty dictionary if not provided
        if queryDict is None:
            queryDict = {}
        # Raise ValueError if neither are provided
        if not new_id and not queryDict:
            raise ValueError("SONG NOT INITIATED PROPERLY")
        # If id is provided
        if new_id:
            queryDict = sp.track(new_id)

        self.id = queryDict['id']
        self.name = queryDict['name']
        self.explicit = queryDict['explicit']
        self.duration_ms = queryDict['duration_ms']
        self.popularity = queryDict['popularity']
        self.album = queryDict['album']['id']
        self.artists = [artist['id'] for artist in queryDict['artists']]
        self.track_number = queryDict['track_number']
        self.isrc = queryDict['external_ids']['isrc']

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists)}"

    @staticmethod
    def store(songDict):
        if not rw.instanceExists(Song.file_path, songDict['id']):
            return rw.saveInstanceToCSV(Song(queryDict=songDict), Song.file_path)


class Album:
    file_path = "albums.csv"

    def __init__(self, new_id="", queryDict=None):
        # Initialize queryDict as an empty dictionary if not provided
        if queryDict is None:
            queryDict = {}
        # Raise ValueError if neither are provided
        if not new_id and not queryDict:
            raise ValueError("ALBUM NOT INITIATED PROPERLY")
        # If id is provided
        if new_id:
            queryDict = sp.album(new_id)

        self.id = queryDict['id']
        self.name = queryDict['name']
        self.total_tracks = queryDict['total_tracks']
        self.release_date = queryDict['release_date']
        self.artists = [artist['id'] for artist in queryDict['artists']]

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists)}"

    def getSongs(self, ofst=0):
        if ofst > self.total_tracks:
            return []
        # Get items of the album
        new_tracks = [
            Song(queryDict=(track | {'album': {'id': self.id}}))
            for track in sp.album_tracks(self.id, limit=50, offset=ofst)['items']
        ]

        return new_tracks + self.getSongs(ofst=ofst + 50)

    @staticmethod
    def store(albumDict):
        if not rw.instanceExists(Album.file_path, albumDict['id']):
            return rw.saveInstanceToCSV(Album(queryDict=albumDict), Album.file_path)


class Artist:
    file_path = "artists.csv"

    def __init__(self, new_id="", queryDict=None):
        # Initialize queryDict as an empty dictionary if not provided
        if queryDict is None:
            queryDict = {}
        # Raise ValueError if neither are provided
        if not new_id and not queryDict:
            raise ValueError("ARTIST NOT INITIATED PROPERLY")
        # If id is provided
        if new_id:
            queryDict = sp.artist(new_id)

        self.id = queryDict['id']
        self.name = queryDict['name']
        self.followers = queryDict['followers']['total']
        self.genres = queryDict['genres']
        self.popularity = queryDict['popularity']
        self.total_albums = sp.artist_albums(self.id)['total']

    def __str__(self):
        return self.name

    def getAlbums(self, ofst=0):
        if ofst > self.total_albums:
            return []
        # Get items of the album
        new_albums = [
            Album(queryDict=album)
            for album in sp.artist_albums(self.id, include_groups='album,single')['items']
        ]

        return new_albums + self.getAlbums(ofst=ofst + 20)

    @staticmethod
    def store(artistDict):
        if not rw.instanceExists(Artist.file_path, artistDict['id']):
            return rw.saveInstanceToCSV(Artist(queryDict=artistDict), Artist.file_path)


class Playlist:
    file_path = "playlists.csv"

    def __init__(self, new_id="", queryDict=None):
        # Initialize queryDict as an empty dictionary if not provided
        if queryDict is None:
            queryDict = {}
        # Raise ValueError if neither are provided
        if not new_id and not queryDict:
            raise ValueError("PLAYLIST NOT INITIATED PROPERLY")
        # If id is provided
        if new_id:
            queryDict = sp.playlist(new_id)

        self.id = queryDict['id']
        self.name = queryDict['name']
        self.description = queryDict['description']
        self.followers = queryDict['followers']
        self.owner = queryDict['owner']['id']
        self.total_tracks = queryDict['tracks']['total']

    def __str__(self):
        return f"{self.name} by {self.owner} with {self.total_tracks} songs"

    def getSongs(self, ofst=0):
        if ofst > self.total_tracks:
            return []
        # Get items of the album
        new_tracks = [
            {'added_at': track['added_at'], 'track': Song(queryDict=track['track'])}
            for track in sp.playlist_items(self.id, limit=100, offset=ofst)['items']
        ]

        return new_tracks + self.getSongs(ofst=ofst + 100)

    @staticmethod
    def store(playlistDict):
        if not rw.instanceExists(Playlist.file_path, playlistDict['id']):
            return rw.saveInstanceToCSV(Playlist(queryDict=playlistDict), Playlist.file_path)


class User:
    def __init__(self, new_id="", queryDict=None):
        # Initialize queryDict as an empty dictionary if not provided
        if queryDict is None:
            queryDict = {}
        # Raise ValueError if neither are provided
        if not new_id and not queryDict:
            raise ValueError("USER NOT INITIATED PROPERLY")
        # If id is provided
        if new_id:
            queryDict = sp.user(id)

        self.id = queryDict['id']
        self.name = queryDict['display_name']
        self.followers = queryDict['followers']

    def __str__(self):
        return self.name


class PlayedSong:
    file_path = "recently_played.csv"

    def __init__(self, playedDict):
        self.played_at = playedDict['played_at']
        self.track = playedDict['track']['id']
        self.context = {
            'type': playedDict['context']['type'],
            'id': playedDict['context']['uri'].split(':')[2]
        }

    def __str__(self):
        return f"[{self.played_at}] {self.track} played from the {self.context['type']} {self.context['uri']}"

    @staticmethod
    def store(playedSongDict):
        if not rw.instanceExists(PlayedSong.file_path, playedSongDict['played_at'], unique_attribute='played_at'):
            return rw.saveInstanceToCSV(PlayedSong(playedDict=playedSongDict), PlayedSong.file_path)


class RecentlyPlayedSongs:

    def __init__(self):
        pass

    @staticmethod
    def saveRecentlyPlayedSongs():
        # Retrieve recently played songs
        recently_played = sp.current_user_recently_played(limit=50)['items'][::-1]

        # Collect sets of all IDs for fetching
        song_ids = list({item['track']['id'] for item in recently_played})
        album_ids = list({item['track']['album']['id'] for item in recently_played})
        artist_ids = list({artist['id'] for item in recently_played for artist in item['track']['artists']})
        playlist_ids = list({item['context']['uri'].split(':')[2] for item in recently_played
                             if item['context']['type'] == 'playlist' and
                             not item['context']['uri'].split(':')[2].startswith("37i9dQZF1E")})

        # Batch fetch and store songs, albums, and artists
        [Song.store(song) for batch_ids in utils.batch(song_ids, 50)
         for song in sp.tracks(batch_ids)['tracks']]
        [Album.store(album) for batch_ids in utils.batch(album_ids, 20)
         for album in sp.albums(batch_ids)['albums']]
        [Artist.store(artist) for batch_ids in utils.batch(artist_ids, 50)
         for artist in sp.artists(batch_ids)['artists']]

        [Playlist.store(sp.playlist(playlist)) for playlist in playlist_ids]
        return [PlayedSong.store(item) for item in recently_played]
