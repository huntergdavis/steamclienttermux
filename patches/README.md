# Source patch provenance

`proot-steam-android.patch` is the exact uncommitted diff extracted from the
working tablet source tree on 2026-08-08. It applies cleanly to Termux PRoot
commit `a89b3732ec6ae1db674510f0843b2f3db54d0a2f`.

The upstream source is <https://github.com/termux/proot>. PRoot is GPL-2.0;
redistribution and use of this derivative patch remain subject to that license.
The build script clones upstream rather than vendoring an unexplained snapshot.

Patch statistics:

```text
src/extension/sysvipc/sysvipc.c          |  35 +
src/extension/sysvipc/sysvipc_internal.h |   7 +
src/extension/sysvipc/sysvipc_sem.c      | 107 +
src/extension/sysvipc/sysvipc_shm.c      |  40 +
src/tracee/event.c                       |  58 +
5 files changed, 244 insertions(+), 3 deletions(-)
```

