/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>

int blackbox_queries_main (int argc, char **argv);

static char *
value (GKeyFile *data, const char *key)
{
  g_autoptr(GError) error = NULL;
  char *result = g_key_file_get_string (data, "query", key, &error);
  g_assert_no_error (error);
  g_assert_nonnull (result);
  return result;
}

static void
identity (FlatpakRef *ref, const char *expected, const char *commit)
{
  g_autofree char *formatted = CALL_API (flatpak_ref_format_ref, ref);
  g_assert_cmpstr (formatted, ==, expected);
  g_assert_cmpstr (CALL_API (flatpak_ref_get_commit, ref), ==, commit);
}

static void
bytes_file (GBytes *bytes, const char *path)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *contents = NULL;
  size_t length = 0;
  g_assert_nonnull (bytes);
  g_assert_true (g_file_get_contents (path, &contents, &length, &error));
  g_assert_no_error (error);
  g_assert_cmpmem (g_bytes_get_data (bytes, NULL), g_bytes_get_size (bytes), contents, length);
}

static void
xml_start (GMarkupParseContext *context, const char *name, const char **names,
           const char **values, void *user_data, GError **error)
{
  GString *output = user_data;
  (void) context;
  (void) error;
  g_string_append_printf (output, "<%s", name);
  /* AppStream attribute ordering is immaterial. Sort copied name/value pairs. */
  g_autoptr(GPtrArray) sorted = g_ptr_array_new_with_free_func (g_free);
  for (size_t i = 0; names[i] != NULL; i++)
    g_ptr_array_add (sorted, g_markup_printf_escaped (" %s=\"%s\"", names[i], values[i]));
  for (size_t i = 0; i < sorted->len; i++)
    for (size_t j = i + 1; j < sorted->len; j++)
      if (strcmp (g_ptr_array_index (sorted, i), g_ptr_array_index (sorted, j)) > 0)
        {
          void *temporary = sorted->pdata[i];
          sorted->pdata[i] = sorted->pdata[j];
          sorted->pdata[j] = temporary;
        }
  for (size_t i = 0; i < sorted->len; i++)
    g_string_append (output, g_ptr_array_index (sorted, i));
  g_string_append_c (output, '>');
}

static void
xml_end (GMarkupParseContext *context, const char *name, void *user_data, GError **error)
{
  (void) context;
  (void) error;
  g_string_append_printf (user_data, "</%s>", name);
}

static void
xml_text (GMarkupParseContext *context, const char *text, size_t length,
          void *user_data, GError **error)
{
  (void) context;
  (void) error;
  gboolean whitespace = TRUE;
  for (size_t i = 0; i < length; i++)
    whitespace &= g_ascii_isspace (text[i]);
  if (!whitespace)
    {
      g_autofree char *escaped = g_markup_escape_text (text, length);
      g_string_append (user_data, escaped);
    }
}

static char *
xml_normalized (const char *contents, size_t length)
{
  static const GMarkupParser parser = { xml_start, xml_end, xml_text, NULL, NULL };
  g_autoptr(GError) error = NULL;
  GString *output = g_string_new (NULL);
  g_autoptr(GMarkupParseContext) context = g_markup_parse_context_new (&parser, 0, output, NULL);
  g_assert_true (g_markup_parse_context_parse (context, contents, length, &error));
  g_assert_no_error (error);
  g_assert_true (g_markup_parse_context_end_parse (context, &error));
  g_assert_no_error (error);
  return g_string_free (output, FALSE);
}

static void
xml_file (GBytes *bytes, const char *path)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(GZlibDecompressor) decoder = g_zlib_decompressor_new (G_ZLIB_COMPRESSOR_FORMAT_GZIP);
  g_autoptr(GInputStream) input = g_memory_input_stream_new_from_bytes (bytes);
  g_autoptr(GInputStream) stream = g_converter_input_stream_new (input, G_CONVERTER (decoder));
  g_autoptr(GByteArray) xml = g_byte_array_new ();
  char buffer[4096];
  gssize count;
  while ((count = g_input_stream_read (stream, buffer, sizeof buffer, NULL, &error)) > 0)
    g_byte_array_append (xml, (const uint8_t *) buffer, count);
  g_assert_no_error (error);
  g_autofree char *expected = NULL;
  size_t expected_length = 0;
  g_assert_true (g_file_get_contents (path, &expected, &expected_length, &error));
  g_assert_no_error (error);
  g_autofree char *actual_xml = xml_normalized ((const char *) xml->data, xml->len);
  g_autofree char *expected_xml = xml_normalized (expected, expected_length);
  g_assert_cmpstr (actual_xml, ==, expected_xml);
}

static void
members (GPtrArray *refs, const char *expected)
{
  g_auto(GStrv) names = g_strsplit (expected, ";", -1);
  size_t length = *expected ? g_strv_length (names) : 0;
  g_assert_nonnull (refs);
  g_assert_cmpuint (refs->len, ==, length);
  for (size_t i = 0; i < length; i++)
    {
      size_t count = 0;
      for (size_t j = 0; j < refs->len; j++)
        {
          g_autofree char *name = CALL_API (flatpak_ref_format_ref, g_ptr_array_index (refs, j));
          count += g_str_equal (name, names[i]);
        }
      g_assert_cmpuint (count, ==, 1);
    }
}

static FlatpakInstalledRef *
installed (FlatpakInstallation *installation, FlatpakRef *ref)
{
  g_autoptr(GError) error = NULL;
  FlatpakInstalledRef *result = CALL_API (
    flatpak_installation_get_installed_ref, installation,
    CALL_API (flatpak_ref_get_kind, ref), CALL_API (flatpak_ref_get_name, ref),
    CALL_API (flatpak_ref_get_arch, ref), CALL_API (flatpak_ref_get_branch, ref), NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (result);
  return result;
}

static void
installed_query (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_autofree char *commit = value (data, "commit");
  g_autoptr(FlatpakRef) parsed = CALL_API (flatpak_ref_parse, full, &error);
  g_assert_no_error (error);
  if (g_str_equal (action, "list"))
    {
      g_autofree char *all = value (data, "all");
      g_autofree char *apps = value (data, "apps");
      g_autofree char *runtimes = value (data, "runtimes");
      g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_installed_refs,
                                          installation, NULL, &error);
      g_assert_no_error (error);
      members (refs, all);
      g_autoptr(GPtrArray) app_refs = CALL_API (flatpak_installation_list_installed_refs_by_kind,
                                              installation, FLATPAK_REF_KIND_APP, NULL, &error);
      g_assert_no_error (error);
      members (app_refs, apps);
      g_autoptr(GPtrArray) runtime_refs = CALL_API (flatpak_installation_list_installed_refs_by_kind,
                                                  installation, FLATPAK_REF_KIND_RUNTIME, NULL, &error);
      g_assert_no_error (error);
      members (runtime_refs, runtimes);
      return;
    }
  g_autoptr(FlatpakInstalledRef) ref = installed (installation, parsed);
  identity (FLATPAK_REF (ref), full, commit);
  if (g_str_equal (action, "metadata"))
    {
      g_autofree char *path = value (data, "metadata");
      g_autoptr(GBytes) metadata = CALL_API (flatpak_installed_ref_load_metadata, ref, NULL, &error);
      g_assert_no_error (error);
      bytes_file (metadata, path);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_origin, ref), ==, "queries");
      g_autofree char *size = value (data, "installed");
      g_assert_cmpuint (CALL_API (flatpak_installed_ref_get_installed_size, ref), ==,
                        g_ascii_strtoull (size, NULL, 10));
      const char *directory = CALL_API (flatpak_installed_ref_get_deploy_dir, ref);
      g_assert_true (g_path_is_absolute (directory));
      g_autofree char *deployed_metadata = g_build_filename (directory, "metadata", NULL);
      bytes_file (metadata, deployed_metadata);
      g_autofree char *payload = g_build_filename (directory, "files", "bin", "probe", NULL);
      g_assert_true (g_file_test (payload, G_FILE_TEST_IS_REGULAR));
    }
  else if (g_str_equal (action, "subpaths"))
    {
      g_autofree char *partial = value (data, "partial");
      const char * const *paths = CALL_API (flatpak_installed_ref_get_subpaths, ref);
      if (*partial)
        {
          g_assert_nonnull (paths);
          g_assert_cmpstr (paths[0], ==, partial);
          g_assert_null (paths[1]);
        }
      else
        g_assert_null (paths);
    }
  else if (g_str_equal (action, "appdata"))
    {
      g_autofree char *path = value (data, "appstream");
      g_autoptr(GBytes) bytes = CALL_API (flatpak_installed_ref_load_appdata, ref, NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (bytes);
      xml_file (bytes, path);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_name, ref), ==, "Query fixture");
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_appdata_summary, ref), ==,
                       "Controlled query metadata");
    }
  else if (g_str_equal (action, "defaults"))
    {
      g_autofree char *master_ref = value (data, "master_ref");
      g_autofree char *master_commit = value (data, "master_commit");
      g_autoptr(FlatpakInstalledRef) master = CALL_API (
        flatpak_installation_get_installed_ref, installation, FLATPAK_REF_KIND_APP,
        CALL_API (flatpak_ref_get_name, parsed), NULL, NULL, NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (master);
      identity (FLATPAK_REF (master), master_ref, master_commit);
      g_autoptr(FlatpakInstalledRef) current = CALL_API (
        flatpak_installation_get_current_installed_app, installation,
        CALL_API (flatpak_ref_get_name, parsed), NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (current);
      identity (FLATPAK_REF (current), full, commit);
      g_assert_true (CALL_API (flatpak_installed_ref_get_is_current, current));
    }
  else if (g_str_equal (action, "ownership"))
    {
      g_autoptr(FlatpakInstallation) source = CALL_API (flatpak_installation_new_user, NULL, &error);
      g_assert_no_error (error);
      g_autoptr(FlatpakInstalledRef) retained = installed (source, parsed);
      g_clear_object (&source);
      identity (FLATPAK_REF (retained), full, commit);
    }
  else
    g_assert_not_reached ();
}

static void
remote_query (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  if (g_str_equal (action, "add"))
    {
      g_autofree char *url = value (data, "url");
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_remote_new, "queries");
      CALL_API (flatpak_remote_set_url, remote, url);
      CALL_API (flatpak_remote_set_gpg_verify, remote, FALSE);
      g_assert_true (CALL_API (flatpak_installation_add_remote, installation, remote,
                               FALSE, NULL, &error));
      g_assert_no_error (error);
      return;
    }
  g_autofree char *full = value (data, "ref");
  g_autofree char *commit = value (data, "commit");
  g_autoptr(FlatpakRef) parsed = CALL_API (flatpak_ref_parse, full, &error);
  g_assert_no_error (error);
  if (g_str_equal (action, "cached") || g_str_equal (action, "uncached"))
    {
      gboolean cached = g_str_equal (action, "cached");
      g_autoptr(FlatpakRemoteRef) ref = CALL_API (flatpak_installation_fetch_remote_ref_sync_full,
        installation, "queries", CALL_API (flatpak_ref_get_kind, parsed),
        CALL_API (flatpak_ref_get_name, parsed), CALL_API (flatpak_ref_get_arch, parsed),
        CALL_API (flatpak_ref_get_branch, parsed), FLATPAK_QUERY_FLAGS_ONLY_CACHED, NULL, &error);
      if (cached)
        {
          g_assert_no_error (error);
          g_assert_nonnull (ref);
          identity (FLATPAK_REF (ref), full, commit);
        }
      else
        {
          g_assert_null (ref);
          g_assert_error (error, CALL_API (flatpak_error_quark), FLATPAK_ERROR_NOT_CACHED);
          g_clear_error (&error);
        }
      g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_remote_refs_sync_full,
        installation, "queries", FLATPAK_QUERY_FLAGS_ONLY_CACHED, NULL, &error);
      if (cached)
        {
          g_autofree char *expected = value (data, "all");
          g_assert_no_error (error);
          members (refs, expected);
        }
      else
        {
          g_assert_null (refs);
          g_assert_error (error, CALL_API (flatpak_error_quark), FLATPAK_ERROR_NOT_CACHED);
        }
      return;
    }
  if (g_str_equal (action, "members") || g_str_equal (action, "all-arches"))
    {
      g_autofree char *expected = value (data, "all");
      if (g_str_equal (action, "all-arches"))
        {
          g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_remote_refs_sync_full,
            installation, "queries", FLATPAK_QUERY_FLAGS_ALL_ARCHES, NULL, &error);
          g_assert_no_error (error);
          members (refs, expected);
        }
      else
        {
          g_autofree char *url = value (data, "url");
          const char *sources[] = { "queries", url };
          for (size_t i = 0; i < G_N_ELEMENTS (sources); i++)
            {
              g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_remote_refs_sync,
                                                   installation, sources[i], NULL, &error);
              g_assert_no_error (error);
              members (refs, expected);
            }
        }
      return;
    }
  g_autoptr(FlatpakRemoteRef) ref = CALL_API (flatpak_installation_fetch_remote_ref_sync,
    installation, "queries", CALL_API (flatpak_ref_get_kind, parsed),
    CALL_API (flatpak_ref_get_name, parsed), CALL_API (flatpak_ref_get_arch, parsed),
    CALL_API (flatpak_ref_get_branch, parsed), NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (ref);
  identity (FLATPAK_REF (ref), full, commit);
  g_assert_cmpstr (CALL_API (flatpak_remote_ref_get_remote_name, ref), ==, "queries");
  if (g_str_equal (action, "metadata"))
    {
      g_autofree char *path = value (data, "metadata");
      g_autofree char *installed_size = value (data, "installed");
      g_autofree char *download_size = value (data, "download");
      guint64 installed_bytes = 0, download_bytes = 0;
      GBytes *metadata = CALL_API (flatpak_remote_ref_get_metadata, ref);
      bytes_file (metadata, path);
      g_assert_cmpuint (CALL_API (flatpak_remote_ref_get_installed_size, ref), ==,
                        g_ascii_strtoull (installed_size, NULL, 10));
      g_assert_cmpuint (CALL_API (flatpak_remote_ref_get_download_size, ref), ==,
                        g_ascii_strtoull (download_size, NULL, 10));
      g_autoptr(GBytes) direct = CALL_API (flatpak_installation_fetch_remote_metadata_sync,
                                          installation, "queries", FLATPAK_REF (ref), NULL, &error);
      g_assert_no_error (error);
      bytes_file (direct, path);
      g_assert_true (CALL_API (flatpak_installation_fetch_remote_size_sync, installation,
                               "queries", FLATPAK_REF (ref), &download_bytes, &installed_bytes,
                               NULL, &error));
      g_assert_no_error (error);
      g_assert_cmpuint (installed_bytes, ==, g_ascii_strtoull (installed_size, NULL, 10));
      g_assert_cmpuint (download_bytes, ==, g_ascii_strtoull (download_size, NULL, 10));
    }
  else if (g_str_equal (action, "current"))
    {
      g_autofree char *old = value (data, "old_commit");
      g_autoptr(FlatpakInstalledRef) deployed = installed (installation, parsed);
      identity (FLATPAK_REF (deployed), full, old);
      g_assert_cmpstr (old, !=, commit);
    }
  else
    g_assert_not_reached ();
}

static void
policy_query (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_autofree char *commit = value (data, "commit");
  g_autofree char *metadata_path = value (data, "metadata");
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  g_autoptr(FlatpakRemoteRef) main_ref = CALL_API (flatpak_installation_fetch_remote_ref_sync,
    installation, "queries", FLATPAK_REF_KIND_APP, parts[1], parts[2], parts[3], NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (main_ref);
  identity (FLATPAK_REF (main_ref), full, commit);
  g_autoptr(GBytes) metadata = CALL_API (flatpak_installation_fetch_remote_metadata_sync,
    installation, "queries", FLATPAK_REF (main_ref), NULL, &error);
  g_assert_no_error (error);
  bytes_file (metadata, metadata_path);
  g_autoptr(GKeyFile) declarations = g_key_file_new ();
  g_assert_true (g_key_file_load_from_data (declarations, g_bytes_get_data (metadata, NULL),
    g_bytes_get_size (metadata), G_KEY_FILE_NONE, &error));
  g_assert_no_error (error);
  g_autoptr(GPtrArray) installed_refs = CALL_API (flatpak_installation_list_installed_refs,
                                                installation, NULL, &error);
  g_assert_no_error (error);
  members (installed_refs, "");
  g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_remote_related_refs_sync,
                                      installation, "queries", full, NULL, &error);
  g_assert_no_error (error);
  g_autofree char *first = value (data, "policy_0_ref");
  g_autofree char *second = value (data, "policy_1_ref");
  g_assert_cmpstr (first, !=, second);
  g_autofree char *expected = g_strjoin (";", first, second, NULL);
  members (refs, expected);
  for (size_t i = 0; i < 2; i++)
    {
      const char *fields[] = { "ref", "commit", "no_autodownload", "autodelete",
                               "should_download", "should_delete" };
      g_autoptr(GPtrArray) values = g_ptr_array_new_with_free_func (g_free);
      for (size_t j = 0; j < G_N_ELEMENTS (fields); j++)
        {
          g_autofree char *key = g_strdup_printf ("policy_%zu_%s", i, fields[j]);
          g_ptr_array_add (values, value (data, key));
        }
      const char *ref_string = g_ptr_array_index (values, 0);
      g_auto(GStrv) identity_parts = g_strsplit (ref_string, "/", -1);
      g_autofree char *group = g_strconcat ("Extension ", identity_parts[1], NULL);
      gboolean download = i == 0;
      gboolean delete = i != 0;
      g_assert_cmpstr (g_ptr_array_index (values, 2), ==, download ? "false" : "true");
      g_assert_cmpstr (g_ptr_array_index (values, 3), ==, delete ? "true" : "false");
      g_assert_cmpstr (g_ptr_array_index (values, 4), ==, download ? "true" : "false");
      g_assert_cmpstr (g_ptr_array_index (values, 5), ==, delete ? "true" : "false");
      gboolean no_autodownload = g_key_file_get_boolean (
        declarations, group, "no-autodownload", &error);
      g_assert_no_error (error);
      g_assert_cmpint (no_autodownload, ==, !download);
      gboolean autodelete = g_key_file_get_boolean (declarations, group, "autodelete", &error);
      g_assert_no_error (error);
      g_assert_cmpint (autodelete, ==, delete);
      for (size_t j = 0; j < refs->len; j++)
        {
          FlatpakRelatedRef *ref = g_ptr_array_index (refs, j);
          g_autofree char *formatted = CALL_API (flatpak_ref_format_ref, FLATPAK_REF (ref));
          if (!g_str_equal (formatted, ref_string))
            continue;
          identity (FLATPAK_REF (ref), ref_string, g_ptr_array_index (values, 1));
          g_assert_cmpint (CALL_API (flatpak_related_ref_should_download, ref), ==, download);
          g_assert_cmpint (CALL_API (flatpak_related_ref_should_delete, ref), ==, delete);
          g_assert_null (CALL_API (flatpak_related_ref_get_subpaths, ref));
        }
    }
}

static void
related_query (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_autofree char *expected = value (data, "related");
  if (g_str_equal (action, "installed") && *expected)
    {
      g_autoptr(FlatpakRef) parsed = CALL_API (flatpak_ref_parse, expected, &error);
      g_assert_no_error (error);
      g_autoptr(FlatpakInstalledRef) deployed = installed (installation, parsed);
      g_autofree char *origin = value (data, "related_origin");
      g_autofree char *commit = value (data, "related_commit");
      identity (FLATPAK_REF (deployed), expected, commit);
      g_assert_cmpstr (CALL_API (flatpak_installed_ref_get_origin, deployed), ==, origin);
    }
  g_autoptr(GPtrArray) refs = NULL;
  if (g_str_equal (action, "remote"))
    refs = CALL_API (flatpak_installation_list_remote_related_refs_sync,
                     installation, "queries", full, NULL, &error);
  else if (g_str_equal (action, "installed"))
    refs = CALL_API (flatpak_installation_list_installed_related_refs_sync,
                     installation, "queries", full, NULL, &error);
  else if (g_str_equal (action, "for-installed"))
    refs = CALL_API (flatpak_installation_list_remote_related_refs_for_installed_sync,
                     installation, "queries", full, NULL, &error);
  else
    g_assert_not_reached ();
  g_assert_no_error (error);
  members (refs, expected);
  if (*expected)
    {
      FlatpakRelatedRef *ref = g_ptr_array_index (refs, 0);
      g_autofree char *commit = value (data, "related_commit");
      identity (FLATPAK_REF (ref), expected, *commit ? commit : NULL);
      g_autofree char *download = value (data, "should_download");
      g_assert_cmpint (CALL_API (flatpak_related_ref_should_download, ref), ==,
                       g_str_equal (download, "true"));
      g_assert_true (CALL_API (flatpak_related_ref_should_delete, ref));
      g_assert_null (CALL_API (flatpak_related_ref_get_subpaths, ref));
    }
}

static void
appstream_query (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  g_autofree char *expected = value (data, "cache_appstream");
  for (size_t i = 0; i < 2; i++)
    {
      gboolean changed = i != 0;
      g_assert_true (CALL_API (flatpak_installation_update_appstream_sync,
                               installation, "queries", parts[2], &changed, NULL, &error));
      g_assert_no_error (error);
      g_assert_cmpint (changed, ==, i == 0);
      g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_installation_get_remote_by_name,
                                                installation, "queries", NULL, &error);
      g_assert_no_error (error);
      g_autoptr(GFile) directory = CALL_API (flatpak_remote_get_appstream_dir, remote, parts[2]);
      g_assert_nonnull (directory);
      g_autoptr(GFile) xml_file_path = g_file_get_child (directory, "appstream.xml.gz");
      g_autoptr(GBytes) bytes = g_file_load_bytes (xml_file_path, NULL, NULL, &error);
      g_assert_no_error (error);
      g_assert_nonnull (bytes);
      xml_file (bytes, expected);
    }
}

typedef struct
{
  GMainContext *context;
  GThread *thread;
  gboolean active;
  size_t calls;
  unsigned int last_percentage;
  gboolean last_estimating;
} AppstreamProgress;

static AppstreamProgress *expected_progress;

static void
appstream_progress (const char *status, guint percentage, gboolean estimating, gpointer user_data)
{
  g_assert_true (user_data == expected_progress);
  AppstreamProgress *state = user_data;
  g_assert_true (state->active);
  g_assert_true (g_thread_self () == state->thread);
  /* GLib invocation permits a direct call while this context is owned, even
   * with another thread-default context pushed. The push below itself acquires
   * ownership: this checks the execution conditions, not main-loop dispatch. */
  g_assert_true (g_main_context_is_owner (state->context));
  g_assert_nonnull (status);
  g_assert_true (g_utf8_validate (status, -1, NULL));
  g_assert_cmpuint (strlen (status), >, 0);
  g_assert_cmpuint (percentage, <=, 100);
  state->calls++;
  state->last_percentage = percentage;
  state->last_estimating = estimating;
  g_printerr ("APPSTREAM_PROGRESS\t%u\t%d\tcaller-context-owned\t%s\n",
              percentage, estimating, status);
}

static void
progress_query (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  g_autoptr(GMainContext) context = g_main_context_new ();
  AppstreamProgress state = { .context = context, .thread = g_thread_self () };
  expected_progress = &state;
  g_main_context_push_thread_default (context);
  state.active = TRUE;
  gboolean changed = FALSE;
  g_assert_true (CALL_API (flatpak_installation_update_appstream_full_sync,
                           installation, "queries", parts[2], appstream_progress,
                           &state, &changed, NULL, &error));
  state.active = FALSE;
  g_assert_no_error (error);
  g_assert_true (changed);
  g_assert_cmpuint (state.calls, >=, 1);
  /* Neither a particular callback count nor a final progress value is promised.
   * gboolean uses zero/nonzero semantics, not an exact 0/1 representation. */
  g_printerr ("APPSTREAM_PROGRESS_RETURN\t%zu\t%u\t%d\n",
              state.calls, state.last_percentage, state.last_estimating);
  size_t completed_calls = state.calls;
  /* Keep user data alive while dispatching both contexts after the call. A
   * queued late callback must fail the active-call assertion, not escape it. */
  int64_t deadline = g_get_monotonic_time () + G_USEC_PER_SEC / 4;
  while (g_get_monotonic_time () < deadline)
    {
      g_main_context_iteration (context, FALSE);
      g_main_context_iteration (NULL, FALSE);
      g_usleep (1000);
    }
  /* A subsequent refresh has no callback. It cannot reuse the previous data. */
  changed = TRUE;
  g_assert_true (CALL_API (flatpak_installation_update_appstream_full_sync,
                           installation, "queries", parts[2], NULL, NULL,
                           &changed, NULL, &error));
  g_assert_no_error (error);
  g_assert_false (changed);
  g_assert_cmpuint (state.calls, ==, completed_calls);
  g_main_context_pop_thread_default (context);
  expected_progress = NULL;
  /* Validate the refreshed public AppStream data against the exported oracle. */
  g_autofree char *expected = value (data, "cache_appstream");
  g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_installation_get_remote_by_name,
                                            installation, "queries", NULL, &error);
  g_assert_no_error (error);
  g_autoptr(GFile) directory = CALL_API (flatpak_remote_get_appstream_dir, remote, parts[2]);
  g_autoptr(GFile) path = g_file_get_child (directory, "appstream.xml.gz");
  g_autoptr(GBytes) bytes = g_file_load_bytes (path, NULL, NULL, &error);
  g_assert_no_error (error);
  xml_file (bytes, expected);
}

static void
updates_query (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *expected = value (data, "updates");
  g_autoptr(GPtrArray) refs = CALL_API (flatpak_installation_list_installed_refs_for_update,
                                      installation, NULL, &error);
  g_assert_no_error (error);
  members (refs, expected);
}

static void
unused_query (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_autofree char *runtime = value (data, "runtime");
  g_autofree char *runtime_commit = value (data, "runtime_commit");
  g_autoptr(GPtrArray) unused = CALL_API (flatpak_installation_list_unused_refs,
                                        installation, NULL, NULL, &error);
  g_assert_no_error (error);
  members (unused, "");
  const char *excluded[] = { full, NULL };
  GVariantBuilder builder;
  g_variant_builder_init (&builder, G_VARIANT_TYPE_VARDICT);
  g_variant_builder_add (&builder, "{sv}", "exclude-refs", g_variant_new_strv (excluded, -1));
  g_autoptr(GVariant) options = g_variant_ref_sink (g_variant_builder_end (&builder));
  g_autoptr(GPtrArray) without_app = CALL_API (flatpak_installation_list_unused_refs_with_options,
                                             installation, NULL, NULL, options, NULL, &error);
  g_assert_no_error (error);
  members (without_app, runtime);
  g_autoptr(GKeyFile) replacement = g_key_file_new ();
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  g_autofree char *missing = g_strdup_printf ("org.flatpak.QueryAbsent/%s/test", parts[2]);
  g_key_file_set_string (replacement, "Application", "name", parts[1]);
  g_key_file_set_string (replacement, "Application", "runtime", missing);
  g_key_file_set_string (replacement, "Application", "sdk", missing);
  g_autoptr(GHashTable) injection = g_hash_table_new (g_str_hash, g_str_equal);
  g_hash_table_insert (injection, full, replacement);
  g_autoptr(GPtrArray) substituted = CALL_API (flatpak_installation_list_unused_refs_with_options,
                                             installation, parts[2], injection, NULL, NULL, &error);
  g_assert_no_error (error);
  members (substituted, runtime);
  g_autoptr(FlatpakRef) runtime_ref = CALL_API (flatpak_ref_parse, runtime, &error);
  g_assert_no_error (error);
  g_autoptr(FlatpakInstalledRef) deployed = installed (installation, runtime_ref);
  identity (FLATPAK_REF (deployed), runtime, runtime_commit);
  installed_query (installation, data, "metadata");
  g_autoptr(GPtrArray) afterward = CALL_API (flatpak_installation_list_unused_refs,
                                           installation, NULL, NULL, &error);
  g_assert_no_error (error);
  members (afterward, "");
}

static void
bundle_query (GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *path = value (data, "bundle");
  g_autofree char *full = value (data, "ref");
  g_autofree char *commit = value (data, "commit");
  g_autofree char *metadata_path = value (data, "metadata");
  g_autofree char *xml_path = value (data, "appstream");
  g_autofree char *size = value (data, "installed");
  g_autofree char *expected_origin = value (data, "origin");
  g_autoptr(GFile) file = g_file_new_for_path (path);
  g_autoptr(FlatpakBundleRef) ref = CALL_API (flatpak_bundle_ref_new, file, &error);
  g_assert_no_error (error);
  g_assert_nonnull (ref);
  identity (FLATPAK_REF (ref), full, commit);
  g_autoptr(GFile) owned_file = CALL_API (flatpak_bundle_ref_get_file, ref);
  g_autoptr(GBytes) metadata = CALL_API (flatpak_bundle_ref_get_metadata, ref);
  g_autofree char *origin = CALL_API (flatpak_bundle_ref_get_origin, ref);
  g_autofree char *runtime_repo = CALL_API (flatpak_bundle_ref_get_runtime_repo_url, ref);
  g_assert_cmpstr (origin, ==, *expected_origin ? expected_origin : NULL);
  g_assert_cmpstr (runtime_repo, ==, *expected_origin ?
                   "https://example.invalid/runtime.flatpakrepo" : NULL);
  g_autoptr(GBytes) xml = CALL_API (flatpak_bundle_ref_get_appstream, ref);
  g_assert_nonnull (xml);
  xml_file (xml, xml_path);
  g_assert_cmpuint (CALL_API (flatpak_bundle_ref_get_installed_size, ref), ==,
                    g_ascii_strtoull (size, NULL, 10));
  for (int pixels = 64; pixels <= 128; pixels *= 2)
    {
      g_autofree char *key = g_strdup_printf ("icon-%d", pixels);
      g_autofree char *icon_path = value (data, key);
      g_autoptr(GBytes) icon = CALL_API (flatpak_bundle_ref_get_icon, ref, pixels);
      bytes_file (icon, icon_path);
    }
  g_clear_object (&ref);
  g_assert_true (g_file_equal (file, owned_file));
  bytes_file (metadata, metadata_path);
  g_assert_cmpstr (origin, ==, *expected_origin ? expected_origin : NULL);
}

G_GNUC_BEGIN_IGNORE_DEPRECATIONS
static void
ref_file_query (FlatpakInstallation *installation, GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *url = value (data, "url");
  g_autofree char *full = value (data, "ref");
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  g_autofree char *contents = g_strdup_printf (
    "[Flatpak Ref]\nName=%s\nBranch=%s\nUrl=%s\nIsRuntime=false\n"
    "Title=Query ref file\nSuggestRemoteName=query-file\n", parts[1], parts[3], url);
  g_autoptr(GBytes) bytes = g_bytes_new (contents, strlen (contents));
  g_autoptr(FlatpakRemoteRef) ref = CALL_API (flatpak_installation_install_ref_file,
                                           installation, bytes, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (ref);
  identity (FLATPAK_REF (ref), full, NULL);
  const char *remote_name = CALL_API (flatpak_remote_ref_get_remote_name, ref);
  g_assert_nonnull (remote_name);
  g_autoptr(FlatpakRemote) remote = CALL_API (flatpak_installation_get_remote_by_name,
                                            installation, remote_name, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (remote);
  g_autofree char *actual_url = CALL_API (flatpak_remote_get_url, remote);
  g_assert_cmpstr (actual_url, ==, url);
  g_autoptr(GPtrArray) installed_refs = CALL_API (flatpak_installation_list_installed_refs,
                                                installation, NULL, &error);
  g_assert_no_error (error);
  members (installed_refs, "");
}

static void
legacy_query (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_autofree char *commit = value (data, "commit");
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  FlatpakRefKind kind = g_str_equal (parts[0], "app") ? FLATPAK_REF_KIND_APP : FLATPAK_REF_KIND_RUNTIME;
  g_autoptr(FlatpakInstalledRef) result = NULL;
  if (g_str_equal (action, "install"))
    result = CALL_API (flatpak_installation_install, installation, "queries", kind,
                       parts[1], parts[2], parts[3], NULL, NULL, NULL, &error);
  else if (g_str_equal (action, "update"))
    result = CALL_API (flatpak_installation_update, installation, FLATPAK_UPDATE_FLAGS_NONE,
                       kind, parts[1], parts[2], parts[3], NULL, NULL, NULL, &error);
  else if (g_str_equal (action, "uninstall"))
    {
      g_assert_true (CALL_API (flatpak_installation_uninstall, installation, kind,
                               parts[1], parts[2], parts[3], NULL, NULL, NULL, &error));
      g_assert_no_error (error);
      result = CALL_API (flatpak_installation_get_installed_ref, installation, kind,
                         parts[1], parts[2], parts[3], NULL, &error);
      g_assert_null (result);
      g_assert_error (error, CALL_API (flatpak_error_quark), FLATPAK_ERROR_NOT_INSTALLED);
      return;
    }
  else if (g_str_equal (action, "noop") || g_str_equal (action, "absent"))
    {
      result = CALL_API (flatpak_installation_update_full, installation, FLATPAK_UPDATE_FLAGS_NONE,
                         kind, parts[1], parts[2], parts[3], NULL, NULL, NULL, NULL, &error);
      g_assert_null (result);
      g_assert_error (error, CALL_API (flatpak_error_quark), g_str_equal (action, "noop") ?
                      FLATPAK_ERROR_ALREADY_INSTALLED : FLATPAK_ERROR_NOT_INSTALLED);
      return;
    }
  else if (g_str_equal (action, "pull") || g_str_equal (action, "deploy") ||
           g_str_equal (action, "partial"))
    {
      const char *subpaths[] = { "/bin", NULL };
      FlatpakInstallFlags flags = g_str_equal (action, "pull") ? FLATPAK_INSTALL_FLAGS_NO_DEPLOY :
        g_str_equal (action, "deploy") ? FLATPAK_INSTALL_FLAGS_NO_PULL : FLATPAK_INSTALL_FLAGS_NONE;
      result = CALL_API (flatpak_installation_install_full, installation, flags, "queries",
                         kind, parts[1], parts[2], parts[3],
                         g_str_equal (action, "partial") ? subpaths : NULL,
                         NULL, NULL, NULL, &error);
      if (g_str_equal (action, "pull"))
        {
          g_assert_null (result);
          g_assert_error (error, CALL_API (flatpak_error_quark), FLATPAK_ERROR_ONLY_PULLED);
          g_clear_error (&error);
          result = CALL_API (flatpak_installation_get_installed_ref, installation, kind,
                             parts[1], parts[2], parts[3], NULL, &error);
          g_assert_null (result);
          g_assert_error (error, CALL_API (flatpak_error_quark), FLATPAK_ERROR_NOT_INSTALLED);
          return;
        }
    }
  else
    g_assert_not_reached ();
  g_assert_no_error (error);
  g_assert_nonnull (result);
  identity (FLATPAK_REF (result), full, commit);
  g_autoptr(FlatpakInstalledRef) queried = installed (installation, FLATPAK_REF (result));
  identity (FLATPAK_REF (queried), full, commit);
}
G_GNUC_END_IGNORE_DEPRECATIONS

static void
child_exited (GPid pid, int status, void *user_data)
{
  gboolean *exited = user_data;
  g_assert_true (WIFEXITED (status));
  g_assert_cmpint (WEXITSTATUS (status), ==, 0);
  *exited = TRUE;
  g_spawn_close_pid (pid);
}

static GPtrArray *
probe_snapshots (const char *directory)
{
  GPtrArray *snapshots = g_ptr_array_new_with_free_func ((GDestroyNotify) g_key_file_unref);
  g_autoptr(GDir) dir = g_dir_open (directory, 0, NULL);
  if (dir == NULL)
    return snapshots;
  const char *entry;
  while ((entry = g_dir_read_name (dir)) != NULL)
    if (g_str_has_suffix (entry, ".ready"))
      {
        g_autofree char *path = g_build_filename (directory, entry, NULL);
        GKeyFile *info = g_key_file_new ();
        g_autoptr(GError) error = NULL;
        g_assert_true (g_key_file_load_from_file (info, path, G_KEY_FILE_NONE, &error));
        g_assert_no_error (error);
        g_ptr_array_add (snapshots, info);
      }
  return snapshots;
}

static void
instance_identity (FlatpakInstance *instance, GKeyFile *data, GPtrArray *snapshots)
{
  g_autofree char *full = value (data, "ref");
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  g_autofree char *commit = value (data, "commit");
  g_autofree char *runtime = value (data, "runtime");
  g_autofree char *runtime_commit = value (data, "runtime_commit");
  g_assert_cmpstr (CALL_API (flatpak_instance_get_app, instance), ==, parts[1]);
  g_assert_cmpstr (CALL_API (flatpak_instance_get_arch, instance), ==, parts[2]);
  g_assert_cmpstr (CALL_API (flatpak_instance_get_branch, instance), ==, parts[3]);
  g_assert_cmpstr (CALL_API (flatpak_instance_get_commit, instance), ==, commit);
  g_assert_cmpstr (CALL_API (flatpak_instance_get_runtime, instance), ==, runtime);
  g_assert_cmpstr (CALL_API (flatpak_instance_get_runtime_commit, instance), ==, runtime_commit);
  g_assert_true (CALL_API (flatpak_instance_is_running, instance));
  const char *id = CALL_API (flatpak_instance_get_id, instance);
  g_assert_nonnull (id);
  g_assert_cmpstr (id, !=, "");
  GKeyFile *snapshot = NULL;
  for (size_t i = 0; i < snapshots->len; i++)
    {
      GKeyFile *candidate = g_ptr_array_index (snapshots, i);
      g_autofree char *candidate_id = g_key_file_get_string (candidate, "Instance", "instance-id", NULL);
      if (g_strcmp0 (id, candidate_id) == 0)
        {
          g_assert_null (snapshot);
          snapshot = candidate;
        }
    }
  g_assert_nonnull (snapshot);
  GKeyFile *info = CALL_API (flatpak_instance_get_info, instance);
  g_assert_nonnull (info);
  g_auto(GStrv) groups = g_key_file_get_groups (snapshot, NULL);
  for (size_t i = 0; groups[i] != NULL; i++)
    {
      g_auto(GStrv) keys = g_key_file_get_keys (snapshot, groups[i], NULL, NULL);
      for (size_t j = 0; keys[j] != NULL; j++)
        {
          g_autofree char *expected = g_key_file_get_value (snapshot, groups[i], keys[j], NULL);
          g_autofree char *actual = g_key_file_get_value (info, groups[i], keys[j], NULL);
          g_assert_cmpstr (actual, ==, expected);
        }
    }
}

static void
instance_processes (FlatpakInstallation *installation, FlatpakInstance *instance,
                    GKeyFile *data)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_autoptr(FlatpakRef) parsed = CALL_API (flatpak_ref_parse, full, &error);
  g_assert_no_error (error);
  g_autoptr(FlatpakInstalledRef) ref = installed (installation, parsed);
  g_autofree char *executable = g_build_filename (
    CALL_API (flatpak_installed_ref_get_deploy_dir, ref), "files", "bin", "probe", NULL);
  int outer = CALL_API (flatpak_instance_get_pid, instance);
  int child = 0;
  int64_t deadline = g_get_monotonic_time () + 5 * G_TIME_SPAN_SECOND;
  do
    {
      child = CALL_API (flatpak_instance_get_child_pid, instance);
      if (child != 0)
        break;
      g_usleep (10000);
    }
  while (g_get_monotonic_time () < deadline);
  g_assert_cmpint (outer, >, 1);
  g_assert_cmpint (child, >, 1);
  g_assert_cmpint (outer, !=, child);
  g_autofree char *proc_exe = g_strdup_printf ("/proc/%d/exe", child);
  g_autofree char *resolved_exe = g_file_read_link (proc_exe, &error);
  g_assert_no_error (error);
  g_printerr ("query-process outer=%d child=%d executable=%s\n", outer, child, resolved_exe);
  g_autofree char *contents = NULL;
  size_t length = 0;
  g_assert_true (g_file_get_contents (proc_exe, &contents, &length, &error));
  g_assert_no_error (error);
  g_autoptr(GBytes) executable_bytes = g_bytes_new (contents, length);
  bytes_file (executable_bytes, executable);
  /* The reported outer process must actually supervise this executable. */
  int ancestor = child;
  while (ancestor > 1 && ancestor != outer)
    {
      g_autofree char *path = g_strdup_printf ("/proc/%d/status", ancestor);
      g_autofree char *status_contents = NULL;
      g_assert_true (g_file_get_contents (path, &status_contents, NULL, &error));
      g_assert_no_error (error);
      char *parent_field = strstr (status_contents, "\nPPid:");
      g_assert_nonnull (parent_field);
      int parent = 0;
      g_assert_cmpint (sscanf (parent_field, "\nPPid: %d", &parent), ==, 1);
      g_assert_cmpint (parent, !=, ancestor);
      ancestor = parent;
    }
  g_assert_cmpint (ancestor, ==, outer);
}

static void
launch_query (FlatpakInstallation *installation, GKeyFile *data, const char *action)
{
  g_autoptr(GError) error = NULL;
  g_autofree char *full = value (data, "ref");
  g_auto(GStrv) parts = g_strsplit (full, "/", -1);
  g_autofree char *commit = value (data, "commit");
  g_autofree char *directory = value (data, "probe_dir");
  gboolean watch = !g_str_equal (action, "basic");
  FlatpakInstance *launched[2] = { NULL, NULL };
  gboolean exited[2] = { FALSE, FALSE };
  for (size_t i = 0; i < G_N_ELEMENTS (launched); i++)
    {
      if (watch)
        {
          g_assert_true (CALL_API (flatpak_installation_launch_full, installation,
            FLATPAK_LAUNCH_FLAGS_DO_NOT_REAP, parts[1], parts[2], parts[3], commit,
            &launched[i], NULL, &error));
          g_assert_no_error (error);
          g_assert_nonnull (launched[i]);
          int pid = CALL_API (flatpak_instance_get_pid, launched[i]);
          g_assert_cmpint (pid, >, 0);
          g_child_watch_add (pid, child_exited, &exited[i]);
        }
      else
        {
          g_assert_true (CALL_API (flatpak_installation_launch, installation,
            parts[1], parts[2], parts[3], commit, NULL, &error));
          g_assert_no_error (error);
        }
    }
  int64_t deadline = g_get_monotonic_time () + 15 * G_TIME_SPAN_SECOND;
  g_autoptr(GPtrArray) snapshots = NULL;
  do
    {
      g_clear_pointer (&snapshots, g_ptr_array_unref);
      snapshots = probe_snapshots (directory);
      if (snapshots->len == 2)
        break;
      g_usleep (10000);
    }
  while (g_get_monotonic_time () < deadline);
  g_assert_cmpuint (snapshots->len, ==, 2);
  g_autoptr(GPtrArray) all = CALL_API (flatpak_instance_get_all);
  g_autoptr(GPtrArray) retained = g_ptr_array_new_with_free_func (g_object_unref);
  for (size_t i = 0; i < all->len; i++)
    {
      FlatpakInstance *instance = g_ptr_array_index (all, i);
      if (g_strcmp0 (CALL_API (flatpak_instance_get_app, instance), parts[1]) == 0)
        {
          instance_identity (instance, data, snapshots);
          g_ptr_array_add (retained, g_object_ref (instance));
        }
    }
  g_assert_cmpuint (retained->len, ==, 2);
  g_assert_cmpstr (CALL_API (flatpak_instance_get_id, g_ptr_array_index (retained, 0)), !=,
                   CALL_API (flatpak_instance_get_id, g_ptr_array_index (retained, 1)));
  if (watch)
    for (size_t i = 0; i < G_N_ELEMENTS (launched); i++)
      {
        instance_identity (launched[i], data, snapshots);
        if (g_str_equal (action, "processes"))
          instance_processes (installation, launched[i], data);
      }
  g_autofree char *release = g_build_filename (directory, "release", NULL);
  g_assert_true (g_file_set_contents (release, "release\n", -1, &error));
  g_assert_no_error (error);
  deadline = g_get_monotonic_time () + 15 * G_TIME_SPAN_SECOND;
  gboolean running;
  do
    {
      while (g_main_context_iteration (NULL, FALSE))
        ;
      running = FALSE;
      for (size_t i = 0; i < retained->len; i++)
        running |= CALL_API (flatpak_instance_is_running, g_ptr_array_index (retained, i));
      if (!running && (!watch || (exited[0] && exited[1])))
        break;
      g_usleep (10000);
    }
  while (g_get_monotonic_time () < deadline);
  g_assert_false (running);
  if (watch)
    for (size_t i = 0; i < G_N_ELEMENTS (launched); i++)
      {
        g_assert_true (exited[i]);
        g_assert_false (CALL_API (flatpak_instance_is_running, launched[i]));
        g_object_unref (launched[i]);
      }
}

int
blackbox_queries_main (int argc, char **argv)
{
  if (argc < 2 || !g_str_has_prefix (argv[1], "queryx-"))
    return -1;
  g_assert_cmpint (argc, ==, 4);
  g_autoptr(GError) error = NULL;
  g_autoptr(GKeyFile) data = g_key_file_new ();
  g_assert_true (g_key_file_load_from_file (data, argv[2], G_KEY_FILE_NONE, &error));
  g_assert_no_error (error);
  g_autoptr(FlatpakInstallation) installation = CALL_API (flatpak_installation_new_user, NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (installation);
  if (g_str_has_prefix (argv[1], "queryx-installed"))
    installed_query (installation, data, argv[3]);
  else if (g_str_has_prefix (argv[1], "queryx-remote"))
    remote_query (installation, data, argv[3]);
  else if (g_str_has_prefix (argv[1], "queryx-bundle"))
    bundle_query (data);
  else if (g_str_has_prefix (argv[1], "queryx-related"))
    related_query (installation, data, argv[3]);
  else if (g_str_has_prefix (argv[1], "queryx-policy"))
    policy_query (installation, data);
  else if (g_str_has_prefix (argv[1], "queryx-updates"))
    updates_query (installation, data);
  else if (g_str_has_prefix (argv[1], "queryx-unused"))
    unused_query (installation, data);
  else if (g_str_has_prefix (argv[1], "queryx-appstream"))
    appstream_query (installation, data);
  else if (g_str_has_prefix (argv[1], "queryx-progress"))
    progress_query (installation, data);
  else if (g_str_has_prefix (argv[1], "queryx-ref-file"))
    ref_file_query (installation, data);
  else if (g_str_has_prefix (argv[1], "queryx-launch"))
    launch_query (installation, data, argv[3]);
  else if (g_str_has_prefix (argv[1], "queryx-legacy"))
    legacy_query (installation, data, argv[3]);
  else
    g_assert_not_reached ();
  return 0;
}
