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


"""Script for unittesting the nxserver_login module"""


import unittest

from neatx import constants
from neatx import errors
from neatx import protocol
from neatx.app import nxserver_login


class TestConstants(unittest.TestCase):
  """Tests for constants"""

  def test(self):
    dummy_password = nxserver_login.NX_DUMMY_PASSWORD
    self.failIf(dummy_password.startswith(protocol.NX_PROMPT))


if __name__ == '__main__':
  unittest.main()
