/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define POLKIT_AGENT_I_KNOW_API_IS_SUBJECT_TO_CHANGE 1
#include <polkitagent/polkitagent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <unistd.h>

typedef struct { PolkitAgentListener parent; } RecordingAgent;
typedef struct { PolkitAgentListenerClass parent; } RecordingAgentClass;
GType recording_agent_get_type (void);
G_DEFINE_TYPE (RecordingAgent, recording_agent, POLKIT_AGENT_TYPE_LISTENER)

static void
initiate (PolkitAgentListener *listener, const gchar *action, const gchar *message,
          const gchar *icon, PolkitDetails *details, const gchar *cookie,
          GList *identities, GCancellable *cancellable, GAsyncReadyCallback callback,
          gpointer data)
{
  (void) message; (void) icon; (void) details; (void) cookie; (void) identities;
  g_print ("REQUEST %s\n", action);
  fflush (stdout);
  g_autoptr(GTask) task = g_task_new (listener, cancellable, callback, data);
  g_task_return_new_error (task, POLKIT_ERROR, POLKIT_ERROR_CANCELLED,
                           "Blackbox recording agent rejects authentication");
}

static gboolean
finish (PolkitAgentListener *listener, GAsyncResult *result, GError **error)
{
  (void) listener;
  return g_task_propagate_boolean (G_TASK (result), error);
}

static void
recording_agent_class_init (RecordingAgentClass *klass)
{
  PolkitAgentListenerClass *parent = POLKIT_AGENT_LISTENER_CLASS (klass);
  parent->initiate_authentication = initiate;
  parent->initiate_authentication_finish = finish;
}

static void recording_agent_init (RecordingAgent *self) { (void) self; }

int
main (int argc, char **argv)
{
  g_assert_cmpint (argc, ==, 2);
  pid_t client = (pid_t) strtol (argv[1], NULL, 10);
  g_assert_cmpint (prctl (PR_SET_PDEATHSIG, SIGTERM), ==, 0);
  g_assert_cmpint (getppid (), ==, client);
  g_assert_cmpuint (getuid (), !=, 0);
  g_autoptr(PolkitSubject) subject = polkit_unix_process_new_for_owner (client, 0, getuid ());
  g_autoptr(PolkitAgentListener) agent = g_object_new (recording_agent_get_type (), NULL);
  GError *error = NULL;
  gpointer registration = polkit_agent_listener_register (
    agent, POLKIT_AGENT_REGISTER_FLAGS_NONE, subject, "/org/flatpak/BlackboxAgent", NULL, &error);
  g_assert_no_error (error);
  g_assert_nonnull (registration);
  puts ("READY");
  fflush (stdout);
  g_autoptr(GMainLoop) loop = g_main_loop_new (NULL, FALSE);
  g_main_loop_run (loop);
  polkit_agent_listener_unregister (registration);
  return 0;
}
