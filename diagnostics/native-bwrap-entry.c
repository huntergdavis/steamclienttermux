#define _GNU_SOURCE

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static void
fail (const char *message)
{
  int error = errno;

  fprintf (stderr, "steam-arm64-native-bwrap-entry: %s", message);
  if (error != 0)
    fprintf (stderr, ": %s", strerror (error));
  fputc ('\n', stderr);
  exit (125);
}

int
main (int argc, char **argv)
{
  static const char *const removed_variables[] = {
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "GLIBC_LD_LIBRARY_PATH",
    "TGCOMPAT_LD_SO",
    "TGCOMPAT_LIBRARY_PATH",
    "TGCOMPAT_EXEC_MATCH_INTERPRETER",
    "TGCOMPAT_EXEC_LD_PRELOAD",
    "TGCOMPAT_EXEC_SHELL",
    "TGCOMPAT_EXEC_PATH_FROM",
    "TGCOMPAT_EXEC_PATH_TO",
    NULL,
  };
  const char *prefix = getenv ("PREFIX");
  const char *base = getenv ("STEAM_ARM64_BASE");
  const char *program_name;
  struct stat metadata;
  char shell[PATH_MAX];
  char script[PATH_MAX];
  char **arguments;
  size_t index;

  errno = 0;
  if (prefix == NULL || prefix[0] != '/' || base == NULL || base[0] != '/')
    fail ("PREFIX and STEAM_ARM64_BASE must be absolute");
  if (snprintf (shell, sizeof (shell), "%s/bin/bash", prefix) < 0
      || strlen (shell) >= sizeof (shell)
      || snprintf (script, sizeof (script),
                   "%s/compat-bin/steam-arm64-native-bwrap", base) < 0
      || strlen (script) >= sizeof (script))
    fail ("bridge path is too long");
  program_name = strrchr (argv[0], '/');
  program_name = program_name == NULL ? argv[0] : program_name + 1;
  if (strcmp (program_name, "_v2-entry-point") == 0)
    {
      if (setenv ("STEAM_ARM64_NATIVE_BRIDGE_MODE", "runtime", 1) < 0)
        fail ("cannot select the runtime bridge");
    }
  else if (setenv ("STEAM_ARM64_NATIVE_BRIDGE_MODE", "bwrap", 1) < 0)
    fail ("cannot select the bwrap bridge");
  if (lstat (script, &metadata) < 0)
    fail ("cannot inspect bridge script");
  if (!S_ISREG (metadata.st_mode) || metadata.st_uid != geteuid ()
      || (metadata.st_mode & 0022) != 0)
    {
      errno = 0;
      fail ("bridge script is not a protected owned regular file");
    }
  if (access (shell, X_OK) < 0)
    fail ("Bionic Bash is unavailable");

  arguments = calloc ((size_t) argc + 2U, sizeof (*arguments));
  if (arguments == NULL)
    fail ("cannot allocate bridge arguments");
  arguments[0] = shell;
  arguments[1] = script;
  for (index = 1; index < (size_t) argc; index++)
    arguments[index + 1U] = argv[index];

  for (index = 0; removed_variables[index] != NULL; index++)
    if (unsetenv (removed_variables[index]) < 0)
      fail ("cannot sanitize loader environment");

  execv (shell, arguments);
  fail ("cannot enter the Bionic game bridge");
  return 125;
}
