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

The production build applies six additional focused patches after the IPC
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
  namespace so they cannot shadow the transient fd alias.

`proot-noderef-fastpath.patch` is a separate experimental performance patch. It
adds an environment-gated fast path for a narrowly constrained metadata lookup
inside a trusted host-visible prefix. It is documented and benchmarked in
`docs/PERFORMANCE.md` but is not part of the production build yet.
