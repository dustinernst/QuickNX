#
#

# Copyright (C) 2009 Google Inc.
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


"""Module containing code used by nxnode

"""


import collections
import errno
import logging
import os
import pwd
import random
import socket
import sys

from cStringIO import StringIO

from neatx import agent
from neatx import constants
from neatx import daemon
from neatx import errors
from neatx import protocol
from neatx import serializer
from neatx import session
from neatx import utils


REQ_FIELD_CMD = "cmd"
REQ_FIELD_ARGS = "args"

RESP_FIELD_SUCCESS = "success"
RESP_FIELD_RESULT = "result"

CMD_STARTSESSION = "start"
CMD_ATTACHSESSION = "attach"
CMD_RESTORESESSION = "restore"
CMD_TERMINATESESSION = "terminate"

CMD_GET_SHADOW_COOKIE = "getshadowcookie"

PROTO_SEPARATOR = "\0"


def _GetUserShell(username):
  return pwd.getpwnam(username).pw_shell


def _GetUserHomedir(username):
  return pwd.getpwnam(username).pw_dir


def FindUnusedDisplay(_pool=None, _check_paths=None):
  """Return an unused display number (corresponding to an unused port)

  FIXME: This should also be checking for open ports.

  """
  if _pool is None:
    # Choosing display numbers from a random pool to alleviate a potential race
    # condition between multiple clients connecting at the same time.  If the
    # checked paths are not created fast enough, they could all detect the same
    # display number as free. By choosing random numbers this shouldn't happen
    # as often, but it's very hard to fix properly.
    # TODO: Find a better way to reserve display numbers in an atomic way.
    # FIXME: Potential DoS: any user could create all checked paths and thereby
    # lock other users out.
    _pool = random.sample(xrange(20, 1000), 10)

  if _check_paths is None:
    _check_paths = constants.DISPLAY_CHECK_PATHS

  for i in _pool:
    logging.debug("Trying display number %s", i)

    ok = True
    for path in _check_paths:
      if os.path.exists(path % i):
        ok = False
        break

    if ok:
      logging.debug("Display number %s appears to be unused", i)
      return i

  raise errors.NoFreeDisplayNumberFound()


class NodeSession(session.SessionBase):
  """Keeps runtime properties of a session.

  """
  def __init__(self, ctx, clientargs, _env=None):
    self._ctx = ctx

    hostname = utils.GetHostname()
    display = FindUnusedDisplay()

    session.SessionBase.__init__(self, ctx.sessid, hostname, display,
                                 ctx.username)

    self.name = clientargs.get("session")
    if not self.name:
      raise errors.SessionParameterError("Session name missing")

    self.type = clientargs.get("type")
    if not self.type:
      raise errors.SessionParameterError("Session type missing")

    if not protocol.ParseNxBoolean(clientargs.get("encryption")):
      raise errors.SessionParameterError("Unencrypted connections not "
                                         "supported")

    self.sessdir = self._ctx.sessmgr.GetSessionDir(self.id)
    self.authorityfile = os.path.join(self.sessdir, "authority")
    self.applogfile = os.path.join(self.sessdir, "app.log")
    self.optionsfile = os.path.join(self.sessdir, "options")

    # Default values
    self.cache = 16
    self.client = "unknown"
    self.fullscreen = False
    self.geometry = "640x480"
    self.images = 64
    self.keyboard = "pc105/gb"
    self.link = "isdn"
    self.rootless = False
    self.screeninfo = None
    self.ssl = True
    self.virtualdesktop = False
    self.resize = False
    self.shadow_cookie = None
    self.shadow_display = None

    self._ParseClientargs(clientargs)

    if _env is None:
      env = os.environ.copy()
    else:
      env = _env.copy()

    env["NX_ROOT"] = self.sessdir
    env["XAUTHORITY"] = self.authorityfile
    env["SHELL"] = _GetUserShell(self._ctx.username)

    self._env = env

    self.command = self._GetCommand(clientargs)

  def _ParseClientargs(self, clientargs):
    self.client = clientargs.get("client", self.client)
    self.geometry = clientargs.get("geometry", self.geometry)
    self.keyboard = clientargs.get("keyboard", self.keyboard)
    self.link = clientargs.get("link", self.link)
    self.screeninfo = clientargs.get("screeninfo", self.screeninfo)

    if self.type == constants.SESS_TYPE_SHADOW:
      if "display" not in clientargs:
        raise errors.SessionParameterError("Missing 'display' parameter")

      self.shadow_display = clientargs["display"]

    if "images" in clientargs:
      self.images = protocol.ParseNxSize(clientargs["images"])

    if "cache" in clientargs:
      self.cache = protocol.ParseNxSize(clientargs["cache"])

    if "resize" in clientargs:
      self.resize = protocol.ParseNxBoolean(clientargs["resize"])
    else:
      self.resize = False

    if "fullscreen" in clientargs:
      self.fullscreen = protocol.ParseNxBoolean(clientargs["fullscreen"])
    else:
      self.fullscreen = False

    if "rootless" in clientargs:
      self.rootless = protocol.ParseNxBoolean(clientargs["rootless"])
    else:
      self.rootless = False

    if "virtualdesktop" in clientargs:
      self.virtualdesktop = \
        protocol.ParseNxBoolean(clientargs["virtualdesktop"])
    else:
      self.virtualdesktop = True

  def _GetCommand(self, clientargs):
    """Returns the command requested by the client.

    """
    cfg = self._ctx.cfg
    sesstype = self.type
    args = [_GetUserShell(self._ctx.username), "-c"]

    if sesstype == constants.SESS_TYPE_SHADOW:
      return None

    elif sesstype == constants.SESS_TYPE_KDE:
      return args + [cfg.start_kde_command]

    elif sesstype == constants.SESS_TYPE_GNOME:
      return args + [cfg.start_gnome_command]

    elif sesstype == constants.SESS_TYPE_CONSOLE:
      return args + [cfg.start_console_command]

    elif sesstype == constants.SESS_TYPE_APPLICATION:
      # Get client-specified application
      app = clientargs.get("application", "")
      if not app.strip():
        raise errors.SessionParameterError(("Session type %s, but missing "
                                            "application") % sesstype)

      return args + [protocol.UnquoteParameterValue(app)]

    raise errors.SessionParameterError("Unsupported session type: %s" %
                                       sesstype)

  def PrepareRestore(self, clientargs):
    """Update session with new settings from client.

    """
    self._ParseClientargs(clientargs)

  def SetShadowCookie(self, cookie):
    """Sets the shadow cookie for this session.

    @type cookie: str
    @param cookie: Shadow cookie

    """
    self.shadow_cookie = cookie

  def GetSessionEnvVars(self):
    return self._env

  def Save(self):
    self._ctx.sessmgr.SaveSession(self)


class SessionRunner(object):
  """Manages the various parts of a session lifetime.

  """
  def __init__(self, ctx):
    self.__ctx = ctx

    self.__nxagent = None
    self.__nxagent_exited_reg = None
    self.__nxagent_display_ready_reg = None

  def Start(self):
    sess = self.__ctx.session

    cookies = []
    cookies.extend(map(lambda display: (display, sess.cookie),
                       self.__GetHostDisplays(sess.display)))

    if sess.shadow_cookie:
      # Add special shadow cookie
      cookies.extend(map(lambda display: (display, sess.shadow_cookie),
                         self.__GetHostDisplays(sess.shadow_display)))

    logging.info("Starting xauth for %r", cookies)
    xauth = agent.XAuthProgram(sess.GetSessionEnvVars(), sess.authorityfile,
                               cookies, self.__ctx.cfg)
    xauth.connect(agent.XAuthProgram.EXITED_SIGNAL, self.__XAuthDone)
    xauth.Start()

  def Restore(self):
    if not self.__nxagent:
      raise errors.GenericError("nxagent not yet started")
    self.__nxagent.Restore()

  def __XAuthDone(self, _, exitstatus, signum):
    """Called when xauth exits.

    """
    if exitstatus != 0 or signum is not None:
      self.__Quit()
      return

    self.__StartNxAgent()

  def __GetHostDisplays(self, display):
    return [":%s" % display,
            "localhost:%s" % display]

  def __GetXProgramEnv(self):
    sess = self.__ctx.session
    env = sess.GetSessionEnvVars().copy()
    env["DISPLAY"] = ":%s.0" % sess.display
    return env

  def __StartNxAgent(self):
    """Starts the nxagent program.

    """
    logging.info("Starting nxagent")
    self.__nxagent = agent.NxAgentProgram(self.__ctx)

    signal_name = agent.NxAgentProgram.EXITED_SIGNAL
    self.__nxagent_exited_reg = \
      daemon.SignalRegistration(self.__nxagent,
                                self.__nxagent.connect(signal_name,
                                                       self.__NxAgentDone))

    signal_name = agent.NxAgentProgram.DISPLAY_READY_SIGNAL
    self.__nxagent_display_ready_reg = \
      daemon.SignalRegistration(self.__nxagent,
                                self.__nxagent.connect(signal_name,
                                                       self.__DisplayReady))

    self.__nxagent.Start()

  def __NxAgentDone(self, prog, exitstatus, signum):
    assert prog == self.__nxagent

    logging.info("nxagent terminated")

    if self.__nxagent_exited_reg:
      self.__nxagent_exited_reg.Disconnect()
      self.__nxagent_exited_reg = None

    if self.__nxagent_display_ready_reg:
      self.__nxagent_display_ready_reg.Disconnect()
      self.__nxagent_display_ready_reg = None

    self.__Quit()

  def __DisplayReady(self, prog):
    assert prog == self.__nxagent

    self.__StartXRdb()

  def __StartXRdb(self):
    """Starts the xrdb program.

    """
    logging.info("Starting xrdb")

    settings = "Xft.dpi: 96"

    xrdb = agent.XRdbProgram(self.__GetXProgramEnv(), settings, self.__ctx.cfg)
    xrdb.connect(agent.XRdbProgram.EXITED_SIGNAL, self.__XRdbDone)
    xrdb.Start()

  def __XRdbDone(self, _, exitstatus, signum):
    # Ignoring xrdb errors

    self.__StartUserApp()

  def __StartUserApp(self):
    """Starts the user-defined or user-requested application.

    """
    sess = self.__ctx.session

    logging.info("Starting user application (%r)", sess.command)

    # Shadow sessions have no command
    if sess.command is None:
      return

    cwd = _GetUserHomedir(self.__ctx.username)

    userapp = agent.UserApplication(self.__GetXProgramEnv(), cwd, sess.command,
                                    sess.applogfile, login=True)
    userapp.connect(agent.UserApplication.EXITED_SIGNAL,
                    self.__UserAppDone)
    userapp.Start()

  def __UserAppDone(self, _, exitstatus, signum):
    """Called when user application terminated.

    """
    sess = self.__ctx.session

    logging.info("User application terminated")

    usable_session = (sess.state in
                      (constants.SESS_STATE_STARTING,
                       constants.SESS_STATE_WAITING,
                       constants.SESS_STATE_RUNNING))

    if usable_session and (exitstatus != 0 or signum is not None):
      msg = StringIO()
      msg.write("Application failed.\n\n")
      msg.write("Command: %s\n" % utils.ShellQuoteArgs(sess.command))

      if exitstatus is not None:
        msg.write("Exit code: %s\n" % exitstatus)

      if signum is not None:
        msg.write("Signal number: %s (%s)\n" %
                  (signum, utils.GetSignalName(signum)))

      self.__StartNxDialog(constants.DLG_TYPE_ERROR,
                           "Error", msg.getvalue())
      return

    self.__TerminateNxAgent()

  def __StartNxDialog(self, dlgtype, caption, message):
    dlg = agent.NxDialogProgram(self.__GetXProgramEnv(), dlgtype,
                                caption, message)
    dlg.connect(agent.NxDialogProgram.EXITED_SIGNAL,
                self.__NxDialogDone)
    dlg.Start()

  def __NxDialogDone(self, _, exitstatus, signum):
    self.__TerminateNxAgent()

  def __TerminateNxAgent(self):
    """Tell nxagent to quit.

    """
    if self.__nxagent:
      self.__nxagent.Terminate()

  def __Quit(self):
    """Called when nxagent terminated.

    """
    self.__nxagent = None

    # Quit nxnode
    sys.exit(0)


def StartNodeDaemon(username, sessid):
  def _StartNxNode():
    os.execl(constants.NXNODE_WRAPPER, "--", username, sessid)

  utils.StartDaemon(_StartNxNode)


# TODO: Move this class somewhere else. It is not used by the node daemon, but
# only by clients connecting to the daemon.
class NodeClient(object):
  """Node RPC client implementation.

  Connects to an nxnode socket and provides methods to execute remote procedure
  calls.

  """
  _RETRY_TIMEOUT = 10
  _CONNECT_TIMEOUT = 10
  _RW_TIMEOUT = 20

  def __init__(self, address):
    """Initializes this class.

    @type address: str
    @param address: Unix socket path

    """
    self._address = address
    self._sock = None
    self._inbuf = ""
    self._inmsg = collections.deque()

  def _InnerConnect(self, sock, retry):
    sock.settimeout(self._CONNECT_TIMEOUT)

    try:
      sock.connect(self._address)
    except socket.timeout, err:
      raise errors.GenericError("Connection timed out: %s" % str(err))
    except socket.error, err:
      if retry and err.args[0] in (errno.ENOENT, errno.ECONNREFUSED):
        # Try again
        raise utils.RetryAgain()

      raise

    sock.settimeout(self._RW_TIMEOUT)

    return sock

  def Connect(self, retry):
    """Connects to Unix socket.

    @type retry: bool
    @param retry: Whether to retry connection for a while

    """
    logging.info("Connecting to %r", self._address)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setblocking(1)

    if retry:
      try:
        utils.Retry(lambda: self._InnerConnect(sock, True),
                    0.1, 1.1, 1.0, self._RETRY_TIMEOUT)
      except utils.RetryTimeout:
        logging.error("Socket didn't become ready in %s seconds",
                      self._RETRY_TIMEOUT)
        raise errors.GenericError("Socket didn't become ready in time")
    else:
      self._InnerConnect(sock, False)

    self._sock = sock

  def Close(self):
    self._sock.close()

  def _SendRequest(self, cmd, args):
    """Sends a request and handles the response.

    @type cmd: str
    @param cmd: Procedure name
    @type args: built-in type
    @param args: Arguments
    @return: Value returned by the procedure call

    """
    # Build request
    req = {
      REQ_FIELD_CMD: cmd,
      REQ_FIELD_ARGS: args,
      }

    logging.debug("Sending request: %r", req)

    # TODO: sendall doesn't report errors properly
    self._sock.sendall(serializer.DumpJson(req))
    self._sock.sendall(PROTO_SEPARATOR)

    resp = serializer.LoadJson(self._ReadResponse())
    logging.debug("Received response: %r", resp)

    # Check whether we received a valid response
    if (not isinstance(resp, dict) or
        RESP_FIELD_SUCCESS not in resp or
        RESP_FIELD_RESULT not in resp):
      raise errors.GenericError("Invalid response from daemon: %r", resp)

    result = resp[RESP_FIELD_RESULT]

    if resp[RESP_FIELD_SUCCESS]:
      return result

    # Is it a serialized exception? They must have the following format (both
    # lists and tuples are accepted):
    #   ("ExceptionClassName", (arg1, arg2, arg3))
    if (isinstance(result, (tuple, list)) and
        len(result) == 2 and
        isinstance(result[1], (tuple, list))):
      errcls = errors.GetErrorClass(result[0])
      if errcls is not None:
        raise errcls(*result[1])

    # Fallback
    raise errors.GenericError(resp[RESP_FIELD_RESULT])

  def _ReadResponse(self):
    """Reads a response from the socket.

    @rtype: str
    @return: Response message

    """
    # Read from socket while there are no messages in the buffer
    while not self._inmsg:
      data = self._sock.recv(4096)
      if not data:
        raise errors.GenericError("Connection closed while reading")

      parts = (self._inbuf + data).split(PROTO_SEPARATOR)
      self._inbuf = parts.pop()
      self._inmsg.extend(parts)

    return self._inmsg.popleft()

  def StartSession(self, args):
    return self._SendRequest(CMD_STARTSESSION, args)

  def AttachSession(self, args, shadowcookie):
    return self._SendRequest(CMD_ATTACHSESSION, [args, shadowcookie])

  def RestoreSession(self, args):
    return self._SendRequest(CMD_RESTORESESSION, args)

  def TerminateSession(self, args):
    return self._SendRequest(CMD_TERMINATESESSION, args)

  def GetShadowCookie(self, args):
    return self._SendRequest(CMD_GET_SHADOW_COOKIE, args)
