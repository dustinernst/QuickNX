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


"""Script for unittesting the utils module"""


import fcntl
import os
import shutil
import tempfile
import unittest
from cStringIO import StringIO

from neatx import constants
from neatx import utils

import mocks


BLOCKSIZES = range(1, 17) + [32, 512, 1024, 4096]


class TestGetExitcodeSignal(unittest.TestCase):
  """Tests for GetExitcodeSignal"""

  def _DoTest(self, status, expected):
    self.failUnlessEqual(utils.GetExitcodeSignal(status), expected)

  def testExitcode(self):
    self._DoTest(0, (0, None))
    self._DoTest(1, (1, None))
    self._DoTest(255, (255, None))

  def testSignal(self):
    self._DoTest(-1, (None, 1))
    self._DoTest(-2, (None, 2))
    self._DoTest(-9, (None, 9))


class TestVersionCompare(unittest.TestCase):
  """Tests for VersionCompare"""

  def _DoTest(self, cmp_fn, first, second, expected):
    self.failUnlessEqual(cmp_fn(first, second), expected)
    self.failUnlessEqual(cmp_fn(second, first), -expected)

  def testMultiSep(self):
    cmp_fn = utils.GetVersionComparator("-,.~")
    self._DoTest(cmp_fn, "1", "2", -1)
    self._DoTest(cmp_fn, "1.0", "2.0", -1)
    self._DoTest(cmp_fn, "1.0~alpha0", "1.0~alpha1", -1)
    self._DoTest(cmp_fn, "1", "1", 0)
    self._DoTest(cmp_fn, "1.0.1.3.9", "1.0.1.3.9", 0)
    self._DoTest(cmp_fn, "foo,bar", "foo,bar", 0)
    self._DoTest(cmp_fn, "foo,a", "foo,b", -1)
    self._DoTest(cmp_fn, "1-3", "1-4", -1)
    self._DoTest(cmp_fn, "1_a0", "1_a1", -1)
    self._DoTest(cmp_fn, "1.0", "1.0.0", -1)
    self._DoTest(cmp_fn, "1.0.1", "1.1", -1)

  def testSingleSep(self):
    cmp_fn = utils.GetVersionComparator(".")
    self._DoTest(cmp_fn, "1", "2", -1)
    self._DoTest(cmp_fn, "1.0", "2.0", -1)
    self._DoTest(cmp_fn, "1.0.1", "1.0.2", -1)

  def testWithCount(self):
    cmp_fn = utils.GetVersionComparator(".", count=3)
    self._DoTest(cmp_fn, "1", "2", -1)
    self._DoTest(cmp_fn, "1.0", "2.0", -1)
    self._DoTest(cmp_fn, "1.0.1", "1.0.2", -1)
    self._DoTest(cmp_fn, "1.0.1.3", "1.0.1.4", 0)
    self._DoTest(cmp_fn, "3.0.3", "3.0.3.1", 0)

    cmp_fn = utils.GetVersionComparator("~.,:", count=2)
    self._DoTest(cmp_fn, "1:2~3", "2:3~3", -1)
    self._DoTest(cmp_fn, "1:2~3", "1:2~4", 0)

  def testConversion(self):
    self.failUnlessEqual(utils._ConvertVersionPart("1"), 1)
    self.failUnlessEqual(utils._ConvertVersionPart("999999"), 999999)
    self.failUnlessEqual(utils._ConvertVersionPart("abc"), "abc")
    self.failUnlessEqual(utils._ConvertVersionPart(u"\u2083"), u"\u2083")

  def _DoTestSplitter(self, version, sep, count, expected):
    fn = utils._GetVersionSplitter(sep, count)
    self.failUnless(callable(fn))
    self.failUnlessEqual(fn(version), expected)

  def testSplitter(self):
    parts = ["1", "2", "3"]
    for sep in (".", ".:~"):
      self._DoTestSplitter("1.2.3", sep, -1, ["1", "2", "3"])
      for i in xrange(1, 50):
        self._DoTestSplitter("1.2.3", sep, i, parts[:i])
      self._DoTestSplitter("1_2_3", sep, 1, ["1_2_3"])

    self.failUnlessRaises(AssertionError, utils._GetVersionSplitter, "", 1)
    self.failUnlessRaises(AssertionError, utils._GetVersionSplitter, ".", 0)
    self.failUnlessRaises(AssertionError, utils._GetVersionSplitter, ".", -100)


class TestParseVersion(unittest.TestCase):
  """Tests for ParseVersion"""

  def test(self):
    self.failUnlessEqual(utils.ParseVersion("0", ".", [2]), 0)
    self.failUnlessEqual(utils.ParseVersion("1", ".", [2]), 1)
    self.failUnlessEqual(utils.ParseVersion("99", ".", [2]), 99)

    self.failUnlessEqual(utils.ParseVersion("3.2.0-6", ".-", [2]), 3)
    self.failUnlessEqual(utils.ParseVersion("3.2.0-6", ".-", [2, 2]), 302)
    self.failUnlessEqual(utils.ParseVersion("3.2.0-6", ".-", [2, 2, 4]),
                         3020000)
    self.failUnlessEqual(utils.ParseVersion("99.99.99", ".-", [2, 2, 2]),
                         999999)
    self.failUnlessEqual(utils.ParseVersion("99.99.99-9999", ".-", [2, 2, 2]),
                         999999)
    self.failUnlessEqual(utils.ParseVersion("99-9999", ".-", [2, 4]), 999999)
    self.failUnlessEqual(utils.ParseVersion("9999", ".-", [4, 2, 2]), 99990000)

    self.failUnlessEqual(utils.ParseVersion("3.3.0.2-1", ".-", [2, 2, 4]),
                         3030000)

    self.failUnlessRaises(ValueError, utils.ParseVersion, "999", ".", [2])
    self.failUnlessRaises(ValueError, utils.ParseVersion, "333.222.0-6", ".-",
                          [2])
    self.failUnlessRaises(ValueError, utils.ParseVersion, "333.222.0-6", ".-",
                          [2, 2])
    self.failUnlessRaises(ValueError, utils.ParseVersion, "1~alpha0", "~",
                          [2, 2])


class TestFormatVersion(unittest.TestCase):
  """Tests for FormatVersion"""

  def test(self):
    self.failUnlessEqual(utils.FormatVersion(0, ".", [2, 2, 2]), "0.0.0")
    self.failUnlessEqual(utils.FormatVersion(1, ".", [2, 2, 2]), "0.0.1")

    self.failUnlessEqual(utils.FormatVersion(3030002, ".", [2, 2, 4]), "3.3.2")
    self.failUnlessEqual(utils.FormatVersion(99000000, ".", [2, 2, 4]),
                         "99.0.0")
    self.failUnlessEqual(utils.FormatVersion(23, ".", [2]), "23")
    self.failUnlessEqual(utils.FormatVersion(123456, ".", [2, 2, 2]),
                         "12.34.56")

    self.failUnlessRaises(ValueError, utils.FormatVersion, 123, ".", [2])
    self.failUnlessRaises(ValueError, utils.FormatVersion, 99123, ".", [2, 2])


class TestNormalizeSpace(unittest.TestCase):
  """Tests for NormalizeSpace"""

  def test(self):
    self.failUnlessEqual(utils.NormalizeSpace(""), "")
    self.failUnlessEqual(utils.NormalizeSpace("abc"), "abc")
    self.failUnlessEqual(utils.NormalizeSpace(" abc"), "abc")
    self.failUnlessEqual(utils.NormalizeSpace("abc "), "abc")
    self.failUnlessEqual(utils.NormalizeSpace(" abc "), "abc")
    self.failUnlessEqual(utils.NormalizeSpace(" abc xyz "), "abc xyz")
    self.failUnlessEqual(utils.NormalizeSpace(" \r\n\t"), "")
    self.failUnlessEqual(utils.NormalizeSpace(" x\ry\nz\t "), "x y z")


class TestSetCloseOnExecFlag(unittest.TestCase):
  """Tests for SetCloseOnExecFlag"""

  def setUp(self):
    self.tmpfile = tempfile.TemporaryFile()

  def testEnable(self):
    utils.SetCloseOnExecFlag(self.tmpfile.fileno(), True)
    self.failUnless(fcntl.fcntl(self.tmpfile.fileno(), fcntl.F_GETFD) &
                    fcntl.FD_CLOEXEC)

  def testDisable(self):
    utils.SetCloseOnExecFlag(self.tmpfile.fileno(), False)
    self.failIf(fcntl.fcntl(self.tmpfile.fileno(), fcntl.F_GETFD) &
                fcntl.FD_CLOEXEC)


class TestListVisibleFiles(unittest.TestCase):
  """Test case for ListVisibleFiles"""

  def setUp(self):
    self.path = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.path)

  def _test(self, files, expected):
    # Sort a copy
    expected = expected[:]
    expected.sort()

    for name in files:
      f = open(os.path.join(self.path, name), 'w')
      try:
        f.write("Test\n")
      finally:
        f.close()

    found = utils.ListVisibleFiles(self.path)
    found.sort()

    self.assertEqual(found, expected)

  def testAllVisible(self):
    files = ["a", "b", "c"]
    expected = files
    self._test(files, expected)

  def testNoneVisible(self):
    files = [".a", ".b", ".c"]
    expected = []
    self._test(files, expected)

  def testSomeVisible(self):
    files = ["a", "b", ".c"]
    expected = ["a", "b"]
    self._test(files, expected)


class TestFormatTable(unittest.TestCase):
  """Tests for FormatTable"""

  def testSimple(self):
    columns = [
      ("col1", 5, lambda i: str(i)),
      ("col2", 8, lambda i: "%04x" % (2 ** i)),
      ]
    self.failUnlessEqual(utils.FormatTable([1, 2, 3, 4], columns),
                         ['col1  col2',
                          '----- --------',
                          '1     0002',
                          '2     0004',
                          '3     0008',
                          '4     0010',
                         ])

    columns = [
      ("rcol1", -5, lambda i: str(i)),
      ("col2", 8, lambda i: "%04x" % (2 ** i)),
      ]
    self.failUnlessEqual(utils.FormatTable([1, 2, 3, 4], columns),
                         ['rcol1 col2',
                          '----- --------',
                          '    1 0002',
                          '    2 0004',
                          '    3 0008',
                          '    4 0010',
                         ])

    columns = [
      ("rcol1", -5, lambda i: str(i)),
      ("rcol2", -8, lambda i: "%04x" % (2 ** i)),
      ]
    self.failUnlessEqual(utils.FormatTable([1, 2, 3, 4], columns),
                         ['rcol1    rcol2',
                          '----- --------',
                          '    1     0002',
                          '    2     0004',
                          '    3     0008',
                          '    4     0010',
                         ])

    # No data
    columns = [
      ("col1", 5, lambda _: "x"),
      ("col2", 8, lambda _: "y"),
      ]
    self.failUnlessEqual(utils.FormatTable([], columns),
                         ["col1  col2",
                          "----- --------",
                         ])

    # No columns
    self.failUnlessEqual(utils.FormatTable([1, 2, 3, 4], []),
                         ["", "", "", "", "", ""])

    # No data and no columns
    self.failUnlessEqual(utils.FormatTable([], []), ["", ""])


class _RetryTestHelper(object):
  def __init__(self, want):
    self.want = want
    self.calls = 0

  def Call(self):
    self.calls += 1
    if self.calls < self.want:
      raise utils.RetryAgain()
    return self.calls


class TestRetry(unittest.TestCase):
  """Tests for Retry"""

  def _DoSimpleTest(self, seconds, start, factor, limit, timeout):
    faketime = mocks.FakeTime(seconds=seconds)
    result = utils.Retry(lambda: "result", start, factor, limit, timeout,
                         _time=faketime)
    self.failUnlessEqual(result, "result")
    self.failUnless(faketime.seconds >= seconds)
    self.failUnless(faketime.seconds < (seconds + timeout))

  def test(self):
    for seconds in [0, 100, 43469, 1236350703]:
      self._DoSimpleTest(seconds, 1, 1.1, 2, 5)
      self._DoSimpleTest(seconds, 0.1, 1.05, 2, 5)
      self._DoSimpleTest(seconds, 0.1, 1.05, 2, 5)
      self._DoSimpleTest(seconds, 0.2, 2, 10, 30)

      data = [
        (8, 1, 1.5, 10, 20),
        (5, 10, 2, 40, 60),
        (12, 0.1, 2, 1, 10),
        (38, 0.1, 1.2, 30, 300),
        ]
      for (calls, start, factor, limit, timeout) in data:
        faketime = mocks.FakeTime(seconds=seconds)
        obj = _RetryTestHelper(calls)

        self.failUnlessRaises(utils.RetryTimeout, utils.Retry,
                              obj.Call, start, factor, limit, timeout,
                              _time=faketime)

        self.failUnlessEqual(obj.calls, calls - 1)


class TestShellQuoting(unittest.TestCase):
  """Test case for shell quoting functions"""

  def testShellQuote(self):
    self.assertEqual(utils.ShellQuote("abc"), "abc")
    self.assertEqual(utils.ShellQuote("ab\"c"), "'ab\"c'")
    self.assertEqual(utils.ShellQuote("a'bc"), "'a'\\''bc'")
    self.assertEqual(utils.ShellQuote("a b c"), "'a b c'")
    self.assertEqual(utils.ShellQuote("a b\\ c"), "'a b\\ c'")
    self.assertEqual(utils.ShellQuote("$foo bar"), "'$foo bar'")

  def testShellQuoteArgs(self):
    self.assertEqual(utils.ShellQuoteArgs(["a", "b", "c"]), "a b c")
    self.assertEqual(utils.ShellQuoteArgs(["a", "b\"", "c"]), "a 'b\"' c")
    self.assertEqual(utils.ShellQuoteArgs(["a", "b'", "c"]), "a 'b'\\\''' c")


class _FakeSignalModule:
  def __init__(self):
    (self.SIGFOO,
     self.SIGBAR,
     self.SIGMOO) = range(1, 4)
    self.SIGLONGER = 22

    # These shouldn't be included in the table
    self.SIG_IGN = 1
    self.SIG_DFL = 2
    self.OTHER_CONSTANT = 123


class TestGetSignalName(unittest.TestCase):
  """Test case for signal name functions"""

  def testGetSignalNumberTable(self):
    table = utils._GetSignalNumberTable(_signal=_FakeSignalModule())
    self.failUnlessEqual(len(table.keys()), 4)
    self.failUnlessEqual(table[1], "SIGFOO")
    self.failUnlessEqual(table[2], "SIGBAR")
    self.failUnlessEqual(table[3], "SIGMOO")
    self.failUnlessEqual(table[22], "SIGLONGER")

  def testGetSignalName(self):
    fake_signal = _FakeSignalModule()
    self.assertEqual("SIGFOO", utils.GetSignalName(1, _signal=fake_signal))
    self.assertEqual("SIGBAR", utils.GetSignalName(2, _signal=fake_signal))
    self.assertEqual("SIGMOO", utils.GetSignalName(3, _signal=fake_signal))
    self.assertEqual("SIGLONGER", utils.GetSignalName(22, _signal=fake_signal))

    self.assertEqual("Signal 999",
                     utils.GetSignalName(999, _signal=fake_signal))


if __name__ == '__main__':
  unittest.main()
