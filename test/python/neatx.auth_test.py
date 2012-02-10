#!/usr/bin/python
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


"""Script for unittesting the auth module"""


import os
import re
import tempfile
import unittest

from neatx import auth
from neatx import constants
from neatx import errors
from neatx import utils


DUMMY_USER = "dummyuser"
DUMMY_USER2 = "anotheruser"
DUMMY_PASSWORD = "Pa$$W0rd"
DUMMY_PASSWORD2 = "something"


def _WriteAuthScript(confirmation):
  (fd, name) = tempfile.mkstemp()
  try:
    os.chmod(name, 0700)

    try:
      def w(*args):
        for i in args:
          os.write(fd, i)
        os.write(fd, "\n")

      w("#!", constants.BASH)
      w("DUMMY_USER='", DUMMY_USER, "'")
      w("DUMMY_PASSWORD='", DUMMY_PASSWORD, "'")
      w("user=$1; shift")
      w("if [[ \"$user\" != \"$DUMMY_USER\" ]]; then")
      w("  echo 'Unknown user'")
      w("  exit 1")
      w("fi")
      w("read -s -p 'Password: ' pw < /dev/tty")
      w("echo")
      w("if [[ \"$pw\" != \"$DUMMY_PASSWORD\" ]]; then")
      w("  echo 'Authentication failed'")
      w("  exit 1")
      w("fi")
      if confirmation:
        w("echo Authentication successful")
      w("exec \"$@\"")
    finally:
      os.close(fd)
  except:
    utils.RemoveFile(name)
    raise

  return name


class _DummyPasswordAuth:
  def __init__(self, cfg):
    pass


class _DummyLdapAuth:
  def __init__(self, cfg):
    pass


class _DummyAuth(auth._ExpectAuthBase):
  def __init__(self, cfg, authcmd, stdout_fileno, stdin_fileno):
    auth._ExpectAuthBase.__init__(self, cfg,
                                  stdout_fileno=stdout_fileno,
                                  stdin_fileno=stdin_fileno)
    self._authcmd = authcmd

  def GetCommand(self, username, args):
    return [self._authcmd, username] + args

  def GetPasswordPrompt(self):
    return re.compile(r"^Password:\s*", re.I)

  def _GetFdCopyPath(self):
    return "src/fdcopy"

  def _GetTtySetupPath(self):
    return "src/ttysetup"


class _FakeAuthConfig:
  def __init__(self, auth_method):
    self.auth_method = auth_method

    self.auth_ssh_host = "localhost"
    self.auth_ssh_port = 22

    self.su = constants.SU
    self.ssh = constants.SSH


class TestGetAuthenticator(unittest.TestCase):
  """Tests for GetAuthenticator"""

  def test(self):
    dummy_map = {
      "password": _DummyPasswordAuth,
      "ldap": _DummyLdapAuth,
      }

    authenticator = auth.GetAuthenticator(_FakeAuthConfig("password"),
                                          _method_map=dummy_map)
    self.failUnless(isinstance(authenticator, _DummyPasswordAuth))
    self.failIf(isinstance(authenticator, _DummyLdapAuth))

    authenticator = auth.GetAuthenticator(_FakeAuthConfig("ldap"),
                                          _method_map=dummy_map)
    self.failUnless(isinstance(authenticator, _DummyLdapAuth))
    self.failIf(isinstance(authenticator, _DummyPasswordAuth))

    self.failUnlessRaises(errors.UnknownAuthMethod, auth.GetAuthenticator,
                          _FakeAuthConfig("nonexisting"),
                          _method_map=dummy_map)


class TestExpectAuthBase(unittest.TestCase):
  """Tests for _ExpectAuthBase"""

  def testGetCommand(self):
    cfg = _FakeAuthConfig("dummy")
    username = "NXtestNX"
    command = "/NX/test/NX"

    for (cls, wanted_arg0) in [(auth.SuAuth, constants.SU),
                               (auth.SshAuth, constants.SSH)]:
      args = cls(cfg).GetCommand(username, [command, "a", "b"])
      self.failUnlessEqual(args[0], wanted_arg0)
      self.failUnless(username in args)
      self.failUnless(filter(lambda value: ("%s a b" % command) in value,
                             args))

  def testAuth(self):
    authcmd = _WriteAuthScript(False)
    try:
      nullfile = tempfile.TemporaryFile()
      input = tempfile.TemporaryFile()
      cfg = _FakeAuthConfig("dummy")

      authenticator = _DummyAuth(cfg, authcmd, nullfile.fileno(),
                                 input.fileno())

      authenticator.AuthenticateAndRun(DUMMY_USER, DUMMY_PASSWORD,
                                       ["/bin/echo", "NX> "])
      authenticator.AuthenticateAndRun(DUMMY_USER, DUMMY_PASSWORD,
                                       ["/bin/echo", "NX> 105"])

      self.failUnlessRaises(errors.AuthFailedError,
                            authenticator.AuthenticateAndRun,
                            DUMMY_USER, DUMMY_PASSWORD2,
                            ["/bin/echo", "NX> 105"])

      self.failUnlessRaises(errors.AuthFailedError,
                            authenticator.AuthenticateAndRun,
                            DUMMY_USER2, DUMMY_PASSWORD,
                            ["/bin/echo", "NX> 105"])

      self.failUnlessRaises(errors.AuthFailedError,
                            authenticator.AuthenticateAndRun,
                            DUMMY_USER, DUMMY_PASSWORD,
                            ["/bin/echo", "ERROR"])
    finally:
      utils.RemoveFile(authcmd)

  def testAuthOutput(self):
    expected = "NX> 105\n" + (1000 * "Hello World\n")
    cmd = ("set -e;"
           "echo 'NX> 105';"
           "for ((i=0; i<1000; ++i)); do"
           "  echo 'Hello World';"
           "done")

    for confirmation in [False, True]:
      dummyout = tempfile.TemporaryFile()
      input = tempfile.TemporaryFile()
      cfg = _FakeAuthConfig("dummy")

      authcmd = _WriteAuthScript(confirmation)
      try:
        authenticator = _DummyAuth(cfg, authcmd, dummyout.fileno(),
                                   input.fileno())

        authenticator.AuthenticateAndRun(DUMMY_USER, DUMMY_PASSWORD,
                                         [constants.BASH, "-c", cmd])
      finally:
        utils.RemoveFile(authcmd)

      os.lseek(dummyout.fileno(), 0, 0)
      data = os.read(dummyout.fileno(), len(expected) * 2)
      self.failUnlessEqual(data, expected)


if __name__ == '__main__':
  unittest.main()
