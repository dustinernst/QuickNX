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


"""Script for unittesting the nxserver module"""


import unittest

from neatx import constants
from neatx import errors
from neatx import utils
from neatx.app import nxserver

import mocks


class TestFormatOptions(unittest.TestCase):
  """Tests for FormatOptions"""

  def _DoTest(self, sess, expected):
    options = nxserver.FormatOptions(sess)
    self.failUnlessEqual(len(options), 8)
    self.failUnlessEqual(options, expected)

  def testNone(self):
    sess = mocks.FakeSession()
    sess.fullscreen = False
    sess.screeninfo = None
    sess.virtualdesktop = None
    self._DoTest(sess, "-----PSA")

  def testFullscreen(self):
    sess = mocks.FakeSession()
    sess.fullscreen = True
    sess.screeninfo = None
    sess.virtualdesktop = None
    self._DoTest(sess, "F----PSA")

  def testRender(self):
    sess = mocks.FakeSession()
    sess.fullscreen = False
    sess.screeninfo = "1024x768x32+render"
    sess.virtualdesktop = None
    self._DoTest(sess, "-R---PSA")

  def testDesktop(self):
    sess = mocks.FakeSession()
    sess.fullscreen = False
    sess.screeninfo = None
    sess.virtualdesktop = True
    self._DoTest(sess, "--D--PSA")


class TestGetSessionCache(unittest.TestCase):
  """Tests for _GetSessionCache"""

  def _DoTest(self, value, expected):
    sess = mocks.FakeSession()
    sess.type = value
    self.failUnlessEqual(nxserver._GetSessionCache(sess), expected)

  def test(self):
    self._DoTest("unix-kde", "unix-kde")
    self._DoTest("something", "unix-something")


if __name__ == '__main__':
  unittest.main()
