from Classes import *


def saveRecentlyPlayedSongs():
    recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()
    [print(i+1, song) for i, song in enumerate(recentlyPlayedSongs)]
    print(f"\n{len(recentlyPlayedSongs)} new songs stored")

#saveRecentlyPlayedSongs()