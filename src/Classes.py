from Spotify import sp
import ReadWrite as rw
import utils
from abc import ABC, abstractmethod
from datetime import datetime, timedelta


# Abstract class
class SpotifyObject(ABC):

    storing_path = None

    # Both can be dictionary paths separated by '.'
    unique_attribute = 'id'
    name_attribute = 'name'

    def __init__(self, id="", queryDict=None):
        # Use queryDict if provided, otherwise get data with new_id
        if queryDict is None and not id:
            raise ValueError(f"{self.__class__.__name__} requires either 'queryDict' or 'new_id' to initialize.")

        csvDict = rw.instanceExists(self.storing_path, id)      # Es busca al CSV
        self.queryDict = csvDict if csvDict else (              # Si existeix al CSV
            self.flatten_dict(queryDict) if queryDict else (    # Altrament si s'ha donat queryDict
                self.flatten_dict(self.fetchFromAPI(id))        # Altrament es busca a la API
            )
        )
        if not self.queryDict:
            raise ValueError(f"Query incorrecta de {self.__class__.__name__}")

        # Id
        self.id = utils.access_dict_path(self.queryDict, self.unique_attribute)
        if not self.id:
            raise ValueError(f"No unique attribute has been found in {self.__class__.__name__}")

        # Name
        self.name = utils.access_dict_path(self.queryDict, self.name_attribute)

    @staticmethod
    @abstractmethod
    def fetchFromAPI(new_id):
        # Abstract method to fetch data using new_id. Subclasses must implement this method.
        pass

    @staticmethod
    @abstractmethod
    def flatten_dict(query):
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


class Song(SpotifyObject):

    storing_path = "songs.csv"

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.explicit = self.queryDict['explicit']
        self.duration_ms = self.queryDict['duration_ms']
        self.popularity = self.queryDict['popularity']
        self.album_id = self.queryDict['album_id']
        self.artists_id = self.queryDict['artists_id']
        self.track_number = self.queryDict['track_number']
        self.isrc = self.queryDict['isrc']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists_id)}"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.track(new_id)

    @staticmethod
    def flatten_dict(query):
        d = utils.flatten_dict(query)
        d['isrc'] = d['external_ids_isrc']
        d['artists_id'] = [item['id'] for item in d['album_artists']]
        return d


class Album(SpotifyObject):

    storing_path = "albums.csv"

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.release_date = self.queryDict['release_date']
        self.artists_id = self.queryDict['artists_id']
        self.tracks = self.queryDict['tracks']
        self.popularity = self.queryDict['popularity']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists_id)}"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.album(new_id)

    @staticmethod
    def flatten_dict(query):
        tracks, results = [], query['tracks']
        while results:
            tracks.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None

        query['tracks'] = tracks
        query['artists_id'] = [item['id'] for item in query['artists']]
        return query


class Artist(SpotifyObject):

    storing_path = "artists.csv"

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.followers = self.queryDict['followers']
        self.genres = self.queryDict['genres']
        self.popularity = self.queryDict['popularity']

        del self.queryDict

    def __str__(self):
        return f"{self.name} with {self.followers} followers"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.artist(new_id)

    @staticmethod
    def flatten_dict(query):
        query['followers'] = query['followers']['total']
        return query

    def getAlbums(self):
        # TODO: BUG DE SPOTIPY | ALBUM_TYPE NO DISCRIMINA ELS TIPUS (ALBUM_TYPE)
        # Get list with all tracks
        albums, results = [], sp.artist_albums(self.id, album_type='album')
        while results:
            albums.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None
        return albums


class Playlist(SpotifyObject):

    storing_path = "playlists.csv"
    likedSongs = '0000000000000000000000'

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.description = self.queryDict['description']
        self.followers = self.queryDict['followers']
        self.owner = self.queryDict['owner']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {self.owner} and {self.followers} followers"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.playlist(new_id)

    @staticmethod
    def flatten_dict(query):
        query['followers'] = query['followers']['total']
        query['owner_id'] = query['owner']['id']
        return query

    def getTracks(self):
        tracks, results = [], sp.playlist_items(self.id)
        while results:
            tracks.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None
        return tracks


class User(SpotifyObject):

    storing_path = "users.csv"
    name_attribute = 'display_name'

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.followers = self.queryDict['followers']

        del self.queryDict

    def __str__(self):
        return self.name

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.user(new_id)

    @staticmethod
    def flatten_dict(query):
        return query

    def getPlaylists(self):
        playlists, results = [], sp.user_playlists(self.id)
        while results:
            playlists.extend(item['id'] for item in results['items'])
            results = sp.next(results) if results['next'] else None
        return playlists


class PlayedSong(SpotifyObject):

    storing_path = "recently_played.csv"
    unique_attribute = 'played_at'
    name_attribute = "track_name"

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.track_id = self.queryDict['track_id']
        self.context_type = self.queryDict['context_type']
        self.context_id = self.queryDict['context_id']

        del self.queryDict

    def __str__(self):
        return f"[{self.playedAt()}] {self.name} played from the {self.context_type} {self.context_id}"

    @staticmethod
    def fetchFromAPI(new_id):
        raise Exception(f"Can't get {__class__.__name__} information from API")

    @staticmethod
    def flatten_dict(query):
        query = utils.flatten_dict(query)
        query['context_id'] = query['context_uri'].split(':')[2]
        return query

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
