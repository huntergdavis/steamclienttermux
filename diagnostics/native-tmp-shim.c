#define _GNU_SOURCE

#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>
#include <sys/un.h>
#include <sys/types.h>
#include <unistd.h>
#include <utime.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static bool resolve_next(void *destination, size_t size, const char *name) {
    void *symbol = dlsym(RTLD_NEXT, name);

    if (symbol == NULL || size != sizeof(symbol)) {
        errno = ENOSYS;
        return false;
    }
    memcpy(destination, &symbol, size);
    return true;
}

static const char *rewrite_path(const char *path, char output[PATH_MAX]) {
    const char *root;
    const char *suffix;
    size_t root_length;
    size_t suffix_length;

    if (path == NULL) {
        return NULL;
    }
    if (strcmp(path, "/tmp") == 0) {
        suffix = "";
        root = getenv("STEAM_ARM64_TMP_ROOT");
    } else if (strncmp(path, "/tmp/", 5) == 0) {
        suffix = path + 4;
        root = getenv("STEAM_ARM64_TMP_ROOT");
    } else if (strcmp(path, "/dev/shm") == 0) {
        suffix = "";
        root = getenv("STEAM_ARM64_SHM_ROOT");
    } else if (strncmp(path, "/dev/shm/", 9) == 0) {
        suffix = path + 8;
        root = getenv("STEAM_ARM64_SHM_ROOT");
    } else if (strcmp(path, "/etc/ssl") == 0 ||
            strncmp(path, "/etc/ssl/", 9) == 0) {
        suffix = path;
        root = getenv("STEAM_ARM64_LINUX_ROOT");
    } else {
        return path;
    }

    if (root == NULL || root[0] != '/') {
        return path;
    }
    root_length = strlen(root);
    if (root_length < 2 || root[root_length - 1] == '/') {
        return path;
    }
    suffix_length = strlen(suffix);
    if (suffix_length >= PATH_MAX ||
            root_length > PATH_MAX - suffix_length - 1) {
        errno = ENAMETOOLONG;
        return NULL;
    }
    memcpy(output, root, root_length);
    memcpy(output + root_length, suffix, suffix_length + 1);
    return output;
}

#define DEFINE_ONE_PATH_INT(name, arguments, call_arguments)                 \
    int name arguments {                                                     \
        static int (*next) arguments;                                        \
        char rewritten[PATH_MAX];                                            \
        const char *mapped = rewrite_path(path, rewritten);                  \
        if (mapped == NULL ||                                                \
                (next == NULL &&                                             \
                    !resolve_next(&next, sizeof(next), #name))) {             \
            return -1;                                                       \
        }                                                                    \
        return next call_arguments;                                          \
    }

DEFINE_ONE_PATH_INT(access, (const char *path, int mode), (mapped, mode))
DEFINE_ONE_PATH_INT(chmod, (const char *path, mode_t mode), (mapped, mode))
DEFINE_ONE_PATH_INT(chown, (const char *path, uid_t owner, gid_t group),
    (mapped, owner, group))
DEFINE_ONE_PATH_INT(mkdir, (const char *path, mode_t mode), (mapped, mode))
DEFINE_ONE_PATH_INT(remove, (const char *path), (mapped))
DEFINE_ONE_PATH_INT(rmdir, (const char *path), (mapped))
DEFINE_ONE_PATH_INT(unlink, (const char *path), (mapped))
DEFINE_ONE_PATH_INT(stat, (const char *path, struct stat *buffer),
    (mapped, buffer))
DEFINE_ONE_PATH_INT(lstat, (const char *path, struct stat *buffer),
    (mapped, buffer))
DEFINE_ONE_PATH_INT(statfs, (const char *path, struct statfs *buffer),
    (mapped, buffer))
DEFINE_ONE_PATH_INT(statfs64, (const char *path, struct statfs64 *buffer),
    (mapped, buffer))
DEFINE_ONE_PATH_INT(statvfs, (const char *path, struct statvfs *buffer),
    (mapped, buffer))
DEFINE_ONE_PATH_INT(statvfs64, (const char *path, struct statvfs64 *buffer),
    (mapped, buffer))
DEFINE_ONE_PATH_INT(utime, (const char *path, const struct utimbuf *times),
    (mapped, times))
DEFINE_ONE_PATH_INT(utimes, (const char *path, const struct timeval times[2]),
    (mapped, times))

#define DEFINE_XSTAT(name, stat_type)                                        \
    int name(int version, const char *path, stat_type *buffer) {              \
        static int (*next)(int, const char *, stat_type *);                   \
        char rewritten[PATH_MAX];                                            \
        const char *mapped = rewrite_path(path, rewritten);                  \
        if (mapped == NULL ||                                                \
                (next == NULL &&                                             \
                    !resolve_next(&next, sizeof(next), #name))) {             \
            return -1;                                                       \
        }                                                                    \
        return next(version, mapped, buffer);                                \
    }

DEFINE_XSTAT(__xstat, struct stat)
DEFINE_XSTAT(__lxstat, struct stat)
DEFINE_XSTAT(__xstat64, struct stat64)
DEFINE_XSTAT(__lxstat64, struct stat64)

static bool open_has_mode(int flags) {
    if ((flags & O_CREAT) != 0) {
        return true;
    }
#ifdef O_TMPFILE
    return (flags & O_TMPFILE) == O_TMPFILE;
#else
    return false;
#endif
}

#define DEFINE_OPEN(name)                                                    \
    int name(const char *path, int flags, ...) {                             \
        static int (*next)(const char *, int, ...);                          \
        char rewritten[PATH_MAX];                                            \
        const char *mapped = rewrite_path(path, rewritten);                  \
        mode_t mode = 0;                                                     \
        if (open_has_mode(flags)) {                                          \
            va_list arguments;                                               \
            va_start(arguments, flags);                                      \
            mode = va_arg(arguments, mode_t);                                \
            va_end(arguments);                                               \
        }                                                                    \
        if (mapped == NULL ||                                                \
                (next == NULL &&                                             \
                    !resolve_next(&next, sizeof(next), #name))) {             \
            return -1;                                                       \
        }                                                                    \
        return open_has_mode(flags)                                          \
            ? next(mapped, flags, mode) : next(mapped, flags);               \
    }

DEFINE_OPEN(open)
DEFINE_OPEN(open64)

#define DEFINE_FOPEN(name)                                                   \
    FILE *name(const char *path, const char *mode) {                         \
        static FILE *(*next)(const char *, const char *);                    \
        char rewritten[PATH_MAX];                                            \
        const char *mapped = rewrite_path(path, rewritten);                  \
        if (mapped == NULL ||                                                \
                (next == NULL &&                                             \
                    !resolve_next(&next, sizeof(next), #name))) {             \
            return NULL;                                                     \
        }                                                                    \
        return next(mapped, mode);                                           \
    }

DEFINE_FOPEN(fopen)
DEFINE_FOPEN(fopen64)

DIR *opendir(const char *path) {
    static DIR *(*next)(const char *);
    char rewritten[PATH_MAX];
    const char *mapped = rewrite_path(path, rewritten);

    if (mapped == NULL ||
            (next == NULL && !resolve_next(&next, sizeof(next), "opendir"))) {
        return NULL;
    }
    return next(mapped);
}

static const char *virtual_proc_self_exe(const char *path) {
    const char *target;
    size_t target_length;

    if (path == NULL || strcmp(path, "/proc/self/exe") != 0) {
        return NULL;
    }
    target = getenv("TGCOMPAT_PROC_SELF_EXE");
    if (target == NULL || target[0] != '/') {
        return NULL;
    }
    target_length = strlen(target);
    if (target_length < 2 || target_length >= PATH_MAX) {
        return NULL;
    }
    return target;
}

static ssize_t copy_link_target(const char *target, char *buffer,
        size_t size) {
    size_t target_length;
    size_t copy_length;

    if (size == 0) {
        errno = EINVAL;
        return -1;
    }
    target_length = strlen(target);
    copy_length = target_length < size ? target_length : size;
    memcpy(buffer, target, copy_length);
    return (ssize_t)copy_length;
}

ssize_t readlink(const char *path, char *buffer, size_t size) {
    static ssize_t (*next)(const char *, char *, size_t);
    char rewritten[PATH_MAX];
    const char *virtual_target = virtual_proc_self_exe(path);
    const char *mapped;

    if (virtual_target != NULL) {
        return copy_link_target(virtual_target, buffer, size);
    }
    mapped = rewrite_path(path, rewritten);

    if (mapped == NULL ||
            (next == NULL && !resolve_next(&next, sizeof(next), "readlink"))) {
        return -1;
    }
    return next(mapped, buffer, size);
}

ssize_t readlinkat(int descriptor, const char *path, char *buffer,
        size_t size) {
    static ssize_t (*next)(int, const char *, char *, size_t);
    char rewritten[PATH_MAX];
    const char *virtual_target = virtual_proc_self_exe(path);
    const char *mapped;

    if (virtual_target != NULL) {
        return copy_link_target(virtual_target, buffer, size);
    }
    mapped = rewrite_path(path, rewritten);
    if (mapped == NULL ||
            (next == NULL &&
                !resolve_next(&next, sizeof(next), "readlinkat"))) {
        return -1;
    }
    return next(descriptor, mapped, buffer, size);
}

char *realpath(const char *path, char *resolved) {
    static char *(*next)(const char *, char *);
    char rewritten[PATH_MAX];
    const char *mapped = rewrite_path(path, rewritten);

    if (mapped == NULL ||
            (next == NULL && !resolve_next(&next, sizeof(next), "realpath"))) {
        return NULL;
    }
    return next(mapped, resolved);
}

#define DEFINE_TWO_PATH_INT(name)                                            \
    int name(const char *source, const char *destination) {                  \
        static int (*next)(const char *, const char *);                      \
        char source_buffer[PATH_MAX];                                        \
        char destination_buffer[PATH_MAX];                                   \
        const char *mapped_source = rewrite_path(source, source_buffer);     \
        const char *mapped_destination =                                    \
            rewrite_path(destination, destination_buffer);                   \
        if (mapped_source == NULL || mapped_destination == NULL ||           \
                (next == NULL &&                                             \
                    !resolve_next(&next, sizeof(next), #name))) {             \
            return -1;                                                       \
        }                                                                    \
        return next(mapped_source, mapped_destination);                      \
    }

DEFINE_TWO_PATH_INT(link)
DEFINE_TWO_PATH_INT(rename)

int symlink(const char *target, const char *path) {
    static int (*next)(const char *, const char *);
    char rewritten[PATH_MAX];
    const char *mapped = rewrite_path(path, rewritten);

    if (mapped == NULL ||
            (next == NULL && !resolve_next(&next, sizeof(next), "symlink"))) {
        return -1;
    }
    return next(target, mapped);
}

static int rewrite_unix_address(const struct sockaddr *address,
        socklen_t length, struct sockaddr_un *output,
        socklen_t *output_length) {
    const struct sockaddr_un *unix_address;
    size_t path_capacity;
    size_t path_length;
    char rewritten[PATH_MAX];
    const char *mapped;

    if (address == NULL || address->sa_family != AF_UNIX ||
            length <= offsetof(struct sockaddr_un, sun_path)) {
        return 0;
    }
    unix_address = (const struct sockaddr_un *)address;
    path_capacity = length - offsetof(struct sockaddr_un, sun_path);
    if (unix_address->sun_path[0] != '/' ||
            path_capacity > sizeof(unix_address->sun_path)) {
        return 0;
    }
    path_length = strnlen(unix_address->sun_path, path_capacity);
    if (path_length == path_capacity) {
        return 0;
    }
    mapped = rewrite_path(unix_address->sun_path, rewritten);
    if (mapped == NULL) {
        return -1;
    }
    if (mapped == unix_address->sun_path) {
        return 0;
    }
    path_length = strlen(mapped);
    if (path_length >= sizeof(output->sun_path)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    memset(output, 0, sizeof(*output));
    output->sun_family = AF_UNIX;
    memcpy(output->sun_path, mapped, path_length + 1);
    *output_length = (socklen_t)(offsetof(struct sockaddr_un, sun_path) +
        path_length + 1);
    return 1;
}

#define DEFINE_SOCKET_PATH(name)                                             \
    int name(int descriptor, const struct sockaddr *address,                 \
            socklen_t length) {                                              \
        static int (*next)(int, const struct sockaddr *, socklen_t);         \
        struct sockaddr_un rewritten;                                        \
        socklen_t rewritten_length = 0;                                      \
        int result = rewrite_unix_address(address, length, &rewritten,        \
            &rewritten_length);                                              \
        if (result < 0 ||                                                    \
                (next == NULL &&                                             \
                    !resolve_next(&next, sizeof(next), #name))) {             \
            return -1;                                                       \
        }                                                                    \
        return result == 0                                                   \
            ? next(descriptor, address, length)                              \
            : next(descriptor, (const struct sockaddr *)&rewritten,          \
                rewritten_length);                                           \
    }

/* glibc declares these through a GCC transparent union. The exported ABI is
 * still a sockaddr pointer, but -Wpedantic diagnoses the matching definition. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
DEFINE_SOCKET_PATH(bind)
DEFINE_SOCKET_PATH(connect)
#pragma GCC diagnostic pop
