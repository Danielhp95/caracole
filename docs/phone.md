# caracole on Android

The app keeps a copy of your library on your phone, so it works with the computer off.
The computer does the nightly work. The phone reads, searches, fetches a song when you ask, and syncs with it.

<p>
  <img src="screenshots/phone-library.png" width="260" alt="The library page on a phone">
  <img src="screenshots/phone-chord.png" width="260" alt="A sheet on a phone, with a chord's card at the foot: its shape, its notes and a scale to solo in">
</p>

## Install

- In F-Droid, go to Settings › Repositories › **+**, and scan or paste `https://danielhp95.github.io/caracole/fdroid/repo?fingerprint=B34AD39AD80D6CE828F0885C68FD81816230BB3CB482C9E7BCC6DAD844500397`.
- Then install caracole from F-Droid's list. Or build it yourself: [android/README.md](../android/README.md#build).
- To switch between F-Droid's app and your own build, you must uninstall first, which deletes the phone's library. Sync first.

## Connect it to your computer

- On the computer, run `caracole serve --address 0.0.0.0` ([caracole serve](usage.md#caracole-serve)). It has no sign-in: use it only on a network you trust.
- On the phone, Settings opens at the first start. Type the computer's address, such as `http://192.168.1.20:8737`.
- Tap **Test**. It says how many songs and songbooks the computer has, or what went wrong.
- Then tap the sync button in the bar.

## Sync

- The sync button (two circular arrows) compares the phone and the computer. Each takes what the other changed.
- You choose what to sync: **Library**, **Songbooks** and **Site indexes**.
- A song changed on both sides gets a card. You choose **Phone** or **Computer**. **Cancel** takes and gives nothing.
- Before it takes anything, the phone backs up its library.
- **Sync on Wi-Fi** (Settings) syncs by itself every 6 hours on an unmetered network. It leaves conflicts for you, with a notification.
- If the two can't reach each other, Settings › **Export** makes a `.caracole` file, and **Import a file** syncs with one. An import sends nothing back.
- Details: [Sync from the phone](../android/README.md#sync-from-the-phone) and [the Share tab](usage.md#the-share-tab).

## Offline

- The library page, with its filters and search over your songs.
- Every sheet: transpose, capo, mode, chord diagrams, harmony, pinyin and strumming.
- Kept versions, harmonica tabs and songbooks. The computer's PDFs open in another app.
- Making a songbook, printing and backups need no network. Fetching songs and syncing do.

## Search and Fetch

- The computer builds the site indexes. The phone never does: a sync brings them (**Site indexes**).
- Once they are synced, search finds songs on Ultimate Guitar, LaCuerda, gtptabs.com, MuseScore, harptabs.com and gametabs.net, offline.
- **Fetch** looks a song up now, from the phone itself, at the pace of a lookup on the computer. Mobile data works too.
- The phone then makes the song's pages itself, without a PDF.
- A song you add without Fetch is fetched by the computer's nightly run, after a sync.
- If caracole isn't sure which song it found, you pick the match on the phone.

## Songbooks, versions and Guitar Pro

- Make and change songbooks. The phone makes each songbook's page; the songbook's PDF is the computer's.
- Choose a sheet's version, or how a harmonica tab is read.
- Guitar Pro files are drawn as score and tab and played, with each track shown or muted.
- **Export PDF** opens Android's print dialog, so you can print the sheet in your key or **Save as PDF**.
- Details: [Songbooks, versions and printing](../android/README.md#songbooks-versions-and-printing).

## Share to caracole

- In a music app (Spotify, Apple Music, TIDAL, YouTube, Deezer, Shazam and more), tap **Share**, then **caracole**.
- caracole shows the song it found, with **Fetch**, **Open** and **Edit**. Nothing goes to a tab site before you tap Fetch.
- Share a Guitar Pro file or a score to caracole, and it is filed under the song its name is of. A file with no song yet waits up to 30 days.
- Details: [a song](../android/README.md#sharing-a-song-from-a-music-app), [a file](../android/README.md#sharing-files-to-caracole).

## Backups, alerts and more

- Settings › Backups: **Back up now**, **Export…** (a `.zip`) and **Restore…**. A backup is also made each day, and before a sync takes anything.
- You get a notification when a site blocks a lookup, or when a request fails while the app is in the background.
- Pinch any page to change its text size, from 50% to 250%. **Reset** in Settings sets it back.
- While the app opens, its steps show under the logo. After an update, "Updating your library…" can take a minute.

## Computer and phone

| | Computer | Phone |
|---|---|---|
| Nightly run over your song list | Yes | No |
| Build the site indexes | Yes | No, gets them by sync |
| Search your songs and the sites, offline | Yes | Yes, once synced |
| iReal Pro charts | Yes | No |
| Fetch one song now | Yes | Yes |
| Sheets, songbooks, versions, Guitar Pro | Yes | Yes |
| PDFs | Yes | No, print or Save as PDF |
| Chords from audio, YouTube | Optional | No |
| Music/ and `_inbox/` folders | Yes | No, share files instead |
| Share from another app | No | Yes |
| Library page for other devices | Yes, `caracole serve` | No, this app only |
| Settings (caracole.toml) | Yes | Takes the computer's at each sync |
| Sync | Answers the phone | Starts it, or every 6 hours on Wi-Fi |
| Backups | Yes | Yes |
| Alerts | ntfy | Android notifications |
| Request limits and cooldowns | Its own | Its own |
