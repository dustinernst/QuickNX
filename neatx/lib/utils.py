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


"""Module for utility functions"""


import errno
import fcntl
import logging
import logging.handlers
import os
import os.path
import pwd
import resource
import re
import signal
import sys
import syslog
import tempfile
import termios
import time

from neatx import constants
from neatx import errors


_SHELL_UNQUOTED_RE = re.compile('^[-.,=:/_+@A-Za-z0-9]+$')

try:
  DEV_NULL = os.devnull
except AttributeError:
  DEV_NULL = "/dev/null"


class CustomSyslogHandler(logging.Handler):
  """Custom syslog handler.

  logging.handlers.SysLogHandler doesn't support splitting exceptions into
  several lines.

  This class should only be used once per process.

  """
  _LEVEL_MAP = {
    logging.CRITICAL: syslog.LOG_CRIT,
    logging.ERROR: syslog.LOG_ERR,
    logging.WARNING: syslog.LOG_WARNING,
    logging.INFO: syslog.LOG_INFO,
    logging.DEBUG: syslog.LOG_DEBUG,
    }

  def __init__(self, ident):
    """Initializes instances.

    @type ident: string
    @param ident: String prepended to every message

    """
    logging.Handler.__init__(self)

    syslog.openlog(ident, syslog.LOG_PID, syslog.LOG_USER)

  def close(self):
    syslog.closelog()

  def _MapLogLevel(self, levelno):
    """Maps log level to syslog.

    @type levelno: int
    @param levelno: Log level

    Default is LOG_DEBUG.

    """
    return self._LEVEL_MAP.get(levelno, syslog.LOG_DEBUG)

  def emit(self, record):
    """Send a log record to syslog.

    @type record: logging.LogRecord
    @param record: Log record

    """
    msg = self.format(record)

    if record.exc_info:
      messages = msg.split(os.linesep)
    else:
      messages = [msg]

    priority = self._MapLogLevel(record.levelno)

    for msg in messages:
      syslog.syslog(priority, msg)


class LoggingSetupOptions(object):
  def __init__(self, debug, logtostderr):
    """Initializes logging setup options class.

    @type debug: bool
    @param debug: Whether to enable debug log messages
    @type logtostderr: bool
    @param logtostderr: Whether to write log messages to stderr

    """
    self.debug = debug
    self.logtostderr = logtostderr


class LoggingSetup(object):
  """Logging setup class.

  This class should only be used once per process.

  """
  def __init__(self, program):
    """Configures the logging module

    @type program: str
    @param program: the name under which we should log messages

    """
    self._program = program
    self._options = None
    self._root_logger = None
    self._stderr_handler = None
    self._syslog_handler = None

  def Init(self):
    """Initializes the logging module.

    """
    assert not self._root_logger
    assert not self._stderr_handler
    assert not self._syslog_handler

    # Get root logger
    self._root_logger = self._InitRootLogger()

    # Create stderr handler
    self._stderr_handler = logging.StreamHandler(sys.stderr)

    # Create syslog handler
    self._syslog_handler = CustomSyslogHandler(self._program)

    self._ConfigureHandlers()

  def SetOptions(self, options):
    """Configure logging setup.

    @type options: L{LoggingSetupOptions}
    @param options: Configuration object

    """
    self._options = options
    self._ConfigureHandlers()

  @staticmethod
  def _InitRootLogger():
    """Initializes and returns the root logger.

    """
    root_logger = logging.getLogger("")
    root_logger.setLevel(logging.NOTSET)

    # Remove all previously setup handlers
    for handler in root_logger.handlers:
      root_logger.removeHandler(handler)
      handler.close()

    return root_logger

  def _ConfigureHandlers(self):
    """Set formatters and levels for handlers.

    """
    stderr_level = None
    syslog_level = None

    if self._options is None:
      # Log error and above
      stderr_level = logging.ERROR
    else:
      if self._options.debug:
        # Log everything
        level = logging.NOTSET
      else:
        # Log info and above (e.g. error)
        level = logging.INFO

      if self._options.logtostderr:
        stderr_level = level
      else:
        syslog_level = level

    # Configure handlers
    self._ConfigureSingleHandler(self._stderr_handler, stderr_level, False)
    self._ConfigureSingleHandler(self._syslog_handler, syslog_level, True)

  def _ConfigureSingleHandler(self, handler, level, is_syslog):
    """Configures a handler based on the parameters.

    """
    if level is None:
      self._root_logger.removeHandler(handler)
      return

    debug = self._options is not None and self._options.debug

    fmt = self._GetMessageFormat(self._program, is_syslog, debug)

    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt))

    self._root_logger.addHandler(handler)

  @staticmethod
  def _GetMessageFormat(program, is_syslog, debug):
    """Returns message format.

    """
    assert "%" not in program

    if is_syslog:
      fmt = ""
    else:
      fmt = "%(asctime)s: " + program + " pid=%(process)d "

    fmt += "%(levelname)s"

    if debug:
      fmt += " %(module)s:%(lineno)s"

    fmt += " %(message)s"

    return fmt


def WithoutTerminalEcho(fd, fn, *args, **kwargs):
  """Calls function with ECHO flag disabled on passed file descriptor.

  @type fd: file or int
  @param fd: File descriptor
  @type fn: callable
  @param fn: Called function

  """
  assert callable(fn)

  # Keep old terminal settings
  try:
    old = termios.tcgetattr(fd)
  except termios.error, err:
    if err.args[0] not in (errno.ENOTTY, errno.EINVAL):
      raise
    old = None

  if old is not None:
    new = old[:]

    # Disable the echo flag in lflags (index 3)
    new[3] &= ~termios.ECHO

    termios.tcsetattr(fd, termios.TCSADRAIN, new)

  try:
    return fn(*args, **kwargs)
  finally:
    if old is not None:
      termios.tcsetattr(fd, termios.TCSADRAIN, old)


def NormalizeSpace(text):
  """Replace all whitespace (\\s) with a single space.

  Whitespace at start and end are also removed.

  """
  return re.sub(r"\s+", " ", text).strip()


def RemoveFile(filename):
  """Remove a file ignoring some errors.

  Remove a file, ignoring non-existing ones or directories. Other
  errors are passed.

  @type filename: str
  @param filename: the file to be removed

  """
  try:
    os.unlink(filename)
  except OSError, err:
    if err.errno not in (errno.ENOENT, errno.EISDIR):
      raise


def SetCloseOnExecFlag(fd, enable):
  """Sets or unsets the close-on-exec flag on a file descriptor.

  @type fd: int
  @param fd: File descriptor
  @type enable: bool
  @param enable: Whether to set or unset it.

  """
  flags = fcntl.fcntl(fd, fcntl.F_GETFD)

  if enable:
    flags |= fcntl.FD_CLOEXEC
  else:
    flags &= ~fcntl.FD_CLOEXEC

  fcntl.fcntl(fd, fcntl.F_SETFD, flags)


def SetNonblockFlag(fd, enable):
  """Sets or unsets the O_NONBLOCK flag on on a file descriptor.

  @type fd: int
  @param fd: File descriptor
  @type enable: bool
  @param enable: Whether to set or unset it

  """
  flags = fcntl.fcntl(fd, fcntl.F_GETFL)

  if enable:
    flags |= os.O_NONBLOCK
  else:
    flags &= ~os.O_NONBLOCK

  fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def ListVisibleFiles(path):
  """Returns a list of visible files in a directory.

  @type path: str
  @param path: the directory to enumerate
  @rtype: list
  @return: the list of all files not starting with a dot

  """
  files = [i for i in os.listdir(path) if not i.startswith(".")]
  files.sort()
  return files


def WriteFile(file_name, fn=None, data=None,
              mode=None, uid=-1, gid=-1):
  """(Over)write a file atomically.

  The file_name and either fn (a function taking one argument, the
  file descriptor, and which should write the data to it) or data (the
  contents of the file) must be passed. The other arguments are
  optional and allow setting the file mode, owner and group of the file.

  If the function (WriteFile) doesn't raise an exception, it has succeeded and
  the target file has the new contents. If the function has raised an
  exception, an existing target file should be unmodified and the temporary
  file should be removed.

  @type file_name: str
  @param file_name: the target filename
  @type fn: callable
  @param fn: content writing function, called with
      file descriptor as parameter
  @type data: str
  @param data: contents of the file
  @type mode: int
  @param mode: file mode
  @type uid: int
  @param uid: the owner of the file
  @type gid: int
  @param gid: the group of the file

  @raise errors.ProgrammerError: if any of the arguments are not valid

  """
  if not os.path.isabs(file_name):
    raise errors.ProgrammerError("Path passed to WriteFile is not"
                                 " absolute: '%s'" % file_name)

  if [fn, data].count(None) != 1:
    raise errors.ProgrammerError("fn or data required")

  dir_name, base_name = os.path.split(file_name)
  fd, new_name = tempfile.mkstemp(prefix=".tmp", suffix=base_name,
                                  dir=dir_name)
  try:
    if uid != -1 or gid != -1:
      os.chown(new_name, uid, gid)
    if mode:
      os.chmod(new_name, mode)
    if data is not None:
      os.write(fd, data)
    else:
      fn(fd)
    os.fsync(fd)
    os.rename(new_name, file_name)
  finally:
    os.close(fd)
    # Make sure temporary file is removed in any case
    RemoveFile(new_name)


def FormatTable(data, columns):
  """Formats a list of input data as a table.

  Columns must be passed via the C{columns} parameter. It must be a list of
  tuples, each containing the column caption, width and a function to retrieve
  the value. If the width is negative, the value is aligned to the right. The
  column function is called for every item.

  Example:
    >>> columns = [
      ("Name", 10, lambda item: item[0]),
      ("Value", -5, lambda item: item[1]),
      ]
    >>> data = [("Row%d" % i, i) for i in xrange(3)]
    >>> print "\\n".join(utils.FormatTable(data, columns))
    Name       Value
    ---------- -----
    Row0           0
    Row1           1
    Row2           2

  @type data: list
  @param data: Input data
  @type columns: list of tuples
  @param columns: Column definitions
  @rtype: list of strings
  @return: Rows as strings

  """
  col_width = []
  header_row = []
  dashes_row = []
  format_fields = []

  for idx, (header, width, _) in enumerate(columns):
    if idx == (len(columns) - 1) and width >= 0:
      # Last column
      col_width.append(None)
      fmt = "%s"
    else:
      col_width.append(abs(width))
      if width < 0:
        fmt = "%*s"
      else:
        fmt = "%-*s"

    format_fields.append(fmt)

    if col_width[idx] is not None:
      header_row.append(col_width[idx])
      dashes_row.append(col_width[idx])

    header_row.append(header)
    dashes_row.append(abs(width) * "-")

  format = " ".join(format_fields)

  rows = [header_row, dashes_row]
  for item in data:
    row = []
    for idx, (_, width, fn) in enumerate(columns):
      if col_width[idx] is not None:
        row.append(col_width[idx])
      row.append(fn(item))
    rows.append(row)

  return [format % tuple(row) for row in rows]


class RetryTimeout(Exception):
  """Retry loop timed out.

  """


class RetryAgain(Exception):
  """Retry again.

  """


def Retry(fn, start, factor, limit, timeout, _time=time):
  """Call a function repeatedly until it succeeds.

  The function C{fn} is called repeatedly until it doesn't throw L{RetryAgain}
  anymore. Between calls a delay starting at C{start} and multiplied by
  C{factor} on each run until it's above C{limit} is inserted. After a total of
  C{timeout} seconds, the retry loop fails with L{RetryTimeout}.

  @type fn: callable
  @param fn: Function to be called (no parameters supported)
  @type start: float
  @param start: Initial value for delay
  @type factor: float
  @param factor: Factor for delay increase
  @type limit: float
  @param limit: Upper limit for delay
  @type timeout: float
  @param timeout: Total timeout
  @return: Return value of function

  """
  assert start > 0
  assert factor > 1.0
  assert limit >= 0

  end_time = _time.time() + timeout
  delay = start

  while True:
    try:
      return fn()
    except RetryAgain:
      pass

    if _time.time() > end_time:
      raise RetryTimeout()

    _time.sleep(delay)

    if delay < limit:
      delay *= factor


def ShellQuote(value):
  """Quotes shell argument according to POSIX.

  @type value: str
  @param value: the argument to be quoted
  @rtype: str
  @return: the quoted value

  """
  if _SHELL_UNQUOTED_RE.match(value):
    return value
  else:
    return "'%s'" % value.replace("'", "'\\''")


def ShellQuoteArgs(args):
  """Quotes a list of shell arguments.

  @type args: list
  @param args: list of arguments to be quoted
  @rtype: str
  @return: the quoted arguments concatenaned with spaces

  """
  return " ".join([ShellQuote(i) for i in args])


def CloseFd(fd, retries=5):
  """Close a file descriptor ignoring errors.

  @type fd: int
  @param fd: File descriptor
  @type retries: int
  @param retries: How many retries to make, in case we get any
    other error than EBADF

  """
  while retries > 0:
    retries -= 1
    try:
      os.close(fd)
    except OSError, err:
      if err.errno != errno.EBADF:
        continue
    break


def GetMaxFd():
  """Determine max file descriptor number.

  @rtype: int
  @return: Max file descriptor number

  """
  maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
  if maxfd == resource.RLIM_INFINITY:
    # Default maximum for the number of available file descriptors.
    maxfd = 1024

    try:
      maxfd = os.sysconf("SC_OPEN_MAX")
    except ValueError:
      pass

  if maxfd < 0:
    maxfd = 1024

  return maxfd


def StartDaemon(fn):
  """Start a daemon process.

  Starts a daemon process by double-forking and invoking a function. The
  function should then use exec*(2) to start the process.

  """
  # First fork
  pid = os.fork()
  if pid != 0:
    # Parent process

    # Try to avoid zombies
    try:
      os.waitpid(pid, 0)
    except OSError:
      pass

    return

  # First child process
  os.setsid()

  # Second fork
  pid = os.fork()
  if pid != 0:
    # Second parent process
    os._exit(0)

  # Second child process
  os.chdir("/")
  os.umask(077)

  # Close all file descriptors
  for fd in xrange(GetMaxFd()):
    CloseFd(fd)

  # Open /dev/null
  fd = os.open(DEV_NULL, os.O_RDWR)

  # Redirect stdio to /dev/null
  os.dup2(fd, constants.STDIN_FILENO)
  os.dup2(fd, constants.STDOUT_FILENO)
  os.dup2(fd, constants.STDERR_FILENO)

  try:
    # Call function starting daemon
    fn()
    os._exit(0)
  except (SystemExit, KeyboardInterrupt):
    raise
  except:
    os._exit(1)


def CallWithSignalHandlers(sigtbl, fn, *args, **kwargs):
  previous = {}
  try:
    for (signum, handler) in sigtbl.iteritems():
      # Setup handler
      prev_handler = signal.signal(signum, handler)
      try:
        previous[signum] = prev_handler
      except Exception:
        # Restore previous handler
        signal.signal(signum, prev_handler)
        raise

    return fn(*args, **kwargs)

  finally:
    for (signum, prev_handler) in previous.items():
      signal.signal(signum, prev_handler)

      # If successful, remove from dict
      del previous[signum]

    assert not previous


def _GetSignalNumberTable(_signal=signal):
  table = {}

  for name in dir(_signal):
    if name.startswith("SIG") and not name.startswith("SIG_"):
      signum = getattr(_signal, name)
      if isinstance(signum, (int, long)):
        table[signum] = name

  return table


def GetSignalName(signum, _signal=signal):
  """Returns signal name by signal number.

  If the signal number is not known, "Signal 123" is returned (with the passed
  signal number instead of 123).

  @type signum: int
  @param signum: Signal number
  @rtype: str
  @return: Signal name

  """
  # This table could be cached
  table = _GetSignalNumberTable(_signal=_signal)

  try:
    return table[signum]
  except KeyError:
    return "Signal %s" % signum


def _ConvertVersionPart(value):
  """Tries to convert a value to an integer.

  """
  try:
    return int(value)
  except ValueError:
    return value


def _GetVersionSplitter(sep, count):
  """Returns callable to split wanted parts from version.

  @type sep: string
  @param sep: String of separator characters
  @type count: int
  @param count: How many parts to return

  """
  assert sep
  assert count == -1 or count > 0

  # str.split is a lot faster but doesn't provide the right semantics when
  # the caller wants more than one possible separator.
  #if len(sep) == 1:
  #  if count == -1:
  #    return lambda ver: ver.split(sep)
  #  else:
  #    return lambda ver: ver.split(sep, count)[:count]

  re_split = re.compile("[%s]" % re.escape(sep)).split
  if count == -1:
    return lambda ver: re_split(ver)
  else:
    return lambda ver: re_split(ver, count)[:count]


def GetVersionComparator(sep, count=-1):
  """Returns a cmp-compatible function to compare two version strings.

  @type sep: string
  @param sep: String of separator characters, similar to strsep(3)
  @type count: int
  @param count: How many parts to compare (-1 for all)

  """
  # TODO: Support for versions such as "1.2~alpha0"

  split_fn = _GetVersionSplitter(sep, count)
  split_version = lambda ver: map(_ConvertVersionPart, split_fn(ver))

  return lambda x, y: cmp(split_version(x), split_version(y))


def ParseVersion(version, sep, digits):
  """Parses a version and converts it to a number.

  Example:
    >>> ParseVersion("3.3.7.2-1", ".-", [2, 2, 2])
    30307
    >>> ParseVersion("3.3.5.2-1", ".-", [2, 2, 4])
    3030005
    >>> ParseVersion("3.3.9.2-1", ".-", [2, 2, 2, 2, 2])
    303090201
    >>> ParseVersion("12.1", ".-", [2, 2, 2, 2])
    12010000
    >>> ParseVersion("23.193", ".-", [2, 4])
    230193

  @type version: str
  @param version: Version string
  @type sep: string
  @param sep: String of separator characters, similar to strsep(3)
  @type digits: list
  @param digits: List of digits to be used per part

  """
  split_fn = _GetVersionSplitter(sep, len(digits))
  parts = split_fn(version)

  version = 0
  total_exp = 0

  for idx, exp in reversed(list(enumerate(digits))):
    try:
      value = int(parts[idx])
    except IndexError:
      value = 0

    if value > 10 ** exp:
      raise ValueError("Version part %s (%r) too long for %s digits" %
                       (idx, value, exp))

    version += (10 ** total_exp) * value

    total_exp += exp

  return version


def FormatVersion(version, sep, digits):
  """Format version number.

  @type version: int
  @param version: Version number (as returned by L{ParseVersion})
  @type sep: string
  @param sep: Separator string between digits
  @type digits: list
  @param digits: List of digits used per part in the version numbers

  """
  # TODO: Implement support for more than one separator
  parts = []
  next = version

  for exp in reversed(digits):
    (next, value) = divmod(next, 10 ** exp)

    parts.append(str(value))

  if next > 0:
    raise ValueError("Invalid version number (%r) for given digits (%r)" %
                     (version, digits))

  parts.reverse()

  return sep.join(parts)


def LogFunctionWithPrefix(fn, prefix):
  return lambda msg, *args, **kwargs: fn(prefix + msg, *args, **kwargs)


def GetExitcodeSignal(status):
  if status < 0:
    return (None, -status)
  else:
    return (status, None)


def GetCurrentUserName():
  """Returns the name of the user that owns the current process.

  """
  return pwd.getpwuid(os.getuid())[0]
