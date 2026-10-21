"""``caracole serve``: the library page over HTTP, with a form to request songs.

A small server from the standard library (``http.server``), in these parts:

- security.py: the host names it answers to (a guard against DNS rebinding),
  the cross-origin check every write passes, and the tokens.
- files.py: the library's files, opened without following a link, and only
  the kinds caracole keeps there; and the pages caracole wrote there (the
  sheet viewers and the songbooks' pages), only while each is still as written.
- jobs.py: the queue. A request runs the ``caracole`` command line in a child
  process, one command at a time: ``caracole add``, then, to fetch the song
  now, ``match``, ``fetch --song`` and ``render``; a pick of a review's
  candidate is ``caracole review --song``. Each takes caracole's lock
  and keeps the pause after the last request any caracole sent, as it does
  from a terminal, so the server is never more aggressive than the CLI.
- status.py: the one line a request shows on its song's card and on /jobs,
  read from its job's steps and, once it is over, from the song's state.
- app.py: the router, as a function from a request to a response, what
  every route shares (the answers' shapes, ``Refused``, the database, the
  queue) and the checks every request passes; server.py puts it on a socket.
  Each area's routes are a module: library_routes.py (the library page,
  requests, Fetch now), review_routes.py (the picker), jobs_routes.py (the
  requests page, /jobs.json, /api/jobs), search_routes.py (the lookup page,
  search as you type, lookups), remove_routes.py, songbook_routes.py and
  export_routes.py (a sheet's PDF in the version its viewer was left in).
  pages.py: the pages it writes itself.
- songbooks.py: the songbook forms, each queued as its ``caracole songbook``
  command (songbook_routes.py). Each songbook's page is one of the pages
  caracole wrote that app.py's ``written_pages`` serves.

The server itself never takes caracole's lock. It reads the database, as
``caracole search`` does, and writes only wanted.txt, as ``caracole add`` does
before it waits for the lock.
"""
