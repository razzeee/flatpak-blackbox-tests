/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Independent org.a11y.Bus address provider for a case-private D-Bus. */
#include <gio/gio.h>
#include <stdio.h>
#include <string.h>

static void
method (GDBusConnection *connection, const char *sender, const char *path,
        const char *interface, const char *name, GVariant *parameters,
        GDBusMethodInvocation *invocation, gpointer data)
{
  (void) connection; (void) sender; (void) path; (void) interface; (void) parameters;
  g_assert_cmpstr (name, ==, "GetAddress");
  g_print ("address-request\n");
  fflush (stdout);
  g_dbus_method_invocation_return_value (invocation, g_variant_new ("(s)", (const char *) data));
}

int
main (int argc, char **argv)
{
  const char *xml = "<node><interface name='org.a11y.Bus'><method name='GetAddress'>"
                    "<arg type='s' direction='out'/></method></interface></node>";
  const GDBusInterfaceVTable vtable = { method, NULL, NULL, { 0 } };
  g_autoptr(GError) error = NULL;
  g_autoptr(GDBusNodeInfo) info = g_dbus_node_info_new_for_xml (xml, &error);
  g_autoptr(GDBusConnection) bus = NULL;
  g_autoptr(GVariant) reply = NULL;
  g_autoptr(GMainLoop) loop = g_main_loop_new (NULL, FALSE);
  unsigned int acquired;
  g_assert_no_error (error);
  g_assert_cmpint (argc, ==, 2);
  bus = g_bus_get_sync (G_BUS_TYPE_SESSION, NULL, &error);
  g_assert_no_error (error);
  g_assert_cmpuint (g_dbus_connection_register_object (bus, "/org/a11y/bus", info->interfaces[0],
                    &vtable, argv[1], NULL, &error), !=, 0);
  g_assert_no_error (error);
  reply = g_dbus_connection_call_sync (bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                      "org.freedesktop.DBus", "RequestName",
                                      g_variant_new ("(su)", "org.a11y.Bus", 4u),
                                      G_VARIANT_TYPE ("(u)"), 0, 5000, NULL, &error);
  g_assert_no_error (error);
  g_variant_get (reply, "(u)", &acquired);
  g_assert_cmpuint (acquired, ==, 1);
  g_main_loop_run (loop);
  return 0;
}
