#
#

# Copyright (C) 2007 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""nxserver program for accepting nx connections.

"""


import logging
import optparse
import socket
import subprocess
import sys

from neatx import cli
from neatx import constants
from neatx import errors
from neatx import node
from neatx import protocol
from neatx import session
from neatx import utils


PROGRAM = "nxserver"

NX_PROMPT_PARAMETERS = "Parameters: "

_SESSION_START_TIMEOUT = 30
_SESSION_RESTORE_TIMEOUT = 60

# TODO: Determine how the commercial NX version gets the depth from nxagent
DEFAULT_DEPTH = 24

LISTSESSION_COLUMNS = [
    ("Display", 7, lambda sess: sess.display),
    ("Type", 16, lambda sess: sess.type),
    ("Session ID", 32, lambda sess: sess.id),
    ("Options", 8, lambda sess: FormatOptions(sess)),
    ("Depth", -5, lambda sess: DEFAULT_DEPTH),
    ("Screen", 14, lambda sess: FormatGeometry(sess)),
    ("Status", 11, lambda sess: FormatStatus(sess)),
    ("Session Name", 30, lambda sess: sess.name),
    ]
"""
Column definitions for "listsession" command.

See L{utils.FormatTable} for more details.

"""


def FormatOptions(sess):
  """Format session options for "listsessions" command.

  """
  flags = []
  unset = "-"

  # Fullscreen
  if sess.fullscreen:
    flags.append("F")
  else:
    flags.append(unset)

  # Render
  if sess.screeninfo and "render" in sess.screeninfo:
    flags.append("R")
  else:
    flags.append(unset)

  # Non-rootless (Desktop?)
  if sess.virtualdesktop:
    flags.append("D")
  else:
    flags.append(unset)

  # Unknown
  flags.append(unset)
  flags.append(unset)
  flags.append("P")
  flags.append("S")
  flags.append("A")

  return "".join(flags)


def FormatGeometry(sess):
  if not sess.geometry:
    return "-"

  pos = sess.geometry.find("+")
  if pos == -1:
    return sess.geometry

  return sess.geometry[:pos]


def ConvertStatusForClient(status):
  """Convert status for client.

  The client doesn't know about the "terminating" and "suspending" statuses.

  @type status: str
  @param status: Server-side session status
  @rtype: str
  @return: Client-side session status

  """
  if status == constants.SESS_STATE_TERMINATING:
    return constants.SESS_STATE_TERMINATED

  if status == constants.SESS_STATE_SUSPENDING:
    return constants.SESS_STATE_SUSPENDED

  return status


def FormatStatus(sess):
  """Format session status for session list.

  """
  return ConvertStatusForClient(sess.state).capitalize()


def _GetSessionCache(sess):
  sesstype = sess.type
  if sesstype.startswith(constants.SESS_TYPE_UNIX_PREFIX):
    return sesstype
  return constants.SESS_TYPE_UNIX_PREFIX + sesstype


def GetClientSessionInfo(sess):
  """Get session information for the client

  This is used for starting/resuming a session.

  """
  # "702 Proxy IP: 1.2.3.4" is not used because we don't support unencrypted
  # sessions anyway.
  return [
    (700, "Session id: %s" % sess.full_id),
    (705, "Session display: %s" % sess.display),
    (703, "Session type: %s" % sess.type),
    (701, "Proxy cookie: %s" % sess.cookie),
    (706, "Agent cookie: %s" % sess.cookie),
    (704, "Session cache: %s" % _GetSessionCache(sess)),
    (728, "Session caption: %s" % sess.windowname),
    (707, "SSL tunneling: %s" % protocol.FormatNxBoolean(sess.ssl)),
    (708, "Subscription: %s" % sess.subscription),
    ]


class ServerCommandHandler(object):
  def __init__(self, server, ctx):
    self._server = server
    self._ctx = ctx

  def __call__(self, cmdline):
    """Parses and handles a command sent by the client.

    @type cmdline: str
    @param cmdline: Unparsed command

    """
    (cmd, args) = protocol.SplitCommand(cmdline)

    # Confirm command
    # TODO: Move confirmation code to protocol.py and use it from
    # nxserver_login.py, too.
    self._SendConfirmation(cmdline, cmd, args)

    if cmd in (protocol.NX_CMD_LOGIN,
               protocol.NX_CMD_HELLO,
               protocol.NX_CMD_SET):
      raise protocol.NxNotAfterLogin(cmd)

    try:
      if cmd == protocol.NX_CMD_BYE:
        return self._Bye()

      elif cmd == protocol.NX_CMD_LISTSESSION:
        return self._ListSession(args)

      elif cmd == protocol.NX_CMD_STARTSESSION:
        return self._StartSession(args)

      elif cmd == protocol.NX_CMD_ATTACHSESSION:
        return self._AttachSession(args)

      elif cmd == protocol.NX_CMD_RESTORESESSION:
        return self._RestoreSession(args)

    except errors.SessionParameterError, err:
      logging.exception("Session parameter error")
      raise protocol.NxProtocolError(500, err.args[0], fatal=True)

    raise protocol.NxUndefinedCommand(cmd)

  def _SendConfirmation(self, cmdline, cmd, args):
    """Sends a command confirmation to the client.

    """
    server = self._server

    if cmd == protocol.NX_CMD_STARTSESSION:
      self._server.WriteLine("Start session with: " + args)
      return

    # The "set" command uses a different confirmation in the commercial version
    # (as implemented in nxserver-login), but it shouldn't be used after login
    # anyway.

    server.WriteLine(cmdline.lstrip().capitalize())

  def _Bye(self):
    raise protocol.NxQuitServer()

  def _ListSession(self, args):
    """Handle the listsession NX command.

    "listsession" requests a table of session information for the current
    user. It requires parameters be specified.

    The following parameters have been seen:

      - C{--geometry="1920x1200x24+render"}:
        This seems to specify the desired geometry.
      - C{--status="suspended,running"}:
        This seems to specify the desired type.
      - C{--type="unix-gnome"}:
        This seems to constrain the list to sessions in the given states.
      - C{--user="someone"}:
        This seems to be ignored. No matter what is specified, the user given at
        login is used.

    @type args: string
    @param args: Parameters

    """
    ctx = self._ctx
    server = self._server
    mgr = ctx.session_mgr

    # Parse parameters
    parsed_params = dict(protocol.ParseParameters(self._GetParameters(args)))

    # TODO: Accepted parameters

    # Ignore --user, as per commercial implementation
    # TODO: Check sessions from all users if type=shadow? This is problematic
    # due to file system access permissions.
    find_users = [self._ctx.username]

    find_types = None
    want_shadow = False

    # Ignoring --user, as per commercial implementation

    if "type" in parsed_params:
      types = parsed_params["type"].split(",")

      # If the type is shadow do the settings to get running sessions
      if types[0] == constants.SESS_TYPE_SHADOW:
        want_shadow = True
      else:
        find_types = types

    if want_shadow:
      find_states = constants.SESS_STATE_RUNNING
    elif "status" in parsed_params:
      find_states = parsed_params["status"].split(",")
    else:
      find_states = None

    sessions = self._ListSessionInner(find_types, find_states)

    server.Write(127, "Session list of user '%s':" % ctx.username)
    for line in utils.FormatTable(sessions, LISTSESSION_COLUMNS):
      server.WriteLine(line)
    server.WriteLine("")
    server.Write(148, ("Server capacity: not reached for user: %s" %
                       ctx.username))

  def _ListSessionInner(self, find_types, find_states):
    """Returns a list of sessions filtered by parameters specified.

    @type find_types: list
    @param find_types: List of wanted session types
    @type find_states: list
    @param find_states: List of wanted (client) session states

    """
    ctx = self._ctx
    mgr = ctx.session_mgr

    logging.debug("Looking for sessions with types=%r, state=%r",
                  find_types, find_states)

    def _Filter(sess):
      if find_states and ConvertStatusForClient(sess.state) not in find_states:
        return False

      if find_types and sess.type not in find_types:
        return False

      return True

    return mgr.FindSessionsWithFilter(ctx.username, _Filter)

  def _StartSession(self, args):
    """Handle the startsession NX command.

    "startsession" seems to request a new session be started. It requires
    parameters be specified.

    The following parameters have been seen:

      - C{--backingstore="1"}
      - C{--cache="16M"}
      - C{--client="linux"}
      - C{--composite="1"}
      - C{--encryption="1"}
      - C{--fullscreen="0"}
      - C{--geometry="3840x1150"}
      - C{--images="64M"}
      - C{--keyboard="pc102/gb"}
      - C{--link="lan"}
      - C{--media="0"}
      - C{--rootless="0"}
      - C{--screeninfo="3840x1150x24+render"}
      - C{--session="localtest"}
      - C{--shmem="1"}
      - C{--shpix="1"}
      - C{--strict="0"}
      - C{--type="unix-gnome"}
      - C{--virtualdesktop="1"}

    Experiments with this command by directly invoking nxserver have not
    worked, as it refuses to create a session saying the unencrypted sessions
    are not supported. This is independent of whether the --encryption option
    has been set, so probably is related to the fact the nxserver has not been
    launched by sshd.

    @type args: string
    @param args: Parameters

    """
    ctx = self._ctx
    mgr = ctx.session_mgr
    server = self._server

    # Parse parameters
    params = self._GetParameters(args)
    parsed_params = dict(protocol.ParseParameters(params))

    # Parameters will be checked in nxnode

    sessid = mgr.CreateSessionID()
    logging.info("Starting new session %r", sessid)

    # Start nxnode daemon
    node.StartNodeDaemon(ctx.username, sessid)

    # Connect to daemon and tell it to start our session
    nodeclient = self._GetNodeClient(sessid, True)
    try:
      logging.debug("Sending startsession command")
      nodeclient.StartSession(parsed_params)
    finally:
      nodeclient.Close()

    # Wait for session
    self._ConnectToSession(sessid, _SESSION_START_TIMEOUT)

  def _AttachSession(self, args):
    """Handle the attachsession NX command.

    "attachsession" seems to request a new shadow session be started. It
    requires parameters be specified.

    The following parameters have been seen:
      - C{--backingstore="1"}
      - C{--cache="16M"}
      - C{--client="linux"}
      - C{--composite="1"}
      - C{--encryption="1"}
      - C{--geometry="3840x1150"}
      - C{--images="64M"}
      - C{--keyboard="pc102/gb"}
      - C{--link="lan"}
      - C{--media="0"}
      - C{--screeninfo="3840x1150x24+render"}
      - C{--session="localtest"}
      - C{--shmem="1"}
      - C{--shpix="1"}
      - C{--strict="0"}
      - C{--type="shadow"}

    @type args: string
    @param args: Parameters

    """
    ctx = self._ctx
    server = self._server
    mgr = self._ctx.session_mgr

    # Parse parameters
    params = self._GetParameters(args)
    parsed_params = dict(protocol.ParseParameters(params))

    # Parameters will be checked in nxnode

    try:
      shadowid = parsed_params["id"]
    except KeyError:
      raise protocol.NxProtocolError(500, ("Shadow session requested, "
                                           "but no session specified"))

    logging.info("Preparing to shadow session %r", shadowid)

    # Connect to daemon and ask for shadow cookie
    shadownodeclient = self._GetNodeClient(shadowid, False)
    try:
      logging.debug("Requesting shadow cookie from session %r", shadowid)
      shadowcookie = shadownodeclient.GetShadowCookie(None)
    finally:
      shadownodeclient.Close()

    logging.debug("Got shadow cookie %r", shadowcookie)

    sessid = mgr.CreateSessionID()
    logging.info("Starting new session %r", sessid)

    # Start nxnode daemon
    node.StartNodeDaemon(ctx.username, sessid)

    # Connect to daemon and tell it to shadow our session
    nodeclient = self._GetNodeClient(sessid, True)
    try:
      logging.debug("Sending attachsession command")
      nodeclient.AttachSession(parsed_params, shadowcookie)
    finally:
      nodeclient.Close()

    # Wait for session
    self._ConnectToSession(sessid, _SESSION_START_TIMEOUT)

  def _RestoreSession(self, args):
    """Handle the restoresession NX command.

    "restoresession" requests an existing session be resumed. It requires
    parameters be specified.

    The following parameters have been seen, from which at least the session id
    must be specified:

      - C{--backingstore="1"}
      - C{--cache="16M"}
      - C{--client="linux"}
      - C{--composite="1"}
      - C{--encryption="1"}
      - C{--geometry="3840x1150"}
      - C{--id="A28EBF5AAC354E9EEAFEEB867980C543"}
      - C{--images="64M"}
      - C{--keyboard="pc102/gb"}
      - C{--link="lan"}
      - C{--media="0"}
      - C{--rootless="1"}
      - C{--screeninfo="3840x1150x24+render"}
      - C{--session="localtest"}
      - C{--shmem="1"}
      - C{--shpix="1"}
      - C{--strict="0"}
      - C{--type="unix-gnome"}
      - C{--virtualdesktop="0"}

    @type args: string
    @param args: Parameters

    """
    ctx = self._ctx
    server = self._server
    mgr = ctx.session_mgr

    # Parse parameters
    params = self._GetParameters(args)
    parsed_params = dict(protocol.ParseParameters(params))

    # Parameters will be checked in nxnode

    try:
      sessid = parsed_params["id"]
    except KeyError:
      raise protocol.NxProtocolError(500, ("Restore session requested, "
                                           "but no session specified"))

    logging.info("Restoring session %r", sessid)

    # Try to find session
    sess = mgr.LoadSessionForUser(sessid, ctx.username)
    if sess is None:
      raise protocol.NxProtocolError(500, "Failed to load session")

    sessid = sess.id

    logging.info("Found session %r in session database", sessid)

    # Connect to daemon and tell it to restore our session
    nodeclient = self._GetNodeClient(sessid, False)
    try:
      logging.debug("Sending restoresession command")
      nodeclient.RestoreSession(parsed_params)
    finally:
      nodeclient.Close()

    # Already running sessions take a bit longer to restart
    self._ConnectToSession(sessid, _SESSION_RESTORE_TIMEOUT)

  def _GetParameters(self, args):
    """Returns parameters or, if none were given, query client for them.

    @type args: str
    @param args: Command arguments (can be empty)

    """
    server = self._server

    # Ask for parameters if none have been given
    if args:
      return args

    server.Write(106, NX_PROMPT_PARAMETERS, newline=False)
    try:
      return server.ReadLine()
    finally:
      server.WriteLine("")

  def _WriteSessionInfo(self, sess):
    """Writes session information required by client.

    @type sess: L{session.NxSession}
    @param sess: Session object

    """
    for code, message in GetClientSessionInfo(sess):
      self._server.Write(code, message=message)

  def _WaitForSessionReady(self, sessid, timeout):
    """Waits for a session to become ready for connecting.

    @type sessid: str
    @param sessid: Session ID
    @type timeout: int or float
    @param timeout: Timeout in seconds

    """
    mgr = self._ctx.session_mgr
    server = self._server

    def _CheckForSessionReady():
      sess = mgr.LoadSession(sessid)
      if sess:
        if sess.state == constants.SESS_STATE_WAITING:
          return sess

        elif sess.state in (constants.SESS_STATE_TERMINATING,
                            constants.SESS_STATE_TERMINATED):
          logging.error("Session %r has status %r", sess.id, sess.state)
          server.Write(500, message=("Error: Session %r has status %r, "
                                     "aborting") % (sess.id, sess.state))
          raise protocol.NxQuitServer()

      raise utils.RetryAgain()

    logging.info("Waiting for session %r to achieve waiting status",
                 sessid)

    try:
      return utils.Retry(_CheckForSessionReady, 0.1, 1.5, 1.0, timeout)
    except utils.RetryTimeout:
      logging.error(("Session %s has not achieved waiting status "
                     "within %s seconds"), sessid, timeout)
      server.Write(500, "Session didn't become ready in time")
      raise protocol.NxQuitServer()

  def _ConnectToSession(self, sessid, timeout):
    """Waits for a session to become ready and stores the port.

    @type sessid: str
    @param sessid: Session ID
    @type timeout: int or float
    @param timeout: Timeout in seconds

    """
    server = self._server

    # TODO: Instead of polling for the session, the daemon could only return
    # once the session is ready.

    # Wait for session to become ready
    sess = self._WaitForSessionReady(sessid, timeout)

    # Send session details to client
    self._WriteSessionInfo(sess)
    server.Write(710, "Session status: running")

    # Store session port for use by netcat
    self._ctx.nxagent_port = sess.port

  def _GetNodeClient(self, sessid, retry):
    """Starts the nxnode RPC client for a session.

    @type sessid: str
    @param sessid: Session ID
    @type retry: bool
    @param retry: Whether to retry connecting several times
    @rtype: L{node.NodeClient}
    @return: Node client object

    """
    ctx = self._ctx
    mgr = ctx.session_mgr

    # Connect to nxnode
    nodeclient = node.NodeClient(mgr.GetSessionNodeSocket(sessid))

    logging.debug("Connecting to nxnode")
    nodeclient.Connect(retry)

    return nodeclient


class NxServerContext(object):
  def __init__(self):
    self.username = None
    self.session_mgr = None
    self.nxagent_port = None


class NxServer(protocol.NxServerBase):
  def __init__(self, ctx):
    protocol.NxServerBase.__init__(self, sys.stdin, sys.stdout,
                                   ServerCommandHandler(self, ctx))
    self._ctx = ctx

  def SendBanner(self):
    """Send banner to peer.

    """
    # TODO: Hostname in configuration?
    hostname = socket.getfqdn().lower()
    username = self._ctx.username

    self.Write(103, message="Welcome to: %s user: %s" % (hostname, username))


class NxServerProgram(cli.GenericProgram):
  def BuildOptions(self):
    options = cli.GenericProgram.BuildOptions(self)
    options.extend([
      optparse.make_option("--proto", type="int", dest="proto"),
      ])
    return options

  def Run(self):
    if len(self.args) != 1:
      raise errors.GenericError("Username missing")

    (username, ) = self.args

    logging.info("Starting nxserver for user %s", username)

    ctx = NxServerContext()
    ctx.username = username
    ctx.session_mgr = session.NxSessionManager()

    try:
      NxServer(ctx).Start()
    finally:
      sys.stdout.flush()

    if ctx.nxagent_port is None:
      logging.debug("No nxagent port, not starting netcat")
    else:
      self._RunNetcat("localhost", ctx.nxagent_port)

  def _RunNetcat(self, host, port):
    """Starts netcat and returns only after it's done.

    @type host: str
    @param host: Hostname
    @type port: int
    @param port: Port

    """
    logging.info("Starting netcat (%s:%s)", host, port)

    stderr_logger = utils.LogFunctionWithPrefix(logging.error,
                                                "netcat stderr: ")

    args = [self.cfg.netcat, "--", host, str(port)]

    process = subprocess.Popen(args, shell=False, close_fds=True,
                               stdin=None, stdout=None, stderr=subprocess.PIPE)

    for line in process.stderr:
      stderr_logger(line.rstrip())

    (exitcode, signum) = utils.GetExitcodeSignal(process.wait())
    if exitcode == 0 and signum is None:
      logging.debug("Netcat exited cleanly")
    else:
      logging.error("Netcat failed (code=%s, signal=%s)", exitcode, signum)


def Main():
  logsetup = utils.LoggingSetup(PROGRAM)
  NxServerProgram(logsetup).Main()
