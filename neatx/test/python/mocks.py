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


"""Mocks for unittesting"""


from cStringIO import StringIO


class _FakeLog(object):
  def __init__(self):
    self.entries = []

  def AddEntry(self, fmt, *args):
    if args:
      self.entries.append(fmt % args)
    else:
      self.entries.append(fmt)


class FakeLogging(object):
  def __init__(self):
    self.error_log = _FakeLog()
    self.warning_log = _FakeLog()
    self.info_log = _FakeLog()
    self.debug_log = _FakeLog()

  def error(self, fmt, *args):
    self.error_log.AddEntry(fmt, *args)

  def warning(self, fmt, *args):
    self.warning_log.AddEntry(fmt, *args)

  warn = warning

  def info(self, fmt, *args):
    self.info_log.AddEntry(fmt, *args)

  def debug(self, fmt, *args):
    self.debug_log.AddEntry(fmt, *args)


class FakeTime(object):
  def __init__(self, seconds=0):
    self.seconds = float(seconds)

  def AddSeconds(self, seconds):
    self.seconds += seconds

  def sleep(self, duration):
    self.seconds += duration

  def time(self):
    return self.seconds


class FakeSession(object):
  def __init__(self):
    pass
