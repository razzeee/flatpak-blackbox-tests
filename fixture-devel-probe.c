/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/ptrace.h>

int
main (void)
{
  puts ("probe-started");
  fflush (stdout);
  if (ptrace (PTRACE_TRACEME, 0, NULL, NULL) == -1)
    {
      fprintf (stderr, "ptrace: %s\n", strerror (errno));
      return 1;
    }
  puts ("ptrace-allowed");
  return 0;
}
