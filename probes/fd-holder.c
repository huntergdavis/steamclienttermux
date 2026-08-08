#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int numeric(const char *s)
{
    if (!*s) return 0;
    while (*s) if (!isdigit((unsigned char)*s++)) return 0;
    return 1;
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s 'pipe:[inode]'\n", argv[0]);
        return 2;
    }

    DIR *proc = opendir("/proc");
    if (!proc) { perror("/proc"); return 1; }
    struct dirent *pe;
    int found = 0;

    while ((pe = readdir(proc))) {
        if (!numeric(pe->d_name)) continue;
        char fd_dir[PATH_MAX];
        snprintf(fd_dir, sizeof(fd_dir), "/proc/%s/fd", pe->d_name);
        DIR *fds = opendir(fd_dir);
        if (!fds) continue;

        struct dirent *fe;
        while ((fe = readdir(fds))) {
            if (!numeric(fe->d_name)) continue;
            char link_path[PATH_MAX], target[PATH_MAX];
            snprintf(link_path, sizeof(link_path), "%s/%s", fd_dir, fe->d_name);
            ssize_t n = readlink(link_path, target, sizeof(target) - 1);
            if (n < 0) continue;
            target[n] = '\0';
            if (strcmp(target, argv[1]) != 0) continue;

            char cmd_path[PATH_MAX], cmd[4096] = {0};
            snprintf(cmd_path, sizeof(cmd_path), "/proc/%s/cmdline", pe->d_name);
            FILE *fp = fopen(cmd_path, "r");
            size_t count = fp ? fread(cmd, 1, sizeof(cmd) - 1, fp) : 0;
            if (fp) fclose(fp);
            for (size_t i = 0; i < count; i++) if (cmd[i] == '\0') cmd[i] = ' ';
            printf("pid=%s fd=%s target=%s cmd=%s\n",
                   pe->d_name, fe->d_name, target, cmd);
            found++;
        }
        closedir(fds);
    }
    closedir(proc);
    return found ? 0 : 1;
}
