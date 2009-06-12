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


"""Script for unittesting the protocol module"""


import unittest

from neatx import constants
from neatx import errors
from neatx import protocol
from neatx import utils

import mocks


class TestParseParameters(unittest.TestCase):
  """Tests for ParseParameters"""

  def setUp(self):
    self._fake_logging = mocks.FakeLogging()

  def _DoTest(self, params, expected):
    result = protocol.ParseParameters(params, _logging=self._fake_logging)
    self.failUnlessEqual(result, expected)

  def _DoFailTest(self, params):
    self.failUnlessRaises(protocol.NxParameterParsingError,
                          protocol.ParseParameters, params,
                          _logging=self._fake_logging)

  def test(self):
    self._DoTest("", [])
    self._DoTest(" ", [])
    self._DoTest("\t", [])
    self._DoTest("--session=\"\"", [("session", "")])
    self._DoTest("--session=\"\" --name=\"\"", [("session", ""), ("name", "")])
    self._DoTest("--session=\"123\"", [("session", "123")])
    self._DoTest(" --session=\"123\"", [("session", "123")])
    self._DoTest("--session=\"123\" ", [("session", "123")])
    self._DoTest(" --session=\"123\" ", [("session", "123")])

    self._DoTest("--session=\"123\" --name=\"dummy\"",
                 [("session", "123"), ("name", "dummy")])
    self._DoTest(" --session=\"123\" --name=\"dummy\" ",
                 [("session", "123"), ("name", "dummy")])
    self._DoTest("\t--session=\"123\"\t--name=\"dummy\"\n",
                 [("session", "123"), ("name", "dummy")])
    self._DoTest("--session=\" value with spaces \" --name=\" a b\tc \"\n",
                 [("session", " value with spaces "), ("name", " a b\tc ")])

    self._DoTest("--name=\"x\" --name=\"y\"", [("name", "x"), ("name", "y")])

    self._DoFailTest(",")
    self._DoFailTest("-")
    self._DoFailTest("--x")
    self._DoFailTest("--xyz=")
    self._DoFailTest("--xyz=\"")
    self._DoFailTest("--xyz=\"\"\"")
    self._DoFailTest("--xyz=\"\"a")
    self._DoFailTest("--xyz=\"\" --name")
    self._DoFailTest("--xyz=\"\" --name=\"")
    self._DoFailTest("--xyz=\"\",--name=\"\"")
    self._DoFailTest("--xyz=\"\", --name=\"\"")
    self._DoFailTest("--xyz=\"\" , --name=\"\"")


class TestUnquoteParameterValue(unittest.TestCase):
  """Tests for UnquoteParameterValue"""

  def _DoTest(self, value, expected):
    unquoted = protocol.UnquoteParameterValue(value)
    self.failUnlessEqual(unquoted, expected)

  def test(self):
    self._DoTest("abc", "abc")
    self._DoTest("x%3D%22abc%20+%20%22%3B%3A%3B%20/usr/bin/xterm",
                 """x="abc + ";:; /usr/bin/xterm""")
    self._DoTest("%26%20-%20_%20/%20+%20%27%20%22%20(%20)%20%5B%20%5D%20%7C",
                 """& - _ / + ' " ( ) [ ] |""")


if __name__ == '__main__':
  unittest.main()
