/*
 * Minimal Windows ARM64 helper for the GTA IV / EFLC selector under Wine.
 *
 * This deliberately targets only an exact top-level window title of "GTAIV"
 * and emits one Return press through the Win32 input queue.  It is a bounded
 * diagnostic for launch testing, not a general-purpose input injector.
 */

typedef void *HANDLE;
typedef HANDLE HWND;
typedef unsigned long DWORD;
typedef long BOOL;
typedef long LONG;
typedef unsigned long long ULONG_PTR;
typedef long long LPARAM;
typedef unsigned short WORD;
typedef unsigned short WCHAR;

typedef struct {
    LONG dx;
    LONG dy;
    DWORD mouse_data;
    DWORD flags;
    DWORD time;
    ULONG_PTR extra_info;
} MOUSEINPUT;

typedef struct {
    WORD virtual_key;
    WORD scan_code;
    DWORD flags;
    DWORD time;
    ULONG_PTR extra_info;
} KEYBDINPUT;

typedef struct {
    DWORD message;
    WORD parameter_low;
    WORD parameter_high;
} HARDWAREINPUT;

typedef struct {
    DWORD type;
    union {
        MOUSEINPUT mouse;
        KEYBDINPUT keyboard;
        HARDWAREINPUT hardware;
    } value;
} INPUT;

typedef BOOL (*WNDENUMPROC)(HWND, LPARAM);

__declspec(dllimport) void ExitProcess(unsigned int);
__declspec(dllimport) BOOL EnumWindows(WNDENUMPROC, LPARAM);
__declspec(dllimport) int GetWindowTextW(HWND, WCHAR *, int);
__declspec(dllimport) BOOL IsWindowVisible(HWND);
__declspec(dllimport) BOOL SetForegroundWindow(HWND);
__declspec(dllimport) HWND SetFocus(HWND);
__declspec(dllimport) unsigned int SendInput(unsigned int, INPUT *, int);

#define INPUT_KEYBOARD 1
#define VK_RETURN 0x0d
#define KEYEVENTF_KEYUP 0x0002

static HWND gtaiv_window;

void *memset(void *destination, int value, unsigned long long count) {
    unsigned char *cursor = (unsigned char *)destination;
    while (count--)
        *cursor++ = (unsigned char)value;
    return destination;
}

static int exact_title(const WCHAR *left, const WCHAR *right) {
    while (*left && *right) {
        if (*left++ != *right++)
            return 0;
    }
    return *left == *right;
}

static BOOL find_gtaiv(HWND window, LPARAM unused) {
    static const WCHAR wanted[] = {'G', 'T', 'A', 'I', 'V', 0};
    WCHAR title[64] = {0};
    (void)unused;
    GetWindowTextW(window, title, 63);
    if (IsWindowVisible(window) && exact_title(title, wanted)) {
        gtaiv_window = window;
        return 0;
    }
    return 1;
}

void entry(void) {
    INPUT input[2] = {0};
    unsigned int sent;

    EnumWindows(find_gtaiv, 0);
    if (!gtaiv_window)
        ExitProcess(2);

    SetForegroundWindow(gtaiv_window);
    SetFocus(gtaiv_window);

    input[0].type = INPUT_KEYBOARD;
    input[0].value.keyboard.virtual_key = VK_RETURN;
    input[1].type = INPUT_KEYBOARD;
    input[1].value.keyboard.virtual_key = VK_RETURN;
    input[1].value.keyboard.flags = KEYEVENTF_KEYUP;
    sent = SendInput(2, input, sizeof(INPUT));

    ExitProcess(sent == 2 ? 0 : 3);
}
