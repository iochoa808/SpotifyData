from Spotify import sp
from ReadWrite import *
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
       

class Album():

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


class Artist():

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


class Playlist():

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


class User():
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


class PlayedSong():
    def __init__(self, playedDict):
        self.played_at = playedDict['played_at']
        self.track = playedDict['track']['id']
        self.context = {
            'type': playedDict['context']['type'],
            'id': playedDict['context']['uri'].split(':')[2]
        }

        #saveInstanceToCSV(Song(id=playedDict['track']['id']), Song.file_path)
        #saveInstanceToCSV(Album(id=playedDict['track']['album']['id']), Album.file_path)
        #[saveInstanceToCSV(Artist(id=artist['id']), Artist.file_path) for artist in playedDict['track']['artists']]
        # if self.context['type'] == 'playlist': saveInstanceToCSV(Playlist(id=self.context['id']), Playlist.file_path)

    def __str__(self):
        return f"[{self.played_at}] {self.track} played from the {self.context['type']} {self.context['uri']}"


class RecentlyPlayedSongs():
    file_path = "recently_played.csv"

    def __init__(self):
        pass

    def saveRecentlyPlayedSongs(self):
        [saveInstanceToCSV(song, RecentlyPlayedSongs.file_path, unique_attribute='played_at')
         for song in [PlayedSong(song) for song in sp.current_user_recently_played(limit=50)['items'][::-1]]]