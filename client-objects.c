/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"

#include <stdint.h>
#include <string.h>

#define REF "app/org.example.Objects/x86_64/stable"
#define URL "https://objects.example/repo"
#define URL_EDIT "https://objects.example/edited"
#define COMMIT "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

/* These fixtures use only public, introspectable construct properties. */
static FlatpakInstallation *
open_user (void)
{
  GError *error = NULL;
  FlatpakInstallation *installation = CALL_API (flatpak_installation_new_user, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installation);
  return installation;
}

static FlatpakRemote *
lookup (FlatpakInstallation *installation, const char *name)
{
  GError *error = NULL;
  FlatpakRemote *remote = CALL_API (flatpak_installation_get_remote_by_name,
                                  installation, name, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (remote);
  return remote;
}

static FlatpakRemote *
reopen_remote (const char *name)
{
  g_autoptr(FlatpakInstallation) installation = open_user ();
  return lookup (installation, name);
}

static void
absent (FlatpakInstallation *installation, const char *name)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_installation_get_remote_by_name,
                                            installation, name, NULL, &error);
  g_assert_null (remote);
  g_assert_nonnull (error);
}

static void
save (FlatpakInstallation *installation, FlatpakRemote *remote)
{
  GError *error = NULL;
  g_assert_true (CALL_API (flatpak_installation_modify_remote, installation,
                          remote, NULL, &error));
  g_assert_no_error (error);
}

static FlatpakRemote *
add (FlatpakInstallation *installation, const char *name, int priority)
{
  GError *error = NULL;
  FlatpakRemote *remote = CALL_API (flatpak_remote_new, name);
  CALL_API (flatpak_remote_set_url, remote, URL);
  CALL_API (flatpak_remote_set_title, remote, "Original title");
  CALL_API (flatpak_remote_set_gpg_verify, remote, FALSE);
  CALL_API (flatpak_remote_set_prio, remote, priority);
  g_assert_true (CALL_API (flatpak_installation_add_remote, installation,
                          remote, FALSE, NULL, &error));
  g_assert_no_error (error);
  return remote;
}

static void
assert_url (FlatpakRemote *remote, const char *expected)
{
  g_autofree char *value = CALL_API (flatpak_remote_get_url, remote);
  g_assert_cmpstr (value, ==, expected);
}

static void
ref_case (const char *command)
{
  const char *refs[] = { REF, "runtime/org.example.Platform/aarch64/24.08" };
  const char *names[] = { "org.example.Objects", "org.example.Platform" };
  const char *arches[] = { "x86_64", "aarch64" };
  const char *branches[] = { "stable", "24.08" };

  if (strcmp (command, "objects-ref-invalid") == 0)
    {
      const char *invalid[] = { "", "app/org.example.Objects/x86_64",
                                "widget/org.example.Objects/x86_64/stable",
                                "app//x86_64/stable", REF "/extra" };
      for (size_t i = 0; i < G_N_ELEMENTS (invalid); i++)
        {
          g_autoptr(GError) error = NULL;
          g_autoptr(FlatpakRef) ref = CALL_API (flatpak_ref_parse, invalid[i], &error);
          g_assert_null (ref);
          g_assert_nonnull (error);
        }
      return;
    }
  if (strcmp (command, "objects-ref-properties") == 0)
    {
      g_autoptr(FlatpakRef) ref = g_object_new (CALL_API (flatpak_ref_get_type),
                                               "name", "org.example.Objects",
                                               "arch", "x86_64", "branch", "stable",
                                               "kind", FLATPAK_REF_KIND_APP,
                                               "commit", COMMIT,
                                               "collection-id", "org.example.Collection", NULL);
      g_assert_cmpstr (CALL_API (flatpak_ref_get_commit, ref), ==, COMMIT);
      g_assert_cmpstr (CALL_API (flatpak_ref_get_collection_id, ref), ==,
                       "org.example.Collection");
      return;
    }
  for (size_t i = 0; i < G_N_ELEMENTS (refs); i++)
    {
      GError *error = NULL;
      g_autoptr(FlatpakRef) ref = CALL_API (flatpak_ref_parse, refs[i], &error);
      g_assert_no_error (error);
      g_assert_nonnull (ref);
      if (strcmp (command, "objects-ref-roundtrip") == 0)
        {
          g_autofree char *formatted = CALL_API (flatpak_ref_format_ref, ref);
          g_assert_cmpstr (formatted, ==, refs[i]);
          g_assert_cmpstr (CALL_API (flatpak_ref_get_name, ref), ==, names[i]);
          g_assert_cmpstr (CALL_API (flatpak_ref_get_arch, ref), ==, arches[i]);
          g_assert_cmpstr (CALL_API (flatpak_ref_get_branch, ref), ==, branches[i]);
          g_assert_cmpint (CALL_API (flatpak_ref_get_kind, ref), ==,
                           i == 0 ? FLATPAK_REF_KIND_APP : FLATPAK_REF_KIND_RUNTIME);
          g_assert_null (CALL_API (flatpak_ref_get_commit, ref));
        }
      else
        {
          const char *cached = CALL_API (flatpak_ref_format_ref_cached, ref);
          g_autofree char *first = CALL_API (flatpak_ref_format_ref, ref);
          g_autofree char *second = CALL_API (flatpak_ref_format_ref, ref);
          g_assert_cmpstr (cached, ==, refs[i]);
          g_assert_cmpstr (first, ==, refs[i]);
          g_assert_cmpstr (second, ==, refs[i]);
          g_assert_true (cached == CALL_API (flatpak_ref_format_ref_cached, ref));
          g_clear_pointer (&first, g_free);
          g_assert_cmpstr (cached, ==, refs[i]);
          g_clear_pointer (&second, g_free);
          g_assert_cmpstr (cached, ==, refs[i]);
          g_assert_cmpstr (CALL_API (flatpak_ref_get_name, ref), ==, names[i]);
          second = CALL_API (flatpak_ref_format_ref, ref);
          g_clear_object (&ref);
          g_assert_cmpstr (second, ==, refs[i]);
        }
    }
}

static void
related_case (const char *command)
{
  const char *subpaths[] = { "/en", "/sv", NULL };
  for (int value = 0; value <= 1; value++)
    {
      g_autoptr(FlatpakRelatedRef) ref = g_object_new (
        CALL_API (flatpak_related_ref_get_type),
        "name", "org.example.Objects.Locale", "arch", "x86_64", "branch", "stable",
        "kind", FLATPAK_REF_KIND_RUNTIME,
        "should-download", value, "should-delete", !value,
        "should-autoprune", value, "subpaths", value ? subpaths : NULL, NULL);
      if (strcmp (command, "objects-related-policy") == 0)
        {
          g_assert_cmpint (CALL_API (flatpak_related_ref_should_download, ref), ==, value);
          g_assert_cmpint (CALL_API (flatpak_related_ref_should_delete, ref), ==, !value);
          g_assert_cmpint (CALL_API (flatpak_related_ref_should_autoprune, ref), ==, value);
        }
      else
        {
          const char * const *actual = CALL_API (flatpak_related_ref_get_subpaths, ref);
          if (value)
            {
              g_assert_nonnull (actual);
              g_assert_cmpstr (actual[0], ==, "/en");
              g_assert_cmpstr (actual[1], ==, "/sv");
              g_assert_null (actual[2]);
            }
          else
            g_assert_null (actual);
        }
    }
}

static void
eol_case (void)
{
  for (int value = 0; value <= 1; value++)
    {
      const char *reason = value ? "Superseded fixture" : NULL;
      const char *rebase = value ? "app/org.example.Successor/x86_64/stable" : NULL;
      g_autoptr(FlatpakRemoteRef) remote = g_object_new (
        CALL_API (flatpak_remote_ref_get_type),
        "name", "org.example.Objects", "arch", "x86_64", "branch", "stable",
        "end-of-life", reason, "end-of-life-rebase", rebase, NULL);
      g_autoptr(FlatpakInstalledRef) installed = g_object_new (
        CALL_API (flatpak_installed_ref_get_type),
        "name", "org.example.Objects", "arch", "x86_64", "branch", "stable",
        "end-of-life", reason, "end-of-life-rebase", rebase, NULL);
      g_assert_cmpstr (CALL_API (flatpak_remote_ref_get_eol, remote), ==, reason);
      g_assert_cmpstr (CALL_API (flatpak_remote_ref_get_eol_rebase, remote), ==, rebase);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_eol, installed), ==, reason);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_eol_rebase, installed), ==, rebase);
    }
}

static void
remote_ownership (void)
{
  const char metadata[] = "[Application]\nname=org.example.Objects\n";
  g_autoptr(GBytes) input = g_bytes_new_static (metadata, sizeof metadata - 1);
  g_autoptr(FlatpakRemoteRef) ref = g_object_new (
    CALL_API (flatpak_remote_ref_get_type),
    "name", "org.example.Objects", "arch", "x86_64", "branch", "stable",
    "metadata", input, NULL);
  g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new, "owned");
  CALL_API (flatpak_remote_set_url, remote, URL);
  g_autofree char *url = CALL_API (flatpak_remote_get_url, remote);
  GBytes *borrowed = CALL_API (flatpak_remote_ref_get_metadata, ref);
  g_assert_nonnull (borrowed);
  g_autoptr(GBytes) retained = g_bytes_ref (borrowed);
  g_clear_pointer (&input, g_bytes_unref);
  g_clear_object (&ref);
  g_clear_object (&remote);
  g_assert_cmpstr (url, ==, URL);
  gsize size = 0;
  const char *data = g_bytes_get_data (retained, &size);
  g_assert_cmpuint (size, ==, sizeof metadata - 1);
  g_assert_cmpmem (data, size, metadata, sizeof metadata - 1);
}

static void
appdata_case (void)
{
  g_autoptr(GHashTable) rating = g_hash_table_new (g_str_hash, g_str_equal);
  g_hash_table_insert (rating, "violence-cartoon", "mild");
  g_hash_table_insert (rating, "language-humor", "none");
  for (int value = 0; value <= 1; value++)
    {
      g_autoptr(FlatpakInstalledRef) ref = g_object_new (
        CALL_API (flatpak_installed_ref_get_type),
        "name", "org.example.Objects", "arch", "x86_64", "branch", "stable",
        "appdata-version", value ? "2.4.6" : NULL,
        "appdata-license", value ? "MIT" : NULL,
        "appdata-content-rating-type", value ? "oars-1.1" : NULL,
        "appdata-content-rating", value ? rating : NULL, NULL);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_version, ref), ==,
                       value ? "2.4.6" : NULL);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_license, ref), ==,
                       value ? "MIT" : NULL);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_content_rating_type, ref), ==,
                       value ? "oars-1.1" : NULL);
      GHashTable *actual = CALL_API (flatpak_installed_ref_get_appdata_content_rating, ref);
      if (value)
        {
          g_assert_nonnull (actual);
          g_assert_cmpuint (g_hash_table_size (actual), ==, 2);
          g_assert_cmpstr (g_hash_table_lookup (actual, "violence-cartoon"), ==, "mild");
          g_assert_cmpstr (g_hash_table_lookup (actual, "language-humor"), ==, "none");
        }
      else
        g_assert_null (actual);
    }
}

static void
remote_file (void)
{
  const char data[] = "[Flatpak Repo]\nVersion=1\nUrl=" URL "\nTitle=File title\n";
  GError *error = NULL;
  g_autoptr(FlatpakInstallation) installation = open_user ();
  g_autoptr(GBytes) bytes = g_bytes_new_static (data, sizeof data - 1);
  g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new_from_file,
                                            "from-file", bytes, &error);
  g_assert_no_error (error);
  g_assert_nonnull (remote);
  g_assert_cmpstr (CALL_API (flatpak_remote_get_name, remote), ==, "from-file");
  assert_url (remote, URL);
  g_autofree char *title = CALL_API (flatpak_remote_get_title, remote);
  g_assert_cmpstr (title, ==, "File title");
  absent (installation, "from-file");
  const char *invalid[] = { "not a keyfile", "[Unrelated]\nUrl=" URL "\n",
                            "[Flatpak Repo]\nTitle=Missing URL\n" };
  for (size_t i = 0; i < G_N_ELEMENTS (invalid); i++)
    {
      g_autoptr(GError) failure = NULL;
      g_autoptr(GBytes) bad = g_bytes_new (invalid[i], strlen (invalid[i]));
      g_autoptr(FlatpakRemote) rejected = CALL_API (flatpak_remote_new_from_file,
                                                  "bad-file", bad, &failure);
      g_assert_null (rejected);
      g_assert_nonnull (failure);
      absent (installation, "bad-file");
    }
}

static void
remote_edits (const char *command)
{
  g_autoptr(FlatpakInstallation) installation = open_user ();
  g_autoptr(FlatpakRemote) remote = NULL;
  GError *error = NULL;
  if (strcmp (command, "objects-remote-local") == 0)
    {
      remote = CALL_API (flatpak_remote_new, "local-only");
      CALL_API (flatpak_remote_set_url, remote, URL);
      absent (installation, "local-only");
      g_clear_object (&remote);
      remote = add (installation, "configured", 1);
      CALL_API (flatpak_remote_set_url, remote, URL_EDIT);
      assert_url (remote, URL_EDIT);
      g_autoptr(FlatpakRemote) fresh = reopen_remote ("configured");
      assert_url (fresh, URL);
      return;
    }
  remote = add (installation, "configured", 1);
  if (strcmp (command, "objects-remote-cache") == 0)
    {
      g_autoptr(FlatpakRemote) before = lookup (installation, "configured");
      assert_url (before, URL);
      g_autoptr(FlatpakInstallation) other = open_user ();
      g_autoptr(FlatpakRemote) edit = lookup (other, "configured");
      CALL_API (flatpak_remote_set_url, edit, URL_EDIT);
      save (other, edit);
      g_assert_true (CALL_API (flatpak_installation_drop_caches, installation, NULL, &error));
      g_assert_no_error (error);
      g_autoptr(FlatpakRemote) after = lookup (installation, "configured");
      assert_url (after, URL_EDIT);
    }
  else
    {
      g_autoptr(FlatpakRemote) duplicate = CALL_API (flatpak_remote_new, "configured");
      CALL_API (flatpak_remote_set_url, duplicate, URL_EDIT);
      CALL_API (flatpak_remote_set_title, duplicate, "Replacement title");
      gboolean if_needed = strcmp (command, "objects-remote-if-needed") == 0;
      gboolean result = CALL_API (flatpak_installation_add_remote, installation,
                                  duplicate, if_needed, NULL, &error);
      if (if_needed)
        {
          g_assert_true (result);
          g_assert_no_error (error);
        }
      else
        {
          g_assert_false (result);
          g_assert_error (error, CALL_API (flatpak_error_quark), FLATPAK_ERROR_ALREADY_INSTALLED);
          g_clear_error (&error);
        }
      g_autoptr(FlatpakRemote) fresh = reopen_remote ("configured");
      assert_url (fresh, URL);
      g_autofree char *title = CALL_API (flatpak_remote_get_title, fresh);
      g_assert_cmpstr (title, ==, "Original title");
    }
}

static void
remote_properties (const char *command, const char *filter)
{
  g_autoptr(FlatpakInstallation) installation = open_user ();
  g_autoptr(FlatpakRemote) remote = add (installation, "properties", 1);
  if (strcmp (command, "objects-remote-description") == 0)
    {
      CALL_API (flatpak_remote_set_comment, remote, "Short comment");
      CALL_API (flatpak_remote_set_description, remote, "A literal long description.");
      CALL_API (flatpak_remote_set_homepage, remote, "https://objects.example/home");
      CALL_API (flatpak_remote_set_icon, remote, "https://objects.example/icon.png");
      save (installation, remote);
      g_autoptr(FlatpakRemote) fresh = reopen_remote ("properties");
      g_autofree char *comment = CALL_API (flatpak_remote_get_comment, fresh);
      g_autofree char *description = CALL_API (flatpak_remote_get_description, fresh);
      g_autofree char *homepage = CALL_API (flatpak_remote_get_homepage, fresh);
      g_autofree char *icon = CALL_API (flatpak_remote_get_icon, fresh);
      g_assert_cmpstr (comment, ==, "Short comment");
      g_assert_cmpstr (description, ==, "A literal long description.");
      g_assert_cmpstr (homepage, ==, "https://objects.example/home");
      g_assert_cmpstr (icon, ==, "https://objects.example/icon.png");
    }
  else if (strcmp (command, "objects-remote-policy") == 0)
    {
      /* Every flag has both values, independently of the other flags. */
      for (unsigned int bits = 0; bits < 8; bits++)
        {
          CALL_API (flatpak_remote_set_disabled, remote, (bits & 1) != 0);
          CALL_API (flatpak_remote_set_noenumerate, remote, (bits & 2) != 0);
          CALL_API (flatpak_remote_set_nodeps, remote, (bits & 4) != 0);
          save (installation, remote);
          g_autoptr(FlatpakRemote) fresh = reopen_remote ("properties");
          g_assert_cmpint (CALL_API (flatpak_remote_get_disabled, fresh), ==, (bits & 1) != 0);
          g_assert_cmpint (CALL_API (flatpak_remote_get_noenumerate, fresh), ==, (bits & 2) != 0);
          g_assert_cmpint (CALL_API (flatpak_remote_get_nodeps, fresh), ==, (bits & 4) != 0);
        }
      CALL_API (flatpak_remote_set_disabled, remote, FALSE);
      CALL_API (flatpak_remote_set_noenumerate, remote, FALSE);
      CALL_API (flatpak_remote_set_nodeps, remote, FALSE);
      save (installation, remote);
      g_autoptr(FlatpakRemote) fresh = reopen_remote ("properties");
      g_assert_false (CALL_API (flatpak_remote_get_disabled, fresh));
      g_assert_false (CALL_API (flatpak_remote_get_noenumerate, fresh));
      g_assert_false (CALL_API (flatpak_remote_get_nodeps, fresh));
    }
  else if (strcmp (command, "objects-remote-verification") == 0)
    {
      for (int value = 1; value >= 0; value--)
        {
          CALL_API (flatpak_remote_set_gpg_verify, remote, value);
          save (installation, remote);
          g_autoptr(FlatpakRemote) fresh = reopen_remote ("properties");
          g_assert_cmpint (CALL_API (flatpak_remote_get_gpg_verify, fresh), ==, value);
          g_autofree char *collection = CALL_API (flatpak_remote_get_collection_id, fresh);
          g_assert_null (collection);
        }
    }
  else if (strcmp (command, "objects-remote-branch") == 0)
    {
      /* Local property semantics only: signed-repository persistence is separate. */
      CALL_API (flatpak_remote_set_default_branch, remote, "testing");
      CALL_API (flatpak_remote_set_collection_id, remote, "org.example.Collection");
      g_autofree char *branch = CALL_API (flatpak_remote_get_default_branch, remote);
      g_autofree char *collection = CALL_API (flatpak_remote_get_collection_id, remote);
      g_assert_cmpstr (branch, ==, "testing");
      g_assert_cmpstr (collection, ==, "org.example.Collection");
      CALL_API (flatpak_remote_set_default_branch, remote, NULL);
      CALL_API (flatpak_remote_set_collection_id, remote, NULL);
      g_autofree char *unset_branch = CALL_API (flatpak_remote_get_default_branch, remote);
      g_autofree char *unset_collection = CALL_API (flatpak_remote_get_collection_id, remote);
      g_assert_null (unset_branch);
      g_assert_null (unset_collection);
    }
  else
    {
      CALL_API (flatpak_remote_set_filter, remote, filter);
      CALL_API (flatpak_remote_set_main_ref, remote, REF);
      save (installation, remote);
      g_autoptr(FlatpakRemote) fresh = reopen_remote ("properties");
      g_autofree char *actual_filter = CALL_API (flatpak_remote_get_filter, fresh);
      g_autofree char *main_ref = CALL_API (flatpak_remote_get_main_ref, fresh);
      g_assert_cmpstr (actual_filter, ==, filter);
      g_assert_cmpstr (main_ref, ==, REF);
      if (strcmp (command, "objects-remote-clear-filter") == 0)
        {
          GError *error = NULL;
          g_autoptr(FlatpakRemote) replacement = CALL_API (flatpak_remote_new, "properties");
          CALL_API (flatpak_remote_set_url, replacement, URL);
          CALL_API (flatpak_remote_set_filter, replacement, NULL);
          g_assert_true (CALL_API (flatpak_installation_add_remote, installation,
                                  replacement, TRUE, NULL, &error));
          g_assert_no_error (error);
          g_autoptr(FlatpakRemote) cleared = reopen_remote ("properties");
          g_autofree char *cleared_filter = CALL_API (flatpak_remote_get_filter, cleared);
          g_assert_null (cleared_filter);
        }
    }
}

static void
remote_types (void)
{
  GError *error = NULL;
  g_autoptr(FlatpakInstallation) installation = open_user ();
  g_autoptr(FlatpakRemote) remote = add (installation, "static-fixture", 1);
  FlatpakRemoteType types[] = { FLATPAK_REMOTE_TYPE_STATIC };
  FlatpakRemoteType dynamic[] = { FLATPAK_REMOTE_TYPE_USB, FLATPAK_REMOTE_TYPE_LAN };
  g_autoptr(GPtrArray) statics = CALL_API (flatpak_installation_list_remotes_by_type,
                                         installation, types, G_N_ELEMENTS (types), NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (statics);
  g_assert_cmpuint (statics->len, ==, 1);
  FlatpakRemote *item = g_ptr_array_index (statics, 0);
  g_assert_cmpstr (CALL_API (flatpak_remote_get_name, item), ==, "static-fixture");
  g_assert_cmpint (CALL_API (flatpak_remote_get_remote_type, item), ==, FLATPAK_REMOTE_TYPE_STATIC);
  g_autoptr(GPtrArray) discovered = CALL_API (flatpak_installation_list_remotes_by_type,
                                            installation, dynamic, G_N_ELEMENTS (dynamic),
                                            NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (discovered);
  g_assert_cmpuint (discovered->len, ==, 0);
}

static void
set_config (FlatpakInstallation *installation, const char *key, const char *value)
{
  GError *error = NULL;
  g_assert_true (CALL_API (flatpak_installation_set_config_sync,
                          installation, key, value, NULL, &error));
  g_assert_no_error (error);
}

static void
config_case (const char *command)
{
  g_autoptr(FlatpakInstallation) installation = open_user ();
  if (strcmp (command, "objects-config-roundtrip") == 0)
    {
      const char *keys[] = { "languages", "extra-languages" };
      const char *values[] = { "sv;en;pl", "de_DE;fr_CA" };
      for (size_t i = 0; i < G_N_ELEMENTS (keys); i++)
        {
          GError *error = NULL;
          set_config (installation, keys[i], values[i]);
          g_autoptr(FlatpakInstallation) fresh = open_user ();
          g_autofree char *value = CALL_API (flatpak_installation_get_config,
                                            fresh, keys[i], NULL, &error);
          g_assert_no_error (error);
          g_assert_cmpstr (value, ==, values[i]);
          set_config (installation, keys[i], NULL);
          g_clear_object (&fresh);
          fresh = open_user ();
          g_autofree char *unset = CALL_API (flatpak_installation_get_config,
                                            fresh, keys[i], NULL, &error);
          g_assert_null (unset);
          g_assert_error (error, G_KEY_FILE_ERROR, G_KEY_FILE_ERROR_KEY_NOT_FOUND);
          g_clear_error (&error);
        }
    }
  else
    {
      GError *error = NULL;
      set_config (installation, "languages", "de;fr");
      g_autoptr(FlatpakInstallation) fresh = open_user ();
      g_auto(GStrv) languages = CALL_API (flatpak_installation_get_default_languages, fresh, &error);
      g_assert_no_error (error);
      g_auto(GStrv) locales = CALL_API (flatpak_installation_get_default_locales, fresh, &error);
      g_assert_no_error (error);
      g_assert_nonnull (languages);
      g_assert_nonnull (locales);
      g_assert_cmpuint (g_strv_length (languages), ==, 2);
      g_assert_cmpuint (g_strv_length (locales), ==, 2);
      g_assert_true (g_strv_contains ((const char * const *) languages, "de"));
      g_assert_true (g_strv_contains ((const char * const *) languages, "fr"));
      g_assert_true (g_strv_contains ((const char * const *) locales, "de"));
      g_assert_true (g_strv_contains ((const char * const *) locales, "fr"));
      set_config (installation, "languages", NULL);
      set_config (installation, "extra-languages", "de_DE;fr_CA");
      g_clear_object (&fresh);
      fresh = open_user ();
      g_auto(GStrv) extra_languages = CALL_API (flatpak_installation_get_default_languages,
                                               fresh, &error);
      g_assert_no_error (error);
      g_auto(GStrv) extra_locales = CALL_API (flatpak_installation_get_default_locales,
                                             fresh, &error);
      g_assert_no_error (error);
      g_assert_nonnull (extra_languages);
      g_assert_nonnull (extra_locales);
      g_assert_true (g_strv_contains ((const char * const *) extra_languages, "de"));
      g_assert_true (g_strv_contains ((const char * const *) extra_languages, "fr"));
      g_assert_true (g_strv_contains ((const char * const *) extra_locales, "de_DE"));
      g_assert_true (g_strv_contains ((const char * const *) extra_locales, "fr_CA"));
      set_config (installation, "languages", "");
      g_clear_object (&fresh);
      fresh = open_user ();
      g_auto(GStrv) all = CALL_API (flatpak_installation_get_default_languages, fresh, &error);
      g_assert_no_error (error);
      g_assert_nonnull (all);
      g_assert_null (all[0]);
    }
}

static void
installation_identity (const char *expected)
{
  g_autoptr(FlatpakInstallation) installation = open_user ();
  g_assert_true (CALL_API (flatpak_installation_get_is_user, installation));
  g_assert_cmpstr (CALL_API (flatpak_installation_get_id, installation), ==, "user");
  g_autoptr(GFile) path = CALL_API (flatpak_installation_get_path, installation);
  g_assert_nonnull (path);
  g_clear_object (&installation);
  g_autofree char *actual = g_file_get_path (path);
  g_assert_cmpstr (actual, ==, expected);
}

static void
timestamp_case (void)
{
  g_autoptr(FlatpakInstallation) installation = open_user ();
  int64_t start = g_get_real_time () / G_USEC_PER_SEC;
  g_autoptr(FlatpakRemote) remote = add (installation, "timestamp", 1);
  uint64_t first = CALL_API (flatpak_installation_get_timestamp, installation);
  g_assert_cmpuint (first, !=, G_MAXUINT64);
  g_assert_cmpuint (first, >=, start);
  g_assert_cmpuint (first, <=, g_get_real_time () / G_USEC_PER_SEC);
  g_usleep (2 * G_USEC_PER_SEC);
  CALL_API (flatpak_remote_set_title, remote, "Later title");
  save (installation, remote);
  uint64_t later = CALL_API (flatpak_installation_get_timestamp, installation);
  g_assert_cmpuint (later, !=, G_MAXUINT64);
  g_assert_cmpuint (later, >, first);
  g_assert_cmpuint (later, <=, g_get_real_time () / G_USEC_PER_SEC);

  /* Make the entire public installation location unavailable, without knowing
   * the implementation's monitored filename. Restore it before asserting. */
  GError *error = NULL;
  g_autoptr(GFile) path = CALL_API (flatpak_installation_get_path, installation);
  g_autofree char *path_string = g_file_get_path (path);
  g_autofree char *away_string = g_strconcat (path_string, ".unavailable", NULL);
  g_autoptr(GFile) away = g_file_new_for_path (away_string);
  g_assert_true (g_file_move (path, away, G_FILE_COPY_NONE, NULL, NULL, NULL, &error));
  g_assert_no_error (error);
  uint64_t unavailable = CALL_API (flatpak_installation_get_timestamp, installation);
  g_assert_true (g_file_move (away, path, G_FILE_COPY_NONE, NULL, NULL, NULL, &error));
  g_assert_no_error (error);
  g_assert_cmpuint (unavailable, ==, G_MAXUINT64);
}

static void
custom_path (const char *path, const char *app, const char *runtime)
{
  GError *error = NULL;
  g_autoptr(GFile) file = g_file_new_for_path (path);
  g_autoptr(FlatpakInstallation) custom = CALL_API (flatpak_installation_new_for_path,
                                                  file, TRUE, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (custom);
  g_assert_true (CALL_API (flatpak_installation_get_is_user, custom));
  g_autoptr(GFile) actual = CALL_API (flatpak_installation_get_path, custom);
  g_assert_true (g_file_equal (actual, file));
  g_autoptr(GPtrArray) empty = CALL_API (flatpak_installation_list_installed_refs,
                                        custom, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (empty);
  g_assert_cmpuint (empty->len, ==, 0);
  g_autoptr(FlatpakInstallation) user = open_user ();
  g_autoptr(GPtrArray) installed = CALL_API (flatpak_installation_list_installed_refs,
                                            user, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installed);
  g_assert_cmpuint (installed->len, ==, 2);
  gboolean found_app = FALSE;
  gboolean found_runtime = FALSE;
  for (size_t i = 0; i < installed->len; i++)
    {
      g_autofree char *ref = CALL_API (flatpak_ref_format_ref, g_ptr_array_index (installed, i));
      if (strcmp (ref, app) == 0)
        found_app = TRUE;
      else if (strcmp (ref, runtime) == 0)
        found_runtime = TRUE;
      else
        g_assert_not_reached ();
    }
  g_assert_true (found_app);
  g_assert_true (found_runtime);
  /* An unrelated local configuration edit also stays in the custom path. */
  set_config (custom, "languages", "pl");
  g_clear_object (&custom);
  custom = CALL_API (flatpak_installation_new_for_path, file, TRUE, NULL, &error);
  g_assert_no_error (error);
  g_autofree char *languages = CALL_API (flatpak_installation_get_config,
                                        custom, "languages", NULL, &error);
  g_assert_no_error (error);
  g_assert_cmpstr (languages, ==, "pl");
}

int
blackbox_objects_main (int argc, char **argv)
{
  if (argc < 2)
    return -1;
  const char *command = argv[1];
  if (strcmp (command, "objects-ref-roundtrip") == 0 ||
      strcmp (command, "objects-ref-invalid") == 0 ||
      strcmp (command, "objects-ref-cache") == 0 ||
      strcmp (command, "objects-ref-properties") == 0)
    ref_case (command);
  else if (strcmp (command, "objects-related-policy") == 0 ||
           strcmp (command, "objects-related-subpaths") == 0)
    related_case (command);
  else if (strcmp (command, "objects-eol") == 0)
    eol_case ();
  else if (strcmp (command, "objects-appdata") == 0)
    appdata_case ();
  else if (strcmp (command, "objects-remote-ownership") == 0)
    remote_ownership ();
  else if (strcmp (command, "objects-remote-file") == 0)
    remote_file ();
  else if (strcmp (command, "objects-remote-local") == 0 ||
           strcmp (command, "objects-remote-cache") == 0 ||
           strcmp (command, "objects-remote-duplicate") == 0 ||
           strcmp (command, "objects-remote-if-needed") == 0)
    remote_edits (command);
  else if (strcmp (command, "objects-remote-description") == 0 ||
           strcmp (command, "objects-remote-policy") == 0 ||
           strcmp (command, "objects-remote-verification") == 0 ||
           strcmp (command, "objects-remote-branch") == 0 ||
           strcmp (command, "objects-remote-filter") == 0 ||
           strcmp (command, "objects-remote-clear-filter") == 0)
    {
      g_assert_cmpint (argc, ==, 3);
      remote_properties (command, argv[2]);
    }
  else if (strcmp (command, "objects-remote-types") == 0)
    remote_types ();
  else if (strcmp (command, "objects-config-roundtrip") == 0 ||
           strcmp (command, "objects-config-locales") == 0)
    config_case (command);
  else if (strcmp (command, "objects-installation-identity") == 0)
    {
      g_assert_cmpint (argc, ==, 3);
      installation_identity (argv[2]);
    }
  else if (strcmp (command, "objects-timestamp") == 0)
    timestamp_case ();
  else if (strcmp (command, "objects-custom-path") == 0)
    {
      g_assert_cmpint (argc, ==, 5);
      custom_path (argv[2], argv[3], argv[4]);
    }
  else if (strcmp (command, "objects-overrides") == 0)
    {
      GError *error = NULL;
      g_autoptr(FlatpakInstallation) installation = open_user ();
      g_autofree char *contents = CALL_API (flatpak_installation_load_app_overrides,
                                           installation, "org.example.Objects", NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (contents);
      g_autoptr(GKeyFile) overrides = g_key_file_new ();
      g_assert_true (g_key_file_load_from_data (overrides, contents, strlen (contents),
                                               G_KEY_FILE_NONE, &error));
      g_assert_no_error (error);
      gsize n_keys = 0;
      g_auto(GStrv) keys = g_key_file_get_keys (overrides, "Environment", &n_keys, &error);
      g_assert_no_error (error);
      g_assert_nonnull (keys);
      g_assert_cmpuint (n_keys, ==, 2);
      g_autofree char *value = g_key_file_get_string (overrides, "Environment",
                                                     "BLACKBOX_OBJECTS", &error);
      g_assert_no_error (error);
      g_assert_cmpstr (value, ==, "objects-value");
      g_autofree char *second = g_key_file_get_string (overrides, "Environment",
                                                      "BLACKBOX_OBJECTS_SECOND", &error);
      g_assert_no_error (error);
      g_assert_cmpstr (second, ==, "two words=three");
    }
  else if (strcmp (command, "objects-arches") == 0)
    {
      g_assert_cmpint (argc, ==, 3);
      const char *arch = CALL_API (flatpak_get_default_arch);
      const char * const *arches = CALL_API (flatpak_get_supported_arches);
      const char *canonical[] = { "x86_64", "i386", "aarch64", "arm", "ppc64le",
                                  "ppc64", "s390x", "riscv64", "loongarch64", NULL };
      g_assert_cmpstr (arch, ==, argv[2]);
      g_assert_nonnull (arches);
      g_assert_cmpstr (arches[0], ==, argv[2]);
      size_t count = 0;
      while (count < 16 && arches[count] != NULL)
        {
          g_assert_true (g_strv_contains (canonical, arches[count]));
          for (size_t j = 0; j < count; j++)
            g_assert_cmpstr (arches[j], !=, arches[count]);
          count++;
        }
      g_assert_cmpuint (count, <, 16);
      if (strcmp (argv[2], "x86_64") == 0)
        {
          g_assert_cmpuint (count, ==, 2);
          g_assert_cmpstr (arches[1], ==, "i386");
        }
    }
  else if (strcmp (command, "objects-error-domains") == 0)
    {
      GQuark flatpak = CALL_API (flatpak_error_quark);
      GQuark portal = CALL_API (flatpak_portal_error_quark);
      g_assert_cmpuint (flatpak, !=, 0);
      g_assert_cmpuint (portal, !=, 0);
      g_assert_cmpuint (flatpak, !=, portal);
      g_assert_cmpuint (CALL_API (flatpak_error_quark), ==, flatpak);
      g_assert_cmpuint (CALL_API (flatpak_portal_error_quark), ==, portal);
    }
  else
    return -1;
  return 0;
}
