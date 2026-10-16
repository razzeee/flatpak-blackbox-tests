/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"

#include <fcntl.h>
#include <string.h>
#include <unistd.h>

int blackbox_regressions_main (int argc, char **argv);

int
blackbox_regressions_main (int argc, char **argv)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(GSubprocessLauncher) launcher = NULL;
  g_autoptr(GSubprocess) process = NULL;
  g_autoptr(GPtrArray) instances = NULL;
  char id[128] = { 0 };
  int descriptors[2];
  gboolean found = FALSE;

  if (argc < 2 || strcmp (argv[1], "instance-fd-immediate") != 0)
    return -1;
  g_assert_cmpint (argc, ==, 5);
  g_assert_cmpint (pipe (descriptors), ==, 0);
  g_assert_cmpint (fcntl (descriptors[0], F_SETFD, FD_CLOEXEC), ==, 0);
  launcher = g_subprocess_launcher_new (G_SUBPROCESS_FLAGS_STDIN_PIPE |
                                         G_SUBPROCESS_FLAGS_STDOUT_PIPE);
  g_subprocess_launcher_take_fd (launcher, descriptors[1], 3);
  process = g_subprocess_launcher_spawn (launcher, &error, argv[2], "run", "--user",
                                         "--instance-id-fd=3", argv[3], "barrier", NULL);
  g_assert_no_error (error);
  g_assert_nonnull (process);
  /* A child that exits without writing must produce EOF in the parent. */
  g_clear_object (&launcher);
  /* No readiness output or polling before the first public instance lookup. */
  ssize_t length = read (descriptors[0], id, sizeof id - 1);
  close (descriptors[0]);
  g_assert_cmpint (length, >, 0);
  g_strstrip (id);
  instances = CALL_API (flatpak_instance_get_all, );
  for (size_t i = 0; i < instances->len; i++)
    {
      FlatpakInstance *instance = g_ptr_array_index (instances, i);
      if (strcmp (CALL_API (flatpak_instance_get_id, instance), id) != 0)
        continue;
      g_auto(GStrv) parts = g_strsplit (argv[3], "/", -1);
      g_assert_false (found);
      found = TRUE;
      g_assert_cmpstr (CALL_API (flatpak_instance_get_app, instance), ==, parts[1]);
      g_assert_cmpstr (CALL_API (flatpak_instance_get_commit, instance), ==, argv[4]);
      g_assert_cmpint (CALL_API (flatpak_instance_get_pid, instance), >, 0);
      g_assert_true (CALL_API (flatpak_instance_is_running, instance));
    }
  g_assert_true (found);
  g_autofree char *output = NULL;
  g_assert_true (g_subprocess_communicate_utf8 (process, "R\n", NULL, &output, NULL, &error));
  g_assert_no_error (error);
  g_assert_true (g_subprocess_get_successful (process));
  g_assert_cmpstr (output, ==, "barrier-released\n");
  g_print ("immediate-instance-ok\n");
  return 0;
}
