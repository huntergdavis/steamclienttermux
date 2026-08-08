# PRoot performance investigation

## Measured bottleneck

On 2026-08-08, enumerating the 5,601 regular files in Proton Experimental took:

| Execution path | Elapsed time |
|---|---:|
| Native Termux filesystem access | 0.129 s |
| Debian through patched PRoot, original path | 4.231 s |
| Debian through patched PRoot, short explicit bind | 4.069 s |

PRoot was approximately **33 times slower** for this metadata-heavy operation.
The short bind improved only about 4%, ruling out the long Android path as the
primary cause.

During Steam's compatibility-cache rebuild, PRoot used about 87% of one CPU core
and accumulated hundreds of thousands of context switches. Steam registered one
historical Proton/runtime entry roughly every 33–40 seconds and repeatedly
missed its 60-second post-logon compatibility-manager deadline.

PRoot's seccomp-filter ptrace acceleration was verified active:

```text
ptrace acceleration (seccomp mode 2, new syscall order) enabled
```

The remaining cost is therefore in filesystem/path syscalls that PRoot must
translate, not simply a disabled accelerator.

## Optimization tracks

### 1. Profile and optimize PRoot path translation

Add low-overhead per-syscall counters to the custom PRoot build, reproduce the
5,601-file benchmark, then optimize the dominant translated calls. Potential
work includes safe canonicalization caches and a pass-through fast path for
host-visible trees whose guest and host paths are identical. Any cache must be
correct across rename, symlink, bind, cwd, and process lifecycle changes.

### 2. Remove native ARM64 Steam from ptrace

Steam itself is ARM64, so CPU emulation is unnecessary. A native Termux glibc
launch was already attempted and reached Steam code at native speed, but failed
with `Function not implemented` in thread synchronization and semaphore setup.

A promising architecture is:

```text
native ARM64 Steam under Termux glibc
  + userspace/LD_PRELOAD SysV IPC compatibility library
  + robust-list handling in the Termux glibc build if required
  + private Turnip and existing CEF/network shims
```

This moves only Android's missing Linux behavior into a compatibility library
instead of translating every filesystem syscall with ptrace. Feasibility must
be proven with small semaphore/shared-memory/robust-list probes before Steam.

### 3. Hybrid launcher

If Proton or container-runtime setup still needs a Debian filesystem view, keep
those helpers in PRoot while running the native ARM64 Steam UI outside it. This
requires careful IPC, path, and environment agreement between the two domains.

## Correctness requirement

Performance changes must retain the custom semaphore wakeup behavior and must
not weaken Android security or require root. Benchmarks are insufficient: Steam
authentication, compatibility-cache completion, downloads, and game launch must
all be retested.

