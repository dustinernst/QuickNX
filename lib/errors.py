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


"""Module for exception classes"""


class GenericError(Exception):
  """Base exception.

  """


class ProgrammerError(GenericError):
  """Programming-related error.

  """


class CommandLineError(GenericError):
  """Command line error.

  """


class UnknownAuthMethod(GenericError):
  """Unknown authentication method.

  """


class AuthError(GenericError):
  """Error during authentication.

  """


class AuthTimeoutError(AuthError):
  """Timeout during authentication.

  """


class AuthFailedError(AuthError):
  """Authentication failed.

  """


class InvalidSessionState(GenericError):
  """Invalid session state.

  """


class NoFreeDisplayNumberFound(GenericError):
  """No free display number was found.

  """


class SessionParameterError(GenericError):
  """Session parameter error.

  """

class IllegalCharacterError(GenericError):
  """String contains illegal character (e.g. a comma in session options).

  """


# Exception classes should be added above

def GetErrorClass(name):
  """Return the class of for an exception.

  Given the class name, return the class itself.

  @type name: str
  @param name: Exception name
  @rtype: class
  @return: The actual class, or None if not found

  """
  item = globals().get(name, None)

  if (item is not None and
      isinstance(item, type(Exception)) and
      issubclass(item, GenericError)):
    return item

  return None
