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


"""Module for command line interface functions"""


import logging
import optparse
import sys

from neatx import config
from neatx import constants
from neatx import utils


class GenericProgram(object):
  def __init__(self, logsetup):
    self.logsetup = logsetup
    self.cfg = None
    self.args = None
    self.options = None

  def BuildOptions(self):
    debug_opt = optparse.make_option("-d", "--debug", default=False,
                                     action="store_true",
                                     help="Enable debug logging")
    logtostderr_opt = optparse.make_option("--logtostderr", default=False,
                                           action="store_true",
                                           help="Log to stderr")
    return [debug_opt, logtostderr_opt]

  def Main(self):
    self.logsetup.Init()

    logging.debug("Started with args %r", sys.argv)

    try:
      (self.options, self.args) = self.ParseArgs()

      self.cfg = config.Config(constants.CONFIG_FILE)

      self._ConfigLogging()

      self.Run()

    except (SystemExit, KeyboardInterrupt):
      raise

    except Exception:
      logging.exception("Caught exception")
      sys.exit(constants.EXIT_FAILURE)

  def ParseArgs(self):
    parser = optparse.OptionParser(option_list=self.BuildOptions(),
                                   formatter=optparse.TitledHelpFormatter())
    return parser.parse_args()

  def _ConfigLogging(self):
    """Configures the logging module.

    """
    debug = self.options.debug or self.cfg.debug
    logopts = utils.LoggingSetupOptions(debug, self.options.logtostderr)
    self.logsetup.SetOptions(logopts)

  def Run(self):
    raise NotImplementedError()
