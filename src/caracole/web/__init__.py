"""``caracole serve``: the library page over HTTP, with a form to request songs.

A small server from the standard library (``http.server``), in these parts:

- security.py: the host names it answers to (a guard against DNS rebinding),
  the cross-origin check every write passes, and the tokens.
- files.py: the library's files, opened without following a link, and only
  the kinds caracole keeps there; and the pages caracole wrote there (the
  sheet viewers), only while each is still as written.
- jobs.py: the queue. A request runs the ``caracole`` command line in a child
  process, one command at a time: ``caracole add``, then, to fetch the song
  now, ``match``, ``fetch --song`` and ``render``. Each takes caracole's lock
  and keeps the pause after the last request any caracole sent, as it does
  from a terminal, so the server is never more aggressive than the CLI.
- status.py: the one line a request shows on its song's card and on /jobs,
  read from its job's steps and, once it is over, from the song's state.
- app.py: the routes, as a function from a request to a response, and
  server.py, which puts it on a socket; pages.py, the pages it writes itself.

The server itself never takes caracole's lock. It reads the database, as
``caracole search`` does, and writes only wanted.txt, as ``caracole add`` does
before it waits for the lock.
"""
