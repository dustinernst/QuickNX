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


"""nxserver-login program

"""


import logging
import os.path
import re
import sys

from neatx import auth
from neatx import cli
from neatx import constants
from neatx import errors
from neatx import protocol
from neatx import utils


PROGRAM = "nxserver-login"

NX_PROMPT_USER = "User: "
NX_PROMPT_PASSWORD = "Password: "
NX_DUMMY_PASSWORD = "**********"
NX_GUEST_USER = "NX guest user"

NX_VAR_AUTH_MODE = "auth_mode"
NX_VAR_SHELL_MODE = "shell_mode"

NX_AUTH_MODE_PASSWORD = "password"
NX_SHELL_MODE_SHELL = "shell"

RE_PROTOCOL = re.compile(r"^nxclient\s+-\s+version\s+(?P<ver>[\d.]+)\s*$",
                         re.I)


class LoginCommandHandler(object):
  """NX protocol handler for the nxserver-login component.

  """
  def __init__(self, server, cfg):
    self._server = server
    self._cfg = cfg
    self._protocol_version = None

  def __call__(self, command):
    (cmd, args) = protocol.SplitCommand(command)

    if cmd == protocol.NX_CMD_SET:
      # Special confirmation needed
      return self._Set(args)

    self._server.WriteLine(command.lstrip().capitalize())

    if cmd == protocol.NX_CMD_LOGIN:
      return self._Login(args)

    elif cmd == protocol.NX_CMD_HELLO:
      return self._Hello(args)

    elif cmd == protocol.NX_CMD_QUIT:
      raise protocol.NxQuitServer()

    elif cmd in (protocol.NX_CMD_BYE,
                 protocol.NX_CMD_STARTSESSION,
                 protocol.NX_CMD_ATTACHSESSION):
      raise protocol.NxNotBeforeLogin(cmd)

    else:
      raise protocol.NxUndefinedCommand(cmd)

  def _Hello(self, args):
    """The "hello" command.

    """
    m = RE_PROTOCOL.match(args)
    if not m:
      raise protocol.NxUnsupportedProtocol()

    protocol_version = m.group("ver")

    try:
      parsed_protocol_version = \
        utils.ParseVersion(protocol_version, ".-",
                           constants.PROTOCOL_VERSION_DIGITS)
    except ValueError:
      raise protocol.NxUnsupportedProtocol()

    logging.debug("Got client protocol version %r (%r), want %r",
                  parsed_protocol_version, protocol_version,
                  self._cfg.nx_protocol_version)

    if parsed_protocol_version != self._cfg.nx_protocol_version:
      raise protocol.NxUnsupportedProtocol()

    self._server.Write(134, "Accepted protocol: %s" % protocol_version)

    # Keep the version for nxserver
    self._protocol_version = parsed_protocol_version

  def _Login(self, args):
    """The "login" command.

    """
    if utils.GetCurrentUserName() != constants.NXUSER:
      # If current user is not 'nx', user has already authenticated against
      # ssh as himself. So we just run nx server.
      return self._RunNxServer()

    server = self._server

    server.Write(101, NX_PROMPT_USER, newline=False)
    username = server.ReadLine()

    # Abort if no username was received
    if not username:
      msgs = [
        r"ERROR: Username is not in the expected format.",
        r"ERROR: Please retype your username and be sure you don't",
        r"ERROR: include '\n', '\r', a space or any other unwanted",
        r"ERROR: character.",
        ]

      for msg in msgs:
        server.Write(500, msg)

      raise protocol.NxQuitServer()

    # Not writing username. If user specified a username starting with "NX>",
    # the client could interpret it as a response.
    server.WriteLine("")

    # Read password without echo on interactive terminals
    def _RequestPassword():
      # Write prompt only after echo has been turned off
      server.Write(102, NX_PROMPT_PASSWORD, newline=False)
      return server.ReadLine(hide=True)

    password = server.WithoutTerminalEcho(_RequestPassword)
    if not password:
      server.Write(500, ("Password cannot be in MD5 when not using the NX "
                         "password DB."))
      server.Write(500, "Please update your NX Client")
      raise protocol.NxQuitServer()

    # Not writing real password for security reasons.
    server.WriteLine(NX_DUMMY_PASSWORD)

    self._TryLogin(username, password)

  def _Set(self, args):
    """The "set" command.

    """
    parts = args.split(None, 1)

    if parts:
      var = parts[0]
    else:
      var = ""

    if len(parts) > 1:
      value = parts[1]
    else:
      value = ""

    # Write confirmation
    self._server.WriteLine("Set %s: %s" % (var, value))

    if not var:
      self._server.Write(500, message="ERROR: missing parameter 'variable'")

    elif var.lower() == NX_VAR_AUTH_MODE:
      return self._SetAuthMode(value)

    elif var.lower() == NX_VAR_SHELL_MODE:
      return self._SetShellMode(value)

    raise protocol.NxProtocolError(500, "ERROR: unknown variable '%s'" % var)

  def _SetAuthMode(self, value):
    """The "set auth_mode" command.

    """
    if not (value and value.lower() == NX_AUTH_MODE_PASSWORD):
      raise protocol.NxProtocolError(500,
                                     "ERROR: unknown auth mode '%s'" % value)

  def _SetShellMode(self, value):
    """The "set shell_mode" command.

    """
    if not (value and value.lower() == NX_SHELL_MODE_SHELL):
      raise protocol.NxProtocolError(500,
                                     "ERROR: unknown shell mode '%s'" % value)

  def _GetNxServerArgs(self, username):
    """Returns command line arguments to run nxserver for a given username

    """
    if self._protocol_version is None:
      # Fallback to default version
      protocol_version = self._cfg.nx_protocol_version
    else:
      protocol_version = self._protocol_version

    return [constants.NXSERVER, "--proto=%s" % protocol_version, "--", username]

  def _RunNxServer(self):
    """Runs nxserver as the current user.

    This method executes nxserver that replaces the current process and
    does not return if successful.
    In case of error appropriate exception is thrown.

    """
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    args = self._GetNxServerArgs(utils.GetCurrentUserName())
    os.execve(args[0], args, env)

  def _TryLogin(self, username, password):
    """Login user and run nxserver.

    """
    server = self._server

    logging.info("Trying login for user %r using auth method %r", username,
                 self._cfg.auth_method)

    # Passing username to support virtual users in the future
    args = self._GetNxServerArgs(username)

    authenticator = auth.GetAuthenticator(self._cfg)

    try:
      # AuthenticateAndRun doesn't return until the client disconnects or an
      # error occurs.
      authenticator.AuthenticateAndRun(username, password, args)
    except errors.AuthFailedError:
      logging.exception("Authentication failed")
      server.Write(404, "ERROR: wrong password or login.")
    except errors.AuthError:
      logging.exception("Error in authentication")
      server.Write(503, "ERROR: Internal error.")

    raise protocol.NxQuietQuitServer()


class LoginServer(protocol.NxServerBase):
  def __init__(self, cfg):
    self._cfg = cfg
    protocol.NxServerBase.__init__(self, sys.stdin, sys.stdout,
                                   LoginCommandHandler(self, cfg))

  def SendBanner(self):
    """Send banner to peer.

    """
    banner = ("HELLO NXSERVER - Version %s - GPL" %
              utils.FormatVersion(self._cfg.nx_protocol_version, ".",
                                  constants.PROTOCOL_VERSION_DIGITS))

    self.WriteLine(banner)


class NxServerLoginProgram(cli.GenericProgram):
  def Run(self):
    LoginServer(self.cfg).Start()


def Main():
  logsetup = utils.LoggingSetup(PROGRAM)
  NxServerLoginProgram(logsetup).Main()
