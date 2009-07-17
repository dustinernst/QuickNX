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


"""NX protocol utilities

"""


import logging
import re
import urllib

from neatx import utils


NX_PROMPT = "NX>"
NX_EOL = "\n"
NX_EOL_CHARS = NX_EOL

NX_CMD_HELLO = "hello"
NX_CMD_BYE = "bye"
NX_CMD_LOGIN = "login"
NX_CMD_LISTSESSION = "listsession"
NX_CMD_STARTSESSION = "startsession"
NX_CMD_ATTACHSESSION = "attachsession"
NX_CMD_RESTORESESSION = "restoresession"
NX_CMD_TERMINATE = "terminate"
NX_CMD_SET = "set"
NX_CMD_QUIT = "quit"

NX_FALSE = "0"
NX_TRUE = "1"


class NxQuitServer(Exception):
  pass


class NxQuietQuitServer(NxQuitServer):
  pass


class NxProtocolError(Exception):
  def __init__(self, code, message, fatal=False):
    self.code = code
    self.msg = message
    self.fatal = fatal


class NxUndefinedCommand(NxProtocolError):
  def __init__(self, command):
    NxProtocolError.__init__(self, 503,
                             "Error: undefined command: '%s'" % command)


class NxNotBeforeLogin(NxProtocolError):
  def __init__(self, command):
    message = ("Error: the command '%s' cannot be called before to login" %
               command)
    NxProtocolError.__init__(self, 554, message)


class NxNotAfterLogin(NxProtocolError):
  def __init__(self, command):
    message = "Error: the command '%s' cannot be called after login" % command
    NxProtocolError.__init__(self, 554, message)


class NxUnsupportedProtocol(NxProtocolError):
  def __init__(self):
    # Had to set code to 500 instead of 552, otherwise client ignores
    # this error.
    NxProtocolError.__init__(self, 500,
                             ("Protocol you requested is not supported, "
                              "please upgrade your client to latest version"),
                             True)


class NxUnencryptedSessionsNotAllowed(NxProtocolError):
  def __init__(self, x):
    message = "ERROR: Unencrypted sessions are not allowed on this server"
    NxProtocolError.__init__(self, 594, message)


class NxParameterParsingError(NxProtocolError):
  def __init__(self, params):
    message = (("Error: Parsing parameters: string \"%s\" has "
                "invalid format") % params)
    NxProtocolError.__init__(self, 597, message)


class NxServerBase(object):
  """Base class for NX protocol servers.

  """
  def __init__(self, input, output, handler):
    """Instance initialization.

    @type input: file
    @param input: Input file handle
    @type output: file
    @param output: Output file handle
    @type handler: callable
    @param handler: Called for received lines

    """
    assert callable(handler)

    self._input = input
    self._output = output
    self._handler = handler

  def Start(self):
    """Start responding to requests.

    """
    self.SendBanner()

    while True:
      self.Write(105)
      try:
        try:
          line = self.ReadLine()

          # Ignore empty lines
          if line.strip():
            self._HandleLine(line)

        except NxProtocolError, err:
          self.Write(err.code, message=err.msg)
          if err.fatal:
            raise NxQuitServer()

      except NxQuietQuitServer:
        break

      except NxQuitServer:
        self.Write(999, "Bye.")
        break

  def _HandleLine(self, line):
    try:
      self._handler(line)
    except (SystemExit, KeyboardInterrupt, NxProtocolError, NxQuitServer):
      raise
    except Exception:
      logging.exception("Error while handling line %r", line)
      raise NxProtocolError(500, "Internal error", fatal=True)

  def _Write(self, data):
    """Write to output after logging.

    """
    logging.debug(">>> %r", data)
    try:
      self._output.write(data)
    finally:
      self._output.flush()

  def Write(self, code, message=None, newline=None):
    """Write prompt to output.

    @type code: int
    @param code: Status code
    @type message: str
    @param message: Message text
    @type newline: bool
    @param newline: Whether to add newline

    Note: The "newline" parameter is a tri-state variable. If there's a
    message, print newline by default (e.g. "NX> 500 something\\n"). If there's
    no message, don't print newline (e.g. "NX> 105 "). This logic can be
    overridden by explictly setting the "newline" parameter to a non-None
    value.

    """
    assert code >= 0 and code <= 999

    # Build prompt
    prompt = "%s %s " % (NX_PROMPT, code)
    if message:
      prompt += "%s" % message
    if (newline is None and message) or (newline is not None and newline):
      prompt += NX_EOL

    self._Write(prompt)

  def WriteLine(self, line):
    """Write line to output.

    One newline char is automatically added.

    """
    self._Write(line + NX_EOL)

  def ReadLine(self, hide=False):
    """Reads line from input.

    @type hide: bool
    @param hide: Whether to hide line read from log output

    """
    # TODO: Timeout (poll, etc.)
    line = self._input.readline()

    if hide:
      logging.debug("<<< [hidden]")
    else:
      logging.debug("<<< %r", line)

    # Has the client closed the connection?
    if not line:
      raise NxQuitServer()

    return line.rstrip(NX_EOL_CHARS)

  def WithoutTerminalEcho(self, fn, *args, **kwargs):
    """Calls function with ECHO flag disabled.

    @type fn: callable
    @param fn: Called function

    """
    return utils.WithoutTerminalEcho(self._input, fn, *args, **kwargs)

  def SendBanner(self):
    """Send banner to peer.

    Can be overriden by subclass.

    """


def SplitCommand(command):
  """Split line into command and arguments on first whitespace.

  """
  parts = command.split(None, 1)

  # Empty lines should've been filtered out earlier
  assert parts

  if len(parts) == 1:
    args = ""
  else:
    args = parts[1]

  return (parts[0].lower(), args)


def ParseParameters(params, _logging=logging):
  """Parse parameters sent by client.

  @type params: string
  @param params: Parameter string

  """
  param_re = re.compile((r"^\s*--(?P<name>[a-z][a-z0-9_-]*)="
                         "\"(?P<value>[^\"]*)\"\\s*"), re.I)
  result = []
  work = params.strip()

  while work:
    m = param_re.search(work)
    if not m:
      _logging.warning("Failed to parse parameter string %r", params)
      raise NxParameterParsingError(params)

    result.append((m.group("name"), m.group("value")))
    work = work[m.end():]

  assert not work

  return result


def UnquoteParameterValue(value):
  """Unquotes parameter value.

  @type value: str
  @param value: Quoted value
  @rtype: str
  @return: Unquoted value

  """
  return urllib.unquote(value)


def ParseNxBoolean(value):
  """Parses a boolean parameter value.

  @type value: str
  @param value: Value
  @rtype: bool
  @return: Whether parameter evaluates to true

  """
  return value == NX_TRUE


def FormatNxBoolean(value):
  """Format boolean value for nxagent.

  @type value: bool
  @param value: Value
  @rtype: str

  """
  if value:
    return NX_TRUE

  return NX_FALSE


def ParseNxSize(value):
  """Parses a size unit parameter value.

  @type value: str
  @param value: Value
  @rtype: int
  @return: Size in Mebibytes

  """
  return int(value.rstrip("M"))


def FormatNxSize(value):
  """Format size value.

  @type value: int
  @param value: Value in Mebibytes
  @rtype: str

  """
  return "%dM" % value
