#
#

# Copyright (C) 2008 Google Inc.
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


"""nxdialog program for handling dialog display."""


# If an "NX_CLIENT" environment variable is not provided to nxagent
# nxcomp library assumes this script is located in /usr/NX/bin/nxclient

import pygtk
pygtk.require("2.0")
import gtk

import logging
import optparse
import os
import signal
import sys

from neatx import cli
from neatx import constants
from neatx import errors
from neatx import utils


PROGRAM = "nxdialog"

DISCONNECT = 1
TERMINATE = 2

CANCEL_TEXT = "Cancel"
DISCONNECT_TEXT = "Disconnect"
TERMINATE_TEXT = "Terminate"


class PullDownMenu:
  """Shows a popup menu to disconnect/terminate session.

  """
  def __init__(self, window_id):
    """Initializes this class.

    @type window_id: int
    @param window_id: X11 window id of target window

    """
    self._window_id = window_id
    self._result = None

  def Show(self):
    """Shows popup and returns result.

    """
    win = gtk.gdk.window_foreign_new(self._window_id)

    menu = gtk.Menu()
    menu.connect("deactivate", self._MenuDeactivate)

    # TODO: Show title item in bold font
    title = gtk.MenuItem(label="Neatx session")
    title.set_sensitive(False)
    menu.append(title)

    disconnect = gtk.MenuItem(label=DISCONNECT_TEXT)
    disconnect.connect("activate", self._ItemActivate, DISCONNECT)
    menu.append(disconnect)

    terminate = gtk.MenuItem(label=TERMINATE_TEXT)
    terminate.connect("activate", self._ItemActivate, TERMINATE)
    menu.append(terminate)

    menu.append(gtk.SeparatorMenuItem())

    cancel = gtk.MenuItem(label=CANCEL_TEXT)
    menu.append(cancel)

    menu.show_all()

    menu.popup(parent_menu_shell=None, parent_menu_item=None,
               func=self._PosMenu, data=win,
               button=0, activate_time=gtk.get_current_event_time())

    gtk.main()

    return self._result

  def _ItemActivate(self, _, result):
    self._result = result
    gtk.main_quit()

  def _MenuDeactivate(self, _):
    logging.debug("Aborting pulldown menu")
    gtk.main_quit()

  def _PosMenu(self, menu, parent):
    """Positions menu at the top center of the parent window.

    """
    # Get parent geometry and origin
    (_, _, win_width, win_height, _) = parent.get_geometry()
    (win_x, win_y) = parent.get_origin()

    # Calculate width of menu
    (menu_width, menu_height) = menu.size_request()

    # Calculate center
    x = win_x + ((win_width - menu_width) / 2)

    return (x, win_y, True)


def ShowYesNoSuspendBox(title, text):
  """Shows a message box to disconnect/terminate session.

  @type title: str
  @param title: Message box title
  @type text: str
  @param text: Message box text
  @return: Choosen action

  """
  dlg = gtk.MessageDialog(type=gtk.MESSAGE_QUESTION, flags=gtk.DIALOG_MODAL)
  dlg.set_title(title)
  dlg.set_markup(text)
  dlg.add_button(DISCONNECT_TEXT, DISCONNECT)
  dlg.add_button(TERMINATE_TEXT, TERMINATE)
  dlg.add_button(CANCEL_TEXT, gtk.RESPONSE_CANCEL)

  res = dlg.run()

  if res in (DISCONNECT, TERMINATE):
    return res

  # Everything else is cancel
  return None


def HandleSessionAction(agentpid, action):
  """Execute session action choosen by user.

  @type agentpid: int
  @param agentpid: Nxagent process id as passed by command line
  @type action: int or None
  @param action: Choosen action

  """
  if action == DISCONNECT:
    ppid = os.getppid()
    logging.info("Disconnecting from session, sending SIGHUP to %s", ppid)
    os.kill(ppid, signal.SIGHUP)

  elif action == TERMINATE:
    if agentpid:
      logging.info("Terminating session, sending SIGTERM to process %s",
                   agentpid)
      os.kill(agentpid, signal.SIGTERM)

  elif action is None:
    logging.debug("Dialog canceled, nothing to do")

  else:
    raise NotImplementedError()


def ShowSimpleMessageBox(icon, title, text):
  """Shows a simple message box.

  @type icon: QMessageBox.Icon
  @param icon: Icon for message box
  @type title: str
  @param title: Message box title
  @type text: str
  @param text: Message box text

  """
  dlg = gtk.MessageDialog(type=icon, flags=gtk.DIALOG_MODAL,
                          buttons=gtk.BUTTONS_OK)
  dlg.set_title(title)
  dlg.set_markup(text)
  dlg.run()


class NxDialogProgram(cli.GenericProgram):
  def BuildOptions(self):
    options = cli.GenericProgram.BuildOptions(self)
    options.extend([
      optparse.make_option("--caption", type="string", dest="caption"),
      optparse.make_option("--dialog", type="string", dest="dialog_type"),
      optparse.make_option("--display", type="string", dest="display"),
      optparse.make_option("--message", type="string", dest="text"),
      optparse.make_option("--parent", type="int", dest="agentpid"),
      optparse.make_option("--window", type="int", dest="window"),
      ])
    return options

  def Run(self):
    """Disconnect/terminate NX session upon user's request.

    """
    logging.debug("Nxdialog options: %r", self.options)

    dlgtype = self.options.dialog_type

    if dlgtype not in constants.VALID_DLG_TYPES:
      logging.error("Dialog type '%s' not supported", dlgtype)
      sys.exit(constants.EXIT_FAILURE)

    if self.options.caption:
      message_caption = self.options.caption
    else:
      message_caption = sys.argv[0]

    if self.options.text:
      message_text = self.options.text
    else:
      message_text = ""

    if self.options.display:
      os.environ["DISPLAY"] = self.options.display

    if dlgtype == constants.DLG_TYPE_OK:
      ShowSimpleMessageBox(gtk.MESSAGE_INFO, message_caption, message_text)

    elif dlgtype in (constants.DLG_TYPE_ERROR, constants.DLG_TYPE_PANIC):
      ShowSimpleMessageBox(gtk.MESSAGE_ERROR, message_caption, message_text)

    elif dlgtype == constants.DLG_TYPE_PULLDOWN:
      HandleSessionAction(self.options.agentpid,
                          PullDownMenu(self.options.window).Show())

    elif dlgtype == constants.DLG_TYPE_YESNOSUSPEND:
      HandleSessionAction(self.options.agentpid,
                          ShowYesNoSuspendBox(message_caption, message_text))

    else:
      # TODO: Implement all dialog types
      raise errors.GenericError("Dialog type %r not implemented" %
                                self.options.dialog_type)


def Main():
  logsetup = utils.LoggingSetup(PROGRAM)
  NxDialogProgram(logsetup).Main()
