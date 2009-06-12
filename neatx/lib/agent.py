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


"""Module for nxagent interaction and session runtime


"""


import errno
import gobject
import logging
import os
import re
import signal

from cStringIO import StringIO

from neatx import constants
from neatx import daemon
from neatx import errors
from neatx import protocol
from neatx import utils


_STATUS_MAP = {
  constants.SESS_STATE_STARTING:
    re.compile(r"^Session:\s+Starting\s+session\s+at\s+"),
  constants.SESS_STATE_WAITING:
    re.compile(r"Info:\s+Waiting\s+for\s+connection\s+from\s+"
               r"'(?P<host>.*)'\s+on\s+port\s+'(?P<port>\d+)'\."),
  constants.SESS_STATE_RUNNING:
    re.compile(r"^Session:\s+Session\s+(started|resumed)\s+at\s+"),
  constants.SESS_STATE_SUSPENDING:
    re.compile(r"^Session:\s+Suspending\s+session\s+at\s+"),
  constants.SESS_STATE_SUSPENDED:
    re.compile(r"^Session:\s+Session\s+suspended\s+at\s+"),
  constants.SESS_STATE_TERMINATING:
    re.compile(r"^Session:\s+(Terminat|Abort)ing\s+session\s+at\s+"),
  constants.SESS_STATE_TERMINATED:
    re.compile(r"^Session:\s+Session\s+(terminat|abort)ed\s+at\s+"),
  }

_WATCHDOG_PID_RE = re.compile(r"^Info:\s+Watchdog\s+running\s+with\s+pid\s+"
                              r"'(?P<pid>\d+)'\.")
_WAIT_WATCHDOG_RE = re.compile(r"^Info:\s+Waiting\s+the\s+watchdog\s+"
                               r"process\s+to\s+complete\.")
_AGENT_PID_RE = re.compile(r"^Info:\s+Agent\s+running\s+with\s+pid\s+"
                           r"'(?P<pid>\d+)'\.")
_GENERAL_ERROR_RE = re.compile(r"^Error:\s+(?P<error>.*)$")
_GENERAL_WARNING_RE = re.compile(r"^Warning:\s+(?P<warning>.*)$")
_GEOMETRY_RE = re.compile(r"^Info:\s+Screen\s+\[0\]\s+resized\s+to\s+"
                          r"geometry\s+\[(?P<geometry>.*)]\.$")


class UserApplication(daemon.Program):
  """Wraps the user-defined application.

  """
  def __init__(self, env, cwd, args, logfile, login=False):
    """Initializes this class.

    @type env: dict
    @param env: Environment variables
    @type cwd: str
    @param cwd: Working directory
    @type args: list
    @param args: Command and arguments
    @type logfile: str
    @param logfile: Path to application logfile
    @type login: boolean
    @param login: Run the command as a login shell

    """
    if login:
      executable = args[0]
      args = args[:]
      args[0] = "-%s" % os.path.basename(args[0])
    else:
      executable = None

    # TODO: logfile

    daemon.Program.__init__(self, args, env=env, cwd=cwd,
                            executable=executable,
                            umask=constants.DEFAULT_APP_UMASK)


class XAuthProgram(daemon.Program):
  """Wrapper for xauth.

  Quoting xauth(1): "The xauth program is used to edit and display the
  authorization information used in connecting to the X server."

  """
  _MIT_MAGIC_COOKIE_1 = "MIT-MAGIC-COOKIE-1"

  def __init__(self, env, filename, cookies):
    """Initializes this class.

    @type env: dict
    @param env: Environment variables
    @type cookies: list of tuples
    @param cookies: Cookies as [(display, cookie), ...]

    """
    args = [constants.XAUTH, "-f", filename]
    daemon.Program.__init__(self, args, env=env,
                            stdin_data=self.__BuildInput(cookies))

  @classmethod
  def __BuildInput(cls, cookies):
    """Builds the input for xauth.

    @type cookies: list of tuples
    @param cookies: Cookies as [(display, cookie), ...]

    """
    buf = StringIO()

    for (display, cookie) in cookies:
      buf.write("add %s %s %s\n" % (display, cls._MIT_MAGIC_COOKIE_1, cookie))

    buf.write("exit\n")

    return buf.getvalue()


class XRdbProgram(daemon.Program):
  """Wrapper for xrdb.

  Quoting xrdb(1): "X server resource database utility. Xrdb is used to get or
  set the contents of the RESOURCE_MANAGER property [...] Most X clients use
  the RESOURCE_MANAGER and SCREEN_RESOURCES properties to get user preferences
  about color, fonts, and so on for applications."

  """
  def __init__(self, env, settings):
    args = [constants.XRDB, "-merge"]

    if not settings.endswith(os.linesep):
      settings += os.linesep

    xrdbenv = env.copy()
    xrdbenv["LC_ALL"] = "C"

    daemon.Program.__init__(self, args, env=xrdbenv, stdin_data=settings)


class NxDialogProgram(daemon.Program):
  """Wrapper for nxdialog program.

  """
  def __init__(self, env, dlgtype, caption, message):
    args = [constants.NXDIALOG, "--dialog", dlgtype,
            "--caption", caption, "--message", message]
    daemon.Program.__init__(self, args, env=env)


class NxAgentProgram(daemon.Program):
  """Wraps nxagent and acts on its output.

  """
  DISPLAY_READY_SIGNAL = "display-ready"

  __gsignals__ = {
    DISPLAY_READY_SIGNAL:
      (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
       ()),
    }

  def __init__(self, ctx):
    """Initializes this class.

    @type ctx: NxNodeContext
    @param ctx: Nxnode context object

    """
    self._ctx = ctx

    args = [constants.NXAGENT] + self._GetNxAgentArgs()

    display = self._GetDisplayWithOptions()
    logging.debug("Display for nxagent: %r", display)

    env = ctx.session.GetSessionEnvVars().copy()
    env["DISPLAY"] = display
    env["NX_CLIENT"] = constants.NXDIALOG

    self._agent_pid = None
    self._watchdog_pid = None
    self._want_restore = False

    daemon.Program.__init__(self, args, env=env)

    signal_name = daemon.ChopReader.SLICE_COMPLETE_SIGNAL
    self._stderr_line_reg = \
      daemon.SignalRegistration(self,
                                self.stderr_line.connect(signal_name,
                                                         self._HandleStderrLine))

  def Start(self):
    """Starts nxagent.

    See L{daemon.Program.Start} for more details.

    """
    # Ensure options file exists
    self._UpdateOptionsFile()

    pid = daemon.Program.Start(self)
    self._agent_pid = pid
    return pid

  def Restore(self):
    """Prepare session restore.

    Depending on the current status, different things need to be done. If the
    session is already suspended, SIGHUP can be sent right away. If it's still
    running, sending SIGHUP will suspend the session and can be restored after
    sending another SIGHUP.

    """
    sess = self._ctx.session

    if sess.state == constants.SESS_STATE_SUSPENDING:
      # Restore once in suspended status
      self._want_restore = True

    elif sess.state == constants.SESS_STATE_SUSPENDED:
      # Restore directly
      self._PrepareSessionRestore()

    elif sess.state == constants.SESS_STATE_RUNNING:
      # Send SIGHUP to terminate session
      self._SendSighup()

      # Send SIGHUP again on status change
      self._want_restore = True

    else:
      raise errors.GenericError("Cannot restore session in %r state" %
                                sess.state)

  def Terminate(self):
    """Terminates nxagent by sending SIGTERM.

    """
    return self._SendSignal(signal.SIGTERM)

  def _SendSighup(self):
    """Sends a SIGHUP signal to nxagent.

    """
    return self._SendSignal(signal.SIGHUP)

  def _SendSignal(self, signum):
    """Sends a signal to nxagent.

    @type signum: int
    @param signum: Signal number

    """
    # Get signal name as string
    signame = utils.GetSignalName(signum)

    logging.info("Sending %s to nxagent", signame)
    try:
      os.kill(self._agent_pid, signum)
    except OSError, err:
      # kill(2) on ESRCH: The pid or process group does not exist. Note that
      # an existing process might be a zombie, a process which already
      # committed termination, but has not yet been wait(2)ed for.
      if err.errno not in (errno.ESRCH, ):
        raise
      logging.exception("Failed to send %s to nxagent", signame)

  def _HandleStderrLine(self, _, line):
    """Handle a line on nxagent's stderr output.

    @type line: string
    @param line: Line without newline

    """
    if self._CheckStatus(line):
      return

    m = _WATCHDOG_PID_RE.match(line)
    if m:
      self._watchdog_pid = int(m.group("pid"))
      logging.info("Matched info watchdog, PID %r", self._watchdog_pid)
      return

    m = _AGENT_PID_RE.match(line)
    if m:
      real_agent_pid = int(m.group("pid"))
      logging.info("Matched info agent_pid, PID %r", real_agent_pid)

      if self._agent_pid != real_agent_pid:
        # Probably caused by nxagent being a shell script
        logging.warning("Agent pid (%r) doesn't match spawned PID (%r)",
                        self._agent_pid, real_agent_pid)
        self._agent_pid = real_agent_pid

      return

    m = _WAIT_WATCHDOG_RE.match(line)
    if m:
      if self._watchdog_pid is None:
        logging.error("Matched info kill_watchdog, but no known watchdog pid")
      else:
        # Before terminating, nxagent starts a separate process, called
        # watchdog here, which must be sent SIGTERM. Otherwise it wouldn't
        # terminate.
        try:
          os.kill(self._watchdog_pid, signal.SIGTERM)
        except OSError, err:
          logging.warning(("Matched info kill_watchdog, got error from "
                           "killing PID %r: %r"), self._watchdog_pid, err)
        else:
          logging.info("Matched info kill_watchdog, sent SIGTERM.")

      return

    m = _GENERAL_ERROR_RE.match(line)
    if m:
      logging.error("Agent error: %s", m.group("error"))
      return

    m = _GENERAL_WARNING_RE.match(line)
    if m:
      logging.warning("Agent warning: %s", m.group("warning"))
      return

    m = _GEOMETRY_RE.match(line)
    if m:
      geometry = m.group("geometry")
      self._ChangeGeometry(geometry)
      logging.info("Matched info geometry change, new is %r", geometry)
      return

  def _CheckStatus(self, line, _status_map=None):
    """Check whether the line indicates a session status change.

    @type line: string
    @param line: Line without newline

    """
    sess = self._ctx.session

    if _status_map is None:
      _status_map = _STATUS_MAP

    for status, rx in _status_map.iteritems():
      m = rx.match(line)
      if m:
        logging.info("Nxagent changed status from %r to %r",
                     sess.state, status)
        self._ChangeStatus(m, sess.state, status)
        return True

    return False

  def _ChangeStatus(self, m, old, new):
    """Called when session status changed.

    @type m: x
    @param m: Regex match object
    @type old: str
    @param old: Previous session status
    @type new: str
    @param new: New session status

    """
    sess = self._ctx.session

    if new == old:
      pass

    elif (old == constants.SESS_STATE_CREATED and
          new == constants.SESS_STATE_STARTING):
      self.__EmitDisplayReady()

    elif new == constants.SESS_STATE_WAITING:
      port = m.group("port")

      try:
        portnum = int(port)
      except ValueError:
        logging.warning("Port number for nxagent (%r) is not numeric",
                        port)
        portnum = None

      logging.debug("Setting session port to %r", portnum)

      sess.port = portnum

    elif (old == constants.SESS_STATE_SUSPENDING and
          new == constants.SESS_STATE_SUSPENDED and
          self._want_restore):
      self._want_restore = False

      self._PrepareSessionRestore()

    elif (old == constants.SESS_STATE_TERMINATING and
          new == constants.SESS_STATE_TERMINATED):
      logging.info("Nxagent terminated")

    sess.state = new
    sess.Save()

  def _PrepareSessionRestore(self):
    """Prepare session restore by telling nxagent to reopen its port.

    """
    # Write options file with new options
    self._UpdateOptionsFile()

    # Send SIGHUP to reopen port
    self._SendSighup()

  def _ChangeGeometry(self, geometry):
    """Called when geometry changed.

    @type geometry: str
    @param geometry: Geometry information

    """
    sess = self._ctx.session
    sess.geometry = geometry
    sess.Save()

  def _FormatNxAgentOptions(self, opts):
    """Formats options for nxagent.

    @type opts: dict
    @param opts: Options

    """
    sess = self._ctx.session

    formatted = ",".join(["%s=%s" % (name, value)
                          for name, value in opts.iteritems()])

    return "%s:%s" % (formatted, sess.display)

  def _GetDisplayWithOptions(self):
    """Returns the value for the DISPLAY variable for nxagent.

    """
    opts = self._GetStaticOptions()

    return "nx/nx,%s" % self._FormatNxAgentOptions(opts)

  def _GetStaticOptions(self):
    """Returns static session options for nxagent.

    These don't change during the lifetime of a session.

    @rtype: dict
    @return: Options

    """
    sess = self._ctx.session

    # We need to write the type without the "unix-" prefix for nxagent
    if sess.type.startswith(constants.SESS_TYPE_UNIX_PREFIX):
      shorttype = sess.type[len(constants.SESS_TYPE_UNIX_PREFIX):]
    else:
      shorttype = sess.type

    opts = {
      # This limits what IPs nxagent will accept connections from. When using
      # encrypted sessions, connections are always from localhost. Unencrypted
      # connections come directly from nxclient.
      # Note: Unencrypted connections are not supported.
      "accept": "127.0.0.1",

      "backingstore": "1",
      "cleanup": "0",
      "clipboard": "both",
      "composite": "1",
      "cookie": sess.cookie,
      "id": sess.full_id,
      # TODO: What is this used for in nxagent?
      "product": "Neatx-%s" % constants.DEFAULT_SUBSCRIPTION,
      "shmem": "1",
      "shpix": "1",
      "strict": "0",
      "type": shorttype,
      "render": "1",
      }

    if sess.type == constants.SESS_TYPE_SHADOW:
      # TODO: Make shadowmode configurable and/or controllable by the shadowed
      # user.  Be aware, though, that this flag is under the control of the
      # shadowing user.
      # 0 = view only, 1 = interactive
      opts["shadowmode"] = "1"
      # TODO: Check which UID we should pass here.
      opts["shadowuid"] = self._ctx.uid
      opts["shadow"] = ":%s" % sess.shadow_display

    return opts

  def _GetOptions(self):
    """Returns session options for nxagent.

    These can change between different connections.

    @rtype: dict
    @return: Options

    """
    sess = self._ctx.session

    return {
      "cache": protocol.FormatNxSize(sess.cache),
      "client": sess.client,
      "fullscreen": protocol.FormatNxBoolean(sess.fullscreen),
      "geometry": sess.geometry,
      "images": protocol.FormatNxSize(sess.images),
      "keyboard": sess.keyboard,
      "link": sess.link,
      "resize": protocol.FormatNxBoolean(sess.resize),
      }

  def _GetNxAgentArgs(self):
    """Returns command line arguments for nxagent.

    """
    sess = self._ctx.session

    if sess.type == constants.SESS_TYPE_SHADOW:
      # Run nxagent in shadow mode
      mode = "-S"

    elif sess.rootless:
      # Run nxagent in rootless mode
      mode = "-R"

    else:
      # Run nxagent in desktop mode
      mode = "-D"

    args = [
      mode,
      "-name", sess.windowname,
      "-options", self._ctx.session.optionsfile,

      # Disable permanently-open TCP port for X protocol (doesn't affect
      # nxagent port).
      "-nolisten", "tcp",

      ":%s" % sess.display,
      ]

    if sess.type == constants.SESS_TYPE_SHADOW:
      args.append("-nopersistent")

    return args

  def _UpdateOptionsFile(self):
    """Update session options file.

    """
    self._WriteOptionsFile(self._GetOptions())

  def _WriteOptionsFile(self, opts):
    """Writes session options to the session-specific options file.

    @type opts: dict
    @param opts: Options

    """
    sess = self._ctx.session
    filename = sess.optionsfile
    formatted = self._FormatNxAgentOptions(opts)

    logging.debug("Writing session options %r to %s", formatted, filename)
    utils.WriteFile(filename, data=formatted, mode=0600)

  def __EmitDisplayReady(self):
    self.emit(self.DISPLAY_READY_SIGNAL)
