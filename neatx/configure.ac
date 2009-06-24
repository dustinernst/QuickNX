# Configure script for Neatx
m4_define([version_major], [0])
m4_define([version_minor], [3])
m4_define([version_revision], [1])
m4_define([version_suffix], [])
m4_define([version_full],
          m4_format([%d.%d.%d%s],
                    version_major, version_minor,
                    version_revision, version_suffix))

AC_PREREQ(2.59)
AC_INIT(neatx, version_full, ganeti@googlegroups.com)
AC_CONFIG_AUX_DIR(autotools)
AC_CONFIG_SRCDIR(configure)
AM_INIT_AUTOMAKE([1.9 foreign tar-ustar -Wall -Wno-portability])

AC_SUBST([VERSION_MAJOR], version_major)
AC_SUBST([VERSION_MINOR], version_minor)
AC_SUBST([VERSION_REVISION], version_revision)
AC_SUBST([VERSION_SUFFIX], version_suffix)
AC_SUBST([VERSION_FULL], version_full)

# Check common programs
AC_PROG_INSTALL
AC_PROG_LN_S
AC_PROG_CC

# Check for Python
AM_PATH_PYTHON(2.4)

# Check for rst2html
AC_ARG_VAR(RST2HTML, [rst2html path])
AC_PATH_PROG(RST2HTML, [rst2html], [])
if test -z "$RST2HTML"
then
  AC_MSG_WARN([rst2html not found, documentation rebuild will not be possible])
fi

AC_CONFIG_HEADERS([config.h])
AC_CONFIG_FILES([Makefile])

AC_OUTPUT
