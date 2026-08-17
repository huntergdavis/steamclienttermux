#!/usr/bin/env python3
"""Exercise the native Steam /tmp path shim outside the Android device."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap


REPO_ROOT = Path(__file__).resolve().parent.parent
SHIM_SOURCE = REPO_ROOT / "diagnostics" / "native-tmp-shim.c"

DRIVER_SOURCE = r"""
#define _GNU_SOURCE

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

static void fail(const char *operation) {
    perror(operation);
    exit(1);
}

int main(void) {
    char directory[256];
    char marker[320];
    char scratch[320];
    char renamed[320];
    char socket_path[320];
    char shm_marker[320];
    char link_target[320];
    char certificate[32];
    struct sockaddr_un address;
    struct stat metadata;
    DIR *stream;
    FILE *file;
    int descriptor;
    int server;
    int client;
    int accepted;
    ssize_t link_length;
    socklen_t address_length;

    if (snprintf(directory, sizeof(directory),
            "/tmp/steam-native-tmp-shim-%ld", (long)getpid()) < 0) {
        fail("snprintf directory");
    }
    if (snprintf(shm_marker, sizeof(shm_marker),
            "/dev/shm/steam-native-shm-shim-%ld", (long)getpid()) < 0) {
        fail("snprintf shm marker");
    }
    if (mkdir(directory, 0700) != 0) {
        fail("mkdir");
    }
    if (snprintf(marker, sizeof(marker), "%s/marker", directory) < 0 ||
            snprintf(scratch, sizeof(scratch), "%s/scratch", directory) < 0 ||
            snprintf(renamed, sizeof(renamed), "%s/renamed", directory) < 0 ||
            snprintf(socket_path, sizeof(socket_path), "%s/socket", directory) < 0) {
        fail("snprintf paths");
    }

    file = fopen(marker, "w");
    if (file == NULL || fputs("mapped\n", file) == EOF || fclose(file) != 0) {
        fail("fopen marker");
    }
    descriptor = open(scratch, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (descriptor < 0 || write(descriptor, "x", 1) != 1 ||
            close(descriptor) != 0) {
        fail("open scratch");
    }
    if (rename(scratch, renamed) != 0 || unlink(renamed) != 0) {
        fail("rename/unlink");
    }
    descriptor = openat(AT_FDCWD, shm_marker,
        O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (descriptor < 0 || write(descriptor, "shm\n", 4) != 4 ||
            close(descriptor) != 0) {
        fail("openat shm marker");
    }
    if (faccessat(AT_FDCWD, "/dev/shm", W_OK | X_OK, 0) != 0 ||
            fstatat(AT_FDCWD, shm_marker, &metadata, 0) != 0 ||
            metadata.st_size != 4) {
        fail("faccessat/fstatat shm marker");
    }
    if (access(marker, R_OK) != 0 || stat(marker, &metadata) != 0 ||
            metadata.st_size != 7) {
        fail("access/stat");
    }
    stream = opendir(directory);
    if (stream == NULL || closedir(stream) != 0) {
        fail("opendir");
    }

    file = fopen("/etc/ssl/certs/ca-certificates.crt", "r");
    if (file == NULL || fgets(certificate, sizeof(certificate), file) == NULL ||
            fclose(file) != 0 || strcmp(certificate, "mapped-cert\n") != 0) {
        fail("mapped certificate");
    }
    link_length = readlink("/proc/self/exe", link_target,
        sizeof(link_target) - 1);
    if (link_length < 0) {
        fail("readlink proc self exe");
    }
    link_target[link_length] = '\0';
    if (strcmp(link_target, "/virtual/original/steam") != 0) {
        errno = EINVAL;
        fail("readlink proc self exe value");
    }
    link_length = readlinkat(AT_FDCWD, "/proc/self/exe", link_target,
        sizeof(link_target) - 1);
    if (link_length < 0) {
        fail("readlinkat proc self exe");
    }
    link_target[link_length] = '\0';
    if (strcmp(link_target, "/virtual/original/steam") != 0) {
        errno = EINVAL;
        fail("readlinkat proc self exe value");
    }

    if (strlen(socket_path) >= sizeof(address.sun_path)) {
        errno = ENAMETOOLONG;
        fail("socket path length");
    }
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    memcpy(address.sun_path, socket_path, strlen(socket_path) + 1);
    address_length = (socklen_t)(offsetof(struct sockaddr_un, sun_path) +
        strlen(address.sun_path) + 1);
    server = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server < 0 || bind(server, (const struct sockaddr *)&address,
            address_length) != 0 || listen(server, 1) != 0) {
        fail("bind/listen");
    }
    client = socket(AF_UNIX, SOCK_STREAM, 0);
    if (client < 0 || connect(client, (const struct sockaddr *)&address,
            address_length) != 0) {
        fail("connect");
    }
    accepted = accept(server, NULL, NULL);
    if (accepted < 0 || close(accepted) != 0 || close(client) != 0 ||
            close(server) != 0 || unlink(socket_path) != 0) {
        fail("accept/cleanup socket");
    }

    puts(directory);
    puts(shm_marker);
    return 0;
}
"""


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, **kwargs)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="native-tmp-shim-test-") as temporary:
        temporary_path = Path(temporary)
        mapped_root = temporary_path / "mapped"
        mapped_root.mkdir(mode=0o700)
        mapped_shm_root = temporary_path / "mapped-shm"
        mapped_shm_root.mkdir(mode=0o700)
        linux_root = temporary_path / "linux-root"
        certificate_dir = linux_root / "etc" / "ssl" / "certs"
        certificate_dir.mkdir(parents=True, mode=0o700)
        (certificate_dir / "ca-certificates.crt").write_text(
            "mapped-cert\n", encoding="utf-8"
        )
        shim = temporary_path / "native-tmp-shim.so"
        driver_source = temporary_path / "driver.c"
        driver = temporary_path / "driver"
        driver_source.write_text(textwrap.dedent(DRIVER_SOURCE), encoding="utf-8")

        common_warnings = [
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wpedantic",
            "-Wformat=2",
            "-Wshadow",
        ]
        run(
            [
                os.environ.get("CC", "cc"),
                "-std=c11",
                "-O2",
                "-fPIC",
                "-shared",
                *common_warnings,
                str(SHIM_SOURCE),
                "-ldl",
                "-o",
                str(shim),
            ]
        )
        run(
            [
                os.environ.get("CC", "cc"),
                "-std=c11",
                "-O2",
                *common_warnings,
                str(driver_source),
                "-o",
                str(driver),
            ]
        )
        environment = os.environ.copy()
        environment.update(
            {
                "LD_PRELOAD": str(shim),
                "STEAM_ARM64_TMP_ROOT": str(mapped_root),
                "STEAM_ARM64_SHM_ROOT": str(mapped_shm_root),
                "STEAM_ARM64_LINUX_ROOT": str(linux_root),
                "TGCOMPAT_PROC_SELF_EXE": "/virtual/original/steam",
            }
        )
        completed = run([str(driver)], env=environment, capture_output=True)
        output_lines = completed.stdout.splitlines()
        if len(output_lines) != 2:
            raise AssertionError(f"unexpected shim output: {completed.stdout!r}")
        virtual_directory = Path(output_lines[0])
        virtual_shm_marker = Path(output_lines[1])
        if virtual_directory.parent != Path("/tmp"):
            raise AssertionError(f"unexpected virtual directory: {virtual_directory}")
        if virtual_directory.exists():
            raise AssertionError(f"shim leaked into real /tmp: {virtual_directory}")
        mapped_directory = mapped_root / virtual_directory.name
        marker = mapped_directory / "marker"
        if marker.read_text(encoding="utf-8") != "mapped\n":
            raise AssertionError(f"mapped marker is incorrect: {marker}")
        if (mapped_directory / "socket").exists():
            raise AssertionError("mapped Unix socket was not removed")
        if virtual_shm_marker.parent != Path("/dev/shm"):
            raise AssertionError(f"unexpected virtual shm path: {virtual_shm_marker}")
        if virtual_shm_marker.exists():
            raise AssertionError(f"shim leaked into real /dev/shm: {virtual_shm_marker}")
        mapped_shm_marker = mapped_shm_root / virtual_shm_marker.name
        if mapped_shm_marker.read_text(encoding="utf-8") != "shm\n":
            raise AssertionError(f"mapped shm marker is incorrect: {mapped_shm_marker}")

    print("native /tmp shim tests: PASS")


if __name__ == "__main__":
    main()
