/*
 * Credential-free x86-64 Windows callback probe for Proton ARM64/FEX.
 *
 * Chromium's Windows message pump combines kernel events, thread messages,
 * and alertable waits.  Exercise those primitives without loading CEF or an
 * application's Wine prefix.  The program is freestanding so Termux's LLVM
 * can build it without a Windows SDK.
 */

typedef unsigned int u32;
typedef unsigned long long u64;
typedef signed long long i64;
typedef void *handle;

typedef struct point {
    int x;
    int y;
} point;

typedef struct message {
    void *window;
    u32 message;
    u32 padding;
    u64 wparam;
    i64 lparam;
    u32 time;
    point cursor;
    u32 private_data;
} message;

typedef u32 (*thread_start)(void *context);
typedef void (*apc_callback)(u64 context);

extern handle GetStdHandle(int which);
extern int WriteFile(handle file, const void *buffer, u32 bytes,
                     u32 *written, void *overlapped);
extern void ExitProcess(u32 code);
extern void Sleep(u32 milliseconds);
extern handle CreateEventW(void *attributes, int manual_reset,
                           int initial_state, const unsigned short *name);
extern handle CreateFileW(const unsigned short *name, u32 access, u32 share,
                          void *attributes, u32 creation, u32 flags,
                          handle template_file);
extern int SetEvent(handle event);
extern int CloseHandle(handle object);
extern handle CreateThread(void *attributes, u64 stack_size,
                           thread_start start, void *context,
                           u32 flags, u32 *thread_id);
extern u32 WaitForSingleObject(handle object, u32 milliseconds);
extern u32 GetCurrentThreadId(void);
extern handle OpenThread(u32 access, int inherit, u32 thread_id);
extern u32 QueueUserAPC(apc_callback callback, handle thread, u64 context);

extern u32 MsgWaitForMultipleObjectsEx(u32 count, const handle *objects,
                                       u32 milliseconds, u32 wake_mask,
                                       u32 flags);
extern int PeekMessageW(message *output, void *window, u32 minimum,
                        u32 maximum, u32 remove);
extern int PostThreadMessageW(u32 thread_id, u32 message,
                              u64 wparam, i64 lparam);

#define WAIT_OBJECT_0 0u
#define WAIT_IO_COMPLETION 0x000000c0u
#define WAIT_TIMEOUT 0x00000102u
#define QS_ALLINPUT 0x000004ffu
#define MWMO_ALERTABLE 0x00000002u
#define MWMO_INPUTAVAILABLE 0x00000004u
#define PM_REMOVE 0x00000001u
#define THREAD_SET_CONTEXT 0x00000010u
#define WM_APP 0x00008000u
#define TEST_MESSAGE (WM_APP + 37u)
#define GENERIC_WRITE 0x40000000u
#define FILE_SHARE_READ 0x00000001u
#define CREATE_ALWAYS 2u
#define FILE_ATTRIBUTE_NORMAL 0x00000080u
#define INVALID_HANDLE_VALUE ((handle)(i64)-1)

typedef struct event_context {
    handle event;
    volatile u32 set_result;
} event_context;

typedef struct message_context {
    u32 main_thread_id;
    volatile u32 post_result;
} message_context;

typedef struct apc_context {
    u32 main_thread_id;
    volatile u32 open_result;
    volatile u32 queue_result;
} apc_context;

static handle stdout_handle;
static handle result_handle;
static volatile u32 apc_count;

static const unsigned short result_name[] = {
    'm','e','s','s','a','g','e','-','l','o','o','p','-','p','r','o','b','e',
    '.','l','o','g',0
};

static void write_bytes(const char *text, u32 length)
{
    u32 written;
    WriteFile(stdout_handle, text, length, &written, (void *)0);
    if (result_handle && result_handle != INVALID_HANDLE_VALUE)
        WriteFile(result_handle, text, length, &written, (void *)0);
}

static void write_text(const char *text)
{
    u32 length = 0;
    while (text[length]) ++length;
    write_bytes(text, length);
}

static void write_u32(u32 value)
{
    char buffer[10];
    u32 offset = 10;

    do {
        buffer[--offset] = (char)('0' + value % 10);
        value /= 10;
    } while (value);
    write_bytes(buffer + offset, 10 - offset);
}

static void write_hex32(u32 value)
{
    static const char digits[] = "0123456789abcdef";
    char buffer[10];
    u32 index;

    buffer[0] = '0';
    buffer[1] = 'x';
    for (index = 0; index < 8; ++index)
        buffer[index + 2] = digits[(value >> (28 - index * 4)) & 15];
    write_bytes(buffer, 10);
}

static void write_decimal_result(const char *name, u32 value)
{
    write_text(name);
    write_text("=");
    write_u32(value);
    write_text("\r\n");
}

static void write_hex_result(const char *name, u32 value)
{
    write_text(name);
    write_text("=");
    write_hex32(value);
    write_text("\r\n");
}

static u32 event_worker(void *opaque)
{
    event_context *context = (event_context *)opaque;
    Sleep(50);
    context->set_result = SetEvent(context->event) != 0;
    return 0;
}

static u32 message_worker(void *opaque)
{
    message_context *context = (message_context *)opaque;
    Sleep(50);
    context->post_result = PostThreadMessageW(context->main_thread_id,
                                              TEST_MESSAGE, 123u, 456) != 0;
    return 0;
}

static void apc_routine(u64 context)
{
    if (context == 0x12345678u) ++apc_count;
}

static u32 apc_worker(void *opaque)
{
    apc_context *context = (apc_context *)opaque;
    handle main_thread;

    Sleep(50);
    main_thread = OpenThread(THREAD_SET_CONTEXT, 0, context->main_thread_id);
    context->open_result = main_thread != (handle)0;
    if (main_thread) {
        context->queue_result = QueueUserAPC(apc_routine, main_thread,
                                             0x12345678u) != 0;
        CloseHandle(main_thread);
    }
    return 0;
}

static u32 run_event_test(void)
{
    event_context context;
    handle worker;
    u32 wait_result;

    context.event = CreateEventW((void *)0, 0, 0,
                                 (const unsigned short *)0);
    context.set_result = 0;
    write_decimal_result("EVENT_CREATED", context.event != (handle)0);
    if (!context.event) return 0;

    worker = CreateThread((void *)0, 0, event_worker, &context, 0,
                          (u32 *)0);
    write_decimal_result("EVENT_THREAD_CREATED", worker != (handle)0);
    if (!worker) {
        CloseHandle(context.event);
        return 0;
    }

    wait_result = MsgWaitForMultipleObjectsEx(1, &context.event, 2000,
                                               QS_ALLINPUT,
                                               MWMO_INPUTAVAILABLE);
    WaitForSingleObject(worker, 2000);
    write_hex_result("EVENT_WAIT_RC", wait_result);
    write_decimal_result("EVENT_SET_RC", context.set_result);
    CloseHandle(worker);
    CloseHandle(context.event);
    return wait_result == WAIT_OBJECT_0 && context.set_result;
}

static u32 run_message_test(u32 main_thread_id)
{
    message_context context;
    message queued;
    handle worker;
    u32 wait_result;
    u32 found = 0;

    /* Peek once so Windows creates a message queue for this thread. */
    PeekMessageW(&queued, (void *)0, 0, 0, 0);
    context.main_thread_id = main_thread_id;
    context.post_result = 0;
    worker = CreateThread((void *)0, 0, message_worker, &context, 0,
                          (u32 *)0);
    write_decimal_result("MESSAGE_THREAD_CREATED", worker != (handle)0);
    if (!worker) return 0;

    wait_result = MsgWaitForMultipleObjectsEx(0, (const handle *)0, 2000,
                                               QS_ALLINPUT,
                                               MWMO_INPUTAVAILABLE);
    WaitForSingleObject(worker, 2000);
    while (PeekMessageW(&queued, (void *)0, 0, 0, PM_REMOVE)) {
        if (queued.message == TEST_MESSAGE && queued.wparam == 123u &&
                queued.lparam == 456)
            found = 1;
    }
    write_hex_result("MESSAGE_WAIT_RC", wait_result);
    write_decimal_result("MESSAGE_POST_RC", context.post_result);
    write_decimal_result("MESSAGE_FOUND", found);
    CloseHandle(worker);
    return wait_result == WAIT_OBJECT_0 && context.post_result && found;
}

static u32 run_apc_test(u32 main_thread_id)
{
    apc_context context;
    handle worker;
    u32 wait_result;

    context.main_thread_id = main_thread_id;
    context.open_result = 0;
    context.queue_result = 0;
    apc_count = 0;
    worker = CreateThread((void *)0, 0, apc_worker, &context, 0,
                          (u32 *)0);
    write_decimal_result("APC_THREAD_CREATED", worker != (handle)0);
    if (!worker) return 0;

    wait_result = MsgWaitForMultipleObjectsEx(0, (const handle *)0, 2000,
                                               QS_ALLINPUT,
                                               MWMO_ALERTABLE |
                                               MWMO_INPUTAVAILABLE);
    WaitForSingleObject(worker, 2000);
    write_hex_result("APC_WAIT_RC", wait_result);
    write_decimal_result("APC_OPEN_RC", context.open_result);
    write_decimal_result("APC_QUEUE_RC", context.queue_result);
    write_decimal_result("APC_CALLBACKS", apc_count);
    CloseHandle(worker);
    return wait_result == WAIT_IO_COMPLETION && context.open_result &&
           context.queue_result && apc_count == 1;
}

void mainCRTStartup(void)
{
    u32 event_pass;
    u32 message_pass;
    u32 apc_pass;
    u32 main_thread_id;

    stdout_handle = GetStdHandle(-11);
    result_handle = CreateFileW(result_name, GENERIC_WRITE, FILE_SHARE_READ,
                                (void *)0, CREATE_ALWAYS,
                                FILE_ATTRIBUTE_NORMAL, (handle)0);
    main_thread_id = GetCurrentThreadId();
    write_decimal_result("PROBE_VERSION", 1);
    event_pass = run_event_test();
    message_pass = run_message_test(main_thread_id);
    apc_pass = run_apc_test(main_thread_id);
    write_decimal_result("EVENT_PASS", event_pass);
    write_decimal_result("MESSAGE_PASS", message_pass);
    write_decimal_result("APC_PASS", apc_pass);
    write_decimal_result("PASS", event_pass && message_pass && apc_pass);
    if (result_handle && result_handle != INVALID_HANDLE_VALUE)
        CloseHandle(result_handle);
    ExitProcess(event_pass && message_pass && apc_pass ? 0 : 1);
}
