# PDFs and songbooks

Every sheet gets a PDF. A songbook collects some of your songs in order, each in the key you
play it, as one PDF and one page for the phone.

## PDFs

- `sheet.pdf` sits beside each sheet: chord diagrams, then the song in two columns.
- **Export PDF**, under ⋯ on a sheet, gives you the song as you are playing it: your key, capo,
  chord changes and instrument. On a ukulele it draws ukulele diagrams, on a piano keyboards.
- **Make mine** in that dialog saves those choices as the song's default. Its PDF, its page and
  your songbooks then start from them.
- Export PDF downloads with `caracole serve`. Opened as a file, the page shows the command to run.
- A Chinese sheet gets a Simplified PDF and a Traditional one. They need a CJK font, which the
  Nix package includes.

Fonts: [in the PDFs](usage.md#fonts-in-the-pdfs), [for Chinese sheets](usage.md#fonts-for-chinese-sheets).

## Songbooks

![The Songbooks tab: a set list, each song with the key it is played in](screenshots/songbooks.png)

To make one, press **Select** in the library (or **+ New songbook** on the Songbooks tab), tick
the songs in order, name it, and press **Make songbook**.

Each songbook is a folder in `Library/_songbooks/` with three files:

| File | What it is |
|---|---|
| `songbook.pdf` | A title page, the contents, then every song |
| `songbook.html` | The same for a phone: contents, then each song as a sheet |
| `songbook.cho` | ChordPro, for apps such as SongbookPro or OnSong |

On the Songbooks tab you reorder songs, remove them, add more, and set each song's key, mode,
capo and instrument. Changing them needs `caracole serve`. A song with no sheet yet keeps its
place, and the contents mark it as missing.

<img src="screenshots/songbook-pdf.png" width="440" alt="A page of a songbook's PDF: chord diagrams, then the verses with the chords over the words">

From a terminal:

```sh
caracole songbook make "Friday set" "Oasis - Wonderwall" "Eagles - Hotel California"
caracole songbook set "Friday set" "Oasis - Wonderwall" --key G --capo 2
caracole songbook list
```

All the sub-commands: [caracole songbook](usage.md#caracole-songbook). The file format:
[Songbooks](usage.md#songbooks).

## On the phone

You make and change songbooks in the app, and it builds their phone pages offline. It makes no
PDF of its own. **Export PDF** opens Android's print dialog, where you can print or save as PDF.
PDFs synced from the computer open in another app.
