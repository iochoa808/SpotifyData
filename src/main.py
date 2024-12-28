from Classes import *
import json


def saveRecentlyPlayedSongs():
    recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()
    [print(i + 1, song) for i, song in enumerate(recentlyPlayedSongs)]
    print(f"\n{len(recentlyPlayedSongs)} new songs stored\n")


#saveRecentlyPlayedSongs()


"""mySong = Song('5Tel0VT0bHJyZnb058mZvU')
print(mySong)
mySong.saveToDB()

song = Song.getFromDB('5Tel0VT0bHJyZnb058mZvU')
print(song)

myAlbum = Album('5ciBtE0wpwlIew7zvUKmd2')
print(myAlbum)
myAlbum.saveToDB()

album = Album.getFromDB('5ciBtE0wpwlIew7zvUKmd2')
print(album)

myArtist = Artist('43JlwunhXm1oqdKyOa2Z9Y')
print(myArtist)
myArtist.saveToDB()

artist = Artist.getFromDB('43JlwunhXm1oqdKyOa2Z9Y')
print(artist)"""



#mySong = Song.getFromDB('02ppMPbg1OtEdHgoPqoqju')
#print(mySong)"""

