/*
 * Click only the GTA IV side of the GTA IV / EFLC selector under Wine.
 *
 * The probe requires an exact visible top-level title of "GTAIV", derives the
 * target from the current full-screen dimensions, and emits one left click
 * through Wine's Win32 input queue.  It is intentionally not a general mouse
 * tool.
 */

typedef void *HANDLE;
typedef HANDLE HWND;
typedef unsigned long DWORD;
typedef long BOOL;
typedef unsigned long long ULONG_PTR;
typedef long long LPARAM;
typedef unsigned short WORD;
typedef unsigned short WCHAR;

typedef struct {
    long dx;
    long dy;
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
__declspec(dllimport) int GetSystemMetrics(int);
__declspec(dllimport) int GetWindowTextW(HWND, WCHAR *, int);
__declspec(dllimport) BOOL IsWindowVisible(HWND);
__declspec(dllimport) BOOL SetCursorPos(int, int);
__declspec(dllimport) HWND SetFocus(HWND);
__declspec(dllimport) BOOL SetForegroundWindow(HWND);
__declspec(dllimport) unsigned int SendInput(unsigned int, INPUT *, int);

#define INPUT_MOUSE 0
#define MOUSEEVENTF_LEFTDOWN 0x0002
#define MOUSEEVENTF_LEFTUP 0x0004
#define SM_CXSCREEN 0
#define SM_CYSCREEN 1

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
    int width;
    int height;
    int target_x;
    int target_y;

    EnumWindows(find_gtaiv, 0);
    if (!gtaiv_window)
        ExitProcess(2);

    width = GetSystemMetrics(SM_CXSCREEN);
    height = GetSystemMetrics(SM_CYSCREEN);
    if (width < 640 || height < 480)
        ExitProcess(3);

    /* Center of the left PLAY hit target in the full-screen selector. */
    target_x = (width * 28) / 100;
    target_y = (height * 79) / 100;

    SetForegroundWindow(gtaiv_window);
    SetFocus(gtaiv_window);
    if (!SetCursorPos(target_x, target_y))
        ExitProcess(4);

    input[0].type = INPUT_MOUSE;
    input[0].value.mouse.flags = MOUSEEVENTF_LEFTDOWN;
    input[1].type = INPUT_MOUSE;
    input[1].value.mouse.flags = MOUSEEVENTF_LEFTUP;
    ExitProcess(SendInput(2, input, sizeof(INPUT)) == 2 ? 0 : 5);
}
