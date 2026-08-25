# Packaging the native Steam stack

The near-term deliverable is Option A: a signed, reproducible Termux bootstrap
archive and one command. Option B packages the same engine and locks as a
signed-repository `.deb`. APK and ADB product paths are out of scope.

## Supported product shape

1. Install official Termux and the matching Termux:X11 build from the same
   trusted signing source.
2. Unpack the signed/checksummed project release and run:

   ```sh
   scripts/bootstrap-termux-stack.sh
   ```
3. Fetch the ARM64 Steam seed directly from Valve, verify its pinned identity,
   and safely extract it.
4. Build/install the native glibc compatibility tools and sensible defaults.
5. Start Valve's client; Valve performs the remaining update, login, Steam
   Guard, Proton, and game downloads.

This avoids sharing Termux's UID, SSH keys, or application data with another
APK. Android deprecates `sharedUserId`, and a shared-UID add-on cannot join an
arbitrary Termux install unless both APKs use the same signing key. A monolithic
Termux/X11 fork would also inherit Android target-SDK and executable/JIT
maintenance costs, so it is not the MVP.

## Locked Steam seed

[`config/steam-arm64-bootstrap-lock.json`](../config/steam-arm64-bootstrap-lock.json)
pins Valve stable build `1785799196`, the official manifest, the raw AArch64
seed ZIP, and the extracted ELF identity. The lock forbids redistribution.

The one-command bootstrap installs dependencies first, then runs the locked
Steam-seed phase. The lower-level commands remain available for diagnosis:

```sh
python3 scripts/setup-steam-stack.py plan
python3 scripts/setup-steam-stack.py prepare
python3 scripts/setup-steam-stack.py status
python3 scripts/setup-steam-stack.py rollback
```

`prepare` is idempotent. `rollback` refuses modified/unreceipted trees and
moves the verified seed plus receipt into a private quarantine; it never
deletes the download cache or user libraries. An interrupted prepare or
rollback retains a durable transaction that the same command resumes.
[Host evidence](evidence/steam-stack-phase1-setup-host-20260824.json) records
the exact proof boundary; no fresh-device or full-runtime claim is made yet.

The authoritative plan calls the product shape
`two-apks-one-termux-command`: Android Package Manager installs Termux and the
Termux:X11 app; the setup command owns every automatable step afterward; Valve
owns login. Text and JSON output share one tested data structure so later UI
work cannot overstate the automation boundary.

The first Option-A runtime slice is an exact, executable package profile:

```sh
python3 scripts/setup-steam-stack.py dependencies
python3 scripts/setup-steam-stack.py dependencies --check
python3 scripts/setup-steam-stack.py dependencies --install --yes
```

[`termux-setup-profile.json`](../config/termux-setup-profile.json) separates
repository enablers from 34 build/runtime packages, maps 27 required commands
to their owning packages, and records every tested package version. The
working tablet satisfies all 36 entries. Installation is repository-first,
receipt-backed, restartable after interruption, and idempotent. It deliberately
preserves shared Termux packages during rollback/uninstall. Versions are
evidence rather than hard equality pins; signed Termux metadata chooses
compatible updates.

The first accelerated hardware profile is AArch64 Qualcomm/Adreno KGSL with
Turnip. The installer engine is generic, but claiming acceleration on Mali,
PowerVR, or other GPU families requires a separately tested graphics profile.

## Locked Turnip runtime

The Option-A command fetches the Qualcomm/Adreno Turnip runtime directly from
its open-source release publisher. The lock pins its source tag and full
commit, archive URL/size/SHA and shape, driver size/SHA, Mesa version, and
Vulkan API version:

```sh
python3 scripts/install-turnip-runtime.py install --base "$HOME/steam-arm64"
```

The extractor accepts only bounded directories, regular files, and relative
in-tree symlinks. It rejects traversal, collisions, special files, symlink
descendants, expanded-size changes, and any driver mismatch. Promotion is by
rename after verification; an unchanged receipted rerun is idempotent. The
project fetches the archive from the publisher and does not rebundle it.

## Locked native compatibility runtime

The next Option-A phase builds tgcompat from exact public source:

```sh
python3 scripts/install-tgcompat-runtime.py --base "$HOME/steam-arm64"
```

[`tgcompat-runtime-lock.json`](../config/tgcompat-runtime-lock.json) pins the
Git origin and full commit. The installer stages a detached clone, rejects
tracked drift and symlinks, runs the optimized native build and full tests,
hashes six binaries plus the session helper, and records elapsed time before
rename promotion. `tgcompat/current` is a product-owned selector; an unchanged
rerun does no work. Native hashes are device evidence, not equality constraints
across different ARM64 CPUs.

Option B will build that same locked source in release infrastructure and
deliver it through a signed Termux repository `.deb`.

The lower-level verifier can also use an already-downloaded archive:

```sh
python3 scripts/bootstrap-steam-arm64-client.py verify \
  --archive "$HOME/Downloads/bins_linuxarm64_linuxarm64.seed.zip"

python3 scripts/bootstrap-steam-arm64-client.py extract \
  --archive "$HOME/Downloads/bins_linuxarm64_linuxarm64.seed.zip" \
  --destination "$HOME/steam-arm64/client-seed"
```

Or fetch and extract directly from Valve:

```sh
python3 scripts/bootstrap-steam-arm64-client.py install \
  --cache "$HOME/steam-arm64/download-cache" \
  --destination "$HOME/steam-arm64/client-seed"
```

The installer verifies the manifest and archive size/SHA before extraction. It
normalizes Valve's mixed slash/backslash member names, rejects absolute paths,
`..`, normalized collisions, special files, symlink traversal, descendants of
symlinks, size-limit violations, and existing destinations. It preserves file
modes and only permits relative symlinks that remain inside the extracted tree.
Extraction occurs in a new sibling staging directory and is promoted by rename
only after the locked AArch64 ELF is re-hashed.

## Read-only doctor

```sh
python3 scripts/steam-stack-doctor.py --mode bootstrap
python3 scripts/steam-stack-doctor.py --mode runtime
```

| Mode | Checks |
| --- | --- |
| `bootstrap` | ARM64 Android, Termux/X11, build tools, private storage, release source |
| `runtime` | Bootstrap checks plus Steam, Turnip, glibc, audio, and launcher artifacts |

The doctor changes nothing and does not read Steam credentials. Use `--json`
for installer/UI integration. Missing project licensing is a warning for local
research; any missing runtime prerequisite fails closed.

| Tab S8+ hardware check | Result |
| --- | --- |
| Installed runtime at 1 GiB floor | Pass; all runtime components verified |
| Fresh bootstrap at default 4 GiB floor | Refused; only 1.65 GiB free |
| Steam/X11 disruption | None; process identities preserved |

See [the compact hardware evidence](evidence/steam-stack-doctor-tablet-20260824.json).

## Release and trust plan

- Build a deterministic package from an exact Git commit and stack lock.
- Publish SHA-256 sums, an external signature, source commit, dependency lock,
  Android/Termux compatibility matrix, and third-party notices.
- Keep signing keys outside the repository and CI artifacts.
- Never bundle Valve, Proton, games, redistributables, or account state.
- Fail closed when a live upstream no longer matches a tested lock; publish a
  new lock only after hardware validation.
- Make every system mutation transactional with exact backups and a dry-run.

The remaining package gates are full open-source runtime build/install,
fresh-device and uninstall tests, license selection, and release signing. A
later optional target-SDK-36 UI can invoke fixed Termux `RUN_COMMAND` entry
points, but it remains separately signed and never shares Termux's UID.

## Deterministic project archive

```sh
python3 scripts/build-release-archive.py \
  --commit HEAD \
  --destination "$PWD/dist/release-candidate"
```

The builder reads exact committed Git blobs, not the working tree. It includes
runtime code, tests, locks, key documentation, and the README image while
excluding historical bulk evidence and all proprietary payload locations. ZIP
entries use fixed timestamps, preserved executable modes, and deterministic
stored bytes. The external manifest records the source commit, archive identity,
and every included file's path, size, mode, and SHA-256.

| Real-tree proof (`f71e1b6`) | Result |
| --- | ---: |
| Independent build A | 2.57s |
| Independent build B | 2.52s |
| Byte-for-byte equality | Pass |
| Payload files | 267 |
| Archive size | 3,322,952 bytes |
| Archive SHA-256 | `08822e3d...31bd` |
| Valve binaries | None |
| Tracked license | **Missing; public release blocked** |

The missing license is a project-owner decision and is not inferred by the
builder. Local candidate construction and testing can continue, but no archive
should be described or published as an open-source release until a license is
chosen and tracked.

## Provenance

The required local recall query
`steamclienttermux signed reproducible package Valve ARM64 manifest lock safe zip extractor bootstrap`
returned no indexed implementation. This design reuses the repository's
retained native updater evidence in `docs/logs/debian-native-linked-20260807-115310.log`
and `docs/logs/bootstrap-driver-2.log`, plus the existing fail-closed artifact
identity and no-clobber staging patterns.

The focused deterministic-archive query
`steamclienttermux deterministic release archive builder manifest sha256
reproducible zip tar` also returned no indexed implementation.
