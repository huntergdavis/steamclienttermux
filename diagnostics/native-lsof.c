#define _GNU_SOURCE

#include <ctype.h>
#include <dirent.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static bool numeric_name(const char *name) {
    if (name == NULL || name[0] == '\0') {
        return false;
    }
    for (const unsigned char *cursor = (const unsigned char *)name;
            *cursor != '\0'; cursor++) {
        if (!isdigit(*cursor)) {
            return false;
        }
    }
    return true;
}

static bool build_proc_path(char output[PATH_MAX], const char *root,
        const char *pid, const char *leaf) {
    int written = snprintf(output, PATH_MAX, "%s/%s/%s", root, pid, leaf);

    return written > 0 && written < PATH_MAX;
}

static bool read_cmdline(const char *proc_root, const char *pid,
        char output[16384]) {
    char path[PATH_MAX];
    FILE *stream;
    size_t length;

    if (!build_proc_path(path, proc_root, pid, "cmdline")) {
        return false;
    }
    stream = fopen(path, "rb");
    if (stream == NULL) {
        return false;
    }
    length = fread(output, 1, 16383, stream);
    (void)fclose(stream);
    if (length == 0) {
        return false;
    }
    for (size_t index = 0; index < length; index++) {
        if (output[index] == '\0') {
            output[index] = ' ';
        }
    }
    output[length] = '\0';
    return true;
}

static long read_parent_pid(const char *proc_root, const char *pid) {
    char path[PATH_MAX];
    char line[256];
    FILE *stream;
    long parent = 0;

    if (!build_proc_path(path, proc_root, pid, "status")) {
        return 0;
    }
    stream = fopen(path, "r");
    if (stream == NULL) {
        return 0;
    }
    while (fgets(line, sizeof(line), stream) != NULL) {
        if (sscanf(line, "PPid:%ld", &parent) == 1) {
            break;
        }
    }
    (void)fclose(stream);
    return parent;
}

static const char *requested_port(int argc, char *argv[]) {
    static const char prefix[] = "TCP@127.0.0.1:";

    for (int index = 1; index < argc; index++) {
        if (strncmp(argv[index], prefix, sizeof(prefix) - 1) == 0 &&
                argv[index][sizeof(prefix) - 1] != '\0') {
            return argv[index] + sizeof(prefix) - 1;
        }
    }
    return NULL;
}

int main(int argc, char *argv[]) {
    const char *proc_root = getenv("STEAM_ARM64_LSOF_PROC_ROOT");
    const char *port = requested_port(argc, argv);
    DIR *directory;
    struct dirent *entry;
    bool found = false;

    if (port == NULL) {
        return 1;
    }
    if (proc_root == NULL || proc_root[0] == '\0') {
        proc_root = "/proc";
    }
    if (proc_root[0] != '/') {
        return 1;
    }
    directory = opendir(proc_root);
    if (directory == NULL) {
        return 1;
    }
    while ((entry = readdir(directory)) != NULL) {
        char command[16384];
        long parent;

        if (!numeric_name(entry->d_name) ||
                !read_cmdline(proc_root, entry->d_name, command) ||
                strstr(command, "/steamrtarm64/steamwebhelper") == NULL ||
                strstr(command, "NetworkService") == NULL) {
            continue;
        }
        parent = read_parent_pid(proc_root, entry->d_name);
        printf("p%s\nR%ld\nu%ld\nn127.0.0.1:%s->127.0.0.1:27060\n",
            entry->d_name, parent, (long)geteuid(), port);
        found = true;
    }
    (void)closedir(directory);
    return found ? 0 : 1;
}
