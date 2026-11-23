# Search

The library page's search box finds your songs, and the songs the sites have, as you type. It
reads caracole's own copy of each site's catalogue, so it asks no site, but in two cases below.

![The library page searching "traditional": four songs you have and three you can get, under one artist](screenshots/library.png)

## What you can type

- Opened as a file, the page searches your songs; served, or in the Android app, the sites too.
- Words of the title, the artist or both, case and accents aside: "musica" finds "De Música Ligera".
- A title's initials: "wywh" finds "Wish You Were Here". Chinese by pinyin too: "banma" finds 斑马斑马.
- A key ("a minor", "F# major", "bbm") filters your songs alone: the sites' catalogues know no keys.
- Served, a chord progression ("vi IV I V", "andalusian") finds your songs that play it, in any key.
- Served, a misspelling that matches nothing well suggests what it is close to: "lynrd" is Lynyrd Skynyrd.

## Filter and Sort

- **Filter**: Status (found, wanted, needs review), Matches (Chords, Guitar, Ukulele, Harmonica, Score), Key.
- Status and Matches count the songs each choice shows. The filters on are tags; Clear lets them go.
- Over the sites' results, Matches keeps their songs too: Harmonica keeps harptabs.com's tabs.
- **Sort**: by artist, by title, or by when added.
- Sorted by artist or title, with more than 40 songs, a row of letters takes you to each letter.
- The address keeps your search, filters and sort, so a bookmark opens the page as you left it.
- Details: [Library/index.html](usage.md#libraryindexhtml).

## The results

- They come under artist headers: "Estopa · you have 2 · UG 60 · LaCuerda 159 · Guitar Pro 12".
- Your songs first. A song several sites have is one line: "chords ×9 · LaCuerda ×3 · Guitar Pro file".
- "+ 57 more by Estopa" lists the rest of an artist's songs. An artist's name searches for them.
- A badge marks a row for one instrument (Ukulele, Harmonica, Score…); a song you removed has **Add again**.
- When the sites have nothing, the query becomes a line with **Request**, to ask for the song by name.

## A result's line

- **Fetch**, the download icon near its end, looks the song up now. Enter never does: it moves to the first result.
- Its name or blank space opens what each site has: Ultimate Guitar's versions, LaCuerda's and gtptabs.com's pages.
- From there you can fetch one Ultimate Guitar version, or LaCuerda's sheet, as the song's sheet.
- While it runs, the line shows its steps ("Sheet · Ultimate Guitar · 3 of 7"); once a sheet is kept, it is your song's.
- **Add for tonight**, folded under it, leaves the song to the nightly run. A song of yours opens its card.

![A song's card open beside the list](screenshots/card.png)

## Paste a link

- A YouTube video's link searches nothing: caracole reads the video's title, channel and length, once.
- Check the Artist and Title it guesses, then press **Add and make the sheet**.
- An Ultimate Guitar link is read once too: a tab offers **Fetch this version**, an artist their songs.
- Opened as a file, a YouTube link gives the command to run, and a UG link is plain words.

## The two requests a search may send

- **LaCuerda's own search**, for a query neither your songs nor caracole's copy of LaCuerda answer well.
- It goes once the box is still for 1.5 s, at most 20 an hour; Enter sends it at once, Ask LaCuerda by hand.
- **YouTube's first video**, where caracole can make a sheet from a video and the sites have no sheet.
- Its row shows the thumbnail, title and channel; **Make sheet** fills in the request form for you to send.
- Each is a request in the Journal, a query once in 30 days. Nothing else asks before you press a button.

## The marks under the box

- First your songs, by caracole's logo, then each site that found something: its icon and how many.
- One quiet mark, "0 on 4 more", stands for the rest; its tooltip says each one's state.
- Amber with a pie cut: caracole is still reading that site. A site that blocks caracole says so.
- Details: [caracole serve](usage.md#caracole-serve).

## On the command line

- `caracole search QUERY` searches your library and the sites' catalogues, and sends no request.
- Each hit comes with the line to paste, such as `caracole add "Stone Temple Pilots" "Creep"`.
- `--add N` adds hit N, `--artist NAME` lists an artist's songs, `--title TITLE` the songs of that title.
- `--key KEY` keeps your songs in that key; `--progression "vi IV I V"` lists those that play it.
- Details: [caracole search](usage.md#caracole-search).
