#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0601

#include <windows.h>

#include <cpuid.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static unsigned int count_bits(ULONG_PTR value)
{
    unsigned int count = 0;

    while (value)
    {
        count += value & 1;
        value >>= 1;
    }
    return count;
}

static void print_cpuid(void)
{
    unsigned int eax, ebx, ecx, edx;
    unsigned int maximum = __get_cpuid_max(0, NULL);
    unsigned int extended = __get_cpuid_max(0x80000000, NULL);

    printf("cpuid.maximum=0x%x\n", maximum);
    if (__get_cpuid(1, &eax, &ebx, &ecx, &edx))
        printf("cpuid.1.logical_ids=%u\n", (ebx >> 16) & 0xff);
    if (maximum >= 4 && __get_cpuid_count(4, 0, &eax, &ebx, &ecx, &edx))
        printf("cpuid.4.cores=%u\n", ((eax >> 26) & 0x3f) + 1);
    if (maximum >= 0x0b)
    {
        unsigned int level;

        for (level = 0; level < 8; level++)
        {
            __cpuid_count(0x0b, level, eax, ebx, ecx, edx);
            printf("cpuid.b.%u.type=%u logical=%u shift=%u\n", level,
                   (ecx >> 8) & 0xff, ebx & 0xffff, eax & 0x1f);
            if (!(ebx & 0xffff)) break;
        }
    }
    if (extended >= 0x80000008 &&
        __get_cpuid(0x80000008, &eax, &ebx, &ecx, &edx))
        printf("cpuid.80000008.cores=%u\n", (ecx & 0xff) + 1);
}

static void print_extended_topology(void)
{
    PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX data = NULL;
    DWORD length = 0;
    DWORD offset = 0;
    unsigned int cores = 0, packages = 0, numa_nodes = 0, groups = 0;
    unsigned int core_threads = 0, group_active = 0;

    if (!GetLogicalProcessorInformationEx(RelationAll, NULL, &length) &&
        GetLastError() != ERROR_INSUFFICIENT_BUFFER)
    {
        printf("glpiex.error=%lu\n", GetLastError());
        return;
    }
    data = malloc(length);
    if (!data)
    {
        printf("glpiex.error=out-of-memory\n");
        return;
    }
    if (!GetLogicalProcessorInformationEx(RelationAll, data, &length))
    {
        printf("glpiex.error=%lu\n", GetLastError());
        free(data);
        return;
    }
    while (offset < length)
    {
        PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX item =
            (PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX)((BYTE *)data + offset);
        WORD index;

        if (!item->Size || item->Size > length - offset) break;
        switch (item->Relationship)
        {
        case RelationProcessorCore:
            cores++;
            for (index = 0; index < item->Processor.GroupCount; index++)
                core_threads += count_bits(item->Processor.GroupMask[index].Mask);
            break;
        case RelationProcessorPackage:
            packages++;
            break;
        case RelationNumaNode:
            numa_nodes++;
            break;
        case RelationGroup:
            groups += item->Group.ActiveGroupCount;
            for (index = 0; index < item->Group.ActiveGroupCount; index++)
                group_active += item->Group.GroupInfo[index].ActiveProcessorCount;
            break;
        default:
            break;
        }
        offset += item->Size;
    }
    printf("glpiex.cores=%u\n", cores);
    printf("glpiex.core_threads=%u\n", core_threads);
    printf("glpiex.packages=%u\n", packages);
    printf("glpiex.numa_nodes=%u\n", numa_nodes);
    printf("glpiex.groups=%u\n", groups);
    printf("glpiex.group_active=%u\n", group_active);
    free(data);
}

static void print_legacy_topology(void)
{
    PSYSTEM_LOGICAL_PROCESSOR_INFORMATION data = NULL;
    DWORD length = 0;
    DWORD index;
    unsigned int cores = 0, packages = 0, numa_nodes = 0;
    unsigned int core_threads = 0;
    ULONG_PTR processor_mask = 0;

    if (!GetLogicalProcessorInformation(NULL, &length) &&
        GetLastError() != ERROR_INSUFFICIENT_BUFFER)
    {
        printf("glpi.error=%lu\n", GetLastError());
        return;
    }
    data = malloc(length);
    if (!data)
    {
        printf("glpi.error=out-of-memory\n");
        return;
    }
    if (!GetLogicalProcessorInformation(data, &length))
    {
        printf("glpi.error=%lu\n", GetLastError());
        free(data);
        return;
    }
    for (index = 0; index < length / sizeof(*data); index++)
    {
        processor_mask |= data[index].ProcessorMask;
        switch (data[index].Relationship)
        {
        case RelationProcessorCore:
            cores++;
            core_threads += count_bits(data[index].ProcessorMask);
            break;
        case RelationProcessorPackage:
            packages++;
            break;
        case RelationNumaNode:
            numa_nodes++;
            break;
        default:
            break;
        }
    }
    printf("glpi.entries=%lu\n", length / (DWORD)sizeof(*data));
    printf("glpi.logical=%u\n", count_bits(processor_mask));
    printf("glpi.core_threads=%u\n", core_threads);
    printf("glpi.cores=%u\n", cores);
    printf("glpi.packages=%u\n", packages);
    printf("glpi.numa_nodes=%u\n", numa_nodes);
    printf("glpi.mask=0x%llx\n", (unsigned long long)processor_mask);
    free(data);
}

int main(void)
{
    SYSTEM_INFO system_info, native_info;
    GROUP_AFFINITY thread_affinity;
    DWORD_PTR process_mask = 0, system_mask = 0;
    char processors[64] = "<unset>";
    DWORD processors_length = sizeof(processors);

    GetSystemInfo(&system_info);
    GetNativeSystemInfo(&native_info);
    GetEnvironmentVariableA("NUMBER_OF_PROCESSORS", processors,
                            processors_length);

    printf("environment.number_of_processors=%s\n", processors);
    printf("system.logical=%lu\n", system_info.dwNumberOfProcessors);
    printf("system.mask=0x%llx\n",
           (unsigned long long)system_info.dwActiveProcessorMask);
    printf("native.logical=%lu\n", native_info.dwNumberOfProcessors);
    printf("native.mask=0x%llx\n",
           (unsigned long long)native_info.dwActiveProcessorMask);
    if (GetProcessAffinityMask(GetCurrentProcess(), &process_mask, &system_mask))
    {
        printf("affinity.process=0x%llx\n", (unsigned long long)process_mask);
        printf("affinity.system=0x%llx\n", (unsigned long long)system_mask);
    }
    else
        printf("affinity.process_error=%lu\n", GetLastError());
    if (GetThreadGroupAffinity(GetCurrentThread(), &thread_affinity))
        printf("affinity.thread_group=%u mask=0x%llx\n", thread_affinity.Group,
               (unsigned long long)thread_affinity.Mask);
    else
        printf("affinity.thread_error=%lu\n", GetLastError());
    printf("groups.active=%u\n", GetActiveProcessorGroupCount());
    printf("groups.logical=%lu\n", GetActiveProcessorCount(ALL_PROCESSOR_GROUPS));
    printf("groups.maximum=%lu\n", GetMaximumProcessorCount(ALL_PROCESSOR_GROUPS));
    print_legacy_topology();
    print_extended_topology();
    print_cpuid();
    return 0;
}
