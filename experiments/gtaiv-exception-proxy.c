/*
 * Minimal 32-bit Windows DLL used to record GTAIV first-chance exceptions.
 *
 * This intentionally uses no CRT.  It is loaded as an app-local version.dll;
 * all public Version APIs are forwarded by gtaiv-version-proxy.def to an
 * unmodified copy named version_real.dll.
 */

typedef unsigned char BYTE;
typedef unsigned short WORD;
typedef unsigned long DWORD;
typedef long LONG;
typedef unsigned long ULONG_PTR;
typedef ULONG_PTR SIZE_T;
typedef void *PVOID;
typedef void *HANDLE;
typedef void *HMODULE;
typedef int BOOL;

#define WINAPI __attribute__((stdcall))
#define DLLIMPORT __attribute__((dllimport))

#define DLL_PROCESS_ATTACH 1
#define EXCEPTION_CONTINUE_SEARCH 0
#define EXCEPTION_MAXIMUM_PARAMETERS 15

#define FILE_APPEND_DATA 0x00000004UL
#define GENERIC_WRITE 0x40000000UL
#define FILE_SHARE_READ 0x00000001UL
#define FILE_SHARE_WRITE 0x00000002UL
#define FILE_SHARE_DELETE 0x00000004UL
#define OPEN_ALWAYS 4UL
#define CREATE_ALWAYS 2UL
#define FILE_ATTRIBUTE_NORMAL 0x00000080UL
#define INVALID_HANDLE_VALUE ((HANDLE)(ULONG_PTR)-1)

typedef struct _FLOATING_SAVE_AREA {
  DWORD ControlWord;
  DWORD StatusWord;
  DWORD TagWord;
  DWORD ErrorOffset;
  DWORD ErrorSelector;
  DWORD DataOffset;
  DWORD DataSelector;
  BYTE RegisterArea[80];
  DWORD Cr0NpxState;
} FLOATING_SAVE_AREA;

typedef struct _CONTEXT32 {
  DWORD ContextFlags;
  DWORD Dr0;
  DWORD Dr1;
  DWORD Dr2;
  DWORD Dr3;
  DWORD Dr6;
  DWORD Dr7;
  FLOATING_SAVE_AREA FloatSave;
  DWORD SegGs;
  DWORD SegFs;
  DWORD SegEs;
  DWORD SegDs;
  DWORD Edi;
  DWORD Esi;
  DWORD Ebx;
  DWORD Edx;
  DWORD Ecx;
  DWORD Eax;
  DWORD Ebp;
  DWORD Eip;
  DWORD SegCs;
  DWORD EFlags;
  DWORD Esp;
  DWORD SegSs;
  BYTE ExtendedRegisters[512];
} CONTEXT32;

typedef struct _EXCEPTION_RECORD32 {
  DWORD ExceptionCode;
  DWORD ExceptionFlags;
  struct _EXCEPTION_RECORD32 *ExceptionRecord;
  PVOID ExceptionAddress;
  DWORD NumberParameters;
  ULONG_PTR ExceptionInformation[EXCEPTION_MAXIMUM_PARAMETERS];
} EXCEPTION_RECORD32;

typedef struct _EXCEPTION_POINTERS32 {
  EXCEPTION_RECORD32 *ExceptionRecord;
  CONTEXT32 *ContextRecord;
} EXCEPTION_POINTERS32;

typedef LONG(WINAPI *PVECTORED_EXCEPTION_HANDLER)(EXCEPTION_POINTERS32 *);

DLLIMPORT DWORD WINAPI GetModuleFileNameA(HMODULE, char *, DWORD);
DLLIMPORT PVOID WINAPI AddVectoredExceptionHandler(DWORD, PVECTORED_EXCEPTION_HANDLER);
DLLIMPORT HANDLE WINAPI CreateFileA(const char *, DWORD, DWORD, PVOID, DWORD, DWORD, HANDLE);
DLLIMPORT BOOL WINAPI WriteFile(HANDLE, const void *, DWORD, DWORD *, PVOID);
DLLIMPORT BOOL WINAPI CloseHandle(HANDLE);
DLLIMPORT BOOL WINAPI DisableThreadLibraryCalls(HMODULE);
DLLIMPORT DWORD WINAPI GetCurrentProcessId(void);
DLLIMPORT DWORD WINAPI GetCurrentThreadId(void);
DLLIMPORT HANDLE WINAPI GetCurrentProcess(void);
DLLIMPORT BOOL WINAPI ReadProcessMemory(HANDLE, const void *, void *, SIZE_T, SIZE_T *);

static HANDLE log_handle = INVALID_HANDLE_VALUE;
static volatile LONG handler_busy;
static volatile LONG event_count;
static volatile LONG fatal_dumped;

static char lower_ascii(char value) {
  if (value >= 'A' && value <= 'Z') return (char)(value + ('a' - 'A'));
  return value;
}

static BOOL is_gtaiv_process(void) {
  char path[512];
  DWORD length = GetModuleFileNameA((HMODULE)0, path, sizeof(path));
  const char expected[] = "gtaiv.exe";
  DWORD base = 0;
  DWORD i;

  if (!length || length >= sizeof(path)) return 0;
  for (i = 0; i < length; ++i) {
    if (path[i] == '\\' || path[i] == '/') base = i + 1;
  }
  if (length - base != sizeof(expected) - 1) return 0;
  for (i = 0; i < sizeof(expected) - 1; ++i) {
    if (lower_ascii(path[base + i]) != expected[i]) return 0;
  }
  return 1;
}

static DWORD append_text(char *buffer, DWORD position, DWORD capacity, const char *text) {
  while (*text && position < capacity) buffer[position++] = *text++;
  return position;
}

static DWORD append_hex32(char *buffer, DWORD position, DWORD capacity, DWORD value) {
  static const char digits[] = "0123456789ABCDEF";
  int shift;
  if (position < capacity) buffer[position++] = '0';
  if (position < capacity) buffer[position++] = 'x';
  for (shift = 28; shift >= 0; shift -= 4) {
    if (position < capacity) buffer[position++] = digits[(value >> shift) & 0xf];
  }
  return position;
}

static DWORD append_hex8(char *buffer, DWORD position, DWORD capacity, BYTE value) {
  static const char digits[] = "0123456789ABCDEF";
  if (position < capacity) buffer[position++] = digits[(value >> 4) & 0xf];
  if (position < capacity) buffer[position++] = digits[value & 0xf];
  return position;
}

static void dump_memory_file(const char *path, DWORD address, DWORD length) {
  BYTE buffer[1024];
  HANDLE output;
  HANDLE process = GetCurrentProcess();
  DWORD offset = 0;

  output = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ, (PVOID)0,
                       CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, (HANDLE)0);
  if (output == INVALID_HANDLE_VALUE) return;

  while (offset < length) {
    DWORD requested = length - offset;
    DWORD written = 0;
    SIZE_T received = 0;
    if (requested > sizeof(buffer)) requested = sizeof(buffer);
    if (!ReadProcessMemory(process, (const void *)(ULONG_PTR)(address + offset),
                           buffer, requested, &received) || !received) break;
    if (!WriteFile(output, buffer, (DWORD)received, &written, (PVOID)0) ||
        written != (DWORD)received) break;
    offset += (DWORD)received;
  }
  CloseHandle(output);
}

static void dump_fatal_context(CONTEXT32 *context) {
  DWORD saved_caller_ebp = 0;
  SIZE_T received = 0;

  dump_memory_file("C:\\gtaiv-code-40b000.bin", 0x0040B000UL, 0x1000UL);
  dump_memory_file("C:\\gtaiv-code-8c5000.bin", 0x008C5000UL, 0x3000UL);
  dump_memory_file("C:\\gtaiv-data-e7f000.bin", 0x00E7F000UL, 0x1000UL);
  dump_memory_file("C:\\gtaiv-data-110c000.bin", 0x0110C000UL, 0x2000UL);
  dump_memory_file("C:\\gtaiv-data-1160000.bin", 0x01160000UL, 0x10000UL);
  dump_memory_file("C:\\gtaiv-stack.bin", context->Esp & ~0xFFFUL, 0x3000UL);

  if (ReadProcessMemory(GetCurrentProcess(),
                        (const void *)(ULONG_PTR)(context->Esp + sizeof(DWORD)),
                        &saved_caller_ebp, sizeof(saved_caller_ebp), &received) &&
      received == sizeof(saved_caller_ebp) && saved_caller_ebp >= 0x1000UL) {
    dump_memory_file("C:\\gtaiv-caller-object.bin",
                     saved_caller_ebp & ~0xFFFUL, 0x2000UL);
  }
}

static void write_line(const char *tag, EXCEPTION_POINTERS32 *pointers) {
  char line[2048];
  DWORD position = 0;
  DWORD written = 0;
  EXCEPTION_RECORD32 *record = pointers ? pointers->ExceptionRecord : (EXCEPTION_RECORD32 *)0;
  CONTEXT32 *context = pointers ? pointers->ContextRecord : (CONTEXT32 *)0;

  if (log_handle == INVALID_HANDLE_VALUE) return;
  position = append_text(line, position, sizeof(line), tag);
  position = append_text(line, position, sizeof(line), " pid=");
  position = append_hex32(line, position, sizeof(line), GetCurrentProcessId());
  position = append_text(line, position, sizeof(line), " tid=");
  position = append_hex32(line, position, sizeof(line), GetCurrentThreadId());

  if (record) {
    position = append_text(line, position, sizeof(line), " code=");
    position = append_hex32(line, position, sizeof(line), record->ExceptionCode);
    position = append_text(line, position, sizeof(line), " address=");
    position = append_hex32(line, position, sizeof(line), (DWORD)(ULONG_PTR)record->ExceptionAddress);
    position = append_text(line, position, sizeof(line), " flags=");
    position = append_hex32(line, position, sizeof(line), record->ExceptionFlags);
    position = append_text(line, position, sizeof(line), " info0=");
    position = append_hex32(line, position, sizeof(line), record->NumberParameters > 0 ? (DWORD)record->ExceptionInformation[0] : 0);
    position = append_text(line, position, sizeof(line), " info1=");
    position = append_hex32(line, position, sizeof(line), record->NumberParameters > 1 ? (DWORD)record->ExceptionInformation[1] : 0);
  }

  if (context) {
    position = append_text(line, position, sizeof(line), " eip=");
    position = append_hex32(line, position, sizeof(line), context->Eip);
    position = append_text(line, position, sizeof(line), " esp=");
    position = append_hex32(line, position, sizeof(line), context->Esp);
    position = append_text(line, position, sizeof(line), " eax=");
    position = append_hex32(line, position, sizeof(line), context->Eax);
    position = append_text(line, position, sizeof(line), " ebx=");
    position = append_hex32(line, position, sizeof(line), context->Ebx);
    position = append_text(line, position, sizeof(line), " ecx=");
    position = append_hex32(line, position, sizeof(line), context->Ecx);
    position = append_text(line, position, sizeof(line), " edx=");
    position = append_hex32(line, position, sizeof(line), context->Edx);
    position = append_text(line, position, sizeof(line), " ebp=");
    position = append_hex32(line, position, sizeof(line), context->Ebp);
    position = append_text(line, position, sizeof(line), " esi=");
    position = append_hex32(line, position, sizeof(line), context->Esi);
    position = append_text(line, position, sizeof(line), " edi=");
    position = append_hex32(line, position, sizeof(line), context->Edi);
  }

  if (record && context && record->ExceptionCode == 0xC0000005UL) {
    BYTE code[64];
    DWORD stack[64];
    SIZE_T received = 0;
    DWORD i;
    DWORD code_start = context->Eip >= 16 ? context->Eip - 16 : context->Eip;

    if (ReadProcessMemory(GetCurrentProcess(), (const void *)(ULONG_PTR)code_start,
                          code, sizeof(code), &received)) {
      position = append_text(line, position, sizeof(line), " code_at=");
      position = append_hex32(line, position, sizeof(line), code_start);
      position = append_text(line, position, sizeof(line), " code=");
      for (i = 0; i < (DWORD)received; ++i) position = append_hex8(line, position, sizeof(line), code[i]);
    }

    received = 0;
    if (ReadProcessMemory(GetCurrentProcess(), (const void *)(ULONG_PTR)context->Esp,
                          stack, sizeof(stack), &received)) {
      position = append_text(line, position, sizeof(line), " stack=");
      for (i = 0; i < (DWORD)(received / sizeof(stack[0])); ++i) {
        if (i && position < sizeof(line)) line[position++] = ',';
        position = append_hex32(line, position, sizeof(line), stack[i]);
      }
    }
  }

  if (position < sizeof(line)) line[position++] = '\r';
  if (position < sizeof(line)) line[position++] = '\n';
  WriteFile(log_handle, line, position, &written, (PVOID)0);
}

static LONG WINAPI record_exception(EXCEPTION_POINTERS32 *pointers) {
  LONG sequence = __atomic_add_fetch(&event_count, 1, __ATOMIC_RELAXED);
  if (sequence <= 1024 && !__atomic_exchange_n(&handler_busy, 1, __ATOMIC_ACQUIRE)) {
    write_line("exception", pointers);
    if (pointers && pointers->ExceptionRecord && pointers->ContextRecord &&
        pointers->ExceptionRecord->ExceptionCode == 0xC0000005UL &&
        pointers->ContextRecord->Eip == 0x0040E877UL &&
        !__atomic_exchange_n(&fatal_dumped, 1, __ATOMIC_ACQ_REL)) {
      dump_fatal_context(pointers->ContextRecord);
      write_line("fatal-dumps-written", (EXCEPTION_POINTERS32 *)0);
    }
    __atomic_store_n(&handler_busy, 0, __ATOMIC_RELEASE);
  }
  return EXCEPTION_CONTINUE_SEARCH;
}

BOOL WINAPI DllMain(HMODULE module, DWORD reason, PVOID reserved) {
  (void)reserved;
  if (reason != DLL_PROCESS_ATTACH || !is_gtaiv_process()) return 1;

  DisableThreadLibraryCalls(module);
  log_handle = CreateFileA("C:\\gtaiv-firstchance.log", FILE_APPEND_DATA,
                           FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           (PVOID)0, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, (HANDLE)0);
  if (log_handle != INVALID_HANDLE_VALUE) {
    write_line("loaded", (EXCEPTION_POINTERS32 *)0);
  }
  AddVectoredExceptionHandler(1, record_exception);
  return 1;
}
