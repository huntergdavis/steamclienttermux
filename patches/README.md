# Source patch provenance

`fex-2605-native-arm64-offline-compiler-compat.patch` is the narrow
compatibility layer applied after six pinned upstream FEX offline-compiler and
Windows-on-ARM correctness commits. The resulting tool is a native ARM64
Windows executable, avoiding Wine's failing ARM64EC entry thunk, while an
explicit build definition keeps generated game code on the ARM64EC host type.
The companion build script uses Proton's exact FEX-2605 Git hash in cache
headers and disables PE timestamps for reproducible artifact identity.

`proot-steam-android.patch` is the exact uncommitted diff extracted from the
working tablet source tree on 2026-08-08. It applies cleanly to Termux PRoot
commit `a89b3732ec6ae1db674510f0843b2f3db54d0a2f`.

The upstream source is <https://github.com/termux/proot>. Its source headers
grant GPL-2.0-or-later; redistribution and use of these derivative patches
remain subject to those terms. The build script clones upstream rather than
vendoring an unexplained snapshot.

Patch statistics:

```text
src/extension/sysvipc/sysvipc.c          |  35 +
src/extension/sysvipc/sysvipc_internal.h |   7 +
src/extension/sysvipc/sysvipc_sem.c      | 107 +
src/extension/sysvipc/sysvipc_shm.c      |  40 +
src/tracee/event.c                       |  58 +
5 files changed, 244 insertions(+), 3 deletions(-)
```

The production build applies nine additional focused patches after the IPC
patch:

- `proot-link2symlink-getdents.patch` reports `DT_UNKNOWN` only for confirmed
  `.l2s` pseudo-hardlinks, while genuine symlinks remain `DT_LNK`;
- `proot-link2symlink-host-path.patch` resolves a confirmed final `.l2s`
  backing path during canonicalization;
- `proot-link2symlink-force-exdev.patch` returns `EXDEV` only inside an exact,
  opt-in mutable-runtime `tmp-` prefix, translated to the canonical host path,
  so Pressure Vessel uses its normal copy fallback;
- `proot-runtime-bind-exact-detranslate.patch` lets an exact runtime bind win
  host-to-guest fd detranslation;
- `proot-pivot-detached-root.patch` preserves Bubblewrap's detached old root
  through its open fd during `pivot_root(".", ".")`;
- `proot-pivot-drop-stale-bindings.patch` removes bindings from the detached
  namespace so they cannot shadow the transient fd alias;
- `proot-mountinfo-escape-paths.patch` emits Linux mountinfo octal escapes for
  whitespace and backslashes in synthetic mount points and sources, allowing
  Bubblewrap to match compatibility-tool paths such as `Proton 11.0 (ARM64)`;
- `proot-runtime-mount-stack.patch` retains covered equal-path runtime mounts,
  so Bubblewrap's tmpfs-over-`/tmp` setup can still reach the original shared
  Termux tmp directory below `/oldroot/tmp` after its first `pivot_root`;
- `proot-runtime-directory-bind-target.patch` keeps the final component of an
  emulated directory mount literal, matching startup-bind behavior and allowing
  a post-`--proc` `/proc/net` directory bind to replace Android's
  process-specific `/proc/self/net` symlink.

`proot-noderef-fastpath.patch` is a separate experimental performance patch. It
adds an environment-gated fast path for a narrowly constrained metadata lookup
inside a trusted host-visible prefix. It is documented and benchmarked in
`docs/PERFORMANCE.md` but is not part of the production build yet.
