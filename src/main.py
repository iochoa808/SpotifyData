from Classes import *


def saveRecentlyPlayedSongs():
    recentlyPlayedSongs = RecentlyPlayedSongs.saveRecentlyPlayedSongs()
    [print(i+1, song) for i, song in enumerate(recentlyPlayedSongs)]
    print(f"\n{len(recentlyPlayedSongs)} new songs stored")


saveRecentlyPlayedSongs()
#recently_played = sp.current_user_recently_played(limit=50)['items'][::-1]


#playlist = Playlist(id='6bYdhADwAwPJNXrc2i3nSY')
#print(playlist.getTracks())