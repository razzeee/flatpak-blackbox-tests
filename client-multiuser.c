/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"

#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static FlatpakInstallation *
installation (const char *scope)
{
  GError *error = NULL;
  FlatpakInstallation *result;
  if (strcmp (scope, "user") == 0)
    result = CALL_API (flatpak_installation_new_user, NULL, &error);
  else if (strcmp (scope, "system") == 0)
    result = CALL_API (flatpak_installation_new_system, NULL, &error);
  else
    result = CALL_API (flatpak_installation_new_system_with_id, scope, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (result);
  g_assert_cmpint (CALL_API (flatpak_installation_get_is_user, result), ==,
                  strcmp (scope, "user") == 0);
  if (strcmp (scope, "blackbox-ci") == 0)
    g_assert_cmpstr (CALL_API (flatpak_installation_get_id, result), ==, scope);
  return result;
}

static void
assert_ref (FlatpakInstallation *inst, const char *ref, const char *commit)
{
  GError *error = NULL;
  g_autoptr(FlatpakRef) parsed = CALL_API (flatpak_ref_parse, ref, &error);
  g_assert_no_error (error);
  g_autoptr(FlatpakInstalledRef) installed = CALL_API (
    flatpak_installation_get_installed_ref, inst,
    CALL_API (flatpak_ref_get_kind, parsed), CALL_API (flatpak_ref_get_name, parsed),
    CALL_API (flatpak_ref_get_arch, parsed), CALL_API (flatpak_ref_get_branch, parsed),
    NULL, &error);
  if (strcmp (commit, "-") == 0)
    {
      g_assert_null (installed);
      g_assert_error (error, FLATPAK_ERROR, FLATPAK_ERROR_NOT_INSTALLED);
      g_clear_error (&error);
    }
  else
    {
      g_assert_no_error (error);
      g_assert_nonnull (installed);
      g_assert_cmpstr (CALL_API (flatpak_ref_get_commit, FLATPAK_REF (installed)), ==, commit);
    }
}

static gboolean
ready (FlatpakTransaction *transaction, gpointer data)
{
  (void) transaction;
  (void) data;
  return TRUE;
}

static void
add_operation (FlatpakTransaction *tx, const char *op, const char *ref)
{
  GError *error = NULL;
  gboolean added;
  if (strcmp (op, "install") == 0)
    added = CALL_API (flatpak_transaction_add_install, tx, "fixture", ref, NULL, &error);
  else if (strcmp (op, "update") == 0)
    added = CALL_API (flatpak_transaction_add_update, tx, ref, NULL, NULL, &error);
  else
    added = CALL_API (flatpak_transaction_add_uninstall, tx, ref, &error);
  g_assert_no_error (error);
  g_assert_true (added);
  g_signal_connect (tx, "ready", G_CALLBACK (ready), NULL);
}

/* This separate fixture records real polkit callbacks, rejecting every request.
 * It never calls libflatpak or supplies credentials. */
static GSubprocess *
start_agent (const char *agent, GDataInputStream **output)
{
  GError *error = NULL;
  g_autofree char *pid = g_strdup_printf ("%d", (int) getpid ());
  GSubprocess *process = g_subprocess_new (G_SUBPROCESS_FLAGS_STDOUT_PIPE, &error,
                                         agent, pid, NULL);
  g_assert_no_error (error);
  *output = g_data_input_stream_new (g_subprocess_get_stdout_pipe (process));
  g_autofree char *line = g_data_input_stream_read_line (*output, NULL, NULL, &error);
  g_assert_no_error (error);
  g_assert_cmpstr (line, ==, "READY");
  return process;
}

static void
stop_agent (GSubprocess *process, GDataInputStream *output, gboolean silent)
{
  GError *error = NULL;
  guint requests = 0;
  g_subprocess_send_signal (process, SIGTERM);
  for (;;)
    {
      g_autofree char *line = g_data_input_stream_read_line (output, NULL, NULL, &error);
      g_assert_no_error (error);
      if (line == NULL)
        break;
      g_assert_true (g_str_has_prefix (line, "REQUEST org.freedesktop.Flatpak."));
      g_print ("polkit-%s\n", line);
      requests++;
    }
  g_assert_true (g_subprocess_wait (process, NULL, &error));
  g_assert_no_error (error);
  g_print ("polkit-request-count %u no-interaction=%d\n", requests, silent);
  if (silent)
    g_assert_cmpuint (requests, ==, 0);
  else
    g_assert_cmpuint (requests, >, 0);
}

static gboolean
permission_denied (const GError *error)
{
  return g_error_matches (error, G_DBUS_ERROR, G_DBUS_ERROR_ACCESS_DENIED) ||
    g_error_matches (error, FLATPAK_ERROR, FLATPAK_ERROR_PERMISSION_DENIED);
}

typedef struct { const char *ref; gboolean seen; } AuthorizationFailure;

static gboolean
authorization_error (FlatpakTransaction *tx, FlatpakTransactionOperation *operation,
                     const GError *error, FlatpakTransactionErrorDetails details,
                     AuthorizationFailure *failure)
{
  (void) tx; (void) details;
  TRACE_SIGNAL (FlatpakTransaction, "operation-error");
  g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_ref, operation), ==, failure->ref);
  g_assert_true (permission_denied (error));
  failure->seen = TRUE;
  g_print ("authorization-operation-error %s %d\n", g_quark_to_string (error->domain), error->code);
  return FALSE;
}

int blackbox_multiuser_main (int argc, char **argv);

int
blackbox_multiuser_main (int argc, char **argv)
{
  if (argc < 5 || strcmp (argv[1], "multiuser") != 0)
    return -1;
  g_assert_cmpuint (getuid (), ==, strtoul (argv[2], NULL, 10));
  g_assert_cmpuint (geteuid (), ==, getuid ());
  g_assert_cmpuint (getuid (), !=, 0);
  const char *op = argv[3];
  g_autoptr(FlatpakInstallation) inst = installation (argv[4]);
  GError *error = NULL;

  if (strcmp (op, "remote-snapshot") == 0)
    {
      g_autoptr(GPtrArray) remotes = CALL_API (flatpak_installation_list_remotes, inst, NULL, &error);
      g_assert_no_error (error);
      for (guint i = 0; i < remotes->len; i++)
        {
          FlatpakRemote *remote = g_ptr_array_index (remotes, i);
          g_autofree char *url = CALL_API (flatpak_remote_get_url, remote);
          g_print ("remote %s %s\n", CALL_API (flatpak_remote_get_name, remote), url);
        }
    }
  else if (strcmp (op, "remote-add") == 0)
    {
      g_assert_cmpint (argc, ==, 6);
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new, "fixture");
      CALL_API (flatpak_remote_set_url, remote, argv[5]);
      CALL_API (flatpak_remote_set_gpg_verify, remote, FALSE);
      g_assert_true (CALL_API (flatpak_installation_add_remote, inst, remote, FALSE, NULL, &error));
      g_assert_no_error (error);
    }
  else if (strcmp (op, "remote-modify") == 0 || strcmp (op, "remote-query") == 0)
    {
      g_assert_cmpint (argc, ==, 6);
      g_autoptr(FlatpakRemote) remote = CALL_API (
        flatpak_installation_get_remote_by_name, inst, "fixture", NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (remote);
      if (strcmp (op, "remote-modify") == 0)
        {
          CALL_API (flatpak_remote_set_url, remote, argv[5]);
          g_assert_true (CALL_API (flatpak_installation_modify_remote, inst, remote, NULL, &error));
          g_assert_no_error (error);
        }
      else
        {
          g_autofree char *url = CALL_API (flatpak_remote_get_url, remote);
          g_assert_cmpstr (url, ==, argv[5]);
        }
    }
  else if (strcmp (op, "remote-remove") == 0)
    {
      g_assert_true (CALL_API (flatpak_installation_remove_remote, inst, "fixture", NULL, &error));
      g_assert_no_error (error);
    }
  else if (strcmp (op, "expect") == 0)
    {
      g_assert_cmpint (argc, ==, 9);
      assert_ref (inst, argv[5], argv[6]);
      assert_ref (inst, argv[7], argv[8]);
      g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_installed_refs, inst, NULL, &error);
      g_assert_no_error (error);
      g_assert_cmpuint (refs->len, ==, (strcmp (argv[6], "-") != 0) + (strcmp (argv[8], "-") != 0));
    }
  else if (strcmp (op, "config-set") == 0 || strcmp (op, "config-check") == 0)
    {
      g_assert_cmpint (argc, ==, 6);
      if (strcmp (op, "config-set") == 0)
        g_assert_true (CALL_API (flatpak_installation_set_config_sync, inst, "languages", argv[5], NULL, &error));
      else
        {
          g_autofree char *value = CALL_API (flatpak_installation_get_config, inst, "languages", NULL, &error);
          g_assert_cmpstr (value, ==, argv[5]);
        }
      g_assert_no_error (error);
    }
  else if (g_str_has_prefix (op, "auth-"))
    {
      g_assert_cmpint (argc, ==, 9);
      gboolean inherited = strcmp (argv[5], "true") == 0;
      gboolean silent = inherited;
      CALL_API (flatpak_installation_set_no_interaction, inst, inherited);
      g_assert_cmpint (CALL_API (flatpak_installation_get_no_interaction, inst), ==, inherited);
      g_autoptr(FlatpakTransaction) tx = NULL;
      AuthorizationFailure failure = { argv[7], FALSE };
      if (strcmp (op, "auth-transaction") == 0)
        {
          tx = CALL_API (flatpak_transaction_new_for_installation, inst, NULL, &error);
          g_assert_no_error (error);
          g_assert_cmpint (CALL_API (flatpak_transaction_get_no_interaction, tx), ==, inherited);
          if (strcmp (argv[6], "inherit") != 0)
            {
              silent = strcmp (argv[6], "true") == 0;
              CALL_API (flatpak_transaction_set_no_interaction, tx, silent);
              g_assert_cmpint (CALL_API (flatpak_transaction_get_no_interaction, tx), ==, silent);
            }
          add_operation (tx, "uninstall", argv[7]);
          g_signal_connect (tx, "operation-error", G_CALLBACK (authorization_error), &failure);
        }
      g_autoptr(GDataInputStream) output = NULL;
      g_autoptr(GSubprocess) agent = start_agent (argv[8], &output);
      gboolean result = tx != NULL ? CALL_API (flatpak_transaction_run, tx, NULL, &error) :
        CALL_API (flatpak_installation_set_config_sync, inst, "languages", "fr", NULL, &error);
      stop_agent (agent, output, silent);
      g_assert_false (result);
      g_assert_nonnull (error);
      g_printerr ("expected authorization failure: %s\n", error->message);
      g_assert_true (permission_denied (error) ||
                     (failure.seen && g_error_matches (error, FLATPAK_ERROR, FLATPAK_ERROR_ABORTED)));
      g_clear_error (&error);
    }
  else if (strcmp (op, "install") == 0 || strcmp (op, "update") == 0 || strcmp (op, "uninstall") == 0)
    {
      g_assert_cmpint (argc, ==, 6);
      g_autoptr(FlatpakTransaction) tx = CALL_API (flatpak_transaction_new_for_installation, inst, NULL, &error);
      g_assert_no_error (error);
      CALL_API (flatpak_transaction_set_no_interaction, tx, TRUE);
      add_operation (tx, op, argv[5]);
      gboolean result = CALL_API (flatpak_transaction_run, tx, NULL, &error);
      if (error != NULL)
        g_printerr ("system transaction: %s\n", error->message);
      g_assert_no_error (error);
      g_assert_true (result);
    }
  else
    g_assert_not_reached ();
  g_print ("PASS multiuser %s\n", op);
  return 0;
}
