/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "client-extension.h"
#include <stdint.h>
#include <string.h>

int blackbox_auth_main (int argc, char **argv);

typedef struct
{
  const char *mode;
  const char *ref;
  const char *commit;
  FlatpakTransaction *transaction;
  GThread *thread;
  guint id;
  unsigned int pre, start, done, ready;
  unsigned int install;
  FlatpakInstallation *installation;
  const char *candidate, *candidate_commit, *runtime_ref, *parent, *remote_url, *cli;
  GSubprocess *service;
} Auth;

static void
check_thread (Auth *a)
{
  g_assert_true (a->thread == g_thread_self ());
}

/* Run after the start handler has returned TRUE, while the request is active. */
static gboolean
complete_interaction (gpointer data)
{
  Auth *a = data;
  check_thread (a);
  g_assert_cmpuint (a->start, ==, 1);
  g_assert_cmpuint (a->done, ==, 0);
  g_assert_cmpuint (a->ready, ==, 0);
  if (strcmp (a->mode, "web-abort") == 0)
    CALL_API (flatpak_transaction_abort_webflow, a->transaction, a->id);
  else
    CALL_API (flatpak_transaction_complete_basic_auth, a->transaction, a->id,
              strcmp (a->mode, "basic-abort") == 0 ? NULL : "blackbox",
              strcmp (a->mode, "basic-wrong") == 0 ? "wrong" : "test-password", NULL);
  return G_SOURCE_REMOVE;
}

static void
schedule_completion (Auth *a)
{
  g_autoptr(GSource) source = g_idle_source_new ();
  g_source_set_callback (source, complete_interaction, a, NULL);
  g_source_attach (source, g_main_context_get_thread_default ());
}

static gboolean
pre_auth (FlatpakTransaction *tx, Auth *a)
{
  GList *ops = CALL_API (flatpak_transaction_get_operations, tx);
  TRACE_SIGNAL (FlatpakTransaction, "ready-pre-auth");
  check_thread (a);
  g_assert_cmpuint (++a->pre, ==, 1);
  size_t protected_count = 0;
  g_assert_cmpuint (g_list_length (ops), <=, a->candidate ? 3 : 1);
  for (GList *l = ops; l != NULL; l = l->next)
    {
      const char *ref = CALL_API (flatpak_transaction_operation_get_ref, l->data);
      if (strcmp (ref, a->ref) == 0)
        {
          protected_count++;
          g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_commit, l->data), ==, a->commit);
          g_assert_true (CALL_API (flatpak_transaction_operation_get_requires_authentication, l->data));
        }
      else
        {
          g_assert_nonnull (a->candidate);
          g_assert_true (strcmp (ref, a->candidate) == 0 || strcmp (ref, a->runtime_ref) == 0);
          g_assert_false (CALL_API (flatpak_transaction_operation_get_requires_authentication, l->data));
        }
    }
  g_assert_cmpuint (protected_count, ==, 1);
  g_list_free_full (ops, g_object_unref);
  return strcmp (a->mode, "pre-abort") != 0;
}

static gboolean
ready (FlatpakTransaction *tx, Auth *a)
{
  GList *ops = CALL_API (flatpak_transaction_get_operations, tx);
  TRACE_SIGNAL (FlatpakTransaction, "ready");
  check_thread (a);
  g_assert_cmpuint (a->start, ==, 1);
  g_assert_cmpuint (++a->ready, ==, 1);
  size_t protected_count = 0;
  g_assert_cmpuint (g_list_length (ops), <=, a->candidate ? 3 : 1);
  for (GList *l = ops; l != NULL; l = l->next)
    {
      const char *ref = CALL_API (flatpak_transaction_operation_get_ref, l->data);
      if (strcmp (ref, a->ref) == 0)
        {
          protected_count++;
          g_assert_cmpstr (CALL_API (flatpak_transaction_operation_get_commit, l->data), ==, a->commit);
        }
      else
        {
          g_assert_nonnull (a->candidate);
          g_assert_true (strcmp (ref, a->candidate) == 0 || strcmp (ref, a->runtime_ref) == 0);
        }
      g_assert_false (CALL_API (flatpak_transaction_operation_get_requires_authentication, l->data));
    }
  g_assert_cmpuint (protected_count, ==, 1);
  g_list_free_full (ops, g_object_unref);
  return TRUE;
}

static gboolean
basic (FlatpakTransaction *tx, const char *remote, const char *realm,
       GVariant *options, guint id, Auth *a)
{
  (void) tx;
  TRACE_SIGNAL (FlatpakTransaction, "basic-auth-start");
  check_thread (a);
  g_assert_cmpuint (a->pre, ==, 1);
  g_assert_cmpuint (++a->start, ==, 1);
  g_assert_cmpstr (remote, ==, "fixture");
  g_assert_cmpstr (realm, ==, "Blackbox protected runtime");
  g_assert_true (g_variant_is_of_type (options, G_VARIANT_TYPE_VARDICT));
  a->id = id;
  if (strcmp (a->mode, "basic-decline") == 0)
    return FALSE;
  schedule_completion (a);
  return TRUE;
}

static gboolean
webflow (FlatpakTransaction *tx, const char *remote, const char *url,
         GVariant *options, guint id, Auth *a)
{
  (void) tx;
  TRACE_SIGNAL (FlatpakTransaction, "webflow-start");
  check_thread (a);
  g_assert_cmpuint (a->pre, ==, 1);
  g_assert_cmpuint (++a->start, ==, 1);
  g_assert_cmpstr (remote, ==, "fixture");
  g_assert_true (g_variant_is_of_type (options, G_VARIANT_TYPE_VARDICT));
  g_assert_true (g_str_has_prefix (url, "http://127.0.0.1:"));
  a->id = id;
  if (strcmp (a->mode, "web-decline") == 0)
    return FALSE;
  if (strcmp (a->mode, "web-abort") == 0)
    schedule_completion (a);
  else
    {
      g_autoptr(GError) error = NULL;
      g_autoptr(GUri) uri = g_uri_parse (url, G_URI_FLAGS_NONE, &error);
      g_autoptr(GSocketClient) client = g_socket_client_new ();
      g_autoptr(GSocketConnection) connection = NULL;
      g_autofree char *request = NULL;
      g_assert_no_error (error);
      connection = g_socket_client_connect_to_host (client, g_uri_get_host (uri),
                                                    g_uri_get_port (uri), NULL, &error);
      g_assert_no_error (error);
      request = g_strdup_printf ("GET %s HTTP/1.0\r\nAuthorization: Bearer %s\r\n\r\n",
                                 g_uri_get_path (uri),
                                 strcmp (a->mode, "web-wrong") == 0 ? "wrong" : "test-password");
      g_assert_true (g_output_stream_write_all (g_io_stream_get_output_stream (G_IO_STREAM (connection)),
                                               request, strlen (request), NULL, NULL, &error));
      g_assert_no_error (error);
    }
  return TRUE;
}

static void
web_done (FlatpakTransaction *tx, GVariant *options, guint id, Auth *a)
{
  (void) tx;
  TRACE_SIGNAL (FlatpakTransaction, "webflow-done");
  check_thread (a);
  g_assert_true (g_variant_is_of_type (options, G_VARIANT_TYPE_VARDICT));
  g_assert_cmpuint (a->start, ==, 1);
  g_assert_cmpuint (id, ==, a->id);
  g_assert_cmpuint (++a->done, ==, 1);
}

static void
install_required (FlatpakTransaction *tx, const char *remote, const char *ref, Auth *a)
{
  TRACE_SIGNAL (FlatpakTransaction, "install-authenticator");
  check_thread (a);
  g_assert_true (tx == a->transaction);
  g_assert_cmpstr (remote, ==, "fixture");
  g_assert_cmpstr (ref, ==, a->ref);
  g_assert_cmpuint (++a->start, ==, 1);
  /* Decline by returning without installing the suggested app. */
}

static gboolean
accept_install (FlatpakTransaction *tx, gpointer data)
{
  (void) tx;
  (void) data;
  return TRUE;
}

static void
install_authenticator (FlatpakTransaction *tx, const char *remote, const char *ref, Auth *a)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakTransaction) install = NULL;
  g_autoptr(FlatpakInstalledRef) installed = NULL;
  g_autoptr(GDBusConnection) bus = NULL;
  g_auto(GStrv) parts = g_strsplit (ref, "/", -1);
  int64_t deadline;
  gboolean owned = FALSE;

  TRACE_SIGNAL (FlatpakTransaction, "install-authenticator");
  check_thread (a);
  g_assert_true (tx == a->transaction);
  g_assert_cmpstr (remote, ==, "fixture");
  g_assert_cmpstr (ref, ==, a->candidate);
  g_assert_cmpuint (++a->install, ==, 1);
  installed = CALL_API (flatpak_installation_get_installed_ref, a->installation,
                       FLATPAK_REF_KIND_APP, parts[1], parts[2], parts[3], NULL, &error);
  g_assert_null (installed);
  g_assert_error (error, FLATPAK_ERROR, FLATPAK_ERROR_NOT_INSTALLED);
  g_clear_error (&error);
  install = CALL_API (flatpak_transaction_new_for_installation, a->installation, NULL, &error);
  g_assert_no_error (error);
  g_signal_connect (install, "ready", G_CALLBACK (accept_install), NULL);
  g_assert_true (CALL_API (flatpak_transaction_add_install, install, remote, ref, NULL, &error));
  g_assert_no_error (error);
  g_assert_true (CALL_API (flatpak_transaction_run, install, NULL, &error));
  g_assert_no_error (error);
  installed = CALL_API (flatpak_installation_get_installed_ref, a->installation,
                       FLATPAK_REF_KIND_APP, parts[1], parts[2], parts[3], NULL, &error);
  g_assert_no_error (error);
  g_assert_cmpstr (CALL_API (flatpak_ref_get_commit, FLATPAK_REF (installed)), ==,
                  a->candidate_commit);

  /* Launch only the newly installed app through the target's public CLI. The
   * service implementation is an independently prepared fixture, not a host
   * replacement that could satisfy authentication without installing the app. */
  a->service = g_subprocess_new (G_SUBPROCESS_FLAGS_STDOUT_PIPE | G_SUBPROCESS_FLAGS_STDERR_PIPE,
                               &error, a->cli, "run", "--user", "--die-with-parent",
                               a->candidate, "basic",
                               a->ref, a->commit, a->parent, a->remote_url, NULL);
  g_assert_no_error (error);
  bus = g_bus_get_sync (G_BUS_TYPE_SESSION, NULL, &error);
  g_assert_no_error (error);
  deadline = g_get_monotonic_time () + 10 * G_TIME_SPAN_SECOND;
  while (!owned && g_get_monotonic_time () < deadline)
    {
      g_autoptr(GVariant) reply = g_dbus_connection_call_sync (
          bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
          "NameHasOwner", g_variant_new ("(s)", "org.flatpak.BlackboxAuthenticator"),
          G_VARIANT_TYPE ("(b)"), G_DBUS_CALL_FLAGS_NONE, 1000, NULL, &error);
      g_assert_no_error (error);
      g_variant_get (reply, "(b)", &owned);
      if (g_subprocess_get_identifier (a->service) == NULL)
        break;
      if (!owned)
        g_usleep (20000);
    }
  if (!owned)
    {
      g_autofree char *output = NULL;
      g_autofree char *diagnostic = NULL;
      g_subprocess_force_exit (a->service);
      g_subprocess_communicate_utf8 (a->service, NULL, NULL, &output, &diagnostic, NULL);
      g_error ("installed authenticator failed to start: %s %s", output, diagnostic);
    }
}

static void
required_authenticator (const char *protected_ref, const char *candidate)
{
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakInstallation) installation =
    CALL_API (flatpak_installation_new_user, NULL, &error);
  g_assert_no_error (error);
  g_autoptr(FlatpakTransaction) tx = CALL_API (
      flatpak_transaction_new_for_installation, installation, NULL, &error);
  g_assert_no_error (error);
  Auth a = { .ref = candidate, .transaction = tx, .thread = g_thread_self () };
  g_signal_connect (tx, "install-authenticator", G_CALLBACK (install_required), &a);
  g_assert_true (CALL_API (flatpak_transaction_add_install,
      tx, "fixture", protected_ref, NULL, &error));
  g_assert_no_error (error);
  g_assert_false (CALL_API (flatpak_transaction_run, tx, NULL, &error));
  g_assert_nonnull (error);
  g_assert_cmpuint (a.start, ==, 1);
  g_clear_error (&error);
  g_autoptr(GPtrArray) installed = CALL_API (
      flatpak_installation_list_installed_refs, installation, NULL, &error);
  g_assert_no_error (error);
  g_assert_cmpuint (installed->len, ==, 0);
  g_print ("auth-install-declined\n");
}

int
blackbox_auth_main (int argc, char **argv)
{
  if (argc >= 2 && strcmp (argv[1], "auth-install-required") == 0)
    {
      g_assert_cmpint (argc, ==, 4);
      required_authenticator (argv[2], argv[3]);
      return 0;
    }
  g_autoptr(GError) error = NULL;
  g_autoptr(FlatpakInstallation) installation = NULL;
  g_autoptr(FlatpakTransaction) tx = NULL;
  gboolean result, success;
  Auth a = { 0 };
  gboolean installing = argc >= 2 && strcmp (argv[1], "auth-install-success") == 0;
  if (argc < 2 || (strcmp (argv[1], "auth-run") != 0 && !installing))
    return -1;
  g_assert_cmpint (argc, ==, installing ? 11 : 6);
  a.mode = argv[2]; a.ref = argv[3]; a.commit = argv[4]; a.thread = g_thread_self ();
  installation = CALL_API (flatpak_installation_new_user, NULL, &error);
  g_assert_no_error (error);
  tx = CALL_API (flatpak_transaction_new_for_installation, installation, NULL, &error);
  g_assert_no_error (error);
  a.transaction = tx;
  if (installing)
    {
      a.installation = installation;
      a.parent = argv[5];
      a.candidate = argv[6];
      a.candidate_commit = argv[7];
      a.remote_url = argv[8];
      a.cli = argv[9];
      a.runtime_ref = argv[10];
      g_signal_connect (tx, "install-authenticator", G_CALLBACK (install_authenticator), &a);
    }
  g_assert_null (CALL_API (flatpak_transaction_get_parent_window, tx));
  CALL_API (flatpak_transaction_set_parent_window, tx, argv[5]);
  g_assert_cmpstr (CALL_API (flatpak_transaction_get_parent_window, tx), ==, argv[5]);
  g_signal_connect (tx, "ready-pre-auth", G_CALLBACK (pre_auth), &a);
  g_signal_connect (tx, "ready", G_CALLBACK (ready), &a);
  g_signal_connect (tx, "basic-auth-start", G_CALLBACK (basic), &a);
  g_signal_connect (tx, "webflow-start", G_CALLBACK (webflow), &a);
  g_signal_connect (tx, "webflow-done", G_CALLBACK (web_done), &a);
  g_assert_true (CALL_API (flatpak_transaction_add_install, tx, "fixture", a.ref, NULL, &error));
  g_assert_no_error (error);
  result = CALL_API (flatpak_transaction_run, tx, NULL, &error);
  success = strcmp (a.mode, "basic") == 0 || strcmp (a.mode, "web") == 0;
  g_assert_cmpint (result, ==, success);
  if (success)
    g_assert_no_error (error);
  else
    g_assert_nonnull (error);
  g_assert_cmpuint (a.pre, ==, 1);
  g_assert_cmpuint (a.start, ==, strcmp (a.mode, "pre-abort") != 0);
  g_assert_cmpuint (a.ready, ==, success);
  if (strcmp (a.mode, "web") == 0 || strcmp (a.mode, "web-wrong") == 0)
    g_assert_cmpuint (a.done, ==, 1);
  if (installing)
    {
      g_autofree char *output = NULL;
      g_autofree char *diagnostic = NULL;
      g_assert_cmpuint (a.install, ==, 1);
      g_assert_nonnull (a.service);
      g_subprocess_force_exit (a.service);
      g_assert_true (g_subprocess_communicate_utf8 (a.service, NULL, NULL,
                                                  &output, &diagnostic, &error));
      g_assert_no_error (error);
      g_assert_nonnull (strstr (output, "service-ready\n"));
      g_assert_nonnull (strstr (output, "response 0\n"));
      g_print ("%s", output);
      g_clear_object (&a.service);
    }
  g_print ("auth-result\t%d\n", result);
  return 0;
}
