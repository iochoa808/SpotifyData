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
    flattenPaths = {}

    def __init__(self, id="", queryDict=None):
        # Use queryDict if provided, otherwise get data with new_id
        if queryDict is None and not id:
            raise ValueError(f"{self.__class__.__name__} requires either 'queryDict' or 'new_id' to initialize.")

        if queryDict is not None:
            # Data already in hand. The old code still searched the CSV here —
            # for id="", a key that cannot match, so it read the entire file
            # every time only to fall through to this same branch.
            self.queryDict = self.adaptPaths(queryDict)
        else:
            csvDict = rw.instanceExists(self.storing_path, id)      # Es busca al CSV
            self.queryDict = csvDict if csvDict else self.adaptPaths(
                self.fetchFromAPI(id)                               # Altrament es busca a la API
            )
        if not self.queryDict:
            raise ValueError(f"Query incorrecta de {self.__class__.__name__}")

        # Id
        self.id = utils.getValueFromNestedDictionary(self.queryDict, self.unique_attribute)
        if not self.id:
            raise ValueError(f"No unique attribute has been found in {self.__class__.__name__}")

        # Name
        self.name = utils.getValueFromNestedDictionary(self.queryDict, self.name_attribute)

    @staticmethod
    @abstractmethod
    def fetchFromAPI(new_id):
        # Abstract method to fetch data using new_id. Subclasses must implement this method.
        pass

    @classmethod
    def store(cls, objDict):
        # Checking if cls.storing_path has been declared
        if cls.storing_path is None:
            raise ValueError(f"{cls.__name__} must define a 'storing_path'.")

        if not rw.idExists(cls.storing_path, objDict.get(cls.unique_attribute)):
            new_instance = cls(queryDict=objDict)  # Dynamically call the subclass constructor
            rw.saveInstanceToCSV(new_instance, cls.storing_path)
            return new_instance
        return None

    @classmethod
    def adaptPaths(cls, query):
        query.update({key: utils.getValueFromNestedDictionary(query, value) for key, value in cls.flattenPaths.items()})
        return query


class Song(SpotifyObject):
    storing_path = "songs.csv"
    flattenPaths = {
        'isrc': "external_ids.isrc",
        'artists_id': "artists.id",
        'album_id': "album.id",
    }

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.album_id = self.queryDict['album_id']
        self.artists_id = self.queryDict['artists_id']
        self.duration_ms = self.queryDict['duration_ms']
        self.explicit = self.queryDict['explicit']
        self.isrc = self.queryDict['isrc']
        self.track_number = self.queryDict['track_number']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists_id)}"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.track(new_id)


class Album(SpotifyObject):
    storing_path = "albums.csv"
    flattenPaths = {
        'tracks': "tracks.items.id",
        'artists_id': "artists.id",
        'images': "images.url"
    }

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.artists_id = self.queryDict['artists_id']
        self.tracks = self.queryDict['tracks']
        self.release_date = self.queryDict['release_date']
        self.images = self.queryDict['images']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {', '.join(artist for artist in self.artists_id)}"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.album(new_id)


class Artist(SpotifyObject):
    storing_path = "artists.csv"
    flattenPaths = {
        'images': "images.url"
    }

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.genres = self.queryDict['genres']
        self.images = self.queryDict['images']

        del self.queryDict

    def __str__(self):
        return f"{self.name}"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.artist(new_id)

    # TODO: BUG DE SPOTIPY | ALBUM_TYPE NO DISCRIMINA ELS TIPUS (ALBUM_TYPE)
    def getAlbums(self):
        return utils.getValueFromNestedDictionary(data=sp.artist_albums(self.id, album_type='album'),
                                                  path='items.id')


class Playlist(SpotifyObject):
    storing_path = "playlists.csv"
    flattenPaths = {
        'owner_id': "owner.id",
        'images': "images.url",
    }

    likedSongs = '0000000000000000000000'
    excludeStore = ['37i9dQZ', '0000000000']

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.collaborative = self.queryDict['collaborative']
        self.description = self.queryDict['description']
        self.owner_id = self.queryDict['owner_id']
        self.images = self.queryDict['images']

        del self.queryDict

    def __str__(self):
        return f"{self.name} by {self.owner_id}"

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.playlist(new_id)

    def getTracks(self, timestamps=True):
        playlistItems = sp.playlist_items(self.id)

        track_ids = utils.getValueFromNestedDictionary(data=playlistItems, path='items.track.id')
        if timestamps:
            track_added = [utils.toTimestamp(added_at) for added_at in
                           utils.getValueFromNestedDictionary(data=playlistItems, path='items.added_at')]
            return list(zip(track_added, track_ids))
        else:
            return track_ids


class User(SpotifyObject):
    storing_path = "users.csv"
    flattenPaths = {
        'name': 'display_name',
        'images': "images.url",
    }

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.images = self.queryDict['images']

        del self.queryDict

    def __str__(self):
        return self.name

    @staticmethod
    def fetchFromAPI(new_id):
        return sp.user(new_id)

    def getPlaylists(self):
        return utils.getValueFromNestedDictionary(data=sp.user_playlists(self.id), path='items.id')


class PlayedSong(SpotifyObject):
    storing_path = "recently_played.csv"

    flattenPaths = {
        'name': "track.name",
        'track_id': "track.id",
        'track_popularity': "track.popularity",
        'context_type': "context.type",
        'context_id': "context.uri"
    }

    def __init__(self, id="", queryDict=None):
        super().__init__(id, queryDict)

        self.track_id = self.queryDict['track_id']
        self.track_popularity = self.queryDict['track_popularity']
        self.context_type = self.queryDict['context_type']
        self.context_id = self.queryDict['context_id']

        del self.queryDict

    def __str__(self):
        return f"[{self.playedAt()}] {self.name} played from the {self.context_type} {self.context_id}"

    @staticmethod
    def fetchFromAPI(new_id):
        raise Exception(f"Can't get {__class__.__name__} information from API")

    def playedAt(self):
        return utils.toDateTime(self.id)

    def isRecommended(self):    # TODO: PROVAR SI FUNCIONA EN CONTEXT
        # Listening from playlist       ==>     Track added after listening & is in playlist
        if self.context_type == 'playlist':
            return any(playlistTrack[0] >= self.id for playlistTrack in Playlist(self.context_id).getTracks()
                       if playlistTrack[1] == self.track_id)    # Track in playlist

        # Listening from album          ==>     Track not in album tracks
        elif self.context_type == 'album':
            return self.track_id not in Album(self.context_id).tracks

        # Listening from artist         ==>     Artist not in song's artists
        elif self.context_type == 'artist':
            return self.context_id not in Song(self.track_id).artists_id

        else:
            print("LISTENING FROM ANOTHER CONTEXT: ", self.context_type)


class RecentlyPlayedSongs:

    def __init__(self):
        pass

    @staticmethod
    def fetchSinceLastStored(max_pages=20):
        """Every play Spotify still holds that is newer than the last stored one.

        Measured against the live API: Spotify retains roughly 50 plays and no
        more. Asking for a week returns one page of 50 and an empty second page,
        so the cursor does NOT lift that ceiling — only a shorter polling
        interval does, which is why the schedule now runs hourly (the busiest
        2-hour window on record held 44 plays, uncomfortably close to 50).

        What the cursor does buy: `after` is exclusive, so a run sees only
        genuinely new plays instead of re-examining the same 50 every time, the
        items arrive oldest-first, and the code already works if Spotify ever
        widens the window.
        """
        after = rw.latestId(PlayedSong.storing_path)

        # Spotify's cursor is in milliseconds, and `after` is exclusive.
        page = sp.current_user_recently_played(
            limit=50, after=(after * 1000) if after else None
        )

        items, pages = [], 0
        while page and pages < max_pages:
            items.extend(page['items'])
            pages += 1
            page = sp.next(page) if page.get('next') else None

        # Oldest first, so a partial failure still leaves a contiguous history.
        items.sort(key=lambda item: item['played_at'])
        return items

    @staticmethod
    def saveRecentlyPlayedSongs():
        # Retrieve recently played songs
        recently_played = RecentlyPlayedSongs.fetchSinceLastStored()

        # Tractar recently played
        recently_played = [
            {
                **song,
                'context': {'type': 'playlist', 'uri': Playlist.likedSongs} if not song['context'] else
                {'type': song['context']['type'], 'uri': song['context']['uri'].split(':')[2]},
                'id': utils.toTimestamp(song['played_at'])
            }
            for song in recently_played
        ]

        # Collect sets of all IDs for fetching
        song_ids = list(set(utils.getValueFromNestedDictionary(recently_played, 'track.id')))
        album_ids = list(set(utils.getValueFromNestedDictionary(recently_played, 'track.album.id')))
        artist_ids = list(set([item for lst_id in utils.getValueFromNestedDictionary(recently_played, 'track.artists.id') for item in lst_id]))
        playlist_ids = list({item['context']['uri'] for item in recently_played
                             if not any(item['context']['uri'].startswith(exclude) for exclude in Playlist.excludeStore) and
                             item['context']['type'] == 'playlist'})

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
