# Packaging the native Steam stack

The near-term deliverable is a signed, reproducible Termux bootstrap package,
not a private game-service clone and not an APK containing Valve binaries.

## Supported product shape

1. Install official Termux and the matching Termux:X11 build from the same
   trusted signing source.
2. Install one project bootstrap package containing only our open-source code,
   lock files, licenses, and setup scripts.
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

Run against an already-downloaded archive:

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

The remaining package gates are a bootstrap/rollback entry point, fresh-device
setup test, uninstall test, license selection, and release-signing workflow. A later optional
target-SDK-36 Android UI can invoke a small fixed set of Termux `RUN_COMMAND`
entry points, but it must remain separately signed and must not share Termux's
UID.

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
