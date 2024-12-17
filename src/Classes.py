from Spotify import sp
import ReadWrite as rw
import utils
from abc import ABC, abstractmethod
from datetime import datetime


# Abstract class
class SpotifyObject(ABC):
    storing_path = None
    unique_attribute = 'id'
    name_attribute = 'name'

    def __init__(self, queryDict=None, new_id=""):
        # Use queryDict if provided, otherwise get data with new_id
        if queryDict is None and not new_id:
            raise ValueError(f"{self.__class__.__name__} requires either 'queryDict' or 'new_id' to initialize.")

        # Use queryDict if provided, otherwise fetch data using new_id
        self.queryDict = queryDict if queryDict else self.getFromId(new_id)

        # id for most, played_at for recentlyPlayed
        self.id = queryDict.get(self.__class__.unique_attribute)
        if not self.id:
            raise ValueError(f"No unique attribute has been found in {self.__class__}")

        # name for most, display_name for user
        self.name = queryDict.get(self.__class__.name_attribute)
        if not self.name:
            del self.name

    @abstractmethod
    def getFromId(self, new_id):
        # Abstract method to fetch data using new_id. Subclasses must implement this method.
        pass

    @classmethod
    def store(cls, objDict):
        # Checking if cls.storing_path has been declared
        if cls.storing_path is None:
            raise ValueError(f"{cls.__name__} must define a 'storing_path'.")

        if not rw.instanceExists(cls.storing_path, unique_value=objDict.get(cls.unique_attribute), unique_attribute=cls.unique_attribute):
            new_instance = cls(queryDict=objDict)  # Dynamically call the subclass constructor
            rw.saveInstanceToCSV(new_instance, cls.storing_path)
            return new_instance
        return None


class Song(SpotifyObject):

    storing_path = "songs.csv"

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.explicit = self.queryDict['explicit']
        self.duration_ms = self.queryDict['duration_ms']
        self.popularity = self.queryDict['popularity']
        self.album = self.queryDict['album']['id']
        self.artists = [artist['id'] for artist in self.queryDict['artists']]
        self.track_number = self.queryDict['track_number']
        self.isrc = self.queryDict['external_ids']['isrc']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists)}"

    def getFromId(self, new_id):
        return sp.track(new_id)


class Album(SpotifyObject):

    storing_path = "albums.csv"

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.total_tracks = queryDict['total_tracks']
        self.release_date = queryDict['release_date']
        self.artists = [artist['id'] for artist in queryDict['artists']]

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists)}"

    def getFromId(self, new_id):
        return sp.album(new_id)

    def getSongs(self, ofst=0):
        if ofst > self.total_tracks:
            return []
        # Get items of the album
        new_tracks = [
            Song(queryDict=(track | {'album': {'id': self.id}}))
            for track in sp.album_tracks(self.id, limit=50, offset=ofst)['items']
        ]

        return new_tracks + self.getSongs(ofst=ofst + 50)


class Artist(SpotifyObject):

    storing_path = "artists.csv"

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.followers = queryDict['followers']['total']
        self.genres = queryDict['genres']
        self.popularity = queryDict['popularity']
        self.total_albums = sp.artist_albums(self.id)['total']

        del self.queryDict

    def __str__(self):
        return self.name

    def getFromId(self, new_id):
        return sp.artist(new_id)

    def getAlbums(self, ofst=0):
        if ofst > self.total_albums:
            return []
        # Get items of the album
        new_albums = [
            Album(queryDict=album)
            for album in sp.artist_albums(self.id, include_groups='album,single')['items']
        ]

        return new_albums + self.getAlbums(ofst=ofst + 20)


class Playlist(SpotifyObject):
    storing_path = "playlists.csv"
    likedSongs = '0000000000000000000000'

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.description = queryDict['description']
        self.followers = queryDict['followers']
        self.owner = queryDict['owner']['id']
        self.total_tracks = queryDict['tracks']['total']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {self.owner} with {self.total_tracks} songs"

    def getFromId(self, new_id):
        return sp.playlist(new_id)

    def getSongs(self, ofst=0):
        if ofst > self.total_tracks:
            return []
        # Get items of the album
        new_tracks = [
            {'added_at': track['added_at'], 'track': Song(queryDict=track['track'])}
            for track in sp.playlist_items(self.id, limit=100, offset=ofst)['items']
        ]

        return new_tracks + self.getSongs(ofst=ofst + 100)


class User(SpotifyObject):

    storing_path = "users.csv"
    name_attribute = 'display_name'

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.followers = queryDict['followers']

        del self.queryDict

    def __str__(self):
        return self.name

    def getFromId(self, new_id):
        return sp.user(new_id)


class PlayedSong(SpotifyObject):
    storing_path = "recently_played.csv"
    unique_attribute = 'played_at'
    name_attribute = None

    def __init__(self, queryDict):
        super().__init__(queryDict=queryDict)

        self.track = queryDict['track']['id']
        self.context = {
            'type': queryDict['context']['type'],
            'id': queryDict['context']['uri'].split(':')[2]
        }

        del self.queryDict

    def __str__(self):
        return f"[{self.id}] {self.track} played from the {self.context['type']} {self.context['id']}"

    def getFromId(self, new_id):
        return None

    def playedAt(self):
        return datetime.fromtimestamp(self.id)


class RecentlyPlayedSongs:

    def __init__(self):
        pass

    @staticmethod
    def saveRecentlyPlayedSongs():
        # Retrieve recently played songs
        recently_played = sp.current_user_recently_played(limit=50)['items'][::-1]

        # Tractar si context no existeix (Liked songs)
        recently_played = [
            {**song, 'context': {'type': 'playlist', 'uri': f"::{Playlist.likedSongs}"}}
            if not song['context'] else song
            for song in recently_played
        ]
        # Convertir played_at a format datetime
        recently_played = [
            {**item, 'played_at': utils.getTimestamp(item['played_at'])}
            for item in recently_played
        ]

        # Collect sets of all IDs for fetching
        song_ids = list({item['track']['id'] for item in recently_played})
        album_ids = list({item['track']['album']['id'] for item in recently_played})
        artist_ids = list({artist['id'] for item in recently_played for artist in item['track']['artists']})
        playlist_ids = list({item['context']['uri'].split(':')[2] for item in recently_played
                             if item['context']['uri'] != Playlist.likedSongs and item['context']['type'] == 'playlist' and
                             not item['context']['uri'].split(':')[2].startswith("37i9dQZF1E")})

        # Batch fetch and store songs, albums, and artists
        [Song.store(song) for batch_ids in utils.batch(song_ids, 50)
         for song in sp.tracks(batch_ids)['tracks']]
        [Album.store(album) for batch_ids in utils.batch(album_ids, 20)
         for album in sp.albums(batch_ids)['albums']]
        [Artist.store(artist) for batch_ids in utils.batch(artist_ids, 50)
         for artist in sp.artists(batch_ids)['artists']]
        [Playlist.store(sp.playlist(playlist))
         for playlist in playlist_ids if playlist != Playlist.likedSongs]

        # Return the new playedSongs
        return [song for song in (PlayedSong.store(item) for item in recently_played) if song is not None]
