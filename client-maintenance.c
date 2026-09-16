/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"

#include <string.h>

typedef struct
{
  const char *app;
  const char *runtime;
  gboolean install;
  gboolean ready;
} Expected;

static gboolean
ready (FlatpakTransaction *transaction, Expected *expected)
{
  TRACE_SIGNAL (FlatpakTransaction, "ready");
  GList *operations = CALL_API (flatpak_transaction_get_operations, transaction);
  gboolean app_seen = FALSE;
  gboolean runtime_seen = FALSE;

  expected->ready = TRUE;
  g_assert_cmpuint (g_list_length (operations), ==, expected->install ? 2 : 1);
  for (GList *item = operations; item != NULL; item = item->next)
    {
      FlatpakTransactionOperation *operation = item->data;
      const char *ref = CALL_API (flatpak_transaction_operation_get_ref, operation);

      g_assert_cmpint (CALL_API (flatpak_transaction_operation_get_operation_type, operation),
                       ==, expected->install ? FLATPAK_TRANSACTION_OPERATION_INSTALL
                                             : FLATPAK_TRANSACTION_OPERATION_UNINSTALL);
      if (strcmp (ref, expected->app) == 0)
        {
          g_assert_false (app_seen);
          app_seen = TRUE;
        }
      else
        {
          g_assert_cmpstr (ref, ==, expected->runtime);
          g_assert_false (runtime_seen);
          runtime_seen = TRUE;
        }
    }
  g_list_free_full (operations, g_object_unref);
  g_assert_true (app_seen);
  g_assert_cmpint (runtime_seen, ==, expected->install);
  return TRUE;
}

int
blackbox_maintenance_main (int argc, char **argv)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakInstallation) installation = NULL;
  g_autoptr(FlatpakTransaction) transaction = NULL;
  Expected expected = { 0 };

  if (argc < 2 || strcmp (argv[1], "maintenance-sync") != 0)
    return -1;
  g_assert_cmpint (argc, ==, 5);
  g_assert_cmpstr (argv[1], ==, "maintenance-sync");
  g_assert_true (strcmp (argv[2], "install") == 0 || strcmp (argv[2], "remove") == 0);
  expected.install = strcmp (argv[2], "install") == 0;
  expected.app = argv[3];
  expected.runtime = argv[4];
  installation = CALL_API (flatpak_installation_new_system, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installation);
  transaction = CALL_API (flatpak_transaction_new_for_installation,
                          installation, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (transaction);
  CALL_API (flatpak_transaction_set_no_interaction, transaction, TRUE);
  g_signal_connect (transaction, "ready", G_CALLBACK (ready), &expected);
  g_assert_true (CALL_API (flatpak_transaction_add_sync_preinstalled, transaction, &error));
  g_assert_no_error (error);
  if (!CALL_API (flatpak_transaction_run, transaction, NULL, &error))
    {
      g_printerr ("maintenance sync: %s\n", error ? error->message : "no error detail");
      return 1;
    }
  g_assert_no_error (error);
  g_assert_true (expected.ready);
  g_print ("PASS maintenance-sync\n");
  return 0;
}
