/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"
#include <stdint.h>
#include <string.h>

typedef struct
{
  const char *mode;
  GThread *thread;
  gboolean running;
  GList *operations;
  GList *next;
  GPtrArray *refs;
  FlatpakTransactionOperation *active;
  unsigned int started;
  unsigned int finished;
  unsigned int changed;
  uint64_t bytes;
  uint64_t start;
  char *status;
  char *status_copy;
  GCancellable *cancellable;
  const char *marker;
  int cancel_stop;
  GKeyFile *expected_sizes;
} Trace;

static const char *
text (const char *value)
{
  return value != NULL ? value : "-";
}

static void
in_run (Trace *trace)
{
  g_assert_true (trace->running);
  g_assert_true (trace->thread == g_thread_self ());
}

static void
print_metadata (const char *label, GKeyFile *metadata)
{
  if (metadata == NULL)
    g_print ("%s\t-\n", label);
  else
    {
      g_autofree char *data = g_key_file_to_data (metadata, NULL, NULL);
      g_autofree char *encoded = g_base64_encode ((const guchar *) data, strlen (data));
      g_print ("%s\t%s\n", label, encoded);
    }
}

static gboolean
pre_auth (FlatpakTransaction *transaction, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "ready-pre-auth");
  GList *operations = CALL_API (flatpak_transaction_get_operations, transaction);
  in_run (trace);
  g_print ("pre-auth\t%u\n", g_list_length (operations));
  for (GList *item = operations; item != NULL; item = item->next)
    {
      FlatpakTransactionOperation *op = item->data;
      g_assert_false (CALL_API (flatpak_transaction_operation_get_requires_authentication, op));
      g_print ("pre-ref\t%s\t%s\n",
               CALL_API (flatpak_transaction_operation_get_ref, op),
               text (CALL_API (flatpak_transaction_operation_get_commit, op)));
    }
  g_list_free_full (operations, g_object_unref);
  return strcmp (trace->mode, "abort-pre-auth") != 0;
}

static gboolean
ready (FlatpakTransaction *transaction, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "ready");
  in_run (trace);
  g_assert_null (trace->operations);
  trace->operations = CALL_API (flatpak_transaction_get_operations, transaction);
  trace->refs = g_ptr_array_new_with_free_func (g_free);
  trace->next = trace->operations;
  g_assert_cmpint (CALL_API (flatpak_transaction_is_empty, transaction), ==,
                   trace->operations == NULL);
  g_print ("ready\t%u\n", g_list_length (trace->operations));
  for (GList *item = trace->operations; item != NULL; item = item->next)
    {
      FlatpakTransactionOperation *op = item->data;
      GPtrArray *causes = CALL_API (flatpak_transaction_operation_get_related_to_ops, op);
      const char *ref = CALL_API (flatpak_transaction_operation_get_ref, op);
      const char *remote = CALL_API (flatpak_transaction_operation_get_remote, op);
      g_ptr_array_add (trace->refs, g_strdup (ref));
      g_autoptr(GError) error = NULL;
      if (strcmp (trace->mode, "rebase") != 0)
        {
          g_autoptr(FlatpakTransactionOperation) found =
            CALL_API (flatpak_transaction_get_operation_for_ref, transaction, remote, ref, &error);
          g_assert_no_error (error);
          g_assert_true (found == op);
        }
      g_assert_false (CALL_API (flatpak_transaction_operation_get_is_skipped, op));
      g_assert_null (CALL_API (flatpak_transaction_operation_get_bundle_path, op));
      if (strcmp (trace->mode, "sizes") == 0)
        {
          uint64_t download = 0, installed = 0;
          if (CALL_API (flatpak_transaction_operation_get_operation_type, op) !=
              FLATPAK_TRANSACTION_OPERATION_UNINSTALL)
            {
              g_assert_nonnull (trace->expected_sizes);
              download = g_key_file_get_uint64 (trace->expected_sizes, ref, "download", &error);
              g_assert_no_error (error);
              installed = g_key_file_get_uint64 (trace->expected_sizes, ref, "installed", &error);
              g_assert_no_error (error);
              g_assert_cmpuint (download, >, 0);
              g_assert_cmpuint (installed, >, 0);
            }
          g_assert_cmpuint (CALL_API (flatpak_transaction_operation_get_download_size, op), ==, download);
          g_assert_cmpuint (CALL_API (flatpak_transaction_operation_get_installed_size, op), ==, installed);
        }
      g_print ("op\t%s\t%s\t%d\t%s\t%" G_GUINT64_FORMAT "\t%" G_GUINT64_FORMAT "\n",
               ref, text (remote), CALL_API (flatpak_transaction_operation_get_operation_type, op),
               text (CALL_API (flatpak_transaction_operation_get_commit, op)),
               CALL_API (flatpak_transaction_operation_get_download_size, op),
               CALL_API (flatpak_transaction_operation_get_installed_size, op));
      print_metadata ("metadata", CALL_API (flatpak_transaction_operation_get_metadata, op));
      print_metadata ("old-metadata", CALL_API (flatpak_transaction_operation_get_old_metadata, op));
      g_assert_null (CALL_API (flatpak_transaction_operation_get_subpaths, op));
      for (size_t i = 0; causes != NULL && i < causes->len; i++)
        g_print ("cause\t%s\t%s\t%d\n", ref,
                 CALL_API (flatpak_transaction_operation_get_ref, causes->pdata[i]),
                 CALL_API (flatpak_transaction_operation_get_is_skipped, causes->pdata[i]));
    }
  return strcmp (trace->mode, "abort-ready") != 0 &&
         strcmp (trace->mode, "no-dependencies") != 0;
}

static void
changed (FlatpakTransactionProgress *progress, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransactionProgress, "changed");
  g_autofree char *status = CALL_API (flatpak_transaction_progress_get_status, progress);
  int percent = CALL_API (flatpak_transaction_progress_get_progress, progress);
  gboolean estimating = CALL_API (flatpak_transaction_progress_get_is_estimating, progress);
  uint64_t bytes = CALL_API (flatpak_transaction_progress_get_bytes_transferred, progress);
  uint64_t start = CALL_API (flatpak_transaction_progress_get_start_time, progress);
  in_run (trace);
  g_assert_nonnull (status);
  g_assert_cmpint (percent, >=, 0);
  g_assert_cmpint (percent, <=, 100);
  g_assert_true (estimating == TRUE || estimating == FALSE);
  if (strcmp (trace->mode, "progress") == 0)
    {
      g_assert_cmpuint (bytes, >=, trace->bytes);
      if (bytes > 0)
        {
          g_assert_cmpuint (start, >, 0);
          g_assert_cmpuint (start, <=, (uint64_t) g_get_monotonic_time ());
          if (trace->start != 0)
            g_assert_cmpuint (start, ==, trace->start);
        }
    }
  trace->bytes = bytes;
  trace->start = start;
  trace->changed++;
  if (strcmp (trace->mode, "rate") == 0 && start > 0)
    {
      uint64_t rate = CALL_API (flatpak_transaction_progress_get_bytes_per_second, progress);
      uint64_t elapsed = (uint64_t) g_get_monotonic_time () - start;
      if (elapsed < G_USEC_PER_SEC)
        g_assert_cmpuint (rate, ==, 0);
      g_print ("rate\t%" G_GUINT64_FORMAT "\t%" G_GUINT64_FORMAT "\n", elapsed, rate);
    }
  if (trace->status == NULL)
    {
      trace->status_copy = g_strdup (status);
      trace->status = g_steal_pointer (&status);
    }
  g_print ("progress\t%d\t%" G_GUINT64_FORMAT "\n", percent, bytes);
}

static void
new_operation (FlatpakTransaction *transaction, FlatpakTransactionOperation *operation,
               FlatpakTransactionProgress *progress, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "new-operation");
  g_autoptr(FlatpakTransactionOperation) current =
    CALL_API (flatpak_transaction_get_current_operation, transaction);
  in_run (trace);
  g_assert_null (trace->active);
  g_assert_nonnull (trace->next);
  g_assert_true (trace->next->data == operation);
  g_assert_true (current == operation);
  g_assert_nonnull (progress);
  trace->next = trace->next->next;
  trace->active = operation;
  trace->started++;
  trace->bytes = 0;
  trace->start = 0;
  guint interval = strcmp (trace->mode, "frequency-slow") == 0 ? 1000 : 50;
  CALL_API (flatpak_transaction_progress_set_update_frequency, progress, interval);
  g_signal_connect (progress, "changed", G_CALLBACK (changed), trace);
  g_print ("new\t%s\n", CALL_API (flatpak_transaction_operation_get_ref, operation));
}

static void
done (FlatpakTransaction *transaction, FlatpakTransactionOperation *operation,
      const char *commit, FlatpakTransactionResult details, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "operation-done");
  (void) transaction;
  in_run (trace);
  g_assert_true (trace->active == operation);
  if (CALL_API (flatpak_transaction_operation_get_operation_type, operation) !=
      FLATPAK_TRANSACTION_OPERATION_UNINSTALL)
    g_assert_cmpstr (commit, ==, CALL_API (flatpak_transaction_operation_get_commit, operation));
  g_print ("done\t%s\t%s\t%u\n",
           CALL_API (flatpak_transaction_operation_get_ref, operation), text (commit), details);
  trace->active = NULL;
  trace->finished++;
}

static gboolean
operation_error (FlatpakTransaction *transaction, FlatpakTransactionOperation *operation,
                 const GError *error, FlatpakTransactionErrorDetails details, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "operation-error");
  (void) transaction;
  in_run (trace);
  g_assert_true (trace->active == operation);
  g_assert_nonnull (error);
  g_assert_cmpuint (error->domain, !=, 0);
  g_assert_nonnull (error->message);
  g_assert_cmpstr (error->message, !=, "");
  g_assert_cmpuint (details & ~FLATPAK_TRANSACTION_ERROR_DETAILS_NON_FATAL, ==, 0);
  g_print ("operation-error\t%s\t%s\t%d\t%u\n",
           CALL_API (flatpak_transaction_operation_get_ref, operation),
           g_quark_to_string (error->domain), error->code, details);
  trace->active = NULL;
  trace->finished++;
  return strcmp (trace->mode, "continue") == 0;
}

static int
choose_remote (FlatpakTransaction *transaction, const char *app, const char *runtime,
               const char * const *remotes, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "choose-remote-for-ref");
  (void) transaction;
  in_run (trace);
  g_print ("choose\t%s\t%s", app, runtime);
  for (size_t i = 0; remotes[i] != NULL; i++)
    g_print ("\t%s", remotes[i]);
  g_print ("\n");
  return strcmp (trace->mode, "decline") == 0 ? -1 : 0;
}

static gboolean
add_remote (FlatpakTransaction *transaction, FlatpakTransactionRemoteReason reason,
            const char *from, const char *name, const char *url, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "add-new-remote");
  (void) transaction;
  /* Flatpakref additions can emit this while the request is added, before run. */
  g_assert_true (trace->thread == g_thread_self ());
  g_print ("add-remote\t%d\t%s\t%s\t%s\n", reason, from, name, url);
  return strcmp (trace->mode, "decline") != 0;
}

static void
eol (FlatpakTransaction *transaction, const char *ref, const char *reason,
     const char *rebase, Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "end-of-lifed");
  (void) transaction;
  in_run (trace);
  g_print ("eol\t%s\t%s\t%s\n", ref, text (reason), text (rebase));
}

static gboolean
eol_rebase (FlatpakTransaction *transaction, const char *remote, const char *ref,
            const char *reason, const char *replacement, const char **previous_ids,
            Trace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "end-of-lifed-with-rebase");
  g_autoptr(GError) error = NULL;
  in_run (trace);
  g_assert_cmpuint (trace->started, ==, 0);
  g_print ("eol-rebase\t%s\t%s\t%s\t%s", remote, ref, text (reason), text (replacement));
  for (size_t i = 0; previous_ids != NULL && previous_ids[i] != NULL; i++)
    g_print ("\t%s", previous_ids[i]);
  g_print ("\n");
  if (strcmp (trace->mode, "rebase") != 0)
    return FALSE;
  g_assert_nonnull (replacement);
  g_assert_true (CALL_API (flatpak_transaction_add_rebase_and_uninstall, transaction,
                           remote, replacement, ref, NULL, previous_ids, &error));
  g_assert_no_error (error);
  return TRUE;
}

static void *
cancel_when_requested (void *data)
{
  Trace *trace = data;
  while (!g_atomic_int_get (&trace->cancel_stop))
    {
      if (g_file_test (trace->marker, G_FILE_TEST_EXISTS))
        {
          g_cancellable_cancel (trace->cancellable);
          g_print ("cancelled-in-flight\n");
          break;
        }
      g_usleep (10000);
    }
  return NULL;
}

static void
options (FlatpakTransaction *transaction)
{
#define ROUNDTRIP(name) \
  CALL_API (flatpak_transaction_set_##name, transaction, TRUE); \
  g_assert_true (CALL_API (flatpak_transaction_get_##name, transaction)); \
  CALL_API (flatpak_transaction_set_##name, transaction, FALSE); \
  g_assert_false (CALL_API (flatpak_transaction_get_##name, transaction))
  ROUNDTRIP (no_pull);
  ROUNDTRIP (no_deploy);
  ROUNDTRIP (no_interaction);
  ROUNDTRIP (auto_install_sdk);
  ROUNDTRIP (auto_install_debug);
  ROUNDTRIP (include_unused_uninstall_ops);
#undef ROUNDTRIP
  g_assert_null (CALL_API (flatpak_transaction_get_parent_window, transaction));
  CALL_API (flatpak_transaction_set_parent_window, transaction, "x11:1234");
  g_assert_cmpstr (CALL_API (flatpak_transaction_get_parent_window, transaction), ==, "x11:1234");
  CALL_API (flatpak_transaction_set_parent_window, transaction, "wayland:fixture");
  g_assert_cmpstr (CALL_API (flatpak_transaction_get_parent_window, transaction), ==, "wayland:fixture");
  CALL_API (flatpak_transaction_set_parent_window, transaction, NULL);
  g_assert_null (CALL_API (flatpak_transaction_get_parent_window, transaction));
}

int
blackbox_transactions_main (int argc, char **argv)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakInstallation) installation = NULL;
  g_autoptr(FlatpakInstallation) retained = NULL;
  g_autoptr(FlatpakTransaction) transaction = NULL;
  g_autoptr(GFile) path = NULL;
  g_autoptr(GFile) retained_path = NULL;
  g_autoptr(GCancellable) cancellable = g_cancellable_new ();
  g_autoptr(GKeyFile) expected_sizes = NULL;
  GThread *cancel_thread = NULL;
  Trace trace = { 0 };
  gboolean result = FALSE;

  if (argc < 2 || (strcmp (argv[1], "tx-run") != 0 && strcmp (argv[1], "tx-pins") != 0))
    return -1;
  if (argc == 3 && strcmp (argv[1], "tx-pins") == 0)
    {
      g_autoptr(GPtrArray) pins = NULL;
      installation = CALL_API (flatpak_installation_new_user, NULL, &error);
      g_assert_no_error (error);
      pins = CALL_API (flatpak_installation_list_pinned_refs, installation, argv[2], NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (pins);
      for (size_t i = 0; i < pins->len; i++)
        g_print ("%s\n", CALL_API (flatpak_ref_format_ref_cached, pins->pdata[i]));
      return 0;
    }
  if ((argc != 7 && argc != 8) || strcmp (argv[1], "tx-run") != 0)
    return 2;
  trace.mode = argv[2];
  if (argc == 8)
    {
      if (strcmp (trace.mode, "sizes") != 0)
        return 2;
      expected_sizes = g_key_file_new ();
      g_assert_true (g_key_file_load_from_data (expected_sizes, argv[7], -1,
                                               G_KEY_FILE_NONE, &error));
      g_assert_no_error (error);
      trace.expected_sizes = expected_sizes;
    }
  trace.thread = g_thread_self ();
  installation = CALL_API (flatpak_installation_new_user, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installation);
  transaction = CALL_API (flatpak_transaction_new_for_installation, installation, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (transaction);
  retained = CALL_API (flatpak_transaction_get_installation, transaction);
  path = CALL_API (flatpak_installation_get_path, installation);
  retained_path = CALL_API (flatpak_installation_get_path, retained);
  g_assert_true (g_file_equal (path, retained_path));
  g_assert_true (CALL_API (flatpak_installation_get_is_user, retained));
  options (transaction);
  if (strcmp (trace.mode, "download") == 0 || strcmp (trace.mode, "no-deploy") == 0)
    CALL_API (flatpak_transaction_set_no_deploy, transaction, TRUE);
  if (strcmp (trace.mode, "local") == 0)
    CALL_API (flatpak_transaction_set_no_pull, transaction, TRUE);
  if (strcmp (trace.mode, "no-dependencies") == 0)
    CALL_API (flatpak_transaction_set_disable_dependencies, transaction, TRUE);
  if (strcmp (trace.mode, "no-pin") == 0)
    CALL_API (flatpak_transaction_set_disable_auto_pin, transaction, TRUE);
  g_assert_cmpint (CALL_API (flatpak_transaction_get_no_deploy, transaction), ==,
                   strcmp (trace.mode, "download") == 0 || strcmp (trace.mode, "no-deploy") == 0);
  g_assert_cmpint (CALL_API (flatpak_transaction_get_no_pull, transaction), ==,
                   strcmp (trace.mode, "local") == 0);
  g_signal_connect (transaction, "ready-pre-auth", G_CALLBACK (pre_auth), &trace);
  g_signal_connect (transaction, "ready", G_CALLBACK (ready), &trace);
  g_signal_connect (transaction, "new-operation", G_CALLBACK (new_operation), &trace);
  g_signal_connect (transaction, "operation-done", G_CALLBACK (done), &trace);
  g_signal_connect (transaction, "operation-error", G_CALLBACK (operation_error), &trace);
  g_signal_connect (transaction, "choose-remote-for-ref", G_CALLBACK (choose_remote), &trace);
  g_signal_connect (transaction, "add-new-remote", G_CALLBACK (add_remote), &trace);
  g_signal_connect (transaction, "end-of-lifed", G_CALLBACK (eol), &trace);
  g_signal_connect (transaction, "end-of-lifed-with-rebase", G_CALLBACK (eol_rebase), &trace);
  if (strcmp (argv[3], "install") == 0)
    result = CALL_API (flatpak_transaction_add_install, transaction, argv[4], argv[5], NULL, &error);
  else if (strcmp (argv[3], "update") == 0)
    result = CALL_API (flatpak_transaction_add_update, transaction, argv[5], NULL,
                       strcmp (argv[6], "-") == 0 || strcmp (trace.mode, "cancel") == 0
                       ? NULL : argv[6], &error);
  else if (strcmp (argv[3], "update-install") == 0)
    {
      result = CALL_API (flatpak_transaction_add_update, transaction, argv[5], NULL, NULL, &error);
      if (result)
        result = CALL_API (flatpak_transaction_add_install, transaction, argv[4], argv[6], NULL, &error);
    }
  else if (strcmp (argv[3], "rebase") == 0 || strcmp (argv[3], "rebase-null") == 0)
    {
      g_auto(GStrv) fields = g_strsplit (argv[5], "/", -1);
      const char *previous_ids[] = { fields[1], NULL };
      result = CALL_API (flatpak_transaction_add_rebase_and_uninstall, transaction,
                         argv[4], argv[6], argv[5], NULL,
                         strcmp (argv[3], "rebase-null") == 0 ? NULL : previous_ids, &error);
    }
  else if (strcmp (argv[3], "uninstall") == 0)
    result = CALL_API (flatpak_transaction_add_uninstall, transaction, argv[5], &error);
  else if (strcmp (argv[3], "flatpakref") == 0)
    {
      g_autoptr(GBytes) bytes = g_bytes_new (argv[5], strlen (argv[5]));
      result = CALL_API (flatpak_transaction_add_install_flatpakref, transaction, bytes, &error);
    }
  else if (strcmp (argv[3], "empty") == 0)
    result = TRUE;
  else if (strcmp (argv[3], "lookup") == 0)
    {
      const char *remotes[] = { argv[4], argv[6] };
      CALL_API (flatpak_transaction_set_reinstall, transaction, TRUE);
      for (size_t i = 0; i < G_N_ELEMENTS (remotes); i++)
        {
          if (i == 0)
            g_assert_true (CALL_API (flatpak_transaction_add_uninstall, transaction, argv[5], &error));
          else
            g_assert_true (CALL_API (flatpak_transaction_add_install, transaction,
                                     remotes[i], argv[5], NULL, &error));
          if (i == 0)
            {
              g_autoptr(FlatpakTransactionOperation) unique =
                CALL_API (flatpak_transaction_get_operation_for_ref, transaction, NULL, argv[5], &error);
              g_assert_no_error (error);
              g_assert_nonnull (unique);
              g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_remote, unique), ==, remotes[0]);
              g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_ref, unique), ==, argv[5]);
            }
        }
      g_assert_no_error (error);
      for (size_t i = 0; i < G_N_ELEMENTS (remotes); i++)
        {
          g_autoptr(FlatpakTransactionOperation) op =
            CALL_API (flatpak_transaction_get_operation_for_ref, transaction, remotes[i], argv[5], &error);
          g_assert_no_error (error);
          g_assert_nonnull (op);
          g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_ref, op), ==, argv[5]);
          g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_remote, op), ==, remotes[i]);
        }
      g_assert_null (CALL_API (flatpak_transaction_get_operation_for_ref, transaction,
                               NULL, argv[5], &error));
      g_assert_nonnull (error);
      g_clear_error (&error);
      g_assert_null (CALL_API (flatpak_transaction_get_operation_for_ref, transaction,
                               "absent-remote", argv[5], &error));
      g_assert_nonnull (error);
      g_clear_error (&error);
      g_assert_null (CALL_API (flatpak_transaction_get_operation_for_ref, transaction,
                               NULL, "app/org.flatpak.Absent/x86_64/test", &error));
      g_assert_nonnull (error);
      g_print ("result\t1\t0\t0\n");
      return 0;
    }
  else
    return 2;
  if (result)
    {
      if (strcmp (trace.mode, "cancel") == 0)
        {
          trace.cancellable = cancellable;
          trace.marker = argv[6];
          cancel_thread = g_thread_new ("cancel-download", cancel_when_requested, &trace);
        }
      trace.running = TRUE;
      result = CALL_API (flatpak_transaction_run, transaction, cancellable, &error);
      trace.running = FALSE;
      g_atomic_int_set (&trace.cancel_stop, TRUE);
      if (cancel_thread != NULL)
        g_thread_join (cancel_thread);
    }
  g_assert_null (trace.active);
  g_assert_cmpuint (trace.started, ==, trace.finished);
  if (result)
    {
      g_assert_no_error (error);
      g_assert_null (trace.next);
    }
  else
    {
      g_assert_nonnull (error);
      g_print ("error\t%s\t%d\n", g_quark_to_string (error->domain), error->code);
    }
  g_clear_object (&transaction);
  g_clear_object (&installation);
  g_clear_object (&retained_path);
  retained_path = CALL_API (flatpak_installation_get_path, retained);
  g_assert_true (g_file_equal (path, retained_path));
  size_t index = 0;
  for (GList *item = trace.operations; item != NULL; item = item->next, index++)
    g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_ref, item->data), ==,
                     trace.refs->pdata[index]);
  g_list_free_full (trace.operations, g_object_unref);
  g_clear_pointer (&trace.refs, g_ptr_array_unref);
  if (trace.status != NULL)
    g_assert_cmpstr (trace.status, ==, trace.status_copy);
  g_free (trace.status);
  g_free (trace.status_copy);
  g_print ("result\t%d\t%u\t%u\n", result, trace.started, trace.changed);
  return result ? 0 : 1;
}
