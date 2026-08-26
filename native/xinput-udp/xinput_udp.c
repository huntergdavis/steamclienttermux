/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * XInput endpoint for the 64-byte localhost protocol used by
 * moio9/termux-x11-extra v0.11.1. No Android or Wine pointers cross it.
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <ws2tcpip.h>
#include <xinput.h>

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define BVB_CODE_HELLO 1
#define BVB_CODE_GET_GAMEPAD 8
#define BVB_CODE_GAMEPAD_STATE 9
#define BVB_CODE_RELEASE_GAMEPAD 10
#define BVB_CODE_SET_RUMBLE 11
#define BVB_PACKET_SIZE 64
#define BVB_CLIENT_PORT 4600
#define BVB_SERVER_PORT 4602
#define BVB_GAMEPAD_ID 1
#define BVB_STALE_MS 2000

static INIT_ONCE bvb_once = INIT_ONCE_STATIC_INIT;
static CRITICAL_SECTION bvb_lock;
static SOCKET bvb_socket4 = INVALID_SOCKET;
static SOCKET bvb_socket6 = INVALID_SOCKET;
static struct sockaddr_in bvb_peer4;
static struct sockaddr_in6 bvb_peer6;
static volatile LONG bvb_running;
static volatile LONG bvb_enabled = 1;
static volatile LONG bvb_active_family;
static XINPUT_STATE bvb_state;
static DWORD bvb_last_packet;

static uint16_t bvb_read_le16(const unsigned char *data) {
    return (uint16_t)data[0] | ((uint16_t)data[1] << 8);
}

static int32_t bvb_read_le32(const unsigned char *data) {
    return (int32_t)((uint32_t)data[0] | ((uint32_t)data[1] << 8) |
                     ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24));
}

static void bvb_write_le16(unsigned char *data, uint16_t value) {
    data[0] = (unsigned char)(value & 0xff);
    data[1] = (unsigned char)(value >> 8);
}

static void bvb_write_le32(unsigned char *data, uint32_t value) {
    data[0] = (unsigned char)(value & 0xff);
    data[1] = (unsigned char)((value >> 8) & 0xff);
    data[2] = (unsigned char)((value >> 16) & 0xff);
    data[3] = (unsigned char)((value >> 24) & 0xff);
}

static SHORT bvb_invert_axis(SHORT value) {
    return value == (SHORT)-32768 ? (SHORT)32767 : (SHORT)-value;
}

static WORD bvb_buttons(uint16_t buttons, unsigned char dpad) {
    WORD result = 0;
    if (buttons & (1u << 0)) result |= XINPUT_GAMEPAD_A;
    if (buttons & (1u << 1)) result |= XINPUT_GAMEPAD_B;
    if (buttons & (1u << 2)) result |= XINPUT_GAMEPAD_X;
    if (buttons & (1u << 3)) result |= XINPUT_GAMEPAD_Y;
    if (buttons & (1u << 4)) result |= XINPUT_GAMEPAD_LEFT_SHOULDER;
    if (buttons & (1u << 5)) result |= XINPUT_GAMEPAD_RIGHT_SHOULDER;
    if (buttons & (1u << 6)) result |= XINPUT_GAMEPAD_START;
    if (buttons & (1u << 7)) result |= XINPUT_GAMEPAD_BACK;
    if (buttons & (1u << 8)) result |= XINPUT_GAMEPAD_LEFT_THUMB;
    if (buttons & (1u << 9)) result |= XINPUT_GAMEPAD_RIGHT_THUMB;

    if (dpad <= 7) {
        if (dpad == 7 || dpad == 0 || dpad == 1)
            result |= XINPUT_GAMEPAD_DPAD_UP;
        if (dpad == 1 || dpad == 2 || dpad == 3)
            result |= XINPUT_GAMEPAD_DPAD_RIGHT;
        if (dpad == 3 || dpad == 4 || dpad == 5)
            result |= XINPUT_GAMEPAD_DPAD_DOWN;
        if (dpad == 5 || dpad == 6 || dpad == 7)
            result |= XINPUT_GAMEPAD_DPAD_LEFT;
    }
    return result;
}

static void bvb_send_packet(SOCKET socket_value, const void *peer,
                            int peer_length, const unsigned char *packet) {
    if (socket_value != INVALID_SOCKET)
        sendto(socket_value, (const char *)packet, BVB_PACKET_SIZE, 0,
               (const struct sockaddr *)peer, peer_length);
}

static void bvb_send_handshake_one(SOCKET socket_value, const void *peer,
                                   int peer_length) {
    unsigned char packet[BVB_PACKET_SIZE] = {0};
    packet[0] = BVB_CODE_HELLO;
    bvb_send_packet(socket_value, peer, peer_length, packet);

    memset(packet, 0, sizeof(packet));
    packet[0] = BVB_CODE_GET_GAMEPAD;
    packet[1] = 1; /* XInput handshake. */
    bvb_write_le32(packet + 2, BVB_GAMEPAD_ID);
    bvb_send_packet(socket_value, peer, peer_length, packet);
}

static void bvb_send_handshake(void) {
    bvb_send_handshake_one(bvb_socket4, &bvb_peer4, sizeof(bvb_peer4));
    bvb_send_handshake_one(bvb_socket6, &bvb_peer6, sizeof(bvb_peer6));
}

static void bvb_accept_state(const unsigned char *packet, int length,
                             LONG family) {
    XINPUT_GAMEPAD gamepad;
    if (length < 19 || packet[0] != BVB_CODE_GAMEPAD_STATE ||
            packet[1] != 1 || bvb_read_le32(packet + 2) != BVB_GAMEPAD_ID)
        return;

    memset(&gamepad, 0, sizeof(gamepad));
    gamepad.wButtons = bvb_buttons(bvb_read_le16(packet + 6), packet[8]);
    gamepad.sThumbLX = (SHORT)bvb_read_le16(packet + 9);
    gamepad.sThumbLY = bvb_invert_axis((SHORT)bvb_read_le16(packet + 11));
    gamepad.sThumbRX = (SHORT)bvb_read_le16(packet + 13);
    gamepad.sThumbRY = bvb_invert_axis((SHORT)bvb_read_le16(packet + 15));
    gamepad.bLeftTrigger = packet[17];
    gamepad.bRightTrigger = packet[18];

    EnterCriticalSection(&bvb_lock);
    if (memcmp(&bvb_state.Gamepad, &gamepad, sizeof(gamepad)) != 0)
        ++bvb_state.dwPacketNumber;
    bvb_state.Gamepad = gamepad;
    bvb_last_packet = GetTickCount();
    InterlockedExchange(&bvb_active_family, family);
    LeaveCriticalSection(&bvb_lock);
}

static void bvb_accept_packet(const unsigned char *packet, int length,
                              LONG family) {
    if (length >= 6 && packet[0] == BVB_CODE_RELEASE_GAMEPAD &&
            packet[1] == 1 && bvb_read_le32(packet + 2) == BVB_GAMEPAD_ID) {
        EnterCriticalSection(&bvb_lock);
        memset(&bvb_state, 0, sizeof(bvb_state));
        bvb_last_packet = 0;
        InterlockedExchange(&bvb_active_family, 0);
        LeaveCriticalSection(&bvb_lock);
        return;
    }
    bvb_accept_state(packet, length, family);
}

static DWORD WINAPI bvb_receiver(void *unused) {
    unsigned char packet[BVB_PACKET_SIZE];
    DWORD last_handshake = 0;
    (void)unused;

    while (InterlockedCompareExchange(&bvb_running, 1, 1)) {
        fd_set read_set;
        struct timeval timeout;
        DWORD now = GetTickCount();
        if (now - last_handshake >= 1000) {
            bvb_send_handshake();
            last_handshake = now;
        }

        FD_ZERO(&read_set);
        if (bvb_socket4 != INVALID_SOCKET) FD_SET(bvb_socket4, &read_set);
        if (bvb_socket6 != INVALID_SOCKET) FD_SET(bvb_socket6, &read_set);
        timeout.tv_sec = 0;
        timeout.tv_usec = 100000;
        if (select(0, &read_set, NULL, NULL, &timeout) > 0) {
            SOCKET selected = bvb_socket4 != INVALID_SOCKET &&
                                      FD_ISSET(bvb_socket4, &read_set)
                                  ? bvb_socket4
                                  : bvb_socket6;
            struct sockaddr_storage source;
            int source_length = sizeof(source);
            int length = recvfrom(selected, (char *)packet, sizeof(packet), 0,
                                  (struct sockaddr *)&source, &source_length);
            LONG family = 0;
            if (length > 0 && source.ss_family == AF_INET &&
                    ((struct sockaddr_in *)&source)->sin_addr.s_addr ==
                        htonl(INADDR_LOOPBACK))
                family = AF_INET;
            else if (length > 0 && source.ss_family == AF_INET6 &&
                    IN6_IS_ADDR_LOOPBACK(
                        &((struct sockaddr_in6 *)&source)->sin6_addr))
                family = AF_INET6;
            if (family != 0) bvb_accept_packet(packet, length, family);
        }
    }
    return 0;
}

static BOOL CALLBACK bvb_initialize(PINIT_ONCE once, PVOID parameter,
                                    PVOID *context) {
    WSADATA wsa;
    struct sockaddr_in local4;
    struct sockaddr_in6 local6;
    DWORD ipv6_only = 1;
    HANDLE thread;
    (void)once;
    (void)parameter;
    (void)context;

    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0)
        return FALSE;
    InitializeCriticalSection(&bvb_lock);
    memset(&bvb_state, 0, sizeof(bvb_state));
    bvb_socket4 = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (bvb_socket4 != INVALID_SOCKET) {
        memset(&local4, 0, sizeof(local4));
        local4.sin_family = AF_INET;
        local4.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        local4.sin_port = htons(BVB_SERVER_PORT);
        if (bind(bvb_socket4, (const struct sockaddr *)&local4,
                 sizeof(local4)) != 0) {
            closesocket(bvb_socket4);
            bvb_socket4 = INVALID_SOCKET;
        }
    }
    bvb_socket6 = socket(AF_INET6, SOCK_DGRAM, IPPROTO_UDP);
    if (bvb_socket6 != INVALID_SOCKET) {
        setsockopt(bvb_socket6, IPPROTO_IPV6, IPV6_V6ONLY,
                   (const char *)&ipv6_only, sizeof(ipv6_only));
        memset(&local6, 0, sizeof(local6));
        local6.sin6_family = AF_INET6;
        local6.sin6_addr = in6addr_loopback;
        local6.sin6_port = htons(BVB_SERVER_PORT);
        if (bind(bvb_socket6, (const struct sockaddr *)&local6,
                 sizeof(local6)) != 0) {
            closesocket(bvb_socket6);
            bvb_socket6 = INVALID_SOCKET;
        }
    }
    if (bvb_socket4 == INVALID_SOCKET && bvb_socket6 == INVALID_SOCKET)
        return FALSE;

    memset(&bvb_peer4, 0, sizeof(bvb_peer4));
    bvb_peer4.sin_family = AF_INET;
    bvb_peer4.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    bvb_peer4.sin_port = htons(BVB_CLIENT_PORT);
    memset(&bvb_peer6, 0, sizeof(bvb_peer6));
    bvb_peer6.sin6_family = AF_INET6;
    bvb_peer6.sin6_addr = in6addr_loopback;
    bvb_peer6.sin6_port = htons(BVB_CLIENT_PORT);
    InterlockedExchange(&bvb_running, 1);
    thread = CreateThread(NULL, 0, bvb_receiver, NULL, 0, NULL);
    if (thread == NULL) {
        InterlockedExchange(&bvb_running, 0);
        return FALSE;
    }
    CloseHandle(thread);
    return TRUE;
}

static BOOL bvb_ready(void) {
    return InitOnceExecuteOnce(&bvb_once, bvb_initialize, NULL, NULL);
}

static BOOL bvb_connected(void) {
    DWORD last;
    if (!bvb_ready() || !InterlockedCompareExchange(&bvb_enabled, 1, 1))
        return FALSE;
    EnterCriticalSection(&bvb_lock);
    last = bvb_last_packet;
    LeaveCriticalSection(&bvb_lock);
    return last != 0 && GetTickCount() - last <= BVB_STALE_MS;
}

void WINAPI XInputEnable(WINBOOL enable) {
    InterlockedExchange(&bvb_enabled, enable ? 1 : 0);
}

DWORD WINAPI XInputGetState(DWORD user_index, XINPUT_STATE *state) {
    if (state == NULL)
        return ERROR_BAD_ARGUMENTS;
    memset(state, 0, sizeof(*state));
    if (user_index != 0 || !bvb_connected())
        return ERROR_DEVICE_NOT_CONNECTED;
    EnterCriticalSection(&bvb_lock);
    *state = bvb_state;
    LeaveCriticalSection(&bvb_lock);
    return ERROR_SUCCESS;
}

DWORD WINAPI XInputGetStateEx(DWORD user_index, XINPUT_STATE *state) {
    return XInputGetState(user_index, state);
}

DWORD WINAPI XInputSetState(DWORD user_index, XINPUT_VIBRATION *vibration) {
    unsigned char packet[BVB_PACKET_SIZE] = {0};
    if (vibration == NULL)
        return ERROR_BAD_ARGUMENTS;
    if (user_index != 0 || !bvb_connected())
        return ERROR_DEVICE_NOT_CONNECTED;
    packet[0] = BVB_CODE_SET_RUMBLE;
    packet[1] = 1;
    bvb_write_le32(packet + 2, BVB_GAMEPAD_ID);
    bvb_write_le16(packet + 6, vibration->wLeftMotorSpeed);
    bvb_write_le16(packet + 8, vibration->wRightMotorSpeed);
    bvb_write_le16(packet + 10,
                   vibration->wLeftMotorSpeed || vibration->wRightMotorSpeed
                       ? 100 : 0);
    if (InterlockedCompareExchange(&bvb_active_family, 0, 0) == AF_INET6)
        return sendto(bvb_socket6, (const char *)packet, sizeof(packet), 0,
                      (const struct sockaddr *)&bvb_peer6,
                      sizeof(bvb_peer6)) == SOCKET_ERROR
                   ? ERROR_DEVICE_NOT_CONNECTED
                   : ERROR_SUCCESS;
    return sendto(bvb_socket4, (const char *)packet, sizeof(packet), 0,
                  (const struct sockaddr *)&bvb_peer4,
                  sizeof(bvb_peer4)) == SOCKET_ERROR
               ? ERROR_DEVICE_NOT_CONNECTED
               : ERROR_SUCCESS;
}

DWORD WINAPI XInputGetCapabilities(DWORD user_index, DWORD flags,
                                   XINPUT_CAPABILITIES *capabilities) {
    (void)flags;
    if (capabilities == NULL)
        return ERROR_BAD_ARGUMENTS;
    memset(capabilities, 0, sizeof(*capabilities));
    if (user_index != 0 || !bvb_connected())
        return ERROR_DEVICE_NOT_CONNECTED;
    capabilities->Type = XINPUT_DEVTYPE_GAMEPAD;
    capabilities->SubType = XINPUT_DEVSUBTYPE_GAMEPAD;
    capabilities->Flags = XINPUT_CAPS_FFB_SUPPORTED;
    capabilities->Gamepad.wButtons = 0xffff;
    capabilities->Gamepad.bLeftTrigger = 0xff;
    capabilities->Gamepad.bRightTrigger = 0xff;
    capabilities->Gamepad.sThumbLX = 32767;
    capabilities->Gamepad.sThumbLY = 32767;
    capabilities->Gamepad.sThumbRX = 32767;
    capabilities->Gamepad.sThumbRY = 32767;
    capabilities->Vibration.wLeftMotorSpeed = 0xffff;
    capabilities->Vibration.wRightMotorSpeed = 0xffff;
    return ERROR_SUCCESS;
}

DWORD WINAPI XInputGetCapabilitiesEx(DWORD reserved, DWORD user_index,
                                     DWORD flags,
                                     XINPUT_CAPABILITIES_EX *capabilities) {
    DWORD result;
    (void)reserved;
    if (capabilities == NULL)
        return ERROR_BAD_ARGUMENTS;
    memset(capabilities, 0, sizeof(*capabilities));
    result = XInputGetCapabilities(user_index, flags,
                                   &capabilities->Capabilities);
    if (result == ERROR_SUCCESS) {
        capabilities->VendorId = 0x2dc8;
        capabilities->ProductId = 0x5112;
        capabilities->VersionNumber = 0x0100;
    }
    return result;
}

DWORD WINAPI XInputGetKeystroke(DWORD user_index, DWORD reserved,
                                PXINPUT_KEYSTROKE keystroke) {
    (void)reserved;
    if (keystroke == NULL)
        return ERROR_BAD_ARGUMENTS;
    memset(keystroke, 0, sizeof(*keystroke));
    return user_index != 0 || !bvb_connected() ? ERROR_DEVICE_NOT_CONNECTED
                                                : ERROR_EMPTY;
}

DWORD WINAPI XInputGetBatteryInformation(
    DWORD user_index, BYTE device_type,
    XINPUT_BATTERY_INFORMATION *information) {
    (void)device_type;
    if (information == NULL)
        return ERROR_BAD_ARGUMENTS;
    memset(information, 0, sizeof(*information));
    if (user_index != 0 || !bvb_connected())
        return ERROR_DEVICE_NOT_CONNECTED;
    information->BatteryType = BATTERY_TYPE_WIRED;
    information->BatteryLevel = BATTERY_LEVEL_FULL;
    return ERROR_SUCCESS;
}

DWORD WINAPI XInputGetDSoundAudioDeviceGuids(DWORD user_index, GUID *render,
                                             GUID *capture) {
    if (render != NULL) memset(render, 0, sizeof(*render));
    if (capture != NULL) memset(capture, 0, sizeof(*capture));
    return user_index != 0 || !bvb_connected() ? ERROR_DEVICE_NOT_CONNECTED
                                                : ERROR_SUCCESS;
}

#ifdef BVB_XINPUT_1_4
DWORD WINAPI XInputGetAudioDeviceIds(DWORD user_index, WCHAR *render,
                                     UINT *render_count, WCHAR *capture,
                                     UINT *capture_count) {
    if (render_count == NULL || capture_count == NULL)
        return ERROR_BAD_ARGUMENTS;
    if (user_index != 0 || !bvb_connected())
        return ERROR_DEVICE_NOT_CONNECTED;
    if (render != NULL && *render_count != 0) render[0] = L'\0';
    if (capture != NULL && *capture_count != 0) capture[0] = L'\0';
    *render_count = 1;
    *capture_count = 1;
    return ERROR_SUCCESS;
}
#endif

DWORD WINAPI XInputWaitForGuideButton(DWORD user_index, DWORD flags,
                                      void *event) {
    (void)user_index;
    (void)flags;
    (void)event;
    return ERROR_CALL_NOT_IMPLEMENTED;
}

DWORD WINAPI XInputCancelGuideButtonWait(DWORD user_index) {
    (void)user_index;
    return ERROR_CALL_NOT_IMPLEMENTED;
}

DWORD WINAPI XInputPowerOffController(DWORD user_index) {
    (void)user_index;
    return ERROR_CALL_NOT_IMPLEMENTED;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)instance;
    (void)reserved;
    if (reason == DLL_PROCESS_DETACH) {
        unsigned char packet[BVB_PACKET_SIZE] = {0};
        packet[0] = BVB_CODE_RELEASE_GAMEPAD;
        InterlockedExchange(&bvb_running, 0);
        bvb_send_packet(bvb_socket4, &bvb_peer4, sizeof(bvb_peer4), packet);
        bvb_send_packet(bvb_socket6, &bvb_peer6, sizeof(bvb_peer6), packet);
        if (bvb_socket4 != INVALID_SOCKET) closesocket(bvb_socket4);
        if (bvb_socket6 != INVALID_SOCKET) closesocket(bvb_socket6);
    }
    return TRUE;
}
