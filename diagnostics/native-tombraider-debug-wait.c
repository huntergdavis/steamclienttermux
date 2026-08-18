#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifndef STEAM_ARM64_DEBUG_WAIT_SECONDS
#define STEAM_ARM64_DEBUG_WAIT_SECONDS 30
#endif

static bool is_tombraider_preloader(void) {
    char command[8192];
    char probe[512];
    char *argument;
    char *end;
    ssize_t length;
    size_t remaining;
    size_t target_length;
    int descriptor;
    int probe_length;
    ssize_t written;

    descriptor = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
    if (descriptor < 0) {
        return false;
    }
    length = read(descriptor, command, sizeof(command) - 1);
    close(descriptor);
    if (length <= 0 || (size_t)length >= sizeof(command)) {
        return false;
    }
    command[length] = '\0';
    argument = command;
    remaining = (size_t)length;
    for (int index = 0; index < 2; ++index) {
        end = memchr(argument, '\0', remaining);
        if (end == NULL) {
            return false;
        }
        remaining -= (size_t)(end + 1 - argument);
        argument = end + 1;
    }
    if (remaining < 2) {
        return false;
    }
    target_length = strnlen(argument, remaining);
    probe_length = snprintf(
        probe,
        sizeof(probe),
        "TOMB_RAIDER_DEBUG_ARG2_PID=%ld VALUE=%.*s\n",
        (long)getpid(),
        (int)(target_length < 320 ? target_length : 320),
        argument
    );
    if (probe_length > 0 && (size_t)probe_length < sizeof(probe)) {
        written = write(STDERR_FILENO, probe, (size_t)probe_length);
        (void)written;
    }
    if (argument[0] != 'Z' || argument[1] != ':') {
        return false;
    }
    static const char suffix[] = "TombRaider.exe";
    if (target_length < sizeof(suffix) - 1 || target_length == remaining) {
        return false;
    }
    return memcmp(
        argument + target_length - (sizeof(suffix) - 1),
        suffix,
        sizeof(suffix) - 1
    ) == 0;
}

__attribute__((constructor)) static void tombraider_debug_wait(void) {
    char message[128];
    struct timespec delay = {
        .tv_sec = STEAM_ARM64_DEBUG_WAIT_SECONDS,
        .tv_nsec = 0,
    };
    int length;
    ssize_t written;

    if (!is_tombraider_preloader()) {
        return;
    }
    length = snprintf(
        message,
        sizeof(message),
        "TOMB_RAIDER_DEBUG_WAIT_PID=%ld SECONDS=%d\n",
        (long)getpid(),
        STEAM_ARM64_DEBUG_WAIT_SECONDS
    );
    if (length > 0 && (size_t)length < sizeof(message)) {
        written = write(STDERR_FILENO, message, (size_t)length);
        (void)written;
    }
    while (nanosleep(&delay, &delay) != 0 && errno == EINTR) {
    }
}
