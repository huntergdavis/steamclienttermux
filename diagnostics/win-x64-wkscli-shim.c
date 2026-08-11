/*
 * Minimal app-local wkscli.dll for the Chrome 143 renderer probe.
 *
 * Proton 11 ARM64 does not ship this Windows system DLL. Chrome for Testing
 * imports only NetGetJoinInformation from it. Report an unsupported query
 * without allocating a result so the diagnostic can continue to Chromium's
 * renderer boundary.
 */

typedef unsigned short u16;
typedef unsigned int u32;

#define ERROR_NOT_SUPPORTED 50u
#define NET_SETUP_UNKNOWN_STATUS 0u

u32 NetGetJoinInformation(const u16 *server, u16 **name_buffer,
                          u32 *join_status)
{
    (void)server;
    if (name_buffer) *name_buffer = (u16 *)0;
    if (join_status) *join_status = NET_SETUP_UNKNOWN_STATUS;
    return ERROR_NOT_SUPPORTED;
}
