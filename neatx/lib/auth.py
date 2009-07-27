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


"""Module for authentication"""


import logging
import os
import pexpect
import re
from cStringIO import StringIO

from neatx import constants
from neatx import errors
from neatx import utils


class _AuthBase(object):
  def __init__(self, cfg,
               stdout_fileno=constants.STDOUT_FILENO,
               stdin_fileno=constants.STDIN_FILENO):
    self._cfg = cfg
    self._stdout_fileno = stdout_fileno
    self._stdin_fileno = stdin_fileno

  def AuthenticateAndRun(self, username, password, args):
    raise NotImplementedError()


class _ExpectAuthBase(_AuthBase):
  def AuthenticateAndRun(self, username, password, args):
    logging.debug("Authenticating as '%s', running %r", username, args)

    all_args = [self._GetTtySetupPath()] + self.GetCommand(username, args)
    logging.debug("Auth command %r", all_args)

    # Avoid NLS issues by setting LC_ALL=C
    env = os.environ.copy()
    env["LC_ALL"] = "C"

    # Using variables instead of hardcoded indexes
    patterns = []
    password_prompt_idx = self._AddPattern(patterns,
                                           self.GetPasswordPrompt())
    nx_idx = self._AddPattern(patterns, re.compile("^NX> ", re.M))

    # Start child process
    # TODO: Timeout in configuration and/or per auth method
    child = pexpect.spawn(all_args[0], args=all_args[1:], env=env,
                          timeout=30)

    buf = StringIO()
    nxbuf = StringIO()
    auth_successful = False

    try:
      while True:
        idx = child.expect(patterns)

        # Store all output seen before the match
        buf.write(child.before)
        # Store the matched output
        buf.write(child.after)

        if idx == password_prompt_idx:
          self._Send(child, password + os.linesep)

          # Wait for end of password prompt
          child.expect(os.linesep)

        # TODO: Timeout for programs not printing NX prompt within X seconds
        elif idx == nx_idx:
          # Program was started
          auth_successful = True

          nxbuf.write(child.after)
          nxbuf.write(child.buffer)
          break

        else:
          raise AssertionError("Invalid index")

    except pexpect.EOF:
      buf.write(child.before)

    except pexpect.TIMEOUT:
      buf.write(child.before)
      logging.debug("Authentication timed out (output=%r)", buf.getvalue())
      raise errors.AuthTimeoutError()

    if not auth_successful:
      raise errors.AuthFailedError(("Authentication failed (output=%r, "
                                    "exitstatus=%s, signum=%s)") %
                                   (utils.NormalizeSpace(buf.getvalue()),
                                    child.exitstatus, child.signalstatus))

    # Write protocol buffer contents to stdout
    os.write(self._stdout_fileno, nxbuf.getvalue())

    utils.SetCloseOnExecFlag(child.fileno(), False)
    utils.SetCloseOnExecFlag(self._stdin_fileno, False)
    utils.SetCloseOnExecFlag(self._stdout_fileno, False)

    cpargs = [self._GetFdCopyPath(),
              "%s:%s" % (child.fileno(), self._stdout_fileno),
              "%s:%s" % (self._stdin_fileno, child.fileno())]

    # Run fdcopy to copy data between file descriptors
    ret = os.spawnve(os.P_WAIT, cpargs[0], cpargs, env)
    (exitcode, signum) = utils.GetExitcodeSignal(ret)
    logging.debug("fdcopy exited (exitstatus=%s, signum=%s)",
                  exitcode, signum)

    # Discard anything left in buffer
    child.read()

    def _CheckChild():
      if child.isalive():
        raise utils.RetryAgain()

    logging.info("Waiting for authenticated program to finish")
    try:
      utils.Retry(_CheckChild, 0.5, 1.1, 5.0, 30)
    except utils.RetryTimeout:
      logging.error("Timeout while waiting for authenticated program "
                    "to finish")

    child.close()

    logging.debug(("Authenticated program finished (exitstatus=%s, "
                   "signalstatus=%s)"), child.exitstatus, child.signalstatus)

  def _GetFdCopyPath(self):
    return constants.FDCOPY

  def _GetTtySetupPath(self):
    return constants.TTYSETUP


  @staticmethod
  def _Send(child, text):
    """Write password to child program.

    """
    # child.send may not write everything in one go
    pos = 0
    while True:
      pos += child.send(text[pos:])
      if pos >= len(text):
        break

  @staticmethod
  def _AddPattern(patterns, pattern):
    """Adds pattern to list and returns new index.

    """
    patterns.append(pattern)
    return len(patterns) - 1


class SuAuth(_ExpectAuthBase):
  def GetCommand(self, username, args):
    cmd = " && ".join([
      # Change to home directory
      "cd",

      # Run command
      utils.ShellQuoteArgs(args)
      ])
    return [constants.SU, username, "-c", cmd]

  def GetPasswordPrompt(self):
    return re.compile(r"^Password:\s*", re.I | re.M)


class SshAuth(_ExpectAuthBase):
  def GetCommand(self, username, args):
    # TODO: Allow for per-user hostname. A very flexible way would be to run an
    # external script (e.g. "/.../userhost $username"), and let it print the
    # target hostname on stdout. If the hostname is an absolute path it could
    # be used as the script.
    host = self._cfg.auth_ssh_host
    port = self._cfg.auth_ssh_port

    options = [
      "-oNumberOfPasswordPrompts=1",
      "-oPreferredAuthentications=password",
      "-oEscapeChar=none",
      "-oCompression=no",

      # Always trust host keys
      "-oStrictHostKeyChecking=no",
      # Don't try to write a known_hosts file
      "-oUserKnownHostsFile=/dev/null",
      ]

    cmd = utils.ShellQuoteArgs(args)
    return ([constants.SSH, "-2", "-x", "-l", username, "-p", str(port)] +
            options + [host, "--", cmd])

  def GetPasswordPrompt(self):
    return re.compile(r"^.*@.*\s+password:\s*", re.I | re.M)


_AUTH_METHOD_MAP = {
  constants.AUTH_METHOD_SU: SuAuth,
  constants.AUTH_METHOD_SSH: SshAuth,
  }


def GetAuthenticator(cfg, _method_map=_AUTH_METHOD_MAP):
  """Returns the authenticator for an authentication method.

  @type cfg: L{config.Config}
  @param cfg: Configuration object
  @rtype: class
  @return: Authentication class
  @raise errors.UnknownAuthMethod: Raised when an unknown authentication method
    is requested

  """
  method = cfg.auth_method
  try:
    cls = _method_map[method]
  except KeyError:
    raise errors.UnknownAuthMethod("Unknown authentication method %r" % method)

  return cls(cfg)
