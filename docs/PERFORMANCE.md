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

## First prototype results

Tracing showed that Steam's metadata workload is dominated by directory-relative
`fstatat` calls. Fake-root, link-to-symlink, and symlink-size extensions broaden
the seccomp filter and force additional metadata calls through ptrace.

An alternate PRoot invocation without those unnecessary Steam-session extensions
reduced the 5,601-file benchmark to approximately 2.10 seconds. An experimental,
opt-in fast path for non-dereferencing, single-component `fstatat` operations
under an explicitly trusted prefix reduced it further to approximately 1.76
seconds. Together these are about 2.4 times faster than the current 4.23-second
configuration, but still roughly 14 times slower than native access.

The experimental source change is retained as
`patches/proot-noderef-fastpath.patch`. It is not enabled by the production
launcher. It requires `PROOT_NODEREF_FAST_PATH` to name the trusted host-visible
tree and otherwise leaves path translation unchanged.

Build a stamped candidate that combines the complete production patch set with
this experimental patch in a separate source directory:

```sh
PROOT_ENABLE_NODEREF_FASTPATH=1 \
  scripts/build-proot.sh ~/steam-arm64/src/proot-production-fastpath-candidate
```

The default remains the production patch set. The builder accepts only `0` or
`1`, includes the optional patch in its ordered patch-set/diff/binary hashes,
and refuses to reuse a candidate whose stamp or binary has changed. Building a
candidate does not select it in `bin/steam-arm`; tests must set `PD_PROOT_BIN`
or `PROOT_BUILD_DIR` explicitly.

`scripts/benchmark-proot-filesystem.sh` accepts `PROOT_BUILD_DIR` and
`PROOT_BENCHMARK_TARGET` so production and candidate binaries can be compared
against the same tree. When `PROOT_NODEREF_FAST_PATH` is set, the script also
forwards it with `proot-distro --env`. Setting it only in the outer Termux
environment is insufficient because `proot-distro` sanitizes that environment
before it starts PRoot.

## Combined candidate results

On 2026-08-11, the complete production patch set plus the no-dereference patch
was built twice from the pinned `a89b3732ec6ae1db674510f0843b2f3db54d0a2f`
commit. Both builds produced the same candidate binary, SHA-256
`4d38e8a989df054ea119cf9b0981ff74cd41af03e62453c24081f485c275032a`.
The stamped combined diff changes 12 files and includes all ten production
patches followed by `proot-noderef-fastpath.patch`.

All four production PRoot regression probes passed under the candidate:
spaced compatibility-tool paths, shared `/tmp` file and directory binds,
post-`--proc` `/proc/net`, and escaped mountinfo paths. The AMD64 Windows
message-loop control also produced its byte-identical all-PASS transcript
through official Proton 11 ARM64 and bundled FEX.

Three alternating production/candidate trials enumerated the same 5,601 files
in Proton Experimental. The candidate used the exact benchmark tree as its
trusted prefix. Median results were:

| Execution path | Production | Candidate | Improvement |
|---|---:|---:|---:|
| Debian through PRoot, original path | 1.733 s | 1.589 s | 8.3% |
| Debian through PRoot, short explicit bind | 1.742 s | 1.527 s | 12.3% |

The corrected benchmark transcript has SHA-256
`582f407dc655a3a483de1bb1a5ffe970c97f74cc550d915dfedfb10b7c3e0d09`.
An earlier transcript with SHA-256
`91a098316c7f343abbf757120356c487dcbc8abbe1431238de97ea6ea356cb12`
is an inactive control and must not be used to estimate the patch: it set the
variable only outside `proot-distro`. Direct `/proc/<pid>/environ` inspection
proved the candidate received the trusted prefix only after `--env` was added.

This is a real metadata improvement, but the candidate is still not selected
by the live launcher. It did not clear the credential-free Chromium renderer
control, so it is not a fix for GTA IV's Rockstar Code 17 boundary. A live
switch still requires a controlled Steam restart and end-to-end cache,
download, and game-launch validation.

### 1. Profile and optimize PRoot path translation

Add low-overhead per-syscall counters to the custom PRoot build, reproduce the
5,601-file benchmark, then optimize the dominant translated calls. Potential
work includes safe canonicalization caches and a pass-through fast path for
host-visible trees whose guest and host paths are identical. Any cache must be
correct across rename, symlink, bind, cwd, and process lifecycle changes.

The first prototype proves canonicalization is material, but also proves that
canonicalization alone cannot remove the ptrace stop for each `fstatat` call.

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

## 2026-08-16 native PRoot compiler profile

The production patch set now has an opt-in `PROOT_BUILD_PROFILE=native` build
using `-O3`, ThinLTO on eligible hot objects, native ARM64 feature selection,
section garbage collection, hardening, parallel compilation, and stripping.
The ARM32 embedded loader and the inspected `cli/cli.o` payload remain outside
the incompatible optimizations. The portable production build stays the
default.

On the Tab S8+, the resulting 271 KiB candidate has SHA-256
`5e3a5b4992a9717005d6ac84268b24b9cd98fba61b977f790d7435bf16014657`.
Three alternating enumerations of the same 5,601 files improved the long-path
median from 5.5024 to 5.4137 seconds (1.61%), while the short-bind median moved
from 5.3561 to 5.3653 seconds (-0.17%). All four PRoot regression probes and a
complete Pressure Vessel `/bin/true` boundary passed, but the latter took 47
seconds against the earlier 42-second production observation. The evidence
supports keeping this as a controlled compiler A/B, not selecting it for game
launches. Use `STEAM_ARM64_PROOT_DIR` to opt in explicitly.
