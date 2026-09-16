/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"

#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define ALT_PATH "/var/lib/flatpak-selector-alt"
#define USER_PATH "/root/.local/share/flatpak"
#define CONTROL_PATH "/tmp/selector-unreachable"
#define REPOSITORY_A "file:///tmp/system-selector-fixtures/A"
#define REPOSITORY_B "file:///tmp/system-selector-fixtures/B"

static FlatpakInstallation *
open_installation (const char *scope)
{
  GError *error = NULL;
  FlatpakInstallation *installation;

  if (strcmp (scope, "system") == 0)
    installation = CALL_API (flatpak_installation_new_system, NULL, &error);
  else if (strcmp (scope, "user") == 0)
    installation = CALL_API (flatpak_installation_new_user, NULL, &error);
  else
    installation = CALL_API (flatpak_installation_new_system_with_id, scope, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installation);
  return installation;
}

static void
identity (FlatpakInstallation *installation, const char *path,
          const char *id, gboolean user)
{
  GFile *file = CALL_API (flatpak_installation_get_path, installation);
  g_autofree char *actual = g_file_get_path (file);

  g_assert_cmpstr (actual, ==, path);
  g_assert_cmpstr (CALL_API (flatpak_installation_get_id, installation), ==, id);
  g_assert_cmpint (CALL_API (flatpak_installation_get_is_user, installation), ==, user);
}

static void
add_remote (FlatpakInstallation *installation, const char *url)
{
  GError *error = NULL;
  g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new, "fixture");

  CALL_API (flatpak_remote_set_url, remote, url);
  CALL_API (flatpak_remote_set_gpg_verify, remote, FALSE);
  g_assert_true (CALL_API (flatpak_installation_add_remote, installation, remote,
                           FALSE, NULL, &error));
  g_assert_no_error (error);
}

static gboolean
ready (FlatpakTransaction *transaction, gpointer data)
{
  (void) transaction;
  (void) data;
  return TRUE;
}

static void
transaction (FlatpakInstallation *installation, const char *operation,
             const char *ref, gboolean default_sources)
{
  GError *error = NULL;
  g_autoptr(FlatpakTransaction) transaction =
    CALL_API (flatpak_transaction_new_for_installation, installation, NULL, &error);

  g_assert_no_error (error);
  g_assert_nonnull (transaction);
  g_assert_true (CALL_API (flatpak_transaction_get_installation, transaction) == installation);
  CALL_API (flatpak_transaction_set_no_interaction, transaction, TRUE);
  if (default_sources)
    CALL_API (flatpak_transaction_add_default_dependency_sources, transaction);
  g_signal_connect (transaction, "ready", G_CALLBACK (ready), NULL);
  if (strcmp (operation, "install") == 0)
    g_assert_true (CALL_API (flatpak_transaction_add_install, transaction, "fixture", ref, NULL, &error));
  else if (strcmp (operation, "update") == 0)
    g_assert_true (CALL_API (flatpak_transaction_add_update, transaction, ref, NULL, NULL, &error));
  else
    g_assert_true (CALL_API (flatpak_transaction_add_uninstall, transaction, ref, &error));
  g_assert_no_error (error);
  if (!CALL_API (flatpak_transaction_run, transaction, NULL, &error))
    {
      /* Preserve the real diagnostic for environment-block classification. */
      g_printerr ("system transaction: %s\n", error ? error->message : "failed without GError");
      exit (1);
    }
  g_assert_no_error (error);
}

static FlatpakInstalledRef *
query (FlatpakInstallation *installation, const char *full_ref, const char *commit)
{
  GError *error = NULL;
  g_autoptr(FlatpakRef) ref = CALL_API (flatpak_ref_parse, full_ref, &error);
  FlatpakInstalledRef *installed;

  g_assert_no_error (error);
  installed = CALL_API (flatpak_installation_get_installed_ref, installation,
                        CALL_API (flatpak_ref_get_kind, ref),
                        CALL_API (flatpak_ref_get_name, ref),
                        CALL_API (flatpak_ref_get_arch, ref),
                        CALL_API (flatpak_ref_get_branch, ref), NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installed);
  g_autofree char *formatted = CALL_API (flatpak_ref_format_ref, FLATPAK_REF (installed));
  g_assert_cmpstr (formatted, ==, full_ref);
  g_assert_cmpstr (CALL_API (flatpak_ref_get_commit, FLATPAK_REF (installed)), ==, commit);
  g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_origin, installed), ==, "fixture");
  return installed;
}

static void
assert_query (FlatpakInstallation *installation, const char *ref, const char *commit)
{
  g_autoptr(FlatpakInstalledRef) installed = query (installation, ref, commit);
}

static void
assert_absent (FlatpakInstallation *installation, const char *full_ref)
{
  GError *error = NULL;
  g_autoptr(FlatpakRef) ref = CALL_API (flatpak_ref_parse, full_ref, &error);
  g_assert_no_error (error);
  g_autoptr(FlatpakInstalledRef) installed =
    CALL_API (flatpak_installation_get_installed_ref, installation,
              CALL_API (flatpak_ref_get_kind, ref), CALL_API (flatpak_ref_get_name, ref),
              CALL_API (flatpak_ref_get_arch, ref), CALL_API (flatpak_ref_get_branch, ref), NULL, &error);
  g_assert_null (installed);
  g_assert_error (error, FLATPAK_ERROR, FLATPAK_ERROR_NOT_INSTALLED);
  g_clear_error (&error);
}

static void
assert_kind (FlatpakInstallation *installation, FlatpakRefKind kind, const char *expected)
{
  GError *error = NULL;
  g_autoptr(GPtrArray) refs =
    CALL_API (flatpak_installation_list_installed_refs_by_kind, installation, kind, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (refs);
  g_assert_cmpuint (refs->len, ==, expected ? 1 : 0);
  if (expected)
    {
      g_autofree char *formatted = CALL_API (flatpak_ref_format_ref, g_ptr_array_index (refs, 0));
      g_assert_cmpstr (formatted, ==, expected);
    }
}

static void
assert_system_installations (const char *system_path, gboolean control_reachable)
{
  GError *error = NULL;
  g_autoptr(GPtrArray) installations = CALL_API (flatpak_get_system_installations, NULL, &error);
  gboolean have_system = FALSE, have_alt = FALSE, have_control = FALSE;

  g_assert_no_error (error);
  g_assert_nonnull (installations);
  g_assert_cmpuint (installations->len, ==, control_reachable ? 3 : 2);
  for (size_t i = 0; i < installations->len; i++)
    {
      FlatpakInstallation *installation = g_ptr_array_index (installations, i);
      const char *id = CALL_API (flatpak_installation_get_id, installation);

      if (strcmp (id, "default") == 0)
        {
          identity (installation, system_path, "default", FALSE);
          have_system = TRUE;
        }
      else if (strcmp (id, "alt") == 0)
        {
          identity (installation, ALT_PATH, "alt", FALSE);
          have_alt = TRUE;
        }
      else if (strcmp (id, "unreachable") == 0)
        {
          identity (installation, CONTROL_PATH, "unreachable", FALSE);
          have_control = TRUE;
        }
      else
        g_assert_not_reached ();
    }
  g_assert_true (have_system && have_alt);
  g_assert_cmpint (have_control, ==, control_reachable);
}

int
blackbox_system_main (int argc, char **argv)
{
  if (argc < 2 || !g_str_has_prefix (argv[1], "system-"))
    return -1;
  g_assert_cmpint (argc, ==, 7);
  g_assert_cmpint (getuid (), ==, 0);
  g_assert_null (g_getenv ("FLATPAK_SYSTEM_DIR"));
  g_assert_null (g_getenv ("FLATPAK_CONFIG_DIR"));
  const char *system_path = g_getenv ("BLACKBOX_SYSTEM_INSTALL_DIR");
  const char *config_path = g_getenv ("BLACKBOX_SYSTEM_CONFIG_DIR");
  g_assert_nonnull (system_path);
  g_assert_nonnull (config_path);
  g_assert_true (g_path_is_absolute (system_path));
  g_assert_true (g_path_is_absolute (config_path));
  g_assert_true (g_file_test (config_path, G_FILE_TEST_IS_DIR));
  const char *command = argv[1];
  const char *app = argv[2];
  const char *runtime = argv[3];
  const char *a = argv[4];
  const char *b = argv[5];
  const char *runtime_commit = argv[6];
  g_autoptr(FlatpakInstallation) system = open_installation ("system");
  g_autoptr(FlatpakInstallation) alt = open_installation ("alt");
  g_autoptr(FlatpakInstallation) user = open_installation ("user");

  identity (system, system_path, "default", FALSE);
  identity (alt, ALT_PATH, "alt", FALSE);
  identity (user, USER_PATH, "user", TRUE);

  if (strcmp (command, "system-identity") == 0)
    {
      GError *error = NULL;
      g_autoptr(FlatpakInstallation) absent =
        CALL_API (flatpak_installation_new_system_with_id, "missing-selector", NULL, &error);
      g_assert_null (absent);
      g_assert_nonnull (error);
      g_clear_error (&error);
    }
  else if (strcmp (command, "system-metadata") == 0)
    {
      g_assert_cmpstr (CALL_API (flatpak_installation_get_display_name, alt), ==, "Selector alternate");
      g_assert_cmpint (CALL_API (flatpak_installation_get_priority, alt), ==, 25);
      g_assert_cmpint (CALL_API (flatpak_installation_get_storage_type, alt), ==, FLATPAK_STORAGE_TYPE_NETWORK);
    }
  else if (strcmp (command, "system-enumeration") == 0)
    {
      GError *error = NULL;
      g_autoptr(GFile) path = g_file_new_for_path (CONTROL_PATH);
      g_autoptr(GFile) saved = g_file_new_for_path ("/tmp/selector-reachable-control");

      {
        g_autoptr(FlatpakInstallation) control = open_installation ("unreachable");
        identity (control, CONTROL_PATH, "unreachable", FALSE);
        assert_system_installations (system_path, TRUE);
      }
      /* Replace only the public, configured installation path. Moving the
       * reachable directory needs no knowledge of its implementation's layout. */
      g_assert_true (g_file_move (path, saved, G_FILE_COPY_NONE, NULL, NULL, NULL, &error));
      g_assert_no_error (error);
      g_assert_true (g_file_set_contents (CONTROL_PATH, "obstructed installation\n", -1, &error));
      g_assert_no_error (error);
      g_assert_true (g_file_test (CONTROL_PATH, G_FILE_TEST_IS_REGULAR));
      g_autoptr(FlatpakInstallation) rejected =
        CALL_API (flatpak_installation_new_system_with_id, "unreachable", NULL, &error);
      g_printerr ("control-constructor rejected=%s error=%s\n",
                  rejected == NULL ? "yes" : "no", error ? error->message : "none");
      /* Observe enumeration as well, even if the constructor accepted the
       * obstructed path. Both public outcomes must satisfy the contract. */
      assert_system_installations (system_path, FALSE);
      g_assert_null (rejected);
      g_assert_nonnull (error);
      g_clear_error (&error);
    }
  else if (strcmp (command, "system-dependency-sources") == 0)
    {
      add_remote (user, REPOSITORY_A);
      add_remote (system, REPOSITORY_A);
      add_remote (alt, REPOSITORY_A);
      transaction (user, "install", runtime, FALSE);
      transaction (system, "install", app, TRUE);
      /* A user runtime is not an eligible default dependency source. */
      assert_query (system, runtime, runtime_commit);
      assert_query (system, app, a);
      transaction (system, "uninstall", app, FALSE);
      transaction (system, "uninstall", runtime, FALSE);
      transaction (alt, "install", runtime, FALSE);
      transaction (system, "install", app, TRUE);
      /* The named system runtime satisfies the same dependency without copying. */
      assert_absent (system, runtime);
      assert_query (system, app, a);
      assert_query (alt, runtime, runtime_commit);
      assert_query (user, runtime, runtime_commit);
    }
  else
    {
      add_remote (system, REPOSITORY_A);
      add_remote (alt, REPOSITORY_B);
      add_remote (user, REPOSITORY_B);
      transaction (system, "install", app, FALSE);
      transaction (alt, "install", app, FALSE);
      transaction (user, "install", app, FALSE);
      assert_query (system, app, a);
      assert_query (alt, app, b);
      assert_query (user, app, b);
      if (strcmp (command, "system-profile-isolation") == 0)
        {
          /* A fresh object still selects its own deployment. */
          g_autoptr(FlatpakInstallation) reopened = open_installation ("system");
          assert_query (reopened, app, a);
        }
      else if (strcmp (command, "system-custom-path") == 0)
        {
          GError *error = NULL;
          g_autoptr(GFile) path = g_file_new_for_path (ALT_PATH);
          g_autoptr(FlatpakInstallation) custom =
            CALL_API (flatpak_installation_new_for_path, path, FALSE, NULL, &error);
          g_assert_no_error (error);
          g_assert_false (CALL_API (flatpak_installation_get_is_user, custom));
          g_assert_true (g_file_equal (CALL_API (flatpak_installation_get_path, custom), path));
          g_autoptr(GPtrArray) refs =
            CALL_API (flatpak_installation_list_installed_refs, custom, NULL, &error);
          g_assert_no_error (error);
          g_assert_cmpuint (refs->len, ==, 2);
          assert_kind (custom, FLATPAK_REF_KIND_APP, app);
          assert_kind (custom, FLATPAK_REF_KIND_RUNTIME, runtime);
          assert_query (custom, app, b);
          assert_query (system, app, a);
        }
      else if (strcmp (command, "system-update") == 0)
        {
          GError *error = NULL;
          g_autoptr(FlatpakRemote) remote =
            CALL_API (flatpak_installation_get_remote_by_name, system, "fixture", NULL, &error);
          g_assert_no_error (error);
          CALL_API (flatpak_remote_set_url, remote, REPOSITORY_B);
          g_assert_true (CALL_API (flatpak_installation_modify_remote, system, remote, NULL, &error));
          g_assert_no_error (error);
          transaction (system, "update", app, FALSE);
          assert_query (system, app, b);
          assert_query (system, runtime, runtime_commit);
          assert_query (user, app, b);
          assert_query (alt, app, b);
        }
      else if (strcmp (command, "system-query-objects") == 0)
        {
          assert_kind (alt, FLATPAK_REF_KIND_APP, app);
          assert_kind (alt, FLATPAK_REF_KIND_RUNTIME, runtime);
          GError *error = NULL;
          g_autoptr(FlatpakInstalledRef) ref = query (alt, app, b);
          g_autoptr(GBytes) bytes = CALL_API (flatpak_installed_ref_load_metadata, ref, NULL, &error);
          g_assert_no_error (error);
          g_assert_nonnull (bytes);
          g_autoptr(GKeyFile) metadata = g_key_file_new ();
          g_assert_true (g_key_file_load_from_bytes (metadata, bytes, G_KEY_FILE_NONE, &error));
          g_assert_no_error (error);
          g_autofree char *command_value = g_key_file_get_string (metadata, "Application", "command", &error);
          g_assert_no_error (error);
          g_assert_cmpstr (command_value, ==, "blackbox-probe");
          g_autofree char *runtime_value = g_key_file_get_string (metadata, "Application", "runtime", &error);
          g_assert_no_error (error);
          g_assert_cmpstr (runtime_value, ==, runtime + strlen ("runtime/"));
          g_auto(GStrv) groups = g_key_file_get_groups (metadata, NULL);
          g_assert_cmpuint (g_strv_length (groups), ==, 1);
          g_assert_cmpstr (groups[0], ==, "Application");
          g_auto(GStrv) keys = g_key_file_get_keys (metadata, "Application", NULL, &error);
          g_assert_no_error (error);
          g_assert_cmpuint (g_strv_length (keys), ==, 4);
          g_autoptr(FlatpakRef) parsed = CALL_API (flatpak_ref_parse, app, &error);
          g_assert_no_error (error);
          g_autofree char *name_value = g_key_file_get_string (metadata, "Application", "name", &error);
          g_assert_no_error (error);
          g_assert_cmpstr (name_value, ==, CALL_API (flatpak_ref_get_name, parsed));
          g_autofree char *sdk_value = g_key_file_get_string (metadata, "Application", "sdk", &error);
          g_assert_no_error (error);
          g_assert_cmpstr (sdk_value, ==, runtime_value);
          g_assert_true (g_str_has_prefix (CALL_API (flatpak_installed_ref_get_deploy_dir, ref), ALT_PATH "/"));
          transaction (alt, "uninstall", app, FALSE);
          assert_kind (alt, FLATPAK_REF_KIND_APP, NULL);
          assert_kind (alt, FLATPAK_REF_KIND_RUNTIME, runtime);
          transaction (alt, "uninstall", runtime, FALSE);
          assert_kind (alt, FLATPAK_REF_KIND_RUNTIME, NULL);
          assert_query (system, app, a);
          assert_query (user, app, b);
        }
      else
        g_assert_not_reached ();
    }
  g_print ("PASS %s\n", command);
  return 0;
}
