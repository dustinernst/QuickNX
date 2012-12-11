#
#

# Copyright (C) 2007 Google Inc.
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


"""nxnode program.

This program is started once per session. It receives commands from nxserver
via a Unix socket and updates the session database based on nxagent's output.

"""


import logging
import pwd
import select
import signal
import socket
import sys
import gobject

from neatx import cli
from neatx import constants
from neatx import daemon
from neatx import errors
from neatx import node
from neatx import serializer
from neatx import session
from neatx import utils


PROGRAM = "nxnode"

_SESSION_START_TIMEOUT = 30


class NxNodeContext(object):
  def __init__(self):
    self.cfg = None
    self.uid = None
    self.username = None
    self.sessrunner = None
    self.sessid = None
    self.session = None
    self.sessmgr = None
    self.processes = None


def _GetUserUid(username):
  return pwd.getpwnam(username).pw_uid


def ValidateRequest(req):
  if not (isinstance(req, dict) and
          node.REQ_FIELD_CMD in req and
          node.REQ_FIELD_ARGS in req):
    raise errors.GenericError("Incomplete request")


class ClientOperations(object):
  def __init__(self, ctx):
    self._ctx = ctx

  def __call__(self, cmd, args):
    logging.info("Received request: %r, %r", cmd, args)

    if cmd == node.CMD_STARTSESSION:
      return self._StartSession(args)

    elif cmd == node.CMD_ATTACHSESSION:
      assert len(args) == 2
      return self._AttachSession(args[0], args[1])

    elif cmd == node.CMD_RESTORESESSION:
      return self._RestoreSession(args)

    elif cmd == node.CMD_TERMINATESESSION:
      return self._TerminateSession(args)

    elif cmd == node.CMD_GET_SHADOW_COOKIE:
      return self._GetShadowCookie()

    else:
      raise errors.GenericError("Unknown command %r", cmd)

  def _StartSession(self, args):
    """Starts a new session.

    @type args: dict
    @param args: Arguments passed to command by client

    """
    return self._StartSessionInner(args, None)

  def _AttachSession(self, args, shadowcookie):
    """Attaches to an existing session, shadowing it.

    @type args: dict
    @param args: Arguments passed to command by client
    @type shadowcookie: str
    @param shadowcookie: Session cookie for session to be shadowed

    """
    assert shadowcookie
    logging.debug("Attaching to session with shadowcookie %r", shadowcookie)
    return self._StartSessionInner(args, shadowcookie)

  def _StartSessionInner(self, args, shadowcookie):
    ctx = self._ctx

    if ctx.sessrunner:
      raise errors.GenericError("Session already started")

    ctx.session = node.NodeSession(ctx, args)

    if shadowcookie:
      ctx.session.SetShadowCookie(shadowcookie)

    sessrunner = node.SessionRunner(ctx)
    sessrunner.Start()

    ctx.sessrunner = sessrunner

    return True

  def _RestoreSession(self, args):
    """Restores a session.

    @type args: dict
    @param args: Arguments passed to command by client

    """
    ctx = self._ctx

    if not ctx.sessrunner:
      raise errors.GenericError("Session not yet started")

    logging.debug("Resuming session")

    ctx.session.PrepareRestore(args)
    ctx.sessrunner.Restore()

    return True

  def _TerminateSession(self, args):
    """Terminates the current session.

    """
    raise NotImplementedError()

  def _GetShadowCookie(self):
    """Returns the cookie needed to shadow the current session.

    @rtype: str
    @return: Shadow cookie

    """
    ctx = self._ctx

    if not ctx.sessrunner:
      raise errors.GenericError("Session not yet started")

    # TODO: If request is coming from a different user, show dialog before
    # giving out cookie. This is not a problem at the moment--only the user
    # themselves can access the node socket.
    return ctx.session.cookie


class ClientConnection:
  def __init__(self, ctx):
    self._ops = ClientOperations(ctx)
    self.__conn = None

    self.__channel = daemon.IOChannel()

    self.__reader = daemon.ChopReader(node.PROTO_SEPARATOR)
    signal_name = daemon.ChopReader.SLICE_COMPLETE_SIGNAL
    self.__reader_slice_reg = \
      daemon.SignalRegistration(self.__reader,
                                self.__reader.connect(signal_name,
                                                      self.__HandleSlice))
    self.__reader.Attach(self.__channel)

  def Attach(self, conn):
    self.__conn = conn
    self.__channel.Attach(conn.fileno())

  def __del__(self):
    # TODO: Close
    pass

  def __HandleSlice(self, _, data):
    success = False
    try:
      req = serializer.LoadJson(data)
      ValidateRequest(req)

      cmd = req[node.REQ_FIELD_CMD]
      args = req[node.REQ_FIELD_ARGS]

      # Call function
      result = self._ops(cmd, args)
      success = True

    except (SystemExit, KeyboardInterrupt):
      raise

    except errors.GenericError, err:
      # Serialize exception arguments
      result = (err.__class__.__name__, err.args)

    except Exception, err:
      logging.exception("Error while handling request")
      result = "Caught exception: %s" % str(err)

    response = {
      node.RESP_FIELD_SUCCESS: success,
      node.RESP_FIELD_RESULT: result,
      }

    serialized_data = serializer.DumpJson(response)

    assert node.PROTO_SEPARATOR not in serialized_data

    self.__channel.Write(serialized_data + node.PROTO_SEPARATOR)


class NodeSocket:
  def __init__(self, ctx, path):
    self.__ctx = ctx
    self.__path = path
    self.__socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

  def Start(self):
    self.__socket.bind(self.__path)
    self.__socket.listen(32)

    gobject.io_add_watch(self.__socket.fileno(), gobject.IO_IN,
                         self.__HandleIO)

  def __HandleIO(self, source, cond):
    if cond & gobject.IO_IN:
      self.__IncomingConnection()
      return True

    return False

  def __IncomingConnection(self):
    (conn, _) = self.__socket.accept()
    logging.info("Connection established")
    ClientConnection(self.__ctx).Attach(conn)


def _CheckIfSessionWasStarted(ctx):
  if not ctx.sessrunner:
    logging.error("Session wasn't started in %s seconds, terminating",
                  _SESSION_START_TIMEOUT)
    sys.exit(1)
  return False


class NxNodeProgram(cli.GenericProgram):
  def Run(self):
    if len(self.args) != 2:
      raise errors.GenericError("Username or session ID missing")

    ctx = NxNodeContext()
    ctx.cfg = self.cfg
    ctx.sessmgr = session.NxSessionManager()
    ctx.processes = []

    (ctx.username, ctx.sessid) = self.args

    ctx.uid = _GetUserUid(ctx.username)

    server = NodeSocket(ctx, ctx.sessmgr.GetSessionNodeSocket(ctx.sessid))
    server.Start()

    # Terminate if session wasn't started after some time
    gobject.timeout_add(_SESSION_START_TIMEOUT * 1000,
                        _CheckIfSessionWasStarted, ctx)

    mainloop = gobject.MainLoop()

    logging.debug("Starting mainloop")
    mainloop.run()


def Main():
  logsetup = utils.LoggingSetup(PROGRAM)
  NxNodeProgram(logsetup).Main()
