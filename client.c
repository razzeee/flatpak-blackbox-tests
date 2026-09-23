/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* This client deliberately includes only the public library entry point. */
#include <flatpak.h>
#include <stdio.h>
#include <string.h>

#include "blackbox-features.h"
#include "client-extension.h"

typedef enum
{
  OP_UNKNOWN,
  OP_REMOTE,
  OP_INSTALL,
  OP_INSTALL_ABORT_READY,
  OP_DELETE_DATA,
  OP_UPDATE,
  OP_UNINSTALL,
  OP_QUERY,
  OP_LIST_REFS,
  OP_REMOTE_CREATE,
  OP_REMOTE_EDIT,
  OP_REMOTE_QUERY,
  OP_REMOTE_LIST,
  OP_REMOTE_DELETE,
  OP_REMOTE_CLEAR_TITLE,
  OP_REMOTE_REF_QUERY
} Operation;

static const struct
{
  const char *name;
  int argc;
  Operation operation;
} operations[] = {
  { "remote", 3, OP_REMOTE },
  { "install", 3, OP_INSTALL },
  { "install-abort-ready", 3, OP_INSTALL_ABORT_READY },
  { "delete-data", 4, OP_DELETE_DATA },
  { "update", 3, OP_UPDATE },
  { "uninstall", 3, OP_UNINSTALL },
  { "query", 3, OP_QUERY },
  { "list-refs", 3, OP_LIST_REFS },
  { "remote-create", 6, OP_REMOTE_CREATE },
  { "remote-edit", 6, OP_REMOTE_EDIT },
  { "remote-query", 3, OP_REMOTE_QUERY },
  { "remote-list", 2, OP_REMOTE_LIST },
  { "remote-delete", 3, OP_REMOTE_DELETE },
  { "remote-clear-title", 3, OP_REMOTE_CLEAR_TITLE },
  { "remote-ref-query", 4, OP_REMOTE_REF_QUERY }
};

static void
print_error (const GError *error)
{
  if (error != NULL)
    g_printerr ("error domain=%s code=%d message=%s\n",
                g_quark_to_string (error->domain), error->code, error->message);
  else
    g_printerr ("operation failed without a GError\n");
}

/* TSV protocol for controlled fixture strings; \N denotes a NULL title. */
static gboolean
print_remote (FlatpakRemote *remote,
              GError       **error)
{
  const char *name = CALL_API (flatpak_remote_get_name, remote);
  g_autofree char *url = CALL_API (flatpak_remote_get_url, remote);
  g_autofree char *title = CALL_API (flatpak_remote_get_title, remote);
  const char *fields[] = { name, url, title };

  for (size_t i = 0; i < G_N_ELEMENTS (fields); i++)
    if (fields[i] != NULL &&
        (strpbrk (fields[i], "\t\r\n") != NULL || strcmp (fields[i], "\\N") == 0))
      {
        g_set_error_literal (error, G_IO_ERROR, G_IO_ERROR_INVALID_DATA,
                             "remote property cannot be represented in fixture TSV");
        return FALSE;
      }

  g_print ("%s\t%s\t%s\t%d\n", name, url != NULL ? url : "",
           title != NULL ? title : "\\N", CALL_API (flatpak_remote_get_prio, remote));
  return TRUE;
}

static gboolean
ready (FlatpakTransaction *transaction,
       void               *data)
{
  (void) transaction;
  TRACE_SIGNAL (FlatpakTransaction, "ready");
  g_printerr ("signal ready\n");
  return !GPOINTER_TO_INT (data);
}

static void
new_operation (FlatpakTransaction          *transaction,
               FlatpakTransactionOperation *operation,
               FlatpakTransactionProgress  *progress,
               void                        *data)
{
  (void) transaction;
  (void) progress;
  (void) data;
  TRACE_SIGNAL (FlatpakTransaction, "new-operation");
  g_printerr ("signal new-operation ref=%s type=%s\n",
              CALL_API (flatpak_transaction_operation_get_ref, operation),
              CALL_API (flatpak_transaction_operation_type_to_string,
                        CALL_API (flatpak_transaction_operation_get_operation_type, operation)));
}

static void
operation_done (FlatpakTransaction          *transaction,
                FlatpakTransactionOperation *operation,
                const char                  *commit,
                FlatpakTransactionResult     details,
                void                        *data)
{
  (void) transaction;
  (void) data;
  TRACE_SIGNAL (FlatpakTransaction, "operation-done");
  g_printerr ("signal operation-done ref=%s commit=%s details=%u\n",
              CALL_API (flatpak_transaction_operation_get_ref, operation),
              commit != NULL ? commit : "", (unsigned int) details);
}

static gboolean
operation_error (FlatpakTransaction           *transaction,
                 FlatpakTransactionOperation  *operation,
                 const GError                 *error,
                 FlatpakTransactionErrorDetails details,
                 void                         *data)
{
  (void) transaction;
  (void) data;
  TRACE_SIGNAL (FlatpakTransaction, "operation-error");
  g_printerr ("signal operation-error ref=%s details=%u\n",
              CALL_API (flatpak_transaction_operation_get_ref, operation),
              (unsigned int) details);
  print_error (error);
  return FALSE;
}

int
main (int argc, char **argv)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakInstallation) installation = NULL;
  g_autoptr(FlatpakTransaction) transaction = NULL;
  gboolean added = FALSE;
  Operation operation = OP_UNKNOWN;
  int extension_result = blackbox_extension_main (argc, argv);

  if (extension_result >= 0)
    return extension_result;
  int expected_argc = 3;

  if (argc >= 2)
    for (size_t i = 0; i < G_N_ELEMENTS (operations); i++)
      if (strcmp (argv[1], operations[i].name) == 0)
        {
          operation = operations[i].operation;
          expected_argc = operations[i].argc;
          break;
        }

  if (argc < 2 || argc != expected_argc)
    {
      g_printerr ("usage: library-client OPERATION [ARGS...]\n"
                  "  remote|install|update|uninstall|query|list-refs ARG\n"
                  "  install-abort-ready REF\n"
                  "  delete-data APP_ID MODE\n"
                  "  remote-create|remote-edit NAME URL TITLE PRIORITY\n"
                  "  remote-query|remote-delete|remote-clear-title NAME\n"
                  "  remote-ref-query NAME REF\n"
                  "  remote-list\n");
      return 2;
    }

  installation = CALL_API (flatpak_installation_new_user, NULL, &error);
  if (installation == NULL)
    goto fail;

  if (operation == OP_REMOTE_CREATE || operation == OP_REMOTE_EDIT)
    {
      gboolean create = operation == OP_REMOTE_CREATE;
      g_autoptr(FlatpakRemote) remote = NULL;
      guint64 priority;

      if (!g_ascii_string_to_unsigned (argv[5], 10, 0, G_MAXINT, &priority, &error))
        goto fail;
      remote = create ? CALL_API (flatpak_remote_new, argv[2]) :
        CALL_API (flatpak_installation_get_remote_by_name, installation, argv[2], NULL, &error);
      if (remote == NULL)
        goto fail;
      CALL_API (flatpak_remote_set_url, remote, argv[3]);
      CALL_API (flatpak_remote_set_title, remote, argv[4]);
      CALL_API (flatpak_remote_set_prio, remote, (int) priority);
      if (create)
        {
          CALL_API (flatpak_remote_set_gpg_verify, remote, FALSE);
          if (!CALL_API (flatpak_installation_add_remote, installation, remote, FALSE, NULL, &error))
            goto fail;
        }
      else if (!CALL_API (flatpak_installation_modify_remote, installation, remote, NULL, &error))
        goto fail;
      return 0;
    }

  if (operation == OP_REMOTE_QUERY || operation == OP_REMOTE_CLEAR_TITLE)
    {
      g_autoptr(FlatpakRemote) remote =
        CALL_API (flatpak_installation_get_remote_by_name, installation, argv[2], NULL, &error);

      if (remote == NULL)
        goto fail;
      if (operation == OP_REMOTE_CLEAR_TITLE)
        {
          CALL_API (flatpak_remote_set_title, remote, NULL);
          if (!CALL_API (flatpak_installation_modify_remote, installation, remote, NULL, &error))
            goto fail;
        }
      else if (!print_remote (remote, &error))
        goto fail;
      return 0;
    }

  if (operation == OP_REMOTE_LIST)
    {
      g_autoptr(GPtrArray) remotes =
        CALL_API (flatpak_installation_list_remotes, installation, NULL, &error);

      if (remotes == NULL)
        goto fail;
      for (size_t i = 0; i < remotes->len; i++)
        if (!print_remote (g_ptr_array_index (remotes, i), &error))
          goto fail;
      return 0;
    }

  if (operation == OP_REMOTE_DELETE)
    {
      if (!CALL_API (flatpak_installation_remove_remote, installation, argv[2], NULL, &error))
        goto fail;
      return 0;
    }

  if (operation == OP_REMOTE_REF_QUERY)
    {
      g_autoptr(FlatpakRef) ref = CALL_API (flatpak_ref_parse, argv[3], &error);
      g_autoptr(FlatpakRemoteRef) remote_ref = NULL;
      g_autofree char *formatted = NULL;

      if (ref == NULL)
        goto fail;
      remote_ref = CALL_API (flatpak_installation_fetch_remote_ref_sync,
                            installation, argv[2], CALL_API (flatpak_ref_get_kind, ref),
                            CALL_API (flatpak_ref_get_name, ref),
                            CALL_API (flatpak_ref_get_arch, ref),
                            CALL_API (flatpak_ref_get_branch, ref), NULL, &error);
      if (remote_ref == NULL)
        goto fail;
      formatted = CALL_API (flatpak_ref_format_ref, FLATPAK_REF (remote_ref));
      g_print ("%s\n", formatted);
      return 0;
    }

  if (operation == OP_DELETE_DATA)
    {
      g_autoptr(GCancellable) cancellable = NULL;

      if (strcmp (argv[3], "cancel") == 0)
        {
          cancellable = g_cancellable_new ();
          g_cancellable_cancel (cancellable);
        }
#if BLACKBOX_HAVE_FLATPAK_USER_DATA_DELETE
      if (!CALL_API (flatpak_user_data_delete, argv[2], cancellable, &error))
        goto fail;
      return 0;
#else
      g_set_error_literal (&error, G_IO_ERROR, G_IO_ERROR_NOT_SUPPORTED,
                           "flatpak_user_data_delete is unavailable");
      goto fail;
#endif
    }

  if (operation == OP_LIST_REFS)
    {
      g_autoptr(GPtrArray) refs = NULL;

      refs = CALL_API (flatpak_installation_list_installed_refs, installation, NULL, &error);
      if (refs == NULL)
        goto fail;
      for (size_t i = 0; i < refs->len; i++)
        {
          g_autofree char *formatted = CALL_API (flatpak_ref_format_ref,
            FLATPAK_REF (g_ptr_array_index (refs, i)));

          g_print ("%s\n", formatted);
        }
      return 0;
    }

  if (operation == OP_REMOTE)
    {
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new, "fixture");

      CALL_API (flatpak_remote_set_url, remote, argv[2]);
      CALL_API (flatpak_remote_set_gpg_verify, remote, FALSE);
      if (!CALL_API (flatpak_installation_modify_remote, installation, remote, NULL, &error))
        goto fail;
      return 0;
    }

  if (operation == OP_QUERY)
    {
      g_autoptr(FlatpakRef) ref = CALL_API (flatpak_ref_parse, argv[2], &error);
      g_autoptr(FlatpakInstalledRef) installed = NULL;
      g_autofree char *formatted = NULL;

      if (ref == NULL)
        goto fail;
      installed = CALL_API (flatpak_installation_get_installed_ref,
                            installation, CALL_API (flatpak_ref_get_kind, ref),
                            CALL_API (flatpak_ref_get_name, ref),
                            CALL_API (flatpak_ref_get_arch, ref),
                            CALL_API (flatpak_ref_get_branch, ref), NULL, &error);
      if (installed == NULL)
        goto fail;
      formatted = CALL_API (flatpak_ref_format_ref, FLATPAK_REF (installed));
      g_print ("%s %s\n", formatted, CALL_API (flatpak_ref_get_commit, FLATPAK_REF (installed)));
      return 0;
    }

  transaction = CALL_API (flatpak_transaction_new_for_installation, installation, NULL, &error);
  if (transaction == NULL)
    goto fail;
  CALL_API (flatpak_transaction_set_no_interaction, transaction, TRUE);
  g_signal_connect (transaction, "ready", G_CALLBACK (ready),
                    GINT_TO_POINTER (operation == OP_INSTALL_ABORT_READY));
  g_signal_connect (transaction, "new-operation", G_CALLBACK (new_operation), NULL);
  g_signal_connect (transaction, "operation-done", G_CALLBACK (operation_done), NULL);
  g_signal_connect (transaction, "operation-error", G_CALLBACK (operation_error), NULL);

  if (operation == OP_INSTALL || operation == OP_INSTALL_ABORT_READY)
    added = CALL_API (flatpak_transaction_add_install, transaction, "fixture", argv[2], NULL, &error);
  else if (operation == OP_UPDATE)
    added = CALL_API (flatpak_transaction_add_update, transaction, argv[2], NULL, NULL, &error);
  else if (operation == OP_UNINSTALL)
    added = CALL_API (flatpak_transaction_add_uninstall, transaction, argv[2], &error);
  else
    {
      g_printerr ("unknown operation: %s\n", argv[1]);
      return 2;
    }
  if (!added || !CALL_API (flatpak_transaction_run, transaction, NULL, &error))
    goto fail;
  return 0;

fail:
  print_error (error);
  /* Client protocol statuses, not Flatpak's public enum numeric values. */
  if (g_error_matches (error, FLATPAK_ERROR, FLATPAK_ERROR_NOT_INSTALLED))
    return 3;
  if (g_error_matches (error, FLATPAK_ERROR, FLATPAK_ERROR_ALREADY_INSTALLED))
    return 4;
  if (g_error_matches (error, FLATPAK_ERROR, FLATPAK_ERROR_REF_NOT_FOUND))
    return 5;
  return 1;
}
