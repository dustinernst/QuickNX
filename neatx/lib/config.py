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


"""Module for config functions"""


import ConfigParser
import os
import socket

from neatx import constants
from neatx import utils


VAR_AUTH_METHOD = "auth-method"
VAR_AUTH_SSH_HOST = "auth-ssh-host"
VAR_AUTH_SSH_PORT = "auth-ssh-port"
VAR_LOGLEVEL = "loglevel"
VAR_START_KDE_COMMAND = "start-kde-command"
VAR_START_GNOME_COMMAND = "start-gnome-command"
VAR_START_CONSOLE_COMMAND = "start-console-command"
VAR_NX_PROTOCOL_VERSION = "nx-protocol-version"
VAR_BASH = "bash-path"
VAR_NETCAT = "netcat-path"
VAR_XRDB = "xrdb-path"
VAR_SU = "su-path"
VAR_SSH = "ssh-path"
VAR_XAUTH = "xauth-path"
VAR_XSESSION = "xsession-path"
VAR_NXAGENT = "nxagent-path"
VAR_USE_XSESSION = "use-xsession"

_LOGLEVEL_DEBUG = "debug"

_GLOBAL_SECTION = "global"


def _ReadConfig(filename):
  cfg = ConfigParser.RawConfigParser()
  cfg.read(filename)
  return cfg

def __GetDefault(func):
  def wrapped(cfg, section, name, default):
    if cfg.has_option(section, name):
      return func(cfg, section, name)
    return default
  return wrapped

_GetOption = __GetDefault(ConfigParser.RawConfigParser.get)
_GetBoolOption = __GetDefault(ConfigParser.RawConfigParser.getboolean)


def _GetSshPort():
  """Get the SSH port.

  Note that this function queries the system-wide services database.

  @rtype: int

  """
  try:
    return socket.getservbyname("ssh", "tcp")
  except socket.error:
    return constants.DEFAULT_SSH_PORT

class Config(object):
  def __init__(self, filename, section=_GLOBAL_SECTION, _hostname=None):
    """Load configuration file.

    @type filename: str
    @param filename: Path to configuration file

    """
    if _hostname is None:
      _hostname = socket.gethostname()

    cfg = _ReadConfig(filename)

    # If speed becomes an issue, the following attributes could be converted to
    # properties and be evaluated only when actually read.

    if cfg.has_option(section, VAR_LOGLEVEL):
      loglevel = cfg.get(section, VAR_LOGLEVEL)

      # Enable debug if loglevel is "debug"
      self.debug = (loglevel.lower() == _LOGLEVEL_DEBUG.lower())
    else:
      self.debug = False

    self.start_kde_command = \
      _GetOption(cfg, section, VAR_START_KDE_COMMAND,
                 constants.START_KDE_COMMAND)

    self.start_gnome_command = \
      _GetOption(cfg, section, VAR_START_GNOME_COMMAND,
                 constants.START_GNOME_COMMAND)

    self.start_console_command = \
      _GetOption(cfg, section, VAR_START_CONSOLE_COMMAND,
                 constants.START_CONSOLE_COMMAND)

    self.auth_method = _GetOption(cfg, section, VAR_AUTH_METHOD,
                                  constants.AUTH_METHOD_DEFAULT)

    self.auth_ssh_host = _GetOption(cfg, section, VAR_AUTH_SSH_HOST,
                                    _hostname)
    self.auth_ssh_port = _GetOption(cfg, section, VAR_AUTH_SSH_PORT,
                                    _GetSshPort())

    ver_string = _GetOption(cfg, section, VAR_NX_PROTOCOL_VERSION,
                            constants.DEFAULT_NX_PROTOCOL_VERSION)
    self.nx_protocol_version = \
      utils.ParseVersion(ver_string, constants.NXAGENT_VERSION_SEP,
                         constants.PROTOCOL_VERSION_DIGITS)

    self.bash = \
      _GetOption(cfg, section, VAR_BASH,
                 constants.BASH)

    self.netcat = \
      _GetOption(cfg, section, VAR_NETCAT,
                 constants.NETCAT)

    self.xrdb = \
      _GetOption(cfg, section, VAR_XRDB,
                 constants.XRDB)

    self.su = \
      _GetOption(cfg, section, VAR_SU,
                 constants.SU)

    self.ssh = \
      _GetOption(cfg, section, VAR_SSH,
                 constants.SSH)

    self.xauth = \
      _GetOption(cfg, section, VAR_XAUTH,
                 constants.XAUTH)

    self.xsession = \
      _GetOption(cfg, section, VAR_XSESSION,
                 constants.XSESSION)

    self.nxagent = \
      _GetOption(cfg, section, VAR_NXAGENT,
                 constants.NXAGENT)

    self.use_xsession = \
      _GetBoolOption(cfg, section, VAR_USE_XSESSION,
                     constants.USE_XSESSION)

    if self.use_xsession:
      self.start_kde_command = "%s %s" % \
          (self.xsession, self.start_kde_command)
      self.start_gnome_command = "%s %s" % \
          (self.xsession, self.start_gnome_command)
