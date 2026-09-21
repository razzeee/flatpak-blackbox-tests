/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Independent implementation of the documented Authenticator D-Bus wire API. */
#include <gio/gio.h>
#include <stdio.h>
#include <string.h>

#define AUTH "org.freedesktop.Flatpak.Authenticator"
#define REQUEST "org.freedesktop.Flatpak.AuthenticatorRequest"
#define OBJECT "/org/freedesktop/Flatpak/Authenticator"

static const char xml[] =
  "<node><interface name='" AUTH "'>"
  "<property name='version' type='u' access='read'/>"
  "<method name='RequestRefTokens'>"
  "<arg type='s' direction='in'/><arg type='a{sv}' direction='in'/>"
  "<arg type='s' direction='in'/><arg type='s' direction='in'/>"
  "<arg type='a(ssia{sv})' direction='in'/><arg type='a{sv}' direction='in'/>"
  "<arg type='s' direction='in'/><arg type='o' direction='out'/>"
  "</method></interface><interface name='" REQUEST "'>"
  "<method name='Close'/><method name='BasicAuthReply'>"
  "<arg type='s' direction='in'/><arg type='s' direction='in'/>"
  "<arg type='a{sv}' direction='in'/></method>"
  "<signal name='BasicAuth'><arg type='s'/><arg type='a{sv}'/></signal>"
  "<signal name='Webflow'><arg type='s'/><arg type='a{sv}'/></signal>"
  "<signal name='WebflowDone'><arg type='a{sv}'/></signal>"
  "<signal name='Response'><arg type='u'/><arg type='a{sv}'/></signal>"
  "</interface></node>";

typedef struct
{
  GDBusConnection *bus;
  GDBusNodeInfo *info;
  const char *mode, *ref, *commit, *parent, *remote_url, *expected_option;
  char *path, *sender;
  GSocketService *http;
  guint16 port;
  gboolean finished;
} Service;

static GVariant *
empty (void)
{
  return g_variant_new_array (G_VARIANT_TYPE ("{sv}"), NULL, 0);
}

static void
emit (Service *s, const char *signal, GVariant *parameters)
{
  g_autoptr(GError) error = NULL;
  g_assert_true (g_dbus_connection_emit_signal (s->bus, s->sender, s->path,
                                               REQUEST, signal, parameters, &error));
  g_assert_no_error (error);
  g_print ("signal %s\n", signal);
  fflush (stdout);
}

static void
finish (Service *s, guint status)
{
  GVariantBuilder results;
  g_assert_false (s->finished);
  s->finished = TRUE;
  g_variant_builder_init (&results, G_VARIANT_TYPE_VARDICT);
  if (status == 0)
    {
      GVariantBuilder tokens;
      const char *refs[] = { s->ref, NULL };
      g_variant_builder_init (&tokens, G_VARIANT_TYPE ("a{sas}"));
      g_variant_builder_add (&tokens, "{s^as}", "blackbox-download-token", refs);
      g_variant_builder_add (&results, "{sv}", "tokens", g_variant_builder_end (&tokens));
    }
  g_print ("response %u\n", status);
  emit (s, "Response", g_variant_new ("(u@a{sv})", status, g_variant_builder_end (&results)));
}

static gboolean
incoming (GSocketService *server, GSocketConnection *connection, GObject *source, gpointer data)
{
  Service *s = data;
  g_autoptr(GDataInputStream) input = NULL;
  g_autofree char *line = NULL;
  gboolean valid = FALSE;
  (void) server; (void) source;
  g_socket_set_timeout (g_socket_connection_get_socket (connection), 5);
  input = g_data_input_stream_new (g_io_stream_get_input_stream (G_IO_STREAM (connection)));
  line = g_data_input_stream_read_line (input, NULL, NULL, NULL);
  g_assert_cmpstr (line, ==, "GET /login HTTP/1.0\r");
  g_clear_pointer (&line, g_free);
  while ((line = g_data_input_stream_read_line (input, NULL, NULL, NULL)) != NULL)
    {
      if (strcmp (line, "Authorization: Bearer test-password\r") == 0)
        valid = TRUE;
      if (strcmp (line, "\r") == 0)
        break;
      g_clear_pointer (&line, g_free);
    }
  g_print ("web-credentials %d\n", valid);
  emit (s, "WebflowDone", g_variant_new ("(@a{sv})", empty ()));
  finish (s, valid ? 0 : 2);
  return TRUE;
}

static void
method (GDBusConnection *connection, const char *sender, const char *path,
        const char *interface, const char *name, GVariant *parameters,
        GDBusMethodInvocation *invocation, gpointer data);

static GVariant *
property (GDBusConnection *connection, const char *sender, const char *path,
          const char *interface, const char *name, GError **error, gpointer data)
{
  (void) connection; (void) sender; (void) path; (void) interface;
  (void) name; (void) error; (void) data;
  return g_variant_new_uint32 (1);
}

static const GDBusInterfaceVTable vtable = { method, property, NULL, { 0 } };

static void
method (GDBusConnection *connection, const char *sender, const char *path,
        const char *interface, const char *name, GVariant *parameters,
        GDBusMethodInvocation *invocation, gpointer data)
{
  Service *s = data;
  (void) connection; (void) path; (void) interface;
  if (strcmp (name, "RequestRefTokens") == 0)
    {
      const char *handle, *remote, *url, *parent;
      const char *ref, *commit;
      gint32 token_type;
      g_autoptr(GVariant) auth_options = NULL, refs = NULL, options = NULL, ref_options = NULL;
      g_autoptr(GError) error = NULL;
      g_autofree char *escaped = g_strdup (sender + 1);
      g_assert_null (s->path);
      g_variant_get (parameters, "(&s@a{sv}&s&s@a(ssia{sv})@a{sv}&s)",
                     &handle, &auth_options, &remote, &url, &refs, &options, &parent);
      g_assert_cmpstr (remote, ==, "fixture");
      g_assert_cmpstr (url, ==, s->remote_url);
      g_assert_cmpstr (parent, ==, s->parent);
      g_assert_cmpuint (g_variant_n_children (refs), ==, 1);
      g_variant_get_child (refs, 0, "(&s&si@a{sv})", &ref, &commit, &token_type, &ref_options);
      g_assert_cmpstr (ref, ==, s->ref);
      g_assert_cmpstr (commit, ==, s->commit);
      g_assert_cmpint (token_type, ==, 2);
      if (s->expected_option != NULL)
        {
          const char *value = NULL;
          g_assert_true (g_variant_lookup (auth_options, "blackbox", "&s", &value));
          g_assert_cmpstr (value, ==, s->expected_option);
          g_print ("auth-option blackbox %s\n", value);
        }
      for (char *p = escaped; *p; p++)
        if (*p == '.') *p = '_';
      s->sender = g_strdup (sender);
      s->path = g_strdup_printf (OBJECT "/request/%s/%s", escaped, handle);
      g_assert_cmpuint (g_dbus_connection_register_object (s->bus, s->path,
                        s->info->interfaces[1], &vtable, s, NULL, &error), !=, 0);
      g_assert_no_error (error);
      g_print ("request %s %s %s %s\n", ref, commit, parent, url);
      g_dbus_method_invocation_return_value (invocation, g_variant_new ("(o)", s->path));
      if (strcmp (s->mode, "options") == 0)
        finish (s, 0);
      else if (strcmp (s->mode, "web") == 0)
        {
          g_autofree char *login = g_strdup_printf ("http://127.0.0.1:%u/login", s->port);
          emit (s, "Webflow", g_variant_new ("(s@a{sv})", login, empty ()));
        }
      else
        emit (s, "BasicAuth", g_variant_new ("(s@a{sv})", "Blackbox protected runtime", empty ()));
    }
  else
    {
      g_assert_cmpstr (sender, ==, s->sender);
      g_dbus_method_invocation_return_value (invocation, NULL);
      if (strcmp (name, "Close") == 0)
        {
          g_print ("close\n");
          finish (s, 1);
        }
      else
        {
          const char *user, *password;
          g_autoptr(GVariant) options = NULL;
          gboolean valid;
          g_assert_cmpstr (name, ==, "BasicAuthReply");
          g_variant_get (parameters, "(&s&s@a{sv})", &user, &password, &options);
          valid = strcmp (user, "blackbox") == 0 && strcmp (password, "test-password") == 0;
          g_print ("basic-credentials %d\n", valid);
          finish (s, valid ? 0 : 2);
        }
    }
}

int
main (int argc, char **argv)
{
  Service s = { 0 };
  g_autoptr(GError) error = NULL;
  g_autoptr(GVariant) reply = NULL;
  g_autoptr(GMainLoop) loop = g_main_loop_new (NULL, FALSE);
  g_assert_true (argc == 6 || argc == 7);
  s.mode = argv[1]; s.ref = argv[2]; s.commit = argv[3];
  s.parent = argv[4]; s.remote_url = argv[5];
  s.expected_option = argc == 7 ? argv[6] : NULL;
  s.info = g_dbus_node_info_new_for_xml (xml, &error);
  g_assert_no_error (error);
  s.bus = g_bus_get_sync (G_BUS_TYPE_SESSION, NULL, &error);
  g_assert_no_error (error);
  g_assert_cmpuint (g_dbus_connection_register_object (s.bus, OBJECT, s.info->interfaces[0],
                    &vtable, &s, NULL, &error), !=, 0);
  g_assert_no_error (error);
  reply = g_dbus_connection_call_sync (s.bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                      "org.freedesktop.DBus", "RequestName",
                                      g_variant_new ("(su)", "org.flatpak.BlackboxAuthenticator", 4u),
                                      G_VARIANT_TYPE ("(u)"), 0, 5000, NULL, &error);
  g_assert_no_error (error);
  s.http = g_socket_service_new ();
  s.port = g_socket_listener_add_any_inet_port (G_SOCKET_LISTENER (s.http), NULL, &error);
  g_assert_no_error (error);
  g_signal_connect (s.http, "incoming", G_CALLBACK (incoming), &s);
  g_print ("service-ready\n");
  fflush (stdout);
  g_main_loop_run (loop);
  return 0;
}
