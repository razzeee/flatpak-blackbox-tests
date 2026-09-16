/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"
#include <stdint.h>
#include <string.h>

int blackbox_lifecycle_extra_main (int argc, char **argv);

static char *
value (GKeyFile *data, const char *key)
{
  g_autoptr(GError) error = NULL;
  char *result = g_key_file_get_string (data, "lifecycle", key, &error);
  g_assert_no_error (error);
  g_assert_nonnull (result);
  return result;
}

static void
identity (FlatpakRef *ref, const char *name, const char *commit)
{
  g_assert_nonnull (ref);
  g_autofree char *actual = CALL_API (flatpak_ref_format_ref, ref);
  g_assert_cmpstr (actual, ==, name);
  g_assert_cmpstr (CALL_API (flatpak_ref_get_commit, ref), ==, commit);
}

static FlatpakInstalledRef *
installed (FlatpakInstallation *installation, const char *name, gboolean present)
{
  g_autoptr(GError) error = NULL;
  g_auto(GStrv) parts = g_strsplit (name, "/", -1);
  FlatpakInstalledRef *result = CALL_API (flatpak_installation_get_installed_ref,
      installation, g_str_equal (parts[0], "app") ? FLATPAK_REF_KIND_APP : FLATPAK_REF_KIND_RUNTIME,
      parts[1], parts[2], parts[3], NULL, &error);
  if (present)
    {
      g_assert_no_error (error);
      g_assert_nonnull (result);
    }
  else
    {
      g_assert_null (result);
      g_assert_error (error, FLATPAK_ERROR, FLATPAK_ERROR_NOT_INSTALLED);
    }
  return result;
}

static void
same_file (const char *actual, const char *expected)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *a = NULL;
  g_autofree char *b = NULL;
  size_t alen, blen;
  g_assert_true (g_file_get_contents (actual, &a, &alen, &error));
  g_assert_no_error (error);
  g_assert_true (g_file_get_contents (expected, &b, &blen, &error));
  g_assert_no_error (error);
  g_assert_cmpmem (a, alen, b, blen);
}

G_GNUC_BEGIN_IGNORE_DEPRECATIONS
static void
bundle (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *path = value (data, "bundle");
  g_autofree char *ref = value (data, "ref");
  g_autofree char *commit = value (data, "commit");
  g_autoptr(GFile) file = g_file_new_for_path (path);
  if (g_str_equal (action, "invalid"))
    {
      g_autoptr(FlatpakBundleRef) parsed = CALL_API (flatpak_bundle_ref_new, file, &error);
      g_assert_null (parsed);
      g_assert_nonnull (error);
      g_clear_error (&error);
      g_autoptr(FlatpakInstalledRef) result = CALL_API (flatpak_installation_install_bundle,
          installation, file, NULL, NULL, NULL, &error);
      g_assert_null (result);
      g_assert_nonnull (error);
      g_clear_error (&error);
      g_autoptr(FlatpakTransaction) transaction = CALL_API (
          flatpak_transaction_new_for_installation, installation, NULL, &error);
      g_assert_no_error (error);
      if (CALL_API (flatpak_transaction_add_install_bundle, transaction, file, NULL, &error))
        {
          g_assert_no_error (error);
          g_assert_false (CALL_API (flatpak_transaction_run, transaction, NULL, &error));
        }
      g_assert_nonnull (error);
      installed (installation, ref, FALSE);
      return;
    }
  if (g_str_equal (action, "direct"))
    {
      g_autoptr(FlatpakInstalledRef) result = CALL_API (flatpak_installation_install_bundle,
          installation, file, NULL, NULL, NULL, &error);
      g_assert_no_error (error);
      identity (FLATPAK_REF (result), ref, commit);
      g_autoptr(FlatpakInstalledRef) repeated = CALL_API (flatpak_installation_install_bundle,
          installation, file, NULL, NULL, NULL, &error);
      g_assert_null (repeated);
      g_assert_error (error, FLATPAK_ERROR, FLATPAK_ERROR_ALREADY_INSTALLED);
    }
  else
    {
      g_autoptr(FlatpakTransaction) transaction = CALL_API (
          flatpak_transaction_new_for_installation, installation, NULL, &error);
      g_assert_no_error (error);
      g_autoptr(GBytes) key = NULL;
      if (g_str_equal (action, "explicit-key"))
        {
          g_autofree char *key_path = value (data, "key");
          char *contents = NULL;
          size_t length;
          g_assert_true (g_file_get_contents (key_path, &contents, &length, &error));
          g_assert_no_error (error);
          key = g_bytes_new_take (contents, length);
        }
      g_assert_true (CALL_API (flatpak_transaction_add_install_bundle,
          transaction, file, key, &error));
      g_assert_no_error (error);
      gboolean success = CALL_API (flatpak_transaction_run, transaction, NULL, &error);
      g_assert_no_error (error);
      g_assert_true (success);
    }
  g_autoptr(FlatpakInstalledRef) queried = installed (installation, ref, TRUE);
  identity (FLATPAK_REF (queried), ref, commit);
}

static void
direct (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *ref = value (data, "ref");
  g_auto(GStrv) parts = g_strsplit (ref, "/", -1);
  FlatpakRefKind kind = g_str_equal (parts[0], "app") ? FLATPAK_REF_KIND_APP : FLATPAK_REF_KIND_RUNTIME;
  if (g_str_equal (action, "uninstall"))
    {
      g_assert_true (CALL_API (flatpak_installation_uninstall_full, installation,
          FLATPAK_UNINSTALL_FLAGS_NO_PRUNE | FLATPAK_UNINSTALL_FLAGS_NO_TRIGGERS,
          kind, parts[1], parts[2], parts[3], NULL, NULL, NULL, &error));
      g_assert_no_error (error);
      installed (installation, ref, FALSE);
      return;
    }
  g_autoptr(FlatpakInstalledRef) result = NULL;
  if (g_str_equal (action, "update"))
    result = CALL_API (flatpak_installation_update_full, installation,
        FLATPAK_UPDATE_FLAGS_NO_TRIGGERS, kind, parts[1], parts[2], parts[3],
        NULL, NULL, NULL, NULL, &error);
  else
    result = CALL_API (flatpak_installation_install_full, installation,
        g_str_equal (action, "pull") ? FLATPAK_INSTALL_FLAGS_NO_DEPLOY :
        (g_str_equal (action, "local") || g_str_equal (action, "local-missing"))
        ? FLATPAK_INSTALL_FLAGS_NO_PULL : FLATPAK_INSTALL_FLAGS_NO_TRIGGERS,
        "lifecycle", kind, parts[1], parts[2], parts[3], NULL, NULL, NULL, NULL, &error);
  if (g_str_equal (action, "pull"))
    {
      g_assert_null (result);
      g_assert_error (error, FLATPAK_ERROR, FLATPAK_ERROR_ONLY_PULLED);
      installed (installation, ref, FALSE);
    }
  else if (g_str_equal (action, "local-missing"))
    {
      g_assert_null (result);
      g_assert_nonnull (error);
      installed (installation, ref, FALSE);
    }
  else
    {
      g_assert_no_error (error);
      g_autofree char *commit = value (data, "commit");
      identity (FLATPAK_REF (result), ref, commit);
    }
}
G_GNUC_END_IGNORE_DEPRECATIONS

static void
cleanup (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *ref = value (data, "ref");
  if (g_str_equal (action, "remove") || g_str_equal (action, "protected"))
    {
      gboolean result = CALL_API (flatpak_installation_remove_local_ref_sync,
          installation, "lifecycle", ref, NULL, &error);
      if (g_str_equal (action, "protected"))
        {
          g_assert_false (result);
          g_assert_nonnull (error);
          g_autoptr(FlatpakInstalledRef) deployed = installed (installation, ref, TRUE);
          g_autofree char *commit = value (data, "commit");
          identity (FLATPAK_REF (deployed), ref, commit);
          return;
        }
      g_assert_true (result);
    }
  else if (g_str_equal (action, "prune"))
    g_assert_true (CALL_API (flatpak_installation_prune_local_repo, installation, NULL, &error));
  else
    g_assert_true (CALL_API (flatpak_installation_cleanup_local_refs_sync, installation, NULL, &error));
  g_assert_no_error (error);
}

static void
metadata (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *ref = value (data, "ref");
  g_autoptr(FlatpakInstalledRef) local = installed (installation, ref, TRUE);
  if (g_str_equal (action, "rating") || g_str_equal (action, "missing-rating"))
    {
      gboolean missing = g_str_equal (action, "missing-rating");
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_version, local), ==,
                       missing ? NULL : "1.2.3");
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_license, local), ==,
                       missing ? NULL : "MIT");
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_content_rating_type, local), ==,
                       missing ? NULL : "oars-1.1");
      g_autoptr(GHashTable) rating = CALL_API (flatpak_installed_ref_get_appdata_content_rating, local);
      if (missing)
        g_assert_null (rating);
      else
        {
          g_assert_nonnull (rating);
          g_assert_cmpuint (g_hash_table_size (rating), ==, 1);
          g_assert_cmpstr (g_hash_table_lookup (rating, "violence-cartoon"), ==, "none");
        }
      return;
    }
  g_auto(GStrv) parts = g_strsplit (ref, "/", -1);
  g_autoptr(FlatpakRemoteRef) remote = CALL_API (flatpak_installation_fetch_remote_ref_sync,
      installation, "lifecycle", FLATPAK_REF_KIND_APP, parts[1], parts[2], parts[3], NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (remote);
  g_autofree char *reason = value (data, "reason");
  g_autofree char *rebase = value (data, "rebase");
  g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_eol, local), ==, *reason ? reason : NULL);
  g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_eol_rebase, local), ==, *rebase ? rebase : NULL);
  g_assert_cmpstr (CALL_API (flatpak_remote_ref_get_eol, remote), ==, *reason ? reason : NULL);
  g_assert_cmpstr (CALL_API (flatpak_remote_ref_get_eol_rebase, remote), ==, *rebase ? rebase : NULL);
}

static void
runtime_instance (GKeyFile *data)
{
  g_autofree char *id = value (data, "instance");
  g_autofree char *runtime = value (data, "runtime");
  g_autofree char *commit = value (data, "runtime_commit");
  g_autoptr(GPtrArray) instances = CALL_API (flatpak_instance_get_all, );
  size_t found = 0;
  for (size_t i = 0; i < instances->len; i++)
    {
      FlatpakInstance *instance = g_ptr_array_index (instances, i);
      if (!g_str_equal (CALL_API (flatpak_instance_get_id, instance), id))
        continue;
      found++;
      g_assert_true (CALL_API (flatpak_instance_is_running, instance));
      g_assert_null (CALL_API (flatpak_instance_get_app, instance));
      g_assert_cmpstr (CALL_API (flatpak_instance_get_runtime, instance), ==, runtime);
      g_assert_cmpstr (CALL_API (flatpak_instance_get_runtime_commit, instance), ==, commit);
    }
  g_assert_cmpuint (found, ==, 1);
}

static void
ref_set (GPtrArray *refs, const char *expected)
{
  g_auto(GStrv) names = g_strsplit (expected, ";", -1);
  size_t count = *expected ? g_strv_length (names) : 0;
  g_assert_nonnull (refs);
  g_assert_cmpuint (refs->len, ==, count);
  for (size_t i = 0; i < count; i++)
    {
      size_t matches = 0;
      for (size_t j = 0; j < refs->len; j++)
        {
          FlatpakInstalledRef *ref = g_ptr_array_index (refs, j);
          g_assert_true (FLATPAK_IS_INSTALLED_REF (ref));
          g_autofree char *formatted = CALL_API (flatpak_ref_format_ref, FLATPAK_REF (ref));
          matches += g_str_equal (formatted, names[i]);
        }
      g_assert_cmpuint (matches, ==, 1);
    }
}

static void
unused_pinned (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *arch = value (data, "arch");
  g_autofree char *unused = value (data, "unused");
  g_autofree char *pinned = value (data, "pinned");
  g_autofree char *app = value (data, "usage_app");
  g_autofree char *sdk = value (data, "usage_sdk");
  g_autofree char *runtime = value (data, "usage_runtime");
  g_autofree char *app_commit = value (data, "usage_app_commit");
  g_autofree char *sdk_commit = value (data, "usage_sdk_commit");
  g_autoptr(FlatpakInstalledRef) app_ref = installed (installation, app, TRUE);
  g_autoptr(FlatpakInstalledRef) sdk_ref = installed (installation, sdk, TRUE);
  identity (FLATPAK_REF (app_ref), app, app_commit);
  identity (FLATPAK_REF (sdk_ref), sdk, sdk_commit);
  g_autoptr(GBytes) metadata = CALL_API (flatpak_installed_ref_load_metadata,
      app_ref, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (metadata);
  g_autofree char *expected_path = value (data, "usage_metadata");
  g_autofree char *expected = NULL;
  size_t expected_length;
  g_assert_true (g_file_get_contents (expected_path, &expected, &expected_length, &error));
  g_assert_no_error (error);
  g_assert_cmpmem (g_bytes_get_data (metadata, NULL), g_bytes_get_size (metadata),
                   expected, expected_length);
  g_autoptr(GKeyFile) replacement = g_key_file_new ();
  g_assert_true (g_key_file_load_from_data (replacement, expected, expected_length,
                                           G_KEY_FILE_NONE, &error));
  g_assert_no_error (error);
  g_autofree char *declared_sdk = g_key_file_get_string (replacement, "Application", "sdk", &error);
  g_assert_no_error (error);
  g_autofree char *declared_runtime = g_key_file_get_string (replacement, "Application", "runtime", &error);
  g_assert_no_error (error);
  g_assert_true (g_str_has_prefix (sdk, "runtime/"));
  g_assert_true (g_str_has_prefix (runtime, "runtime/"));
  g_assert_cmpstr (declared_sdk, ==, sdk + strlen ("runtime/"));
  g_assert_cmpstr (declared_runtime, ==, runtime + strlen ("runtime/"));
  g_assert_cmpstr (declared_sdk, !=, declared_runtime);
  g_autoptr(GPtrArray) unused_refs = CALL_API (flatpak_installation_list_unused_refs,
      installation, *arch ? arch : NULL, NULL, &error);
  g_assert_no_error (error);
  ref_set (unused_refs, unused);
  g_autoptr(GPtrArray) pinned_refs = CALL_API (flatpak_installation_list_pinned_refs,
      installation, *arch ? arch : NULL, NULL, &error);
  g_assert_no_error (error);
  ref_set (pinned_refs, pinned);
  if (*arch == '\0')
    {
      g_assert_true (g_key_file_remove_key (replacement, "Application", "sdk", &error));
      g_assert_no_error (error);
      g_autoptr(GHashTable) injection = g_hash_table_new (g_str_hash, g_str_equal);
      g_hash_table_insert (injection, app, replacement);
      g_autoptr(GPtrArray) without_sdk = CALL_API (flatpak_installation_list_unused_refs_with_options,
          installation, NULL, injection, NULL, NULL, &error);
      g_assert_no_error (error);
      g_autofree char *counterfactual = g_strconcat (unused, ";", sdk, NULL);
      ref_set (without_sdk, counterfactual);
      g_autoptr(GPtrArray) afterward = CALL_API (flatpak_installation_list_unused_refs,
          installation, NULL, NULL, &error);
      g_assert_no_error (error);
      ref_set (afterward, unused);
      g_autoptr(GBytes) after_metadata = CALL_API (flatpak_installed_ref_load_metadata,
          app_ref, NULL, &error);
      g_assert_no_error (error);
      g_assert_true (g_bytes_equal (metadata, after_metadata));
    }
}

static void
changed (GFileMonitor *monitor, GFile *file, GFile *other,
         GFileMonitorEvent event, void *user_data)
{
  gboolean *observed = user_data;
  (void) monitor;
  (void) file;
  (void) other;
  (void) event;
  *observed = TRUE;
}

static void
monitor_changes (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(GFileMonitor) monitor = CALL_API (flatpak_installation_create_monitor,
      installation, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (monitor);
  gboolean observed = FALSE;
  g_signal_connect (monitor, "changed", G_CALLBACK (changed), &observed);
  direct (installation, data, action);
  int64_t deadline = g_get_monotonic_time () + 10 * G_TIME_SPAN_SECOND;
  while (!observed && g_get_monotonic_time () < deadline)
    {
      while (g_main_context_iteration (NULL, FALSE))
        ;
      if (!observed)
        g_usleep (10000);
    }
  g_assert_true (observed);
  g_assert_true (g_file_monitor_cancel (monitor));
}

static void
force_uninstall (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *ref = value (data, "ref");
  g_autoptr(FlatpakTransaction) transaction = CALL_API (
      flatpak_transaction_new_for_installation, installation, NULL, &error);
  g_assert_no_error (error);
  CALL_API (flatpak_transaction_set_force_uninstall, transaction, g_str_equal (action, "force"));
  g_assert_true (CALL_API (flatpak_transaction_add_uninstall, transaction, ref, &error));
  g_assert_no_error (error);
  gboolean success = CALL_API (flatpak_transaction_run, transaction, NULL, &error);
  g_assert_no_error (error);
  g_assert_true (success);
  installed (installation, ref, FALSE);
}

static void
image (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *ref = value (data, "ref");
  g_autofree char *origin = NULL;
  for (size_t i = 0; i < 2; i++)
    {
      g_autofree char *key = g_strdup_printf ("image_%s", i == 0 ? "A" : "B");
      g_autofree char *location = value (data, key);
      g_autoptr(FlatpakTransaction) transaction = CALL_API (
          flatpak_transaction_new_for_installation, installation, NULL, &error);
      g_assert_no_error (error);
      if (i != 0)
        CALL_API (flatpak_transaction_set_reinstall, transaction, TRUE);
      g_assert_true (CALL_API (flatpak_transaction_add_install_image, transaction, location, &error));
      g_assert_no_error (error);
      gboolean success = CALL_API (flatpak_transaction_run, transaction, NULL, &error);
      g_assert_no_error (error);
      g_assert_true (success);
      g_autoptr(FlatpakInstalledRef) local = installed (installation, ref, TRUE);
      const char *current_origin = CALL_API (flatpak_installed_ref_get_origin, local);
      g_assert_nonnull (current_origin);
      if (i == 0)
        origin = g_strdup (current_origin);
      else
        g_assert_cmpstr (current_origin, ==, origin);
      g_autoptr(GPtrArray) remotes = CALL_API (flatpak_installation_list_remotes, installation, NULL, &error);
      g_assert_no_error (error);
      g_assert_cmpuint (remotes->len, ==, 2); /* Runtime source plus image origin. */
      g_autofree char *payload_key = g_strdup_printf ("payload_%s", i == 0 ? "A" : "B");
      g_autofree char *expected = value (data, payload_key);
      g_autofree char *actual = g_build_filename (
          CALL_API (flatpak_installed_ref_get_deploy_dir, local), "files/bin/blackbox-probe", NULL);
      same_file (actual, expected);
    }
}

static void
sideload (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *ref = value (data, "ref");
  g_autofree char *commit = value (data, "commit");
  if (g_str_equal (action, "query"))
    {
      g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_remote_refs_sync_full,
          installation, "lifecycle", FLATPAK_QUERY_FLAGS_ONLY_SIDELOADED, NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (refs);
      g_assert_cmpuint (refs->len, ==, 1);
      identity (g_ptr_array_index (refs, 0), ref, commit);
    }
  else
    {
      g_autofree char *path = value (data, "sideload");
      g_autoptr(FlatpakTransaction) transaction = CALL_API (
          flatpak_transaction_new_for_installation, installation, NULL, &error);
      g_assert_no_error (error);
      const char *remote_name = g_str_equal (action, "image") ? "lifecycle-oci" : "lifecycle";
      if (g_str_equal (action, "image"))
        {
          g_assert_true (CALL_API (flatpak_transaction_add_sideload_image_collection,
              transaction, path, NULL, &error));
          g_assert_no_error (error);
          g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_installation_get_remote_by_name,
              installation, remote_name, NULL, &error);
          g_assert_no_error (error);
          g_autofree char *collection = CALL_API (flatpak_remote_get_collection_id, remote);
          g_assert_null (collection);
        }
      else
        CALL_API (flatpak_transaction_add_sideload_repo, transaction, path);
      g_assert_true (CALL_API (flatpak_transaction_add_install, transaction, remote_name, ref, NULL, &error));
      g_assert_no_error (error);
      gboolean success = CALL_API (flatpak_transaction_run, transaction, NULL, &error);
      g_assert_no_error (error);
      g_assert_true (success);
      g_autoptr(FlatpakInstalledRef) local = installed (installation, ref, TRUE);
      if (g_str_equal (action, "image"))
        {
          g_autofree char *actual = g_build_filename (
              CALL_API (flatpak_installed_ref_get_deploy_dir, local), "files/bin/blackbox-probe", NULL);
          g_autofree char *expected = value (data, "payload_A");
          same_file (actual, expected);
          g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_origin, local), ==, remote_name);
        }
      else
        identity (FLATPAK_REF (local), ref, commit);
    }
}

int
blackbox_lifecycle_extra_main (int argc, char **argv)
{
  const char * const supported[] = {
    "lifex-bundle", "lifex-direct", "lifex-cleanup", "lifex-metadata",
    "lifex-instance", "lifex-pinned", "lifex-monitor", "lifex-force",
    "lifex-image", "lifex-sideload", "lifex-triggers", NULL
  };
  if (argc < 2 || !g_strv_contains (supported, argv[1]))
    return -1;
  g_assert_cmpint (argc, ==, 4);
  g_autoptr(GError) error = NULL;
  g_autoptr(GKeyFile) data = g_key_file_new ();
  g_assert_true (g_key_file_load_from_file (data, argv[2], G_KEY_FILE_NONE, &error));
  g_assert_no_error (error);
  g_autoptr(FlatpakInstallation) installation = CALL_API (flatpak_installation_new_user, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installation);
  if (g_str_equal (argv[1], "lifex-bundle"))
    bundle (installation, data, argv[3]);
  else if (g_str_equal (argv[1], "lifex-direct"))
    direct (installation, data, argv[3]);
  else if (g_str_equal (argv[1], "lifex-cleanup"))
    cleanup (installation, data, argv[3]);
  else if (g_str_equal (argv[1], "lifex-metadata"))
    metadata (installation, data, argv[3]);
  else if (g_str_equal (argv[1], "lifex-instance"))
    runtime_instance (data);
  else if (g_str_equal (argv[1], "lifex-pinned"))
    unused_pinned (installation, data);
  else if (g_str_equal (argv[1], "lifex-monitor"))
    monitor_changes (installation, data, argv[3]);
  else if (g_str_equal (argv[1], "lifex-force"))
    force_uninstall (installation, data, argv[3]);
  else if (g_str_equal (argv[1], "lifex-image"))
    image (installation, data);
  else if (g_str_equal (argv[1], "lifex-sideload"))
    sideload (installation, data, argv[3]);
  else if (g_str_equal (argv[1], "lifex-triggers"))
    {
      g_assert_true (CALL_API (flatpak_installation_run_triggers, installation, NULL, &error));
      g_assert_no_error (error);
    }
  else
    g_assert_not_reached ();
  return 0;
}
