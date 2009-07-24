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


"""Module with helper classes and functions for daemons.

"""


import gobject
import logging
import os


class SignalRegistration:
  def __init__(self, emitter, handle):
    self.__emitter = emitter
    self.__handle = handle

  def __del__(self):
    if self.__emitter is not None:
      self.Disconnect()

  def Disconnect(self):
    assert self.__emitter is not None
    assert self.__handle is not None

    self.__emitter.disconnect(self.__handle)

    self.__emitter = None
    self.__handle = None


class IOChannel(gobject.GObject, object):
  """Wrapper for gobject.IOChannel.

  Emits signals on I/O events.

  """
  AFTER_READ_SIGNAL = "after-read"
  WRITE_COMPLETE_SIGNAL = "after-write"
  CLOSED_SIGNAL = "closed"

  __BLOCKSIZE = 1024

  __gsignals__ = {
    AFTER_READ_SIGNAL:
      (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
       (gobject.TYPE_PYOBJECT, )),
    WRITE_COMPLETE_SIGNAL:
      (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
       ()),
    CLOSED_SIGNAL:
      (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
       ()),
    }

  def __init__(self):
    """Initializes this class.

    """
    object.__init__(self)
    gobject.GObject.__init__(self)

    self.__channel = None
    self.__handle = None
    self.__writebuf = ""
    self.__writepos = 0

  def __GetClosed(self):
    """Returns whether this channel has been closed.

    """
    return self.__channel is None

  closed = property(fget=__GetClosed)

  @staticmethod
  def __CreateChannel(fd):
    """Creates the inner gobject.IOChannel instance.

    Note: has side-effects on file descriptor by setting O_NONBLOCK.

    @type fd: int
    @param fd: File descriptor

    """
    channel = gobject.IOChannel(fd)
    channel.set_encoding(None)
    channel.set_buffered(0)
    channel.set_flags(gobject.IO_FLAG_NONBLOCK)
    return channel

  def Attach(self, fd):
    """Attaches this channel to a file descriptor.

    @type fd: int
    @param fd: File descriptor

    """
    assert self.__channel is None
    self.__channel = self.__CreateChannel(fd)
    self.__Update(False)

  def Detach(self):
    """Closes this channel.

    """
    self.__Update(True)

  def Write(self, data):
    """Asynchronous write.

    @type data: str
    @param data: Data to be written

    """
    self.__writebuf = self.__writebuf[self.__writepos:] + data
    self.__writepos = 0
    self.__Update(False)

  def __Update(self, detach):
    """Updates this channel's registration with the mainloop.

    @type detach: bool
    @param detach: Whether we're detaching from the file descriptor

    """
    handle = self.__handle

    # TODO: Don't remove and re-add if conditions didn't change
    if handle is not None:
      gobject.source_remove(handle)
      handle = None

    if self.__channel and not detach:
      condition = self.__CalcCondition()
      if condition:
        handle = self.__channel.add_watch(condition, self.__HandleIO)

    self.__handle = handle

  def __CalcCondition(self):
    """Returns necessary flags for mainloop.

    """
    cond = gobject.IO_IN | gobject.IO_HUP | gobject.IO_ERR | gobject.IO_NVAL

    if self.__writebuf and self.__writepos < len(self.__writebuf):
      cond |= gobject.IO_OUT

    return cond

  def __Read(self, channel):
    """Reads data from channel and emits events.

    """
    assert channel == self.__channel

    data = self.__channel.read(self.__BLOCKSIZE)
    if data:
      self.__EmitAfterRead(data)
      return True

    # TODO: Correct when still writing?
    self.__Close()
    return False

  def __Write(self, channel):
    """Writes data from the buffer to the channel.

    """
    assert channel == self.__channel

    endpos = self.__writepos + self.__BLOCKSIZE

    # Use slicing to avoid unnecessary memory reallocations
    data = self.__writebuf[self.__writepos:endpos]

    n = channel.write(data)
    if n == 0:
      self.__Close()
      return False

    self.__writepos += n

    assert self.__writepos <= len(self.__writebuf)

    if self.__writepos == len(self.__writebuf):
      self.__Update(False)
      self.__EmitWriteComplete()

      # TODO: Cleaner solution
      if self.__writepos == len(self.__writebuf):
        self.__Close()
        return False

    return True

  def __HandleIO(self, channel, cond):
    """Triages I/O events.

    """
    assert channel == self.__channel

    if cond & (gobject.IO_IN | gobject.IO_OUT):
      return (((cond & gobject.IO_IN) and self.__Read(channel) or
              ((cond & gobject.IO_OUT) and self.__Write(channel))))

    if cond & (gobject.IO_HUP | gobject.IO_ERR | gobject.IO_NVAL):
      self.__Close()

    return False

  def __Close(self):
    """Closes the channel.

    """
    self.__channel.close(flush=True)
    self.__channel = None
    self.__Update(True)
    self.__EmitClosed()

  def __EmitAfterRead(self, data):
    self.emit(self.AFTER_READ_SIGNAL, data)

  def __EmitWriteComplete(self):
    self.emit(self.WRITE_COMPLETE_SIGNAL)

  def __EmitClosed(self):
    assert self.closed

    self.emit(self.CLOSED_SIGNAL)


class ChopReader(gobject.GObject):
  """Reads slices separated by separator from L{IOChannel}.

  For each slice, a signal is emitted.

  """
  SLICE_COMPLETE_SIGNAL = "slice-complete"

  __gsignals__ = {
    SLICE_COMPLETE_SIGNAL:
      (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
       (gobject.TYPE_PYOBJECT, )),
    }

  def __init__(self, sep):
    """Initializes this class.

    """
    gobject.GObject.__init__(self)
    self.__sep = sep

    self.__channel = None
    self.__after_read_reg = None
    self.__closed_reg = None
    self.__buf = ""

  def Attach(self, channel):
    """Attach to I/O channel.

    @type channel: L{IOChannel}
    @param channel: I/O channel

    """
    assert self.__channel is None
    assert self.__after_read_reg is None
    assert self.__closed_reg is None

    self.__channel = channel

    self.__after_read_reg = \
      SignalRegistration(channel,
                         channel.connect(IOChannel.AFTER_READ_SIGNAL,
                                         self.__ReceivedData))
    self.__closed_reg = \
      SignalRegistration(channel,
                         channel.connect(IOChannel.CLOSED_SIGNAL,
                                         self.__Closed))

  def Detach(self):
    """Detaches from I/O channel.

    """
    self.__channel = None

    if self.__after_read_reg:
      self.__after_read_reg.Disconnect()
      self.__after_read_reg = None

    if self.__closed_reg:
      self.__closed_reg.Disconnect()
      self.__closed_reg = None

  def __del__(self):
    self.Detach()

  def __ParseBuffer(self):
    """Parses internal buffer until no more separators are found.

    """
    pos = 0
    try:
      while True:
        idx = self.__buf.find(self.__sep, pos)
        if idx < 0:
          break

        slice_ = self.__buf[pos:idx]
        pos = idx + len(self.__sep)

        self.__EmitSliceComplete(slice_)
    finally:
      self.__buf = self.__buf[pos:]

  def __ReceivedData(self, channel, data):
    """Adds received data to buffer.

    """
    assert channel == self.__channel

    if data:
      self.__buf += data

    self.__ParseBuffer()

  def __Closed(self, channel):
    """Handles leftovers in buffer.

    """
    assert channel == self.__channel

    self.__ParseBuffer()

    # Handle rest
    if self.__buf:
      if self.__buf.endswith(self.__sep):
        self.__buf = self.__buf[:-len(self.__sep)]
      self.__EmitSliceComplete(self.__buf)
      self.__buf = ""

  def __EmitSliceComplete(self, slice_):
    self.emit(self.SLICE_COMPLETE_SIGNAL, slice_)


class Program(gobject.GObject, object):
  """Wrapper for gobject.spawn_async.

  Emits signals on events.

  """
  EXITED_SIGNAL = "exited"

  __gsignals__ = {
    EXITED_SIGNAL:
      (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE,
       (gobject.TYPE_PYOBJECT, gobject.TYPE_PYOBJECT)),
    }

  def __init__(self, args, env=None, cwd=None, executable=None,
               umask=None, stdin_data=None):
    """Initializes this class.

    @type args: list
    @param args: Program arguments
    @type env: dict
    @param env: Environment variables for program
    @type cwd: str
    @param cwd: Working directory for program
    @type executable: str
    @param executable: If set, the executable to run
    @type stdin_data: str
    @param stdin_data: Data to be written to program's stdin

    """
    object.__init__(self)
    gobject.GObject.__init__(self)

    self.__args = args
    self.__env = env
    self.__cwd = cwd
    self.__executable = executable
    self.__umask = umask
    self.__stdin_data = stdin_data

    self.__progname = args[0]

    self.__pid = None
    self.__exitcode = None
    self.__child_watch_handle = None

    self.stdin = IOChannel()
    self.__stdin_closed_reg = \
      SignalRegistration(self.stdin,
                         self.stdin.connect(IOChannel.CLOSED_SIGNAL,
                                            self.__HandlePipeClosed))

    self.stdout = IOChannel()
    self.__stdout_closed_reg = \
      SignalRegistration(self.stdout,
                         self.stdout.connect(IOChannel.CLOSED_SIGNAL,
                                             self.__HandlePipeClosed))

    self.stderr = IOChannel()
    self.__stderr_closed_reg = \
      SignalRegistration(self.stderr,
                         self.stderr.connect(IOChannel.CLOSED_SIGNAL,
                                             self.__HandlePipeClosed))

    self.stdout_line = ChopReader(os.linesep)
    self.__stdout_line_complete_reg = \
      SignalRegistration(self.stdout_line,
                         self.stdout_line.connect(ChopReader.SLICE_COMPLETE_SIGNAL,
                                                  self.__LogOutput, "stdout"))
    self.stdout_line.Attach(self.stdout)

    self.stderr_line = ChopReader(os.linesep)
    self.__stderr_line_complete_reg = \
      SignalRegistration(self.stderr_line,
                         self.stderr_line.connect(ChopReader.SLICE_COMPLETE_SIGNAL,
                                                  self.__LogOutput, "stderr"))
    self.stderr_line.Attach(self.stderr)

    if stdin_data:
      self.stdin.Write(stdin_data)

  def __GetPid(self):
    """Returns the PID of the started program.

    """
    return self.__pid

  pid = property(fget=__GetPid)

  def __LogOutput(self, _, line, pipename):
    logging.debug("%s %s: %s", self.__progname, pipename, line)

  @staticmethod
  def __FormatEnvironment(env):
    """Formats environment as requested by gobject.spawn_async.

    """
    # gobject.spawn_async needs this list to be a plain string, not unicode
    return [str("%s=%s" % (key, value)) for (key, value) in env.iteritems()]

  @staticmethod
  def __FormatArgs(args):
    """Formats arguments as requested by gobject.spawn_async.

    """
    # gobject.spawn_async needs this list to be a plain string, not unicode
    return map(str, args)

  def __ChildSetup(self):
    """Called in child process just before the actual program is executed.

    """
    if self.__umask is not None:
      os.umask(self.__umask)

  def Start(self):
    """Start program.

    """
    logging.info("Starting program, executable=%r, args=%r",
                 self.__executable, self.__args)

    # TODO: Make gobject.SPAWN_SEARCH_PATH controllable by caller?
    flags = gobject.SPAWN_DO_NOT_REAP_CHILD | gobject.SPAWN_SEARCH_PATH

    if self.__executable:
      args = self.__FormatArgs([self.__executable] + self.__args)
      flags |= gobject.SPAWN_FILE_AND_ARGV_ZERO
    else:
      args = self.__FormatArgs(self.__args)

    # gobject.spawn_async doesn't take None for default values, hence we can
    # only fill these parameters if they need to be set.
    kwargs = {}

    if self.__env is not None:
      kwargs["envp"] = self.__FormatEnvironment(self.__env)

    if self.__cwd is not None:
      kwargs["working_directory"] = self.__cwd

    (pid, stdin_fd, stdout_fd, stderr_fd) = \
      gobject.spawn_async(args, flags=flags, child_setup=self.__ChildSetup,
                          standard_input=True,
                          standard_output=True,
                          standard_error=True,
                          **kwargs)

    logging.info("Child pid %r", pid)
    self.__pid = pid

    self.stdin.Attach(stdin_fd)
    self.stdout.Attach(stdout_fd)
    self.stderr.Attach(stderr_fd)

    self.__child_watch_handle = \
      gobject.child_watch_add(self.__pid, self.__HandleExit)

    return self.pid

  def __HandleExit(self, pid, exitcode):
    """Called when program exits.

    @type pid: int
    @param pid: Process ID
    @type exitcode: int
    @param exitcode: Exit status as returned by waitpid(2)

    """
    assert pid == self.__pid
    assert self.__exitcode is None

    self.__exitcode = exitcode
    self.__CheckExit()

    # TODO: Should child watch handle be removed from mainloop?

  def __HandlePipeClosed(self, _):
    """Called when I/O pipe to process is closed.

    """
    self.__CheckExit()

  def __CheckExit(self):
    """Checks whether program has exitted and all I/O has been handled.

    """
    if (self.stdin.closed and
        self.stdout.closed and
        self.stderr.closed and
        self.__exitcode is not None):
      # TODO: Keep part of stderr output in case of errors (deque)
      exitstatus = None
      signum = None

      if os.WIFSIGNALED(self.__exitcode):
        signum = os.WTERMSIG(self.__exitcode)

      elif os.WIFEXITED(self.__exitcode):
        exitstatus = os.WEXITSTATUS(self.__exitcode)

      else:
        raise RuntimeError("Invalid child status")

      if exitstatus == 0 and signum is None:
        logging.debug("%s exited cleanly", self.__progname)
      else:
        logging.error("%s failed (status=%s, signal=%s)",
                      self.__progname, exitstatus, signum)

      self.__EmitExited(exitstatus, signum)

  def __EmitExited(self, exitcode, signum):
    self.emit(self.EXITED_SIGNAL, exitcode, signum)
