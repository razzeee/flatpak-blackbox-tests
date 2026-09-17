/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"
#include <string.h>

typedef struct
{
  unsigned int started;
} ContractTrace;

static FlatpakInstallation *
open_installation (const char *path)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(GFile) file = g_file_new_for_path (path);
  FlatpakInstallation *installation = CALL_API (flatpak_installation_new_for_path,
                                               file, TRUE, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installation);
  return installation;
}

static gboolean
plan (FlatpakTransaction *transaction, ContractTrace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "ready");
  (void) trace;
  GList *operations = CALL_API (flatpak_transaction_get_operations, transaction);
  for (GList *item = operations; item != NULL; item = item->next)
    {
      FlatpakTransactionOperation *op = item->data;
      const char *ref = CALL_API (flatpak_transaction_operation_get_ref, op);
      GPtrArray *causes = CALL_API (flatpak_transaction_operation_get_related_to_ops, op);
      g_print ("skip\t%s\t%d\n", ref,
               CALL_API (flatpak_transaction_operation_get_is_skipped, op));
      if (causes == NULL || causes->len == 0)
        g_print ("cause-free\t%s\n", ref);
      else
        for (size_t i = 0; i < causes->len; i++)
          {
            FlatpakTransactionOperation *cause = causes->pdata[i];
            g_print ("cause\t%s\t%s\t%d\n", ref,
                     CALL_API (flatpak_transaction_operation_get_ref, cause),
                     CALL_API (flatpak_transaction_operation_get_is_skipped, cause));
          }
      const char *remote = CALL_API (flatpak_transaction_operation_get_remote, op);
      GFile *bundle = CALL_API (flatpak_transaction_operation_get_bundle_path, op);
      g_autofree char *uri = bundle == NULL ? NULL : g_file_get_uri (bundle);
      const char *type = NULL;
      switch (CALL_API (flatpak_transaction_operation_get_operation_type, op))
        {
        case FLATPAK_TRANSACTION_OPERATION_INSTALL:
          type = "install";
          break;
        case FLATPAK_TRANSACTION_OPERATION_UPDATE:
          type = "update";
          break;
        case FLATPAK_TRANSACTION_OPERATION_INSTALL_BUNDLE:
          type = "install-bundle";
          break;
        case FLATPAK_TRANSACTION_OPERATION_UNINSTALL:
          type = "uninstall";
          break;
        default:
          g_assert_not_reached ();
        }
      if (bundle != NULL)
        g_assert_nonnull (uri);
      g_print ("op\t%s\t%s\t%s\t%s\n",
               CALL_API (flatpak_transaction_operation_get_ref, op),
               type, remote == NULL ? "-" : remote, bundle == NULL ? "-" : uri);
    }
  g_list_free_full (operations, g_object_unref);
  return TRUE;
}

static void
executing (FlatpakTransaction *transaction, FlatpakTransactionOperation *operation,
           FlatpakTransactionProgress *progress, ContractTrace *trace)
{
  TRACE_SIGNAL (FlatpakTransaction, "new-operation");
  g_autoptr(FlatpakTransactionOperation) current =
    CALL_API (flatpak_transaction_get_current_operation, transaction);
  (void) progress;
  g_assert_true (current == operation);
  trace->started++;
  g_print ("new\t%s\n", CALL_API (flatpak_transaction_operation_get_ref, current));
}

int
blackbox_transaction_contracts_main (int argc, char **argv)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakInstallation) installation = NULL;
  if (argc < 2 || strcmp (argv[1], "tx-contract") != 0)
    return -1;
  if (argc < 4)
    return 2;
  installation = open_installation (argv[2]);
  if (strcmp (argv[3], "updates") == 0 && argc == 4)
    {
      g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_installed_refs_for_update,
                                          installation, NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (refs);
      for (size_t i = 0; i < refs->len; i++)
        g_print ("update\t%s\n", CALL_API (flatpak_ref_format_ref_cached, refs->pdata[i]));
      return 0;
    }
  if (strcmp (argv[3], "signed-remote") == 0 && argc == 8)
    {
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new, "fixture");
      CALL_API (flatpak_remote_set_url, remote, argv[4]);
      CALL_API (flatpak_remote_set_gpg_verify, remote, TRUE);
      if (strcmp (argv[5], "-") != 0)
        {
          char *contents = NULL;
          size_t length = 0;
          g_assert_true (g_file_get_contents (argv[5], &contents, &length, &error));
          g_assert_no_error (error);
          g_autoptr(GBytes) key = g_bytes_new_take (contents, length);
          CALL_API (flatpak_remote_set_gpg_key, remote, key);
        }
      CALL_API (flatpak_remote_set_default_branch, remote,
                strcmp (argv[6], "-") == 0 ? NULL : argv[6]);
      CALL_API (flatpak_remote_set_collection_id, remote,
                strcmp (argv[7], "-") == 0 ? NULL : argv[7]);
      g_assert_true (CALL_API (flatpak_installation_modify_remote, installation,
                               remote, NULL, &error));
      g_assert_no_error (error);
      return 0;
    }
  if (strcmp (argv[3], "properties") == 0 || strcmp (argv[3], "settings") == 0 ||
      strcmp (argv[3], "branch-clear") == 0 || strcmp (argv[3], "collection-clear") == 0)
    {
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_installation_get_remote_by_name,
                                                installation, "fixture", NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (remote);
      if (strcmp (argv[3], "branch-clear") == 0 && argc == 4)
        CALL_API (flatpak_remote_set_default_branch, remote, NULL);
      else if (strcmp (argv[3], "collection-clear") == 0 && argc == 4)
        CALL_API (flatpak_remote_set_collection_id, remote, NULL);
      else if (strcmp (argv[3], "settings") == 0 && argc == 6)
        {
          CALL_API (flatpak_remote_set_default_branch, remote,
                    strcmp (argv[4], "-") == 0 ? NULL : argv[4]);
          CALL_API (flatpak_remote_set_collection_id, remote,
                    strcmp (argv[5], "-") == 0 ? NULL : argv[5]);
        }
      else if (strcmp (argv[3], "properties") != 0 || argc != 4)
        return 2;
      if (strcmp (argv[3], "properties") != 0)
        {
          g_assert_true (CALL_API (flatpak_installation_modify_remote, installation,
                                   remote, NULL, &error));
          g_assert_no_error (error);
        }
      g_autofree char *branch = CALL_API (flatpak_remote_get_default_branch, remote);
      g_autofree char *collection = CALL_API (flatpak_remote_get_collection_id, remote);
      g_print ("properties\t%d\t%s\t%s\n",
               CALL_API (flatpak_remote_get_gpg_verify, remote),
               branch == NULL ? "-" : branch, collection == NULL ? "-" : collection);
      return 0;
    }
  /* PATH exercise ACTION REFS SDK DEBUG NODEPS NORELATED PREVIOUS_IDS */
  if (strcmp (argv[3], "exercise") == 0 && argc == 11)
    {
      g_autoptr(FlatpakTransaction) transaction =
        CALL_API (flatpak_transaction_new_for_installation, installation, NULL, &error);
      g_assert_no_error (error);
      ContractTrace trace = { 0 };
      g_signal_connect (transaction, "ready", G_CALLBACK (plan), &trace);
      g_signal_connect (transaction, "new-operation", G_CALLBACK (executing), &trace);
      gboolean sdk = strcmp (argv[6], "1") == 0;
      gboolean debug = strcmp (argv[7], "1") == 0;
      CALL_API (flatpak_transaction_set_auto_install_sdk, transaction, sdk);
      CALL_API (flatpak_transaction_set_auto_install_debug, transaction, debug);
      g_assert_cmpint (CALL_API (flatpak_transaction_get_auto_install_sdk, transaction), ==, sdk);
      g_assert_cmpint (CALL_API (flatpak_transaction_get_auto_install_debug, transaction), ==, debug);
      CALL_API (flatpak_transaction_set_disable_dependencies, transaction, strcmp (argv[8], "1") == 0);
      CALL_API (flatpak_transaction_set_disable_related, transaction, strcmp (argv[9], "1") == 0);
      g_auto(GStrv) refs = g_strsplit (argv[5], ";", -1);
      g_auto(GStrv) previous = g_strsplit (argv[10], ";", -1);
      for (size_t i = 0; refs[i] != NULL; i++)
        {
          gboolean added = FALSE;
          if (strcmp (argv[4], "install") == 0 || strcmp (argv[4], "reject-install") == 0)
            added = CALL_API (flatpak_transaction_add_install, transaction, "fixture", refs[i],
                              NULL, &error);
          else if (strcmp (argv[4], "update") == 0)
            added = CALL_API (flatpak_transaction_add_update, transaction, refs[i], NULL, NULL, &error);
          else if (strcmp (argv[4], "uninstall") == 0)
            added = CALL_API (flatpak_transaction_add_uninstall, transaction, refs[i], &error);
          else if (strcmp (argv[4], "rebase") == 0)
            added = CALL_API (flatpak_transaction_add_rebase, transaction, "fixture", refs[i],
                              NULL, (const char **) previous, &error);
          g_assert_no_error (error);
          g_assert_true (added);
        }
      gboolean result = CALL_API (flatpak_transaction_run, transaction, NULL, &error);
      if (strcmp (argv[4], "reject-install") == 0)
        {
          g_assert_false (result);
          g_assert_nonnull (error);
          g_print ("rejected\t%s\t%d\t%s\n", g_quark_to_string (error->domain),
                   error->code, error->message);
          return 0;
        }
      g_assert_no_error (error);
      g_assert_true (result);
      g_print ("completed\t%u\n", trace.started);
      return 0;
    }
  if (strcmp (argv[3], "state") == 0 && argc == 4)
    {
      g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_installed_refs,
                                          installation, NULL, &error);
      g_assert_no_error (error);
      for (size_t i = 0; i < refs->len; i++)
        {
          FlatpakInstalledRef *ref = refs->pdata[i];
          g_print ("state\t%s\t%s\t%s\t%s\n",
                   CALL_API (flatpak_ref_format_ref_cached, FLATPAK_REF (ref)),
                   CALL_API (flatpak_ref_get_commit, FLATPAK_REF (ref)),
                   CALL_API (flatpak_installed_ref_get_origin, ref),
                   CALL_API (flatpak_installed_ref_get_deploy_dir, ref));
        }
      return 0;
    }
  if (strcmp (argv[3], "remote") == 0 && argc == 5)
    {
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new, "fixture");
      CALL_API (flatpak_remote_set_url, remote, argv[4]);
      CALL_API (flatpak_remote_set_gpg_verify, remote, FALSE);
      g_assert_true (CALL_API (flatpak_installation_modify_remote, installation,
                               remote, NULL, &error));
      g_assert_no_error (error);
      return 0;
    }
  if (strcmp (argv[3], "origin") == 0 && argc == 5)
    {
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_installation_get_remote_by_name,
                                                installation, argv[4], NULL, &error);
      g_assert_no_error (error);
      g_autofree char *url = CALL_API (flatpak_remote_get_url, remote);
      g_print ("%s\n", url);
      return 0;
    }
  if (strcmp (argv[3], "languages") == 0 && argc == 5)
    {
      g_assert_true (CALL_API (flatpak_installation_set_config_sync, installation,
                               "languages", argv[4], NULL, &error));
      g_assert_no_error (error);
      return 0;
    }
  /* PATH ACTION REMOTE REF SUBPATHS DISABLE_RELATED DEPENDENCY BUNDLE */
  if (argc != 10)
    return 2;
  g_autoptr(FlatpakTransaction) transaction =
    CALL_API (flatpak_transaction_new_for_installation, installation, NULL, &error);
  g_assert_no_error (error);
  ContractTrace trace = { 0 };
  g_signal_connect (transaction, "ready", G_CALLBACK (plan), &trace);
  g_signal_connect (transaction, "new-operation", G_CALLBACK (executing), &trace);
  CALL_API (flatpak_transaction_set_disable_related, transaction, strcmp (argv[7], "1") == 0);
  if (strcmp (argv[8], "-") != 0)
    {
      g_autoptr(FlatpakInstallation) dependency = open_installation (argv[8]);
      CALL_API (flatpak_transaction_add_dependency_source, transaction, dependency);
    }
  const char *empty[] = { NULL };
  const char *empty_string[] = { "", NULL };
  g_auto(GStrv) explicit = g_strsplit (argv[6], ";", -1);
  const char **subpaths = strcmp (argv[6], "null") == 0 ? NULL :
                         strcmp (argv[6], "empty") == 0 ? empty :
                         strcmp (argv[6], "empty-string") == 0 ? empty_string :
                         (const char **) explicit;
  gboolean added = FALSE;
  if (strcmp (argv[3], "install") == 0)
    added = CALL_API (flatpak_transaction_add_install, transaction, argv[4], argv[5], subpaths, &error);
  else if (strcmp (argv[3], "update") == 0)
    added = CALL_API (flatpak_transaction_add_update, transaction, argv[5], subpaths, NULL, &error);
  else if (strcmp (argv[3], "uninstall") == 0)
    added = CALL_API (flatpak_transaction_add_uninstall, transaction, argv[5], &error);
  else if (strcmp (argv[3], "bundle") == 0)
    {
      g_autoptr(GFile) bundle = g_file_new_for_path (argv[9]);
      added = CALL_API (flatpak_transaction_add_install_bundle, transaction, bundle, NULL, &error);
    }
  g_assert_no_error (error);
  g_assert_true (added);
  gboolean result = CALL_API (flatpak_transaction_run, transaction, NULL, &error);
  if (!result)
    {
      g_assert_nonnull (error);
      g_printerr ("%s\n", error->message);
      return 1;
    }
  g_assert_no_error (error);
  g_print ("completed\t%u\n", trace.started);
  return 0;
}
