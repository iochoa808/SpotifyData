from Classes import *


def saveRecentlyPlayedSongs():
    recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()
    [print(i+1, song) for i, song in enumerate(recentlyPlayedSongs)]
    print(f"\n{len(recentlyPlayedSongs)} new songs stored")


#saveRecentlyPlayedSongs()

#song = sp.track('60SvhHtwefT0e2G7i7kOH3')

album = sp.album('70hX7IYqmUGV97OXs2v848')

tracks = utils.access_dict_pathNext(album, "tracks.items.id")

print(len(tracks))




