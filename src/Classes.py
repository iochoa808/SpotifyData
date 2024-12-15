import time

from Spotify import sp
import ReadWrite as rw
from utils import *


class Song:

    file_path = "songs.csv"

    def __init__(self, id="", queryDict={}):
        if len(queryDict) == 0 and len(id) == 0:
            raise Exception("SONG NOT INITIATED PROPERLY")
        if len(id) > 0:
            queryDict = sp.track(id)
    
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
            rw.saveInstanceToCSV(Song(queryDict=songDict), Song.file_path)
       

class Album:

    file_path = "albums.csv"

    def __init__(self, id="", queryDict={}):
        if len(queryDict) == 0 and len(id) == 0:
            raise Exception("ALBUM NOT INITIATED PROPERLY")
        if len(id) > 0:
            queryDict = sp.album(id)

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

        return new_tracks + self.getSongs(ofst=ofst+50)

    @staticmethod
    def store(albumDict):
        if not rw.instanceExists(Album.file_path, albumDict['id']):
            rw.saveInstanceToCSV(Album(queryDict=albumDict), Album.file_path)


class Artist:

    file_path = "artists.csv"

    def __init__(self, id="", queryDict={}):
        if len(queryDict) == 0 and len(id) == 0:
            raise Exception("ARTIST NOT INITIATED PROPERLY")
        if len(id) > 0:
            queryDict = sp.artist(id)

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

        return new_albums + self.getAlbums(ofst=ofst+20)

    @staticmethod
    def store(artistDict):
        if not rw.instanceExists(Artist.file_path, artistDict['id']):
            rw.saveInstanceToCSV(Artist(queryDict=artistDict), Artist.file_path)


class Playlist:

    file_path = "playlists.csv"

    def __init__(self, id="", queryDict={}):
        if len(queryDict) == 0 and len(id) == 0:
            raise Exception("PLAYLIST NOT INITIATED PROPERLY")
        if len(id) > 0:
            queryDict = sp.playlist(id)

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

        return new_tracks + self.getSongs(ofst=ofst+100)

    @staticmethod
    def store(playlistDict):
        if not rw.instanceExists(Playlist.file_path, playlistDict['id']):
            rw.saveInstanceToCSV(Playlist(queryDict=playlistDict), Playlist.file_path)


class User:
    def __init__(self, id="", queryDict={}):
        if len(queryDict) == 0 and len(id) == 0:
            raise Exception("USER NOT INITIATED PROPERLY")
        if len(id) > 0:
            queryDict = sp.track(id)

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
            rw.saveInstanceToCSV(PlayedSong(playedDict=playedSongDict), PlayedSong.file_path)


class RecentlyPlayedSongs:

    file_path = "recently_played.csv"

    def __init__(self):
        pass

    @staticmethod
    def saveRecentlyPlayedSongs():
        # Retrieve recently played songs
        recently_played = sp.current_user_recently_played(limit=50)['items'][::-1]

        # TODO: PROVAR OUTPUT song_ids I SEGURAMENT ES POT POSAR EN UN SET
        song_ids = [item['track']['id'] for item in recently_played]
        album_ids = list({item['track']['album']['id'] for item in recently_played})
        artist_ids = list({artist['id'] for item in recently_played for artist in item['track']['artists']})

        print(f"song_ids: {len(song_ids)}\nalbum_ids: {len(album_ids)}\nartist_ids: {len(artist_ids)}")

        # TODO: PROVAR ABANS SI FUNCIONA UN DELS LST COMPREHESION
        # TODO: SENSE VARIABLE SEMBLA QUE NO TÈ EFECTE?¿
        # Batch fetch songs, albums, and artists
        song_cache = {Song.store(song) for batch_ids in batch(song_ids, 50)
                      for song in sp.tracks(batch_ids)['tracks']}
        album_cache = {Album.store(album) for batch_ids in batch(album_ids, 20)
                       for album in sp.albums(batch_ids)['albums']}
        # TODO: CREC QUE ARTISTS VA EN LLISTES, PROVAR COM ÉS L'OUTPUT
        artist_cache = {Artist.store(artist) for batch_ids in batch(artist_ids, 50)
                        for artist in sp.artists(batch_ids)['artists']}

        [PlayedSong.store(item) for item in recently_played]


# TODO: GPT
"""
from itertools import islice

# Utility function to split a list into batches
def batch(iterable, n=20):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch

class PlayedSong:
    def __init__(self, playedDict, song_cache, album_cache, artist_cache):
        self.played_at = playedDict['played_at']
        self.track = playedDict['track']['id']
        self.context = {
            'type': playedDict['context']['type'], 
            'id': playedDict['context']['uri'].split(':')[2] if playedDict['context'] and 'uri' in playedDict['context'] else None
        }
        
        # Save song using cached data
        if self.track in song_cache:
            saveInstanceToCSV(Song(song_cache[self.track]), Song.file_path)
        
        # Save album using cached data
        album_id = playedDict['track']['album']['id']
        if album_id in album_cache:
            saveInstanceToCSV(Album(album_cache[album_id]), Album.file_path)

        # Save artists using cached data
        for artist in playedDict['track']['artists']:
            artist_id = artist['id']
            if artist_id in artist_cache:
                saveInstanceToCSV(Artist(artist_cache[artist_id]), Artist.file_path)

    def __str__(self):
        return f"[{self.played_at}] {self.track} played from the {self.context['type']} {self.context['id']}"


class RecentlyPlayedSongs:
    file_path = "recently_played.csv"

    def __init__(self):
        pass

    def saveRecentlyPlayedSongs(self):
        # Retrieve recently played songs
        recently_played = sp.current_user_recently_played(limit=50)['items'][::-1]

        # Collect all IDs for batching
        song_ids = [item['track']['id'] for item in recently_played]
        album_ids = list({item['track']['album']['id'] for item in recently_played})
        artist_ids = list({artist['id'] for item in recently_played for artist in item['track']['artists']})

        # Batch fetch songs, albums, and artists
        song_cache = {song['id']: song for batch_ids in batch(song_ids, 50) for song in sp.tracks(batch_ids)['tracks']}
        album_cache = {album['id']: album for batch_ids in batch(album_ids, 20) for album in sp.albums(batch_ids)['albums']}
        artist_cache = {artist['id']: artist for batch_ids in batch(artist_ids, 50) for artist in sp.artists(batch_ids)['artists']}

        # Save each played song
        for item in recently_played:
            song_instance = PlayedSong(item, song_cache, album_cache, artist_cache)
            saveInstanceToCSV(song_instance, RecentlyPlayedSongs.file_path, unique_attribute='played_at')

"""