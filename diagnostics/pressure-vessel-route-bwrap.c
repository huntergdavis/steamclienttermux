#define _GNU_SOURCE

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_ARGS_DATA (16U * 1024U * 1024U)
#define MAX_ROUTE_DATA (64U * 1024U)

static void
fail (const char *format, ...)
{
  va_list ap;

  fputs ("steam-arm64-bwrap-route: ", stderr);
  va_start (ap, format);
  vfprintf (stderr, format, ap);
  va_end (ap);
  fputc ('\n', stderr);
  exit (125);
}

static void
set_inherited (int fd, const char *description)
{
  int flags = fcntl (fd, F_GETFD);

  if (flags < 0 || fcntl (fd, F_SETFD, flags & ~FD_CLOEXEC) < 0)
    fail ("cannot inherit %s fd: %s", description, strerror (errno));
}

static void
write_all (int fd, const void *data, size_t size)
{
  const unsigned char *cursor = data;

  while (size > 0)
    {
      ssize_t written = write (fd, cursor, size);

      if (written < 0)
        {
          if (errno == EINTR)
            continue;

          fail ("cannot write replacement argument stream: %s",
                strerror (errno));
        }

      cursor += (size_t) written;
      size -= (size_t) written;
    }
}

static void
write_arg (int fd, const char *arg)
{
  write_all (fd, arg, strlen (arg) + 1);
}

static unsigned char *
read_args (int fd, size_t *size_out)
{
  struct stat st;
  unsigned char *data;
  size_t offset = 0;

  if (fstat (fd, &st) < 0)
    fail ("cannot stat --args fd: %s", strerror (errno));

  if (!S_ISREG (st.st_mode) || st.st_size <= 0
      || (uintmax_t) st.st_size > MAX_ARGS_DATA)
    fail ("unexpected --args fd type or size");

  data = malloc ((size_t) st.st_size);
  if (data == NULL)
    fail ("out of memory reading --args fd");

  while (offset < (size_t) st.st_size)
    {
      ssize_t got = pread (fd, data + offset,
                           (size_t) st.st_size - offset, (off_t) offset);

      if (got < 0)
        {
          if (errno == EINTR)
            continue;

          fail ("cannot read --args fd: %s", strerror (errno));
        }

      if (got == 0)
        fail ("short read from --args fd");

      offset += (size_t) got;
    }

  if (data[offset - 1] != '\0')
    fail ("--args data is not NUL-terminated");

  *size_out = offset;
  return data;
}

static size_t
find_proc_mount_end (const unsigned char *data, size_t size)
{
  size_t offset = 0;
  size_t proc_mount_end = 0;
  bool previous_was_proc = false;

  while (offset < size)
    {
      const char *arg = (const char *) data + offset;
      const unsigned char *end = memchr (arg, '\0', size - offset);
      size_t length;

      if (end == NULL)
        fail ("malformed --args data");

      length = (size_t) (end - (const unsigned char *) arg);

      if (previous_was_proc && strcmp (arg, "/proc") == 0)
        proc_mount_end = offset + length + 1;

      previous_was_proc = strcmp (arg, "--proc") == 0;
      offset += length + 1;
    }

  return proc_mount_end;
}

static void
validate_regular_file (int fd, const char *description, bool allow_empty)
{
  struct stat st;

  if (fstat (fd, &st) < 0)
    fail ("cannot stat %s: %s", description, strerror (errno));

  if (!S_ISREG (st.st_mode) || (!allow_empty && st.st_size <= 0)
      || (uintmax_t) st.st_size > MAX_ROUTE_DATA)
    fail ("%s is not a valid small regular file", description);

  if (st.st_uid != geteuid ())
    fail ("%s is not owned by the current user", description);

  if ((st.st_mode & 0022) != 0)
    fail ("%s must not be group- or other-writable", description);
}

static int
validate_proc_net (const char *path)
{
  DIR *directory;
  struct dirent *entry;
  struct stat st;
  int directory_fd;
  int scan_fd;
  int route_fd;
  int ipv6_route_fd;

  if (path == NULL || path[0] != '/')
    fail ("STEAM_ARM64_PROC_NET must be an absolute path");

  directory_fd = open (path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
  if (directory_fd < 0)
    fail ("cannot open /proc/net shadow: %s", strerror (errno));

  if (fstat (directory_fd, &st) < 0)
    fail ("cannot stat /proc/net shadow: %s", strerror (errno));

  if (!S_ISDIR (st.st_mode) || st.st_uid != geteuid ()
      || (st.st_mode & 0022) != 0)
    fail ("/proc/net shadow must be a private directory owned by the current user");

  route_fd = openat (directory_fd, "route", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (route_fd < 0)
    fail ("cannot open route snapshot: %s", strerror (errno));
  validate_regular_file (route_fd, "route snapshot", false);
  close (route_fd);

  ipv6_route_fd = openat (directory_fd, "ipv6_route",
                          O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (ipv6_route_fd < 0)
    fail ("cannot open IPv6 route snapshot: %s", strerror (errno));
  validate_regular_file (ipv6_route_fd, "IPv6 route snapshot", true);
  close (ipv6_route_fd);

  scan_fd = dup (directory_fd);
  if (scan_fd < 0)
    fail ("cannot duplicate /proc/net shadow fd: %s", strerror (errno));
  directory = fdopendir (scan_fd);
  if (directory == NULL)
    {
      close (scan_fd);
      fail ("cannot scan /proc/net shadow: %s", strerror (errno));
    }

  errno = 0;
  while ((entry = readdir (directory)) != NULL)
    {
      if (strcmp (entry->d_name, ".") == 0
          || strcmp (entry->d_name, "..") == 0
          || strcmp (entry->d_name, "route") == 0
          || strcmp (entry->d_name, "ipv6_route") == 0)
        continue;

      fail ("unexpected entry in /proc/net shadow: %s", entry->d_name);
    }

  if (errno != 0)
    fail ("cannot finish scanning /proc/net shadow: %s", strerror (errno));

  closedir (directory);
  set_inherited (directory_fd, "/proc/net shadow");
  return directory_fd;
}

static int
create_args_fd (void)
{
  char temporary[] = "/tmp/steam-arm64-bwrap-args.XXXXXX";
  int fd = mkstemp (temporary);

  if (fd < 0)
    fail ("cannot create replacement --args fd: %s", strerror (errno));

  if (unlink (temporary) < 0)
    fail ("cannot unlink replacement --args file: %s", strerror (errno));

  set_inherited (fd, "replacement --args");
  return fd;
}

static bool
parse_fd (const char *value, int *fd_out)
{
  char *end = NULL;
  long parsed;

  errno = 0;
  parsed = strtol (value, &end, 10);

  if (errno != 0 || value[0] == '\0' || end == NULL || end[0] != '\0'
      || parsed < 0 || parsed > INT_MAX)
    return false;

  *fd_out = (int) parsed;
  return true;
}

int
main (int argc, char **argv)
{
  const char *real_bwrap = getenv ("STEAM_ARM64_REAL_BWRAP");
  const char *proc_net_path = getenv ("STEAM_ARM64_PROC_NET");
  const char *fd_value = NULL;
  char **replacement_argv;
  char replacement_fd_value[32];
  unsigned char *args_data;
  size_t args_size;
  size_t insertion_offset;
  int args_index = -1;
  int args_fd = -1;
  int proc_net_fd;
  int replacement_fd;
  int i;

  if (real_bwrap == NULL || real_bwrap[0] != '/')
    fail ("STEAM_ARM64_REAL_BWRAP must be an absolute path");

  if (strcmp (real_bwrap, argv[0]) == 0)
    fail ("real bwrap path would recurse into this wrapper");

  for (i = 1; i < argc; i++)
    {
      if (strcmp (argv[i], "--args") == 0)
        {
          if (i + 1 >= argc)
            fail ("--args is missing its fd");

          args_index = i + 1;
          fd_value = argv[args_index];
          break;
        }

      if (strncmp (argv[i], "--args=", 7) == 0)
        {
          args_index = i;
          fd_value = argv[i] + 7;
          break;
        }
    }

  /* Pressure Vessel's feature checks use ordinary argv. Delegate those and
   * any unexpected invocation unchanged. Its real container mount plan is
   * the NUL-delimited --args stream. */
  if (args_index < 0)
    {
      execv (real_bwrap, argv);
      fail ("cannot execute real bwrap: %s", strerror (errno));
    }

  if (!parse_fd (fd_value, &args_fd))
    fail ("invalid --args fd");

  args_data = read_args (args_fd, &args_size);
  insertion_offset = find_proc_mount_end (args_data, args_size);

  if (insertion_offset == 0)
    {
      free (args_data);
      execv (real_bwrap, argv);
      fail ("cannot execute real bwrap: %s", strerror (errno));
    }

  proc_net_fd = validate_proc_net (proc_net_path);
  replacement_fd = create_args_fd ();
  write_all (replacement_fd, args_data, insertion_offset);

  snprintf (replacement_fd_value, sizeof (replacement_fd_value), "%d",
            proc_net_fd);
  write_arg (replacement_fd, "--ro-bind-fd");
  write_arg (replacement_fd, replacement_fd_value);
  write_arg (replacement_fd, "/proc/net");
  write_all (replacement_fd, args_data + insertion_offset,
             args_size - insertion_offset);
  free (args_data);

  if (lseek (replacement_fd, 0, SEEK_SET) < 0)
    fail ("cannot rewind replacement --args fd: %s", strerror (errno));

  snprintf (replacement_fd_value, sizeof (replacement_fd_value), "%d",
            replacement_fd);
  replacement_argv = calloc ((size_t) argc + 1, sizeof (*replacement_argv));
  if (replacement_argv == NULL)
    fail ("out of memory building bwrap argv");

  for (i = 0; i < argc; i++)
    replacement_argv[i] = argv[i];

  if (strncmp (argv[args_index], "--args=", 7) == 0)
    {
      size_t length = strlen (replacement_fd_value) + 8;
      char *combined = malloc (length);

      if (combined == NULL)
        fail ("out of memory building --args option");

      snprintf (combined, length, "--args=%s", replacement_fd_value);
      replacement_argv[args_index] = combined;
    }
  else
    {
      replacement_argv[args_index] = replacement_fd_value;
    }

  /* The replacement stream is complete and inherited. Do not leak Pressure
   * Vessel's superseded stream into srt-bwrap or its payload. */
  if (close (args_fd) < 0)
    fail ("cannot close original --args fd: %s", strerror (errno));

  execv (real_bwrap, replacement_argv);
  fail ("cannot execute real bwrap: %s", strerror (errno));
}
