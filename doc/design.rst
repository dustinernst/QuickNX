============
Neatx design
============

.. contents:: :depth: 3


Overview
========

There are three major components in Neatx:

nxserver-login
  Responsible for protocol version negotiation and user login. If user login
  was successful, ``nxserver`` takes over.

nxserver
  Responsible for client/server communication once user is logged in (session
  list/start/resume/stop).

nxnode
  Starts ``nxagent``, monitors its output for state changes and errors.

Although not part of Neatx, these components are required for its use:

nxagent
  A headless version of Xorg's X11 server, patched by NoMachine's NXLibs to add
  NX support.

nxclient
  The remote desktop client which runs on the user's desktop/laptop, similar to
  clients for VNC and RDP.


Detailed Design
===============


nxserver-login-wrapper
----------------------
``nxserver-login-wrapper`` functions as a last-resort handler for log messages.
It starts ``nxserver-login`` and redirects stderr to itself. Everything read
from ``nxserver-login``'s stderr is sent to syslog.


nxserver-login
--------------
This is set as the login shell for the ``nx`` user.

On startup, it sends out a greeting banner (e.g. ``HELLO NXSERVER - Version
3.0.0 GPL``) followed by the standard NX prompt (``NX> 105`` ).
``nxserver-login`` checks that the protocol version requested by the client is
supported: the first two significant numbers in the protocol version match
those of the server (e.g. ``2.1.8`` matches ``2.1.10``, but ``3.1.0`` does not
match ``3.0.0``.).

When it receives ``login`` from the client, ``nxserver-login`` prompts for the
username and password, and invokes ``nxserver`` via a authentication method
specified in the configuration. If authentication fails an appropriate error
message is sent to the client, to be displayed to the user.


nxserver
--------
This component takes care of most of the client/server communication.  By the
time it is connected to the client, the user has already been authenticated, so
it doesn't have to concern itself with login/auth. ``nxserver`` receives the
``listsession``, ``startsession``, ``restoresession``, ``attachsession`` and
``terminate`` commands, parses the arguments, and handles the request:

``listsession``
   ``nxserver`` queries the `session database`_ for any sessions matching the
   request arguments (e.g. session type, owner, state), and prints out the info
   in the session list format.

``startsession``
   ``nxserver`` takes the parsed arguments, and starts ``nxnode``. It then
   connects to ``nxnode`` and tells it to start a session with a generated
   unique session id. After doing so, ``nxserver`` polls the `session
   database`_ until a session with that id appears and is in the ``running``
   state.

   If the session does not appear (or does not become ``running``) within a
   timeout period, ``nxserver`` reports to ``nxclient`` that the session startup
   has failed.

   If the session does appear and become ``running``, ``nxserver`` sends the
   session info to ``nxclient`` (session id, display number, type, auth cookie,
   etc). ``nxserver`` then stores the port number that the session display is
   listening on. When the ``nxclient`` acknowledges the info with the ``bye``
   command, ``nxserver`` execs ``netcat`` to connect stdin/stdout to the session
   display port. After this point, the client is talking directly to the
   session, and the session opens up on the user's desktop.

``restoresession``
   ``nxserver`` queries the `session database`_ for any matching sessions
   (similar to ``listsession``, but a session id is a mandatory parameter for
   this). If a session is found, it connects to the corresponding ``nxnode``
   and tells it to restore the session. Once the session is ready, ``nxserver``
   continues in exactly the same way as with ``startsession`` (i.e. sending the
   session info to ``nxclient``, then connecting the client to the session via
   ``netcat``).

``attachsession``
   This command is used for session shadowing (i.e. allowing a second person to
   share an existing session). ``nxserver`` queries the `session database`_ for
   any matching sessions. If a session is found, ``nxserver`` connects to the
   corresponding ``nxnode`` instance and asks for the `shadow cookie`_. This
   cookie is then passed to the session's own ``nxnode`` instance, which in
   turn connects to the original session and shadows it. Once the session is
   ready, ``nxserver`` continues in exactly the same way as with
   ``startsession`` (i.e. sending the session info to ``nxclient``, then
   connecting the client to the session via ``netcat``).

``terminate``
   Similar to ``restoresession``, ``nxserver`` queries the `session database`_
   for any matching sessions. If one is found, it connects to the corresponding
   ``nxnode`` and tells it to terminate the session.


nxnode
------
This program is spawned by ``nxserver`` as a daemon. On startup, it listens on
a per-session Unix socket and handles commands sent by ``nxserver`` via this
socket. ``nxnode`` contains all code required to start the session (e.g.
setting environment variables).

Supported commands:

``startsession``
  Starts ``nxagent`` and watches its output. Must be passed the client's
  parameters to ``startsession``.

``restoresession``
  Tells the session state machine to resume the session. Clients can connect
  again once the session reached the ``waiting`` status.

``attachsession``
  Starts a new shadow session. The `shadow cookie`_ of the session to be
  shadowed must be passed.

``terminate``
  Terminates the session and exits ``nxnode``.

``getshadowcookie``
  .. _shadow cookie:

  Asks the user for permission to hand out the session cookie. If given, or if
  shadowed by the same user, the session cookie is returned. This can then be
  used to shadow the session.

``nxnode`` is written using asynchronous I/O because it must read from
different file descriptors (client connections, programs, etc.) at the same
time. Threads can't be used because ``nxnode`` needs to start other processes
and therefore needs ``fork(2)`` (which isn't compatible with threads in Python
at least).

Internally ``nxnode`` is more or less a state machine controlled by client
commands and ``nxagent`` output.

The `session database`_ is updated on every major change (e.g. status change).

On session suspension/termination, ``nxagent`` spawns a watchdog process and
prints a message containing the watchdog's process ID. It then waits for
SIGTERM to be sent to that process. ``nxnode`` takes care of this.

The agent pid printed out to the session log may differ from the pid that
``nxnode`` previously had if the command it used to spawn nxagent forks before
exec'ing.

If ``nxagent`` is still running when the user application [#userapp]_ exits,
nxstart sends it SIGTERM to shutdown the session.


nxdialog
--------
This component is invoked by ``nxagent`` to display a dialog to the user inside
their NX session. One use is to ask the user whether to disconnect, terminate
the session or cancel when she tries to close the remote desktop window.


RPC protocol
------------
``nxserver`` and ``nxnode`` communicate via a Unix socket. The protocol
consists of NUL-byte separated junks of JSON encoded data and is synchronous.

Example request (sent by ``nxserver``, received by ``nxnode``)::

  {
    "cmd": "start",
    "args": {
      "session": "mysession1",
      "link": "adsl",
      "type": "unix-kde",
      …
    }
  }\0

Example response (sent by ``nxnode``)::

  {
    "success": true,
    "result": true
  }\0

Recognized exceptions are transported like this (sent by ``nxnode``)::

  {
    "success": false,
    "result": [
      "SessionParameterError",
      [
        "Unencrypted connections not supported"
      ]
    ]
  }\0

All other exceptions are transported like this (sent by ``nxnode``)::

  {
    "success": false,
    "result": "Some error message"
  }\0


Logging
-------
Neatx uses `Python`_'s standard `logging`__ module. All log messages are sent
to syslog for processing. Debug output can be enabled via the `configuration
file`_.

.. __: http://docs.python.org/library/logging.html


Configuration file
------------------
The configuraturation file is located at ``$sysconfdir/neatx.conf`` (usually
``/etc/neatx.conf``) and is read using `Python`_'s standard `ConfigParser`__
module. An example configuration file is included with the source at
``doc/neatx.conf.example``.

.. __: http://docs.python.org/library/configparser.html


Session database
----------------
The session database is stored in ``$localstatedir/lib/neatx/sessions/``
(usually ``/var/lib/neatx/sessions/``). Every session has its own directory,
named after the session ID.

A session's ID is generated by trying to create a new directory in the session
database. This guarantees unique session IDs.

Typical contents of a session directory:

``app.log``
  User application [#userapp]_ output.

``authority``
  Xauth authority file.

``cache-…``
  Cache for ``nxagent``.

``C-…``
  ``nxagent`` data.

``neatx.data``
  Session data serialized using JSON. This is written by ``nxnode`` and read by
  ``nxserver``.

``nxnode.sock``
  Socket listened on by ``nxnode``. ``nxserver`` connects to this socket to
  execute commands.


Session states
--------------

starting
  ``nxagent`` is starting.

waiting
  ``nxagent`` is ready for the client to connect, and is listening on its
  display port.

running
  ``nxclient`` is connected to ``nxagent`` and the session is fully setup.

suspending
  Session suspension is in progress. This happens when the connection to
  ``nxclient`` drops, or the user explicitly requests it.

suspended
  Session is fully suspended.

terminating
  Session termination is in progress.

terminated
  Session is fully terminated, and all associated processes have exited.


Language Choice
===============

All code should be written in Python_. Exceptions can be made for performance
critical components, which then should be written in C_. The build system is
Autoconf_ and Automake_.


The ``nx`` User
===============
NX, as designed by NoMachine, uses SSH_ to connect to the server. It logs in as
the ``nx`` user, using a well-known ssh DSA private key that is distributed with
``nxclient``. The server obtains a username and password from the client, and
uses them to authenticate as the real user. This allows users without system
accounts to have guest access to NX.


Security Considerations
=======================
These are the attack vectors requiring consideration:

- Malicious user without a system account exploits ``nxserver-login`` to run
  commands as the ``nx`` user
- Malicious user with a system account gains root access, reads auth cookies
  from nx session database, and connects to another user's session.
- Malicious user with a system account exploits ``nxserver`` to connect to
  another user's session.


.. [#userapp] User applications such as KDE, Gnome or custom commands.

.. _Autoconf: http://www.gnu.org/software/autoconf/
.. _Automake: http://www.gnu.org/software/automake/
.. _C: http://en.wikipedia.org/wiki/C_(programming_language)
.. _Python: http://www.python.org/
.. _SSH: http://www.openssh.com/
