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
#define GTAIV_APP_ID "12210"
#define GTAIV_VIEW_SUFFIX "/gtaiv-exec-view-12210"
#define GTAIV_PLAY_SUFFIX "/Grand Theft Auto IV/GTAIV/PlayGTAIV.exe"
#define GTAIV_SERVICE_FIRST_BATCH "C:\\gtaiv-service-first.cmd"
#define PROC_NET_SUFFIX "/config/proc-net"
#define HOST_VK_ICD_SUFFIX "/mesa-kgsl/icd.d/freedreno-private.json"

struct expected_file
{
  const char *name;
  off_t size;
};

static const struct expected_file gtaiv_files[] = {
  { "GTAIV.exe", 17425752 },
  { "MTLX.dll", 593240 },
  { "PlayGTAIV.exe", 264176 },
  { "binkw32.dll", 176640 },
  { "commandline.txt", 24 },
  { "gtaEncoder.exe", 47960 },
  { "installscript.vdf", 566 },
  { "metadata.dat", 472036 },
  { "steam_api.dll", 261072 },
  { "title.rgl", 1104 },
};

static const char *gtaiv_directories[] = {
  "Manuals",
  "Redistributables",
  "TBoGT",
  "TLAD",
  "common",
  "movies",
  "pc",
};

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

static size_t
find_payload_terminator (const unsigned char *data, size_t size)
{
  size_t offset = 0;

  while (offset < size)
    {
      const char *arg = (const char *) data + offset;
      const unsigned char *end = memchr (arg, '\0', size - offset);
      size_t length;

      if (end == NULL)
        fail ("malformed --args data");

      length = (size_t) (end - (const unsigned char *) arg);
      if (strcmp (arg, "--") == 0)
        return offset;
      offset += length + 1;
    }

  return 0;
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

static bool
is_expected_gtaiv_entry (const char *name)
{
  size_t i;

  for (i = 0; i < sizeof (gtaiv_files) / sizeof (gtaiv_files[0]); i++)
    if (strcmp (name, gtaiv_files[i].name) == 0)
      return true;

  for (i = 0;
       i < sizeof (gtaiv_directories) / sizeof (gtaiv_directories[0]);
       i++)
    if (strcmp (name, gtaiv_directories[i]) == 0)
      return true;

  return false;
}

static int
validate_gtaiv_view (const char *proc_net_path, int proc_net_fd,
                     char *target, size_t target_size,
                     int directory_fds[], size_t directory_fds_count)
{
  static const char install_tail[] =
    "/steamapps/common/Grand Theft Auto IV";
  const char *app_id = getenv ("STEAM_COMPAT_APP_ID");
  const char *install_path = getenv ("STEAM_COMPAT_INSTALL_PATH");
  struct stat proc_net_stat;
  struct stat view_stat;
  char source[PATH_MAX];
  size_t proc_net_length;
  size_t install_length;
  int directory_fd;
  int scan_fd;
  DIR *directory;
  struct dirent *entry;
  size_t i;

  if (directory_fds_count
      != sizeof (gtaiv_directories) / sizeof (gtaiv_directories[0]))
    fail ("unexpected GTA IV directory fd array size");
  for (i = 0; i < directory_fds_count; i++)
    directory_fds[i] = -1;

  if (app_id == NULL || strcmp (app_id, GTAIV_APP_ID) != 0)
    return -1;

  proc_net_length = strlen (proc_net_path);
  if (proc_net_length <= strlen (PROC_NET_SUFFIX)
      || strcmp (proc_net_path + proc_net_length - strlen (PROC_NET_SUFFIX),
                 PROC_NET_SUFFIX) != 0)
    return -1;

  if (snprintf (source, sizeof (source), "%.*s%s",
                (int) (proc_net_length - strlen (PROC_NET_SUFFIX)),
                proc_net_path, GTAIV_VIEW_SUFFIX) < 0
      || strlen (source) >= sizeof (source))
    fail ("GTA IV view path is too long");

  if (lstat (source, &view_stat) < 0)
    {
      if (errno == ENOENT)
        return -1;
      fail ("cannot inspect GTA IV view: %s", strerror (errno));
    }

  if (install_path == NULL || install_path[0] != '/')
    fail ("GTA IV install path is missing or not absolute");
  install_length = strlen (install_path);
  if (install_length <= strlen (install_tail)
      || strcmp (install_path + install_length - strlen (install_tail),
                 install_tail) != 0)
    fail ("unexpected GTA IV install path: %s", install_path);
  if (snprintf (target, target_size, "%s/GTAIV", install_path) < 0
      || strlen (target) >= target_size)
    fail ("GTA IV target path is too long");

  if (!S_ISDIR (view_stat.st_mode) || view_stat.st_uid != geteuid ()
      || (view_stat.st_mode & 0077) != 0)
    fail ("GTA IV view must be a private directory owned by the current user");

  directory_fd = open (source,
                       O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
  if (directory_fd < 0)
    fail ("cannot open GTA IV view: %s", strerror (errno));
  if (fstat (directory_fd, &view_stat) < 0
      || fstat (proc_net_fd, &proc_net_stat) < 0)
    fail ("cannot stat GTA IV view: %s", strerror (errno));
  if (view_stat.st_dev != proc_net_stat.st_dev)
    fail ("GTA IV view is not on the internal Steam filesystem");

  for (i = 0; i < sizeof (gtaiv_files) / sizeof (gtaiv_files[0]); i++)
    {
      struct stat st;
      int fd = openat (directory_fd, gtaiv_files[i].name,
                       O_RDONLY | O_CLOEXEC | O_NOFOLLOW);

      if (fd < 0 || fstat (fd, &st) < 0)
        fail ("cannot inspect GTA IV view file %s: %s",
              gtaiv_files[i].name, strerror (errno));
      if (!S_ISREG (st.st_mode) || st.st_uid != geteuid ()
          || (st.st_mode & 0022) != 0 || st.st_nlink != 1
          || st.st_size != gtaiv_files[i].size)
        fail ("unexpected GTA IV view file: %s", gtaiv_files[i].name);
      close (fd);
    }

  for (i = 0;
       i < sizeof (gtaiv_directories) / sizeof (gtaiv_directories[0]);
       i++)
    {
      struct stat st;
      char original[PATH_MAX];
      int mountpoint_fd;
      int original_fd;
      DIR *mountpoint;
      struct dirent *mountpoint_entry;

      if (fstatat (directory_fd, gtaiv_directories[i], &st,
                   AT_SYMLINK_NOFOLLOW) < 0
          || !S_ISDIR (st.st_mode) || st.st_uid != geteuid ()
          || st.st_dev != view_stat.st_dev || (st.st_mode & 0077) != 0)
        fail ("GTA IV view mountpoint is not a private internal directory: %s",
              gtaiv_directories[i]);

      mountpoint_fd = openat (directory_fd, gtaiv_directories[i],
                              O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
      if (mountpoint_fd < 0)
        fail ("cannot open GTA IV view mountpoint %s: %s",
              gtaiv_directories[i], strerror (errno));
      mountpoint = fdopendir (mountpoint_fd);
      if (mountpoint == NULL)
        {
          close (mountpoint_fd);
          fail ("cannot scan GTA IV view mountpoint %s: %s",
                gtaiv_directories[i], strerror (errno));
        }
      errno = 0;
      while ((mountpoint_entry = readdir (mountpoint)) != NULL)
        {
          if (strcmp (mountpoint_entry->d_name, ".") == 0
              || strcmp (mountpoint_entry->d_name, "..") == 0)
            continue;
          fail ("GTA IV view mountpoint is not empty: %s",
                gtaiv_directories[i]);
        }
      if (errno != 0)
        fail ("cannot finish scanning GTA IV view mountpoint %s: %s",
              gtaiv_directories[i], strerror (errno));
      closedir (mountpoint);

      if (snprintf (original, sizeof (original), "%s/GTAIV/%s",
                    install_path, gtaiv_directories[i]) < 0
          || strlen (original) >= sizeof (original))
        fail ("GTA IV original directory path is too long");
      original_fd = open (original,
                          O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_DIRECTORY);
      if (original_fd < 0 || fstat (original_fd, &st) < 0
          || !S_ISDIR (st.st_mode))
        fail ("cannot open original GTA IV directory %s: %s",
              gtaiv_directories[i], strerror (errno));
      set_inherited (original_fd, gtaiv_directories[i]);
      directory_fds[i] = original_fd;
    }

  scan_fd = dup (directory_fd);
  if (scan_fd < 0)
    fail ("cannot duplicate GTA IV view fd: %s", strerror (errno));
  directory = fdopendir (scan_fd);
  if (directory == NULL)
    {
      close (scan_fd);
      fail ("cannot scan GTA IV view: %s", strerror (errno));
    }
  errno = 0;
  while ((entry = readdir (directory)) != NULL)
    {
      if (strcmp (entry->d_name, ".") == 0
          || strcmp (entry->d_name, "..") == 0
          || is_expected_gtaiv_entry (entry->d_name))
        continue;
      fail ("unexpected entry in GTA IV view: %s", entry->d_name);
    }
  if (errno != 0)
    fail ("cannot finish scanning GTA IV view: %s", strerror (errno));
  closedir (directory);
  set_inherited (directory_fd, "GTA IV view");
  return directory_fd;
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

static void
validate_host_vk_driver_files (const char *proc_net_path, const char *path)
{
  char expected[PATH_MAX];
  size_t proc_net_length;
  int fd;

  if (path == NULL)
    return;
  if (path[0] != '/')
    fail ("STEAM_ARM64_HOST_VK_DRIVER_FILES must be an absolute path");

  proc_net_length = strlen (proc_net_path);
  if (proc_net_length <= strlen (PROC_NET_SUFFIX)
      || strcmp (proc_net_path + proc_net_length - strlen (PROC_NET_SUFFIX),
                 PROC_NET_SUFFIX) != 0)
    fail ("cannot derive native Vulkan ICD path");
  if (snprintf (expected, sizeof (expected), "%.*s%s",
                (int) (proc_net_length - strlen (PROC_NET_SUFFIX)),
                proc_net_path, HOST_VK_ICD_SUFFIX) < 0
      || strlen (expected) >= sizeof (expected))
    fail ("native Vulkan ICD path is too long");
  if (strcmp (path, expected) != 0)
    fail ("unexpected native Vulkan ICD path: %s", path);

  fd = open (path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (fd < 0)
    fail ("cannot open native Vulkan ICD: %s", strerror (errno));
  validate_regular_file (fd, "native Vulkan ICD", false);
  close (fd);
}

static int
create_args_fd (void)
{
  const char *tmpdir = getenv ("TMPDIR");
  char temporary[PATH_MAX];
  size_t tmpdir_length;
  int fd;
  int length;

  if (tmpdir == NULL || tmpdir[0] != '/')
    tmpdir = "/tmp";

  tmpdir_length = strlen (tmpdir);
  length = snprintf (temporary, sizeof (temporary),
                     "%s%ssteam-arm64-bwrap-args.XXXXXX", tmpdir,
                     tmpdir_length > 0 && tmpdir[tmpdir_length - 1] == '/'
                       ? "" : "/");
  if (length < 0 || (size_t) length >= sizeof (temporary))
    fail ("temporary directory path is too long");

  fd = mkstemp (temporary);

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

static bool
is_decimal_app_id (const char *value)
{
  size_t length;
  size_t i;

  if (value == NULL || value[0] == '\0')
    return false;

  length = strlen (value);
  if (length > 20)
    return false;

  for (i = 0; i < length; i++)
    {
      if (value[i] < '0' || value[i] > '9')
        return false;
    }

  return true;
}

static bool
has_suffix (const char *value, const char *suffix)
{
  size_t value_length;
  size_t suffix_length;

  if (value == NULL || suffix == NULL)
    return false;

  value_length = strlen (value);
  suffix_length = strlen (suffix);
  return value_length >= suffix_length
    && strcmp (value + value_length - suffix_length, suffix) == 0;
}

static bool
is_gtaiv_play_payload (int argc, char **argv, int args_index,
                       int gtaiv_view_fd)
{
  int payload_start = args_index + 1;

  if (gtaiv_view_fd < 0)
    return false;

  if (strcmp (argv[args_index], "--args") == 0)
    payload_start++;

  return argc - payload_start >= 2
    && strcmp (argv[argc - 2], "waitforexitandrun") == 0
    && has_suffix (argv[argc - 1], GTAIV_PLAY_SUFFIX);
}

static void
ensure_steam_game_id (void)
{
  const char *game_id = getenv ("SteamGameId");
  const char *fallback;

  /* Steam prerequisite/install-script launches can omit SteamGameId.  The
   * ARM64 Proton FEX setup currently dereferences it unconditionally, even
   * though STEAM_COMPAT_APP_ID remains available for the same launch. */
  if (game_id != NULL && game_id[0] != '\0')
    return;

  fallback = getenv ("STEAM_COMPAT_APP_ID");
  if (!is_decimal_app_id (fallback))
    fallback = getenv ("SteamAppId");

  if (is_decimal_app_id (fallback)
      && setenv ("SteamGameId", fallback, 1) < 0)
    fail ("cannot set SteamGameId fallback: %s", strerror (errno));
}

int
main (int argc, char **argv)
{
  const char *real_bwrap = getenv ("STEAM_ARM64_REAL_BWRAP");
  const char *proc_net_path = getenv ("STEAM_ARM64_PROC_NET");
  const char *host_vk_driver_files =
    getenv ("STEAM_ARM64_HOST_VK_DRIVER_FILES");
  const char *fd_value = NULL;
  char **replacement_argv;
  char replacement_fd_value[32];
  unsigned char *args_data;
  size_t args_size;
  size_t insertion_offset;
  size_t payload_offset;
  int args_index = -1;
  int args_fd = -1;
  int proc_net_fd;
  int gtaiv_view_fd;
  int gtaiv_directory_fds[
    sizeof (gtaiv_directories) / sizeof (gtaiv_directories[0])];
  int replacement_fd;
  bool gtaiv_service_first;
  char gtaiv_target[PATH_MAX];
  char gtaiv_directory_target[PATH_MAX];
  int i;

  if (real_bwrap == NULL || real_bwrap[0] != '/')
    fail ("STEAM_ARM64_REAL_BWRAP must be an absolute path");

  if (strcmp (real_bwrap, argv[0]) == 0)
    fail ("real bwrap path would recurse into this wrapper");

  ensure_steam_game_id ();

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
  validate_host_vk_driver_files (proc_net_path, host_vk_driver_files);
  gtaiv_view_fd = validate_gtaiv_view (proc_net_path, proc_net_fd,
                                       gtaiv_target, sizeof (gtaiv_target),
                                       gtaiv_directory_fds,
                                       sizeof (gtaiv_directory_fds)
                                         / sizeof (gtaiv_directory_fds[0]));
  payload_offset = find_payload_terminator (args_data, args_size);
  /* Current Pressure Vessel puts the payload in ordinary argv after
   * --args, so the NUL stream can contain mounts only. Appending to that
   * stream is then the last-mount-wins position. Older forms can include a
   * literal -- terminator in the stream; insert immediately before it. */
  if (payload_offset == 0)
    payload_offset = args_size;
  if (payload_offset < insertion_offset)
    fail ("cannot locate payload boundary");
  gtaiv_service_first = is_gtaiv_play_payload (argc, argv, args_index,
                                               gtaiv_view_fd);
  replacement_fd = create_args_fd ();
  write_all (replacement_fd, args_data, insertion_offset);

  snprintf (replacement_fd_value, sizeof (replacement_fd_value), "%d",
            proc_net_fd);
  write_arg (replacement_fd, "--ro-bind-fd");
  write_arg (replacement_fd, replacement_fd_value);
  write_arg (replacement_fd, "/proc/net");
  write_all (replacement_fd, args_data + insertion_offset,
             payload_offset - insertion_offset);
  if (gtaiv_view_fd >= 0)
    {
      snprintf (replacement_fd_value, sizeof (replacement_fd_value), "%d",
                gtaiv_view_fd);
      write_arg (replacement_fd, "--ro-bind-fd");
      write_arg (replacement_fd, replacement_fd_value);
      write_arg (replacement_fd, gtaiv_target);
      for (i = 0;
           i < (int) (sizeof (gtaiv_directories)
                      / sizeof (gtaiv_directories[0]));
           i++)
        {
          if (snprintf (gtaiv_directory_target,
                        sizeof (gtaiv_directory_target), "%s/%s",
                        gtaiv_target, gtaiv_directories[i]) < 0
              || strlen (gtaiv_directory_target)
                   >= sizeof (gtaiv_directory_target))
            fail ("GTA IV directory target path is too long");
          snprintf (replacement_fd_value, sizeof (replacement_fd_value),
                    "%d", gtaiv_directory_fds[i]);
          write_arg (replacement_fd, "--ro-bind-fd");
          write_arg (replacement_fd, replacement_fd_value);
          write_arg (replacement_fd, gtaiv_directory_target);
        }
    }
  if (host_vk_driver_files != NULL)
    {
      /* Pressure Vessel rewrites the private host ICD to a generated
       * /overrides manifest. PRoot cannot materialize that individual
       * generated file, although the original protected host path remains
       * visible in the container. Final assignments for both the current and
       * legacy Vulkan-loader variables select the validated original manifest
       * without bypassing the provider library or the rest of Pressure
       * Vessel's overrides. Winevulkan consults the legacy name even when a
       * native Vulkan client prefers VK_DRIVER_FILES. */
      write_arg (replacement_fd, "--setenv");
      write_arg (replacement_fd, "VK_DRIVER_FILES");
      write_arg (replacement_fd, host_vk_driver_files);
      write_arg (replacement_fd, "--setenv");
      write_arg (replacement_fd, "VK_ICD_FILENAMES");
      write_arg (replacement_fd, host_vk_driver_files);
    }
  write_all (replacement_fd, args_data + payload_offset,
             args_size - payload_offset);
  free (args_data);

  if (lseek (replacement_fd, 0, SEEK_SET) < 0)
    fail ("cannot rewind replacement --args fd: %s", strerror (errno));

  snprintf (replacement_fd_value, sizeof (replacement_fd_value), "%d",
            replacement_fd);
  replacement_argv = calloc ((size_t) argc + 4, sizeof (*replacement_argv));
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

  if (gtaiv_service_first)
    {
      replacement_argv[argc - 1] = "cmd.exe";
      replacement_argv[argc] = "/d";
      replacement_argv[argc + 1] = "/c";
      replacement_argv[argc + 2] = GTAIV_SERVICE_FIRST_BATCH;
    }

  /* The replacement stream is complete and inherited. Do not leak Pressure
   * Vessel's superseded stream into srt-bwrap or its payload. */
  if (close (args_fd) < 0)
    fail ("cannot close original --args fd: %s", strerror (errno));
  if (unsetenv ("STEAM_ARM64_HOST_VK_DRIVER_FILES") < 0)
    fail ("cannot clear native Vulkan ICD handoff: %s", strerror (errno));

  execv (real_bwrap, replacement_argv);
  fail ("cannot execute real bwrap: %s", strerror (errno));
}
