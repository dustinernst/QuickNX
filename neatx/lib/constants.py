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


"""Module for constants"""


from neatx import _autoconf


NXDIR = "/usr/bin"

SYSLOG_ADDRESS = "/dev/log"
BASH = "/bin/bash"
NETCAT = "/bin/netcat"
XRDB = "/usr/bin/xrdb"
SU = "/bin/su"
SSH = "/usr/bin/ssh"
XAUTH = "/usr/bin/xauth"
XSESSION = "/etc/X11/Xsession"

START_CONSOLE_COMMAND = "/usr/bin/xterm"
START_KDE_COMMAND = XSESSION + " startkde"
START_GNOME_COMMAND = XSESSION + " gnome-session"

NXUSER = "nx"
NXSERVER = _autoconf.PKGLIBDIR + "/nxserver"
NXNODE = _autoconf.PKGLIBDIR + "/nxnode"
NXNODE_WRAPPER = _autoconf.PKGLIBDIR + "/nxnode-wrapper"
NXNC = _autoconf.PKGLIBDIR + "/nxnc"
NXDIALOG = _autoconf.PKGLIBDIR + "/nxdialog"
NXAGENT = NXDIR + "/nxagent"
NXAGENT_PKGNAME = "nxagent"
FDCOPY = _autoconf.PKGLIBDIR + "/fdcopy"
TTYSETUP = _autoconf.PKGLIBDIR + "/ttysetup"

NXAGENT_VERSION_SEP = ".-~"

PROTOCOL_VERSION_DIGITS = [2, 2, 4]

CONFIG_FILE = _autoconf.SYSCONFDIR + "/neatx.conf"

DATA_DIR = _autoconf.LOCALSTATEDIR + "/lib/neatx"
SESSIONS_DIR = DATA_DIR + "/sessions"
SESSION_DATA_FILE_NAME = "neatx.data"

NODE_SOCKET_NAME = "nxnode.sock"

DISPLAY_CHECK_PATHS = frozenset([
  "/tmp/.X%s-lock",
  "/tmp/.X11-unix/X%s",
  ])

DEFAULT_SUBSCRIPTION = "GPL"
DEFAULT_SSH_PORT = 22
DEFAULT_APP_UMASK = 0077
DEFAULT_NX_PROTOCOL_VERSION = "3.3.0"

# Taken from nxcomp/Misc.cpp
NX_PROXY_PORT_OFFSET = 4000

EXIT_SUCCESS = 0
EXIT_FAILURE = 1

STDIN_FILENO = 0
STDOUT_FILENO = 1
STDERR_FILENO = 2

AUTH_METHOD_SU = "su"
AUTH_METHOD_SSH = "ssh"
AUTH_METHOD_DEFAULT = AUTH_METHOD_SU

SESS_STATE_CREATED = "created"
SESS_STATE_STARTING = "starting"
SESS_STATE_WAITING = "waiting"
SESS_STATE_RUNNING = "running"
SESS_STATE_SUSPENDING = "suspending"
SESS_STATE_SUSPENDED = "suspended"
SESS_STATE_TERMINATING = "terminating"
SESS_STATE_TERMINATED = "terminated"

VALID_SESS_STATES = frozenset([
  SESS_STATE_CREATED,
  SESS_STATE_STARTING,
  SESS_STATE_WAITING,
  SESS_STATE_RUNNING,
  SESS_STATE_SUSPENDING,
  SESS_STATE_SUSPENDED,
  SESS_STATE_TERMINATING,
  SESS_STATE_TERMINATED,
  ])

SESS_TYPE_UNIX_PREFIX = "unix-"

SESS_TYPE_APPLICATION = SESS_TYPE_UNIX_PREFIX + "application"
SESS_TYPE_CDE = SESS_TYPE_UNIX_PREFIX + "cde"
SESS_TYPE_CONSOLE = SESS_TYPE_UNIX_PREFIX + "console"
SESS_TYPE_GNOME = SESS_TYPE_UNIX_PREFIX + "gnome"
SESS_TYPE_KDE = SESS_TYPE_UNIX_PREFIX + "kde"
SESS_TYPE_SHADOW = "shadow"
SESS_TYPE_XDM = SESS_TYPE_UNIX_PREFIX + "xdm"

VALID_SESS_TYPES = frozenset([
  SESS_TYPE_APPLICATION,
  SESS_TYPE_CDE,
  SESS_TYPE_CONSOLE,
  SESS_TYPE_GNOME,
  SESS_TYPE_KDE,
  SESS_TYPE_SHADOW,
  SESS_TYPE_XDM,
  ])

DLG_TYPE_ERROR = "error"
DLG_TYPE_OK = "ok"
DLG_TYPE_PANIC = "panic"
DLG_TYPE_PULLDOWN = "pulldown"
DLG_TYPE_QUIT = "quit"
DLG_TYPE_YESNO = "yesno"
DLG_TYPE_YESNOSUSPEND = "yesnosuspend"

VALID_DLG_TYPES = frozenset([
  DLG_TYPE_ERROR,
  DLG_TYPE_OK,
  DLG_TYPE_PANIC,
  DLG_TYPE_PULLDOWN,
  DLG_TYPE_QUIT,
  DLG_TYPE_YESNO,
  DLG_TYPE_YESNOSUSPEND,
  ])
