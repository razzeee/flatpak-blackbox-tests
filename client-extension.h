/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef BLACKBOX_CLIENT_EXTENSION_H
#define BLACKBOX_CLIENT_EXTENSION_H

#include <flatpak.h>

#define CALL_API(function, ...) \
  (g_printerr ("api-call " #function "\n"), function (__VA_ARGS__))
#define TRACE_SIGNAL(owner, name) \
  g_printerr ("signal-event " #owner "." name "\n")

/* Extensions return -1 for commands they do not handle. */
int blackbox_extension_main (int argc, char **argv);

#endif
