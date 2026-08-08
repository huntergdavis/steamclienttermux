#define _GNU_SOURCE
#include <errno.h>
#include <linux/futex.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <unistd.h>

int main(void)
{
    struct robust_list_head *head = NULL;
    size_t len = 0;
    long rc = syscall(SYS_get_robust_list, 0, &head, &len);
    printf("rc=%ld errno=%d head=%p len=%zu expected=%zu\n",
           rc, errno, (void *)head, len, sizeof(*head));
    return rc == 0 && head != NULL && len == sizeof(*head) ? 0 : 1;
}
