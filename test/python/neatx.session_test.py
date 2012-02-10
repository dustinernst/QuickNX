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


"""Script for unittesting the session module"""


import logging
import os
import os.path
import shutil
import tempfile
import unittest

from neatx import constants
from neatx import errors
from neatx import session
from neatx import utils


class _SaveableFakeSession(session.SessionBase):
  pass


class TestNewUniqueId(unittest.TestCase):
  """Tests for NewUniqueId"""

  def test(self):
    wanted = set("ABCDEF0123456789")
    found = set()

    # NewUniqueId uses a hash algorithm, hence we've to run it
    # several times to cover the whole charset.
    for i in xrange(1, 5):
      sessid = session.NewUniqueId(_data=i)
      self.failUnlessEqual(len(sessid), 32)

      chars = set(sessid)
      self.failUnlessEqual(len(chars - wanted), 0)

      # Keep used chars
      found |= chars

    self.failUnlessEqual(len(found), len(wanted))


class TestNxSessionManager(unittest.TestCase):
  """Tests for NxSessionManager"""

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.mgr = session.NxSessionManager(_path=self.tmpdir)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _CreateSession(self, host, display, user):
    sessid = self.mgr.CreateSessionID()

    sesspath = os.path.join(self.tmpdir, sessid)
    self.failUnless(os.path.exists(sesspath))

    sess = _SaveableFakeSession(sessid, host, display, user)
    self.failUnlessEqual(sess.id, sessid)
    self.failUnlessEqual(sess.hostname, host)
    self.failUnlessEqual(sess.display, display)
    self.failUnlessEqual(sess.username, user)
    self.failUnlessEqual(sess.state, constants.SESS_STATE_CREATED)
    self.failUnless(sess.cookie is not None)

    sessdatapath = os.path.join(self.tmpdir, sess.id,
                                constants.SESSION_DATA_FILE_NAME)
    self.failIf(os.path.exists(sessdatapath))

    self.mgr.SaveSession(sess)
    self.failUnless(os.path.exists(sessdatapath))

    return (sess, sessid, sesspath, sessdatapath)

  def testSession(self):
    (sess1, sessid1, _, _) = self._CreateSession("localhost", 1, "joedoe")

    sess1.name = "foobar"
    self.failUnlessEqual(sess1.name, "foobar")

    self.mgr.SaveSession(sess1)

    self.failUnlessEqual(sess1.id, sessid1)
    self.failUnlessEqual(sess1.name, "foobar")

  def testFindSessionsWithFilter(self):
    (sess1, _, _, _) = self._CreateSession("localhost", 1, "user_a")
    (sess2, _, _, _) = self._CreateSession("localhost", 2, "user_a")
    (sess3, _, _, _) = self._CreateSession("localhost", 3, "user_b")
    (sess4, _, _, _) = self._CreateSession("localhost", 4, "user_c")

    # Filter without username and function
    result = self.mgr.FindSessionsWithFilter(None, None)
    self.failUnlessEqual(len(result), 4)

    # Filter with username without function
    result = self.mgr.FindSessionsWithFilter("user_a", None)
    self.failUnlessEqual(len(result), 2)
    self.failUnless(isinstance(result[0], session.NxSession))
    self.failUnless(isinstance(result[1], session.NxSession))
    self.failIf(set([result[0].id, result[1].id]) - set([sess1.id, sess2.id]))

    # Filter with username and without function
    result = self.mgr.FindSessionsWithFilter("user_b", None)
    self.failUnlessEqual(len(result), 1)
    self.failUnless(isinstance(result[0], session.NxSession))
    self.failUnlessEqual(result[0].id, sess3.id)

    # Set data for filter function tests
    sess1.state = constants.SESS_STATE_RUNNING
    sess2.state = constants.SESS_STATE_TERMINATING
    sess3.state = constants.SESS_STATE_RUNNING
    sess4.type = "unix-kde"
    self.mgr.SaveSession(sess1)
    self.mgr.SaveSession(sess2)
    self.mgr.SaveSession(sess3)
    self.mgr.SaveSession(sess4)

    # Filter with username and function
    result = self.mgr.FindSessionsWithFilter("user_c", self._FilterTypeUnixKde)
    self.failUnlessEqual(len(result), 1)
    self.failUnlessEqual(result[0].id, sess4.id)

    # Filter without username, with function
    result = self.mgr.FindSessionsWithFilter(None, self._FilterStateRunning)
    self.failUnlessEqual(len(result), 2)
    self.failUnlessEqual(result[0].state, constants.SESS_STATE_RUNNING)
    self.failUnlessEqual(result[1].state, constants.SESS_STATE_RUNNING)
    self.failIf(set([result[0].id, result[1].id]) - set([sess1.id, sess3.id]))

  @staticmethod
  def _FilterTypeUnixKde(sess):
    return sess.type == "unix-kde"

  @staticmethod
  def _FilterStateRunning(sess):
    return sess.state == constants.SESS_STATE_RUNNING

  def testLoadSessionForUser(self):
    (sess1, _, _, _) = self._CreateSession("localhost", 1, "user_a")
    (sess2, _, _, _) = self._CreateSession("localhost", 2, "user_a")
    (sess3, _, _, _) = self._CreateSession("localhost", 2, "user_b")

    self.failUnless(self.mgr.LoadSessionForUser(sess1.id, "user_a"))
    self.failUnless(self.mgr.LoadSessionForUser(sess2.id, "user_a"))
    self.failUnless(self.mgr.LoadSessionForUser(sess3.id, "user_b"))
    self.failIf(self.mgr.LoadSessionForUser(sess1.id, "!otheruser!"))
    self.failIf(self.mgr.LoadSessionForUser(sess2.id, "user_b"))

  def testState(self):
    (sess, _, _, _) = self._CreateSession("localhost", 1, "joedoe")

    def _SetState(state):
      sess.state = state

    _SetState(constants.SESS_STATE_STARTING)
    self.failUnlessRaises(errors.InvalidSessionState, _SetState, "!invalid!")
    self.failUnlessRaises(errors.InvalidSessionState, _SetState, "!dummy!")
    self.failUnlessEqual(sess.state, constants.SESS_STATE_STARTING)


if __name__ == '__main__':
  # TODO: Move this to a generic function
  logging.disable(logging.CRITICAL)
  unittest.main()
