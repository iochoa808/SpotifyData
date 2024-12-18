from Spotify import sp
import ReadWrite as rw
import utils
from abc import ABC, abstractmethod
from datetime import datetime, timedelta


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
        self.queryDict = queryDict if queryDict else self.fetchFromAPI(new_id)
        if not self.queryDict:
            raise ValueError(f"Query incorrecta de {self.__class__.__name__}")

        # id for most, played_at for recentlyPlayed
        self.id = self.queryDict[self.__class__.unique_attribute]
        if not self.id:
            raise ValueError(f"No unique attribute has been found in {self.__class__}")

        # name for most, display_name for user
        self.name = self.queryDict[self.__class__.name_attribute] \
            if self.__class__.name_attribute is not None else None

    @abstractmethod
    def fetchFromAPI(self, new_id):
        # Abstract method to fetch data using new_id. Subclasses must implement this method.
        pass

    @classmethod
    def store(cls, objDict):
        # Checking if cls.storing_path has been declared
        if cls.storing_path is None:
            raise ValueError(f"{cls.__name__} must define a 'storing_path'.")

        if not rw.instanceExists(cls.storing_path, unique_value=objDict.get(cls.unique_attribute)):
            new_instance = cls(queryDict=objDict)  # Dynamically call the subclass constructor
            rw.saveInstanceToCSV(new_instance, cls.storing_path)
            return new_instance
        return None

    @classmethod
    def getFromUniqueValue(cls, unique_value):
        if cls.storing_path is None:
            raise ValueError(f"{cls.__name__} must define a 'storing_path'.")

        #return rw.instanceExists(cls.storing_path, unique_value=unique_value)
        #print(type(res), res)
        # <class 'dict'> {'id': '3AA28KZvwAUcZuOKwyblJQ', 'name': 'Gorillaz', 'followers': '12485975', 'genres': "['alternative hip hop', 'modern rock', 'rock']", 'popularity': '81'}


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

    def fetchFromAPI(self, new_id):
        return sp.track(new_id)


class Album(SpotifyObject):

    storing_path = "albums.csv"

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.release_date = self.queryDict['release_date']
        self.artists = [artist['id'] for artist in self.queryDict['artists']]

        # Get list with all tracks
        self.tracks, results = [], self.queryDict['tracks']
        while results:
            self.tracks.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists)}"

    def fetchFromAPI(self, new_id):
        return sp.album(new_id)


class Artist(SpotifyObject):

    storing_path = "artists.csv"

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        print(self.queryDict['followers']['total'], type(self.queryDict['followers']['total']))

        self.followers = self.queryDict['followers']['total']
        self.genres = self.queryDict['genres']
        self.popularity = self.queryDict['popularity']

        del self.queryDict

    def __str__(self):
        return self.name

    def fetchFromAPI(self, new_id):
        return sp.artist(new_id)

    def getAlbums(self):
        # TODO: BUG DE SPOTIPY | ALBUM_TYPE NO EXCLUEIX ELS TIPUS
        # Get list with all tracks
        albums, results = [], sp.artist_albums(self.id, album_type='album,single')
        while results:
            albums.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None
        return albums


class Playlist(SpotifyObject):

    storing_path = "playlists.csv"
    likedSongs = '0000000000000000000000'

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.description = self.queryDict['description']
        self.followers = self.queryDict['followers']['total']
        self.owner = self.queryDict['owner']['id']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {self.owner} with {self.total_tracks} songs"

    def fetchFromAPI(self, new_id):
        return sp.playlist(new_id)

    def getTracks(self):
        tracks, results = [], sp.playlist_items(self.id)
        while results:
            tracks.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None
        return tracks


class User(SpotifyObject):

    storing_path = "users.csv"
    name_attribute = 'display_name'

    def __init__(self, queryDict=None, new_id=""):
        super().__init__(queryDict=queryDict, new_id=new_id)

        self.followers = self.queryDict['followers']

        del self.queryDict

    def __str__(self):
        return self.name

    def fetchFromAPI(self, new_id):
        return sp.user(new_id)

    def getPlaylists(self):
        playlists, results = [], sp.user_playlists(self.id)
        while results:
            playlists.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None
        return playlists


class PlayedSong(SpotifyObject):

    storing_path = "recently_played.csv"
    unique_attribute = 'played_at'
    name_attribute = None

    def __init__(self, queryDict):
        super().__init__(queryDict=queryDict)

        self.track = self.queryDict['track']['id']
        self.context = {
            'type': self.queryDict['context']['type'],
            'id': self.queryDict['context']['uri'].split(':')[2]
        }

        del self.queryDict

    def __str__(self):
        return f"[{self.playedAt()}] {self.track} played from the {self.context['type']} {self.context['id']}"

    def fetchFromAPI(self, new_id):
        raise Exception(f"This method doesn't exist in {self.__name__}")

    def playedAt(self):
        return datetime.fromtimestamp(int(self.id.split('.')[0])) + timedelta(hours=1)


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
        # Convertir played_at a unix timestamp
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
