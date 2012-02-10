/*
 * Copyright (C) 2009 Google Inc.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
 * 02110-1301, USA.
 */

#ifdef HAVE_CONFIG_H
#include "../config.h"
#endif

#include <sys/select.h>
#include <sys/time.h>
#include <sys/types.h>

#include <errno.h>
#include <fcntl.h>
#include <libgen.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#undef MAX
#define MAX(a, b) (((a) > (b))?(a):(b))

#define BLOCKSIZE (16 * 1024)
#define MAX_CHANNEL_COUNT 4

struct channel {
  int from;
  int to;
  int enabled;
};

struct filedesc {
  int fd;
  int read;
  int write;
};

const char* progname = NULL;

static int verbose;

static struct channel channel[MAX_CHANNEL_COUNT];
static int channel_count;

/* There can only be 2 * MAX_CHANNEL_COUNT different file descriptors */
static struct filedesc filedesc[(2 * MAX_CHANNEL_COUNT) + 1];
static int filedesc_count;

void usage()
{
  fprintf(stderr, "Usage: %s <fromfd>:<tofd> [<fromfd>:<tofd> ...]\n",
          progname);
  exit(EXIT_FAILURE);
}

struct filedesc *get_filedesc(const int fd)
{
  int i;

  for (i = 0; i < filedesc_count; ++i) {
    if (filedesc[i].fd == fd)
      return &filedesc[i];
  }

  /* Not found */
  ++filedesc_count;

  filedesc[i].fd = fd;

  return &filedesc[i];
}

int parse_number(const char* str)
{
  unsigned long int value;
  char *end;

  errno = 0;
  value = strtoul(str, &end, 10);
  if (*str == '\0' || *end != '\0' || errno != 0) {
    if (errno != 0) {
      fprintf(stderr, "Can't parse number: '%s' (%s)\n",
              str, strerror(errno));
    } else {
      fprintf(stderr, "Can't parse number: '%s'\n", str);
    }
    usage();
  }

  return value;
}

void parse_channel(const int chnum, const char *def)
{
  struct channel *ch;
  char *work;
  char *colon;

  /* Create local working copy */
  work = strdup(def);

  colon = strchr(work, ':');
  if (colon == NULL) {
    fprintf(stderr, "Invalid channel format, missing colon.\n");
    usage();
  }

  *colon = '\0';

  ch = &channel[chnum];
  ch->from = parse_number(work);
  ch->to = parse_number(colon + 1);
  ch->enabled = 1;

  free(work);

  /* Make sure there's only one reader per file descriptor */
  if (++get_filedesc(ch->from)->read != 1) {
    fprintf(stderr,
            "More than one channel is reading from file descriptor %d.\n",
            ch->from);
    usage();
  }

  ++get_filedesc(ch->to)->write;
}

void set_blocking(int fd, int blocking)
{
  int flags;

  flags = fcntl(fd, F_GETFL);
  if (flags < 0) {
    perror("fcntl(F_GETFL)");
    exit(EXIT_FAILURE);
  }

  if (blocking) {
    flags &= ~O_NONBLOCK;
  } else {
    flags |= O_NONBLOCK;
  }

  if (fcntl(fd, F_SETFL, flags) < 0) {
    perror("fcntl(F_SETFL)");
    exit(EXIT_FAILURE);
  }
}

void debug_info(const char *where)
{
  int i;

  if (!verbose) {
    return;
  }

  fprintf(stderr, "---\n");
  fprintf(stderr, "%s:\n", where);

  for (i = 0; i < filedesc_count; ++i) {
    fprintf(stderr, "fd %d: %d readers, %d writers\n",
            filedesc[i].fd, filedesc[i].read, filedesc[i].write);
  }

  for (i = 0; i < channel_count; ++i) {
    fprintf(stderr, "channel %d: enabled %d, from %d, to %d\n",
            i, channel[i].enabled, channel[i].from, channel[i].to);
  }

  fprintf(stderr, "---\n");
  fflush(stderr);
}

void try_close_filedesc(struct filedesc *fddesc)
{
  if (fddesc->read == 0 && fddesc->write == 0) {
    if (verbose)
      fprintf(stderr, "close(%d)\n", fddesc->fd);
    close(fddesc->fd);
  }
}

void close_channel(const int chnum)
{
  struct channel *ch;
  struct filedesc *fddesc;

  if (verbose)
    fprintf(stderr, "Closing channel %d\n", chnum);

  ch = &channel[chnum];

  fddesc = get_filedesc(ch->from);
  --fddesc->read;
  try_close_filedesc(fddesc);

  fddesc = get_filedesc(ch->to);
  --fddesc->write;
  try_close_filedesc(fddesc);

  ch->enabled = 0;
}

static ssize_t write_data(const int fd, const char* buf, const ssize_t len)
{
  ssize_t pos = 0;
  ssize_t n;

  while (pos < len) {
    n = write(fd, buf + pos, len - pos);
    if (n < 0) {
      if (errno == EINTR || errno == EAGAIN) {
        continue;

      } else if (errno != EPIPE) {
        perror("write");
      }

      return -1;
    }

    pos += n;
  }

  return pos;
}

static ssize_t read_data(const int fd, char *buf, const size_t len)
{
  ssize_t n;

  while (1) {
    n = read(fd, buf, len);
    if (n < 0) {
      switch (errno) {
        case EINTR:
          /* Try again */
          continue;

        case EAGAIN:
          /* Ignore, fall through */
        case EIO:
          /* PTY closed */
          return 0;
      }

      perror("read");

      return -1;
    }

    return n;
  }
}

void copy_data(const int chnum)
{
  struct channel *ch;
  char buf[BLOCKSIZE];
  ssize_t n;
  int i;

  if (verbose)
    fprintf(stderr, "Copy on channel %d\n", chnum);

  ch = &channel[chnum];

  n = read_data(ch->from, buf, sizeof(buf));
  if (n <= 0) {
    /* Closed while reading */
    close_channel(chnum);

  } else {
    n = write_data(ch->to, buf, n);
    if (n <= 0) {
      /* Closed while writing */
      close_channel(chnum);

      /* Close other channels writing to this fd */
      for (i = 0; i < channel_count; ++i) {
        if (channel[i].enabled &&
            channel[i].to == ch->to) {
          close_channel(i);
        }
      }
    }
  }

  return;
}

int main(int argc, char **argv)
{
  fd_set rfds;
  int maxfd;
  int ret;
  int i;

  progname = strdup(basename(strdup(argv[0])));

  if (argc < 2)
    usage();

  memset(&channel, 0, sizeof(channel));
  memset(&filedesc, 0, sizeof(filedesc));

  /* Parse arguments */
  verbose = 0;
  channel_count = 0;
  for (i = 1; i < argc; ++i) {
    if (strcmp(argv[i], "-v") == 0) {
      verbose = 1;
      continue;
    }

    if (channel_count >= MAX_CHANNEL_COUNT) {
      fprintf(stderr, "Too many channels (max %d)\n", MAX_CHANNEL_COUNT);
      exit(EXIT_FAILURE);
    }

    parse_channel(channel_count, argv[i]);
    ++channel_count;
  }

  for (i = 0; i < channel_count; ++i) {
    /* Set input fd to non-blocking mode */
    set_blocking(channel[i].from, 0);

    /* Set output fd to blocking mode */
    set_blocking(channel[i].to, 1);
  }

  debug_info("Start");

  signal(SIGPIPE, SIG_IGN);

  while (1) {
    FD_ZERO(&rfds);

    /* Build file descriptor list */
    maxfd = -1;
    for (i = 0; i < filedesc_count; ++i) {
      if (filedesc[i].read) {
        FD_SET(filedesc[i].fd, &rfds);
        maxfd = MAX(maxfd, filedesc[i].fd);
      }
    }

    /* maxfd is -1 if all channels are disabled (e.g. closed) */
    if (maxfd == -1)
      break;

    ret = select(maxfd + 1, &rfds, NULL, NULL, NULL);
    if (ret < 0) {
      perror("select");
      exit(EXIT_FAILURE);

    } else if (ret > 0) {
      debug_info("Before copy");
      for (i = 0; i < channel_count; ++i) {
        if (channel[i].enabled && FD_ISSET(channel[i].from, &rfds)) {
          copy_data(i);
        }
      }
      debug_info("After copy");
    }
  }

  exit(EXIT_SUCCESS);
}
