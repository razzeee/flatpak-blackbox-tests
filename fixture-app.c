/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

int
main (int argc, char **argv)
{
  if (argc == 1)
    {
      puts (VERSION);
      return 0;
    }
  if (strcmp (argv[1], "args") == 0)
    {
      for (size_t i = 2; i < (size_t) argc; i++)
        printf ("%s\n", argv[i]);
      return 0;
    }
  if (argc == 3 && (strcmp (argv[1], "env") == 0 ||
                    strcmp (argv[1], "getenv") == 0))
    {
      const char *value = getenv (argv[2]);
      if (value == NULL)
        return 1;
      puts (value);
      return 0;
    }
  if (argc == 3 && strcmp (argv[1], "exists") == 0)
    {
      struct stat st;
      if (stat (argv[2], &st) < 0)
        goto error;
      puts ("exists");
      return 0;
    }
  if (argc == 3 && strcmp (argv[1], "stat") == 0)
    {
      struct stat st;
      if (stat (argv[2], &st) < 0)
        goto error;
      printf ("%o %lu %lu\n", (unsigned int) (st.st_mode & 07777),
              (unsigned long) st.st_uid, (unsigned long) st.st_gid);
      return 0;
    }
  if (argc == 3 && strcmp (argv[1], "read") == 0)
    {
      char buffer[4096];
      size_t count;
      FILE *file = fopen (argv[2], "rb");
      if (file == NULL)
        goto error;
      while ((count = fread (buffer, 1, sizeof buffer, file)) != 0)
        if (fwrite (buffer, 1, count, stdout) != count)
          {
            fclose (file);
            goto error;
          }
      if (ferror (file))
        {
          fclose (file);
          goto error;
        }
      return fclose (file) == 0 ? 0 : 1;
    }
  if (argc == 4 && strcmp (argv[1], "write") == 0)
    {
      FILE *file = fopen (argv[2], "wb");
      if (file == NULL)
        goto error;
      if (fputs (argv[3], file) == EOF)
        {
          fclose (file);
          goto error;
        }
      return fclose (file) == 0 ? 0 : 1;
    }
  if (argc == 3 && strcmp (argv[1], "hold") == 0)
    {
      char *end;
      long seconds = strtol (argv[2], &end, 10);
      if (*end != '\0' || seconds < 0 || seconds > 3600)
        return 2;
      puts ("ready");
      fflush (stdout);
      while (seconds > 0)
        seconds = sleep ((unsigned int) seconds);
      return 0;
    }
  if (argc == 4 && strcmp (argv[1], "tcp-connect") == 0)
    {
      struct sockaddr_in address = { .sin_family = AF_INET };
      char *end;
      long port = strtol (argv[3], &end, 10);
      int fd;
      if (*end != '\0' || port < 1 || port > 65535 ||
          inet_pton (AF_INET, argv[2], &address.sin_addr) != 1)
        return 2;
      address.sin_port = htons ((unsigned short) port);
      fd = socket (AF_INET, SOCK_STREAM, 0);
      if (fd < 0)
        goto error;
      if (connect (fd, (struct sockaddr *) &address, sizeof address) < 0)
        {
          int saved_errno = errno;
          close (fd);
          errno = saved_errno;
          goto error;
        }
      close (fd);
      puts ("connected");
      return 0;
    }
  if (argc == 2 && strcmp (argv[1], "identity") == 0)
    {
      char cwd[4096];
      if (getcwd (cwd, sizeof cwd) == NULL)
        goto error;
      printf ("uid=%lu gid=%lu pid=%lu cwd=%s\n", (unsigned long) getuid (),
              (unsigned long) getgid (), (unsigned long) getpid (), cwd);
      return 0;
    }
  fputs ("unknown mode or incorrect argument count\n", stderr);
  return 2;

error:
  perror (argv[1]);
  return 1;
}
