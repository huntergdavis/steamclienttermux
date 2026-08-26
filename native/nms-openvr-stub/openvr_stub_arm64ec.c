/* SPDX-License-Identifier: MIT */
/* Freestanding ARM64EC flat-screen OpenVR shim. */

typedef unsigned int uint32_t;
typedef _Bool bool;

#define NULL ((void *)0)
#define VR_INIT_ERROR_HMD_NOT_FOUND 108

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
    return 0;
}

uint32_t VR_GetInitToken(void) { return 0; }
