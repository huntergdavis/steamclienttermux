/*
 * Credential-free Windows network-state probe for Proton ARM64.
 *
 * This is deliberately freestanding: Termux's LLVM toolchain can build it
 * without a Windows SDK.  It reports only numeric API status and never makes
 * an HTTP request or reads an application prefix.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef signed int i32;
typedef signed short variant_bool;
typedef void *handle;

typedef struct guid {
    u32 data1;
    u16 data2;
    u16 data3;
    u8 data4[8];
} guid;

typedef struct network_list_manager network_list_manager;

typedef struct network_list_manager_vtbl {
    void *query_interface;
    void *add_ref;
    u32 (*release)(network_list_manager *self);
    void *get_type_info_count;
    void *get_type_info;
    void *get_ids_of_names;
    void *invoke;
    void *get_networks;
    void *get_network;
    void *get_network_connections;
    void *get_network_connection;
    i32 (*is_connected_to_internet)(network_list_manager *self,
                                    variant_bool *connected);
    i32 (*is_connected)(network_list_manager *self, variant_bool *connected);
    i32 (*get_connectivity)(network_list_manager *self, u32 *connectivity);
} network_list_manager_vtbl;

struct network_list_manager {
    network_list_manager_vtbl *vtbl;
};

typedef struct adapter_head {
    u32 length;
    u32 interface_index;
    struct adapter_head *next;
} adapter_head;

extern handle GetStdHandle(i32 which);
extern i32 WriteFile(handle file, const void *buffer, u32 bytes,
                     u32 *written, void *overlapped);
extern void Sleep(u32 milliseconds);
extern handle LoadLibraryW(const u16 *name);
extern void *GetProcAddress(handle module, const char *name);
extern void ExitProcess(u32 code);

extern i32 CoInitializeEx(void *reserved, u32 mode);
extern i32 CoCreateInstance(const guid *class_id, void *outer, u32 context,
                            const guid *interface_id, void **object);
extern void CoUninitialize(void);

typedef u32 (*get_adapters_addresses_fn)(u32 family, u32 flags, void *reserved,
                                         void *addresses, u32 *size);
typedef u32 (*get_unicast_table_fn)(u16 family, void **table);
typedef void (*free_mib_table_fn)(void *table);
typedef void (*network_change_callback)(void *context, void *row,
                                        i32 notification_type);
typedef u32 (*notify_change_fn)(u16 family, network_change_callback callback,
                                void *context, i32 initial_notification,
                                handle *notification_handle);
typedef u32 (*cancel_change_fn)(handle notification_handle);
typedef i32 (*internet_connected_fn)(u32 *flags, u32 reserved);

static handle stdout_handle;
static u8 adapter_buffer[65536] __attribute__((aligned(16)));
static volatile u32 interface_callback_count;
static volatile u32 unicast_callback_count;

static const guid clsid_network_list_manager = {
    0xdcb00c01, 0x570f, 0x4a9b,
    {0x8d, 0x69, 0x19, 0x9f, 0xdb, 0xa5, 0x72, 0x3b}
};
static const guid iid_network_list_manager = {
    0xdcb00000, 0x570f, 0x4a9b,
    {0x8d, 0x69, 0x19, 0x9f, 0xdb, 0xa5, 0x72, 0x3b}
};

static void write_bytes(const char *text, u32 length)
{
    u32 written;
    WriteFile(stdout_handle, text, length, &written, (void *)0);
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

static void interface_changed(void *context, void *row, i32 type)
{
    (void)context;
    (void)row;
    (void)type;
    ++interface_callback_count;
}

static void unicast_changed(void *context, void *row, i32 type)
{
    (void)context;
    (void)row;
    (void)type;
    ++unicast_callback_count;
}

static u32 succeeded(i32 result)
{
    return (((u32)result & 0x80000000u) == 0);
}

static void probe_adapters(get_adapters_addresses_fn get_adapters_addresses,
                           u32 flags, const char *rc_name,
                           const char *size_name, const char *count_name)
{
    adapter_head *adapter;
    u32 size = (u32)sizeof(adapter_buffer);
    u32 result;
    u32 count = 0;

    result = get_adapters_addresses(0, flags, (void *)0,
                                    adapter_buffer, &size);
    if (result == 0) {
        adapter = (adapter_head *)adapter_buffer;
        while (adapter && count < 128) {
            ++count;
            if (adapter->length < sizeof(adapter_head)) break;
            adapter = adapter->next;
        }
    }
    write_decimal_result(rc_name, result);
    write_decimal_result(size_name, size);
    write_decimal_result(count_name, count);
}

void mainCRTStartup(void)
{
    static const u16 iphlpapi_name[] = {
        'i','p','h','l','p','a','p','i','.','d','l','l',0
    };
    static const u16 wininet_name[] = {
        'w','i','n','i','n','e','t','.','d','l','l',0
    };
    handle iphlpapi;
    handle wininet;
    get_adapters_addresses_fn get_adapters_addresses;
    get_unicast_table_fn get_unicast_table;
    free_mib_table_fn free_mib_table;
    notify_change_fn notify_interface;
    notify_change_fn notify_unicast;
    cancel_change_fn cancel_change;
    internet_connected_fn internet_connected;
    network_list_manager *manager = (void *)0;
    void *unicast_table = (void *)0;
    handle notification;
    u32 result;
    u32 flags = 0;
    u32 connectivity = 0;
    variant_bool connected = 0;
    i32 hr;
    i32 com_hr;

    stdout_handle = GetStdHandle(-11);
    write_decimal_result("PROBE_VERSION", 1);

    iphlpapi = LoadLibraryW(iphlpapi_name);
    write_decimal_result("IPHLPAPI_LOADED", iphlpapi != (handle)0);
    if (iphlpapi) {
        get_adapters_addresses = (get_adapters_addresses_fn)
            GetProcAddress(iphlpapi, "GetAdaptersAddresses");
        get_unicast_table = (get_unicast_table_fn)
            GetProcAddress(iphlpapi, "GetUnicastIpAddressTable");
        free_mib_table = (free_mib_table_fn)
            GetProcAddress(iphlpapi, "FreeMibTable");
        notify_interface = (notify_change_fn)
            GetProcAddress(iphlpapi, "NotifyIpInterfaceChange");
        notify_unicast = (notify_change_fn)
            GetProcAddress(iphlpapi, "NotifyUnicastIpAddressChange");
        cancel_change = (cancel_change_fn)
            GetProcAddress(iphlpapi, "CancelMibChangeNotify2");

        write_decimal_result("GET_NETWORK_HINT_PRESENT",
            GetProcAddress(iphlpapi, "GetNetworkConnectivityHint") != (void *)0);
        write_decimal_result("NOTIFY_NETWORK_HINT_PRESENT",
            GetProcAddress(iphlpapi,
                "NotifyNetworkConnectivityHintChange") != (void *)0);
        write_decimal_result("GET_BEST_ROUTE2_PRESENT",
            GetProcAddress(iphlpapi, "GetBestRoute2") != (void *)0);

        if (get_adapters_addresses) {
            probe_adapters(get_adapters_addresses, 0,
                           "GET_ADAPTERS_BASE_RC",
                           "GET_ADAPTERS_BASE_SIZE",
                           "ADAPTER_BASE_COUNT");
            /* Exact flags used by Proton 11 netprofm/list.c. */
            probe_adapters(get_adapters_addresses, 0x8e,
                           "GET_ADAPTERS_NLM_RC",
                           "GET_ADAPTERS_NLM_SIZE",
                           "ADAPTER_NLM_COUNT");
        }

        if (get_unicast_table && free_mib_table) {
            result = get_unicast_table(0, &unicast_table);
            write_decimal_result("GET_UNICAST_TABLE_RC", result);
            write_decimal_result("UNICAST_COUNT",
                result == 0 && unicast_table ? *(u32 *)unicast_table : 0);
            if (result == 0 && unicast_table) free_mib_table(unicast_table);
        }

        write_decimal_result("NOTIFY_INTERFACE_PRESENT",
                             notify_interface != (notify_change_fn)0);
        if (notify_interface) {
            notification = (handle)0x11111111;
            interface_callback_count = 0;
            result = notify_interface(0, interface_changed, (void *)0, 1,
                                      &notification);
            Sleep(250);
            write_decimal_result("NOTIFY_INTERFACE_RC", result);
            write_decimal_result("NOTIFY_INTERFACE_HANDLE",
                                 notification != (handle)0);
            write_decimal_result("NOTIFY_INTERFACE_CALLBACKS",
                                 interface_callback_count);
            if (result == 0 && notification &&
                    notification != (handle)0x11111111 && cancel_change)
                cancel_change(notification);
        }

        write_decimal_result("NOTIFY_UNICAST_PRESENT",
                             notify_unicast != (notify_change_fn)0);
        if (notify_unicast) {
            notification = (handle)0x22222222;
            unicast_callback_count = 0;
            result = notify_unicast(0, unicast_changed, (void *)0, 1,
                                    &notification);
            Sleep(250);
            write_decimal_result("NOTIFY_UNICAST_RC", result);
            write_decimal_result("NOTIFY_UNICAST_HANDLE",
                                 notification != (handle)0);
            write_decimal_result("NOTIFY_UNICAST_CALLBACKS",
                                 unicast_callback_count);
            if (result == 0 && notification &&
                    notification != (handle)0x22222222 && cancel_change)
                cancel_change(notification);
        }
    }

    wininet = LoadLibraryW(wininet_name);
    internet_connected = wininet ? (internet_connected_fn)
        GetProcAddress(wininet, "InternetGetConnectedState") :
        (internet_connected_fn)0;
    write_decimal_result("INTERNET_STATE_PRESENT",
                         internet_connected != (internet_connected_fn)0);
    if (internet_connected) {
        result = (u32)internet_connected(&flags, 0);
        write_decimal_result("INTERNET_STATE_CONNECTED", result);
        write_hex_result("INTERNET_STATE_FLAGS", flags);
    }

    com_hr = CoInitializeEx((void *)0, 0);
    write_hex_result("COM_INIT_HR", (u32)com_hr);
    hr = CoCreateInstance(&clsid_network_list_manager, (void *)0, 1,
                          &iid_network_list_manager, (void **)&manager);
    write_hex_result("NLM_CREATE_HR", (u32)hr);
    if (succeeded(hr) && manager) {
        hr = manager->vtbl->is_connected_to_internet(manager, &connected);
        write_hex_result("NLM_INTERNET_HR", (u32)hr);
        write_decimal_result("NLM_INTERNET", connected != 0);
        connected = 0;
        hr = manager->vtbl->is_connected(manager, &connected);
        write_hex_result("NLM_CONNECTED_HR", (u32)hr);
        write_decimal_result("NLM_CONNECTED", connected != 0);
        hr = manager->vtbl->get_connectivity(manager, &connectivity);
        write_hex_result("NLM_CONNECTIVITY_HR", (u32)hr);
        write_hex_result("NLM_CONNECTIVITY", connectivity);
        manager->vtbl->release(manager);
    }
    if (succeeded(com_hr)) CoUninitialize();

    ExitProcess(0);
}
