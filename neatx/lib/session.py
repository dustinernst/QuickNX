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


"""Module for sessions"""


import errno
import logging
import os
import os.path
import random
import time

# md5 module is deprecated in python2.6, hashlib is the replacement
try:
  import hashlib as md5
except ImportError:
  import md5

from neatx import constants
from neatx import serializer
from neatx import errors
from neatx import utils


def NewUniqueId(_data=None):
  """Generate new, unique ID of 32 characters.

  @rtype: str
  @return: New ID

  """
  if _data is None:
    _data = random.getrandbits(1024)
  return md5.md5(str(_data)).hexdigest().upper()


class SessionBase(object):
  """Data structure for session.

  """
  __slots__ = [
    "cookie",
    "display",
    "fullscreen",
    "geometry",
    "hostname",
    "id",
    "name",
    "options",
    "port",
    "rootless",
    "screeninfo",
    "ssl",
    "state",
    "subscription",
    "type",
    "username",
    "virtualdesktop",
    ]

  def __init__(self, sessid, hostname, display, username):
    """Initializes this class.

    @type hostname: str
    @param hostname: Local hostname
    @type display: str
    @param display: Display number
    @type username: str
    @param username: Username

    """
    # Set default values. Everything else listed in __slots__ is None unless
    # set otherwise.
    self.id = sessid
    self.hostname = hostname
    self.display = display
    self.username = username

    self.cookie = NewUniqueId()
    self.state = constants.SESS_STATE_CREATED
    self.subscription = constants.DEFAULT_SUBSCRIPTION

  def Serialize(self):
    """Serialize instance data.

    @rtype: C{dict}
    @return: Instance attributes and values

    """
    state = {}

    for name in self.__slots__:
      if hasattr(self, name):
        state[name] = getattr(self, name)

    return state

  def __getattr__(self, name):
    if name in self.__slots__:
      # Known attributes default to None. See
      # http://docs.python.org/reference/datamodel.html#object.__getattr__ for
      # more details.
      return None

    raise AttributeError, name

  def __setattr__(self, name, value):
    if name == "state" and value not in constants.VALID_SESS_STATES:
      raise errors.InvalidSessionState()

    return object.__setattr__(self, name, value)

  def _GetFullId(self):
    assert self.hostname
    assert self.display
    assert self.id
    return "%s-%s-%s" % (self.hostname, self.display, self.id)

  def _GetWindowName(self):
    return ("Neatx - %s@%s:%s - %s" %
            (self.username, self.hostname, self.display, self.name))

  # Read-only attributes
  full_id = property(fget=_GetFullId)
  windowname = property(fget=_GetWindowName)


class NxSession(SessionBase):
  def __init__(self, *args, **kwargs):
    raise NotImplementedError()

  @classmethod
  def Restore(cls, state):
    """Restore session from serialized state.

    @type state: C{dict}
    @param state: Serialized state

    """
    obj = cls.__new__(cls)
    cls._Restore(obj, state)
    return obj

  @staticmethod
  def _Restore(obj, state):
    """Restore session from serialized state.

    @type state: C{dict}
    @param state: Serialized state

    """
    if not isinstance(state, dict):
      raise ValueError("Invalid data: expected dict, got %s" % type(state))

    # Remove unset attributes
    for name in obj.__slots__:
      if name not in state:
        delattr(obj, name)

    for name, value in state.iteritems():
      if name in obj.__slots__:
        setattr(obj, name, value)


def DeserializeSessionFromString(data):
  return NxSession.Restore(serializer.LoadJson(data))


def SerializeSessionToString(session):
  data = session.Serialize()
  data["_updated"] = time.time()
  return serializer.DumpJson(data)


class NxSessionManager(object):
  def __init__(self, _path=constants.SESSIONS_DIR):
    self._path = _path

  def FindSessionsWithFilter(self, username, filter_fn):
    """Find sessions filtered by a function.

    The filter function receives one parameter, the session object. If its
    return value evaluates to True, the session is added to the result list.

    @type username: str or None
    @param username: Wanted session owner
    @type filter_fn: callable or None
    @param filter_fn: Filter function
    @return: A list of L{NxSession} instances for any matching sessions in the
      database. If none are found, the list is empty.

    """
    result = []

    for sessid in utils.ListVisibleFiles(self._path):
      sess = self.LoadSession(sessid)
      if (sess is not None and
          (username is None or sess.username == username) and
          (filter_fn is None or filter_fn(sess))):
        result.append(sess)

    return result

  def GetSessionDir(self, sessid):
    """Get absolute path for a session.

    """
    # TODO: If sessid is controlled by client this can be a security problem
    assert os.path.sep not in sessid
    return os.path.join(self._path, sessid)

  def GetSessionNodeSocket(self, sessid):
    return os.path.join(self.GetSessionDir(sessid),
                        constants.NODE_SOCKET_NAME)

  def _GetSessionDataFile(self, sessid):
    return os.path.join(self.GetSessionDir(sessid),
                        constants.SESSION_DATA_FILE_NAME)

  def LoadSession(self, sessid):
    """Load a session from permanent storage.

    @type sessid: str
    @param sessid: Session ID

    """
    filename = self._GetSessionDataFile(sessid)

    logging.debug("Loading session %s from %s", sessid, filename)

    try:
      fd = open(filename, "r")
    except IOError, err:
      # Files can disappear
      if err.errno in (errno.ENOENT, errno.EACCES):
        return None
      raise

    try:
      return DeserializeSessionFromString(fd.read())
    finally:
      fd.close()

  def LoadSessionForUser(self, sessid, username):
    """Load a session from permanent storage and check username.

    @type sessid: str
    @param sessid: Session ID
    @type username: str
    @param username: Username

    """
    sess = self.LoadSession(sessid)

    if sess:
      if sess.username == username:
        return sess

      logging.error("Session %r (owner %r) doesn't belong to user %r",
                    sessid, sess.username, username)

    return None

  def SaveSession(self, sess):
    """Save a session to permanent storage.

    """
    filename = self._GetSessionDataFile(sess.id)
    logging.debug("Writing session %r to %r", sess.id, filename)
    utils.WriteFile(filename, data=SerializeSessionToString(sess))

  def CreateSessionID(self):
    """Create unique session directory.

    @rtype: str
    @return: Session ID

    """
    # Create session directory (catches duplicate session IDs)
    # TODO: Split sessions into several directories (e.g. AB/DEF) to reduce
    # number of subdirectories
    # TODO: Cronjob to remove unused/old session directories
    tries = 0
    while True:
      sessid = NewUniqueId()
      path = self.GetSessionDir(sessid)
      tries += 1

      try:
        os.mkdir(path, 0700)
      except OSError, err:
        if err.errno != errno.EEXIST:
          raise

        # Give up after 10 retries
        if tries > 10:
          raise errors.GenericError("Unable to create session directory (%r)",
                                    err)
        continue

      return sessid
