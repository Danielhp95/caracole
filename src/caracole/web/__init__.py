"""``caracole serve``: the library page over HTTP, with a form to request songs.

A small server from the standard library (``http.server``), in these parts:

- security.py: the host names it answers to (a guard against DNS rebinding),
  the cross-origin check every write passes, and the form token. There is no
  sign-in: whoever can reach the server may use it.
- files.py: the library's files, opened without following a link, and only
  the kinds caracole keeps there; and the pages caracole wrote there (the
  sheet viewers, a kept version's among them, and the songbooks' pages), only
  while each is still as written.
- jobs.py: the queue. A request runs the ``caracole`` command line in a child
  process, one command at a time: ``caracole add``, then, to fetch the song
  now, ``match``, ``fetch --song`` and ``render``; a pick of a review's
  candidate is ``caracole review --song``. Each takes caracole's lock
  and keeps the pause after the last request any caracole sent, as it does
  from a terminal, so the server is never more aggressive than the CLI.
- top.py: the header every page caracole serve writes itself opens with, one line: the "¿" and the name, the
  page's title, its links.
- status.py: the one line a request shows on its song's card, read from its
  job's steps and, once it is over, from the song's state; outcome.py: the
  requests page's own view of it, the running one's steps and a finished
  one's outcome, reason and next step.
- app.py: the router, as a function from a request to a response, what
  every route shares (the answers' shapes, ``Refused``, the database, the
  queue) and the checks every request passes; server.py puts it on a socket.
  Each area's routes are a module: library_routes.py (the library page,
  requests, Fetch now), review_routes.py (the picker), jobs_routes.py (the
  requests page, its Cancel and Try again, /jobs.json, /api/jobs), search_routes.py (the lookup page,
  search as you type, lookups, LaCuerda's pages read and its own search), remove_routes.py, songbook_routes.py,
  export_routes.py (a sheet's PDF in the version its viewer was left in,
  downloaded at once; Make this my version),
  versions_routes.py (one of Ultimate Guitar's versions of a song's sheet made
  the one, or kept beside it), harmonica_routes.py (how a harmonica tab is
  read: the readings caracole weighs, one pinned in overrides.toml),
  guitar_routes.py (a song's Guitar Pro file
  drawn and played in the browser: guitar_page.py, with alphaTab's bundle,
  alphatab.py) and offline_routes.py (``/api/offline``, what caracole's Android
  app copies of the library to read it offline: every file the library page
  caracole wrote links to, as the server sends each).
  pages.py: the pages it writes itself.
- songbooks.py: the songbook forms, each queued as its ``caracole songbook``
  command (songbook_routes.py). Each songbook's page is one of the pages
  caracole wrote that app.py's ``written_pages`` serves.

The server itself never takes caracole's lock. It reads the database, as
``caracole search`` does, and writes only wanted.txt, as ``caracole add`` does
before it waits for the lock.
"""
