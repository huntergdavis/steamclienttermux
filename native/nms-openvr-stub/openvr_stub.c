/* SPDX-License-Identifier: MIT */
/* Flat-screen OpenVR shim: report that no headset is available. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <stdbool.h>
#include <stdint.h>

#define VR_INIT_ERROR_HMD_NOT_FOUND 108

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)instance;
    (void)reason;
    (void)reserved;
    return TRUE;
}

uint32_t VR_InitInternal2(int *error, int application_type,
                          const char *startup_info) {
    (void)application_type;
    (void)startup_info;
    if (error != NULL) *error = VR_INIT_ERROR_HMD_NOT_FOUND;
    return 0;
}

void VR_ShutdownInternal(void) {}

void *VR_GetGenericInterface(const char *version, int *error) {
    (void)version;
    if (error != NULL) *error = VR_INIT_ERROR_HMD_NOT_FOUND;
    return NULL;
}

bool VR_IsInterfaceVersionValid(const char *version) {
    (void)version;
    return false;
}

uint32_t VR_GetInitToken(void) { return 0; }
