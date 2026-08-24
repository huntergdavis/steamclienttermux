# Productization research

## Objective

Turn the working research stack into a reproducible open-source Steam-on-Android
bootstrap without redistributing Valve software or handling user credentials.

## Product decision

| Shape | Decision | Reason |
| --- | --- | --- |
| Signed/checksummed Termux bootstrap archive | **Deterministic builder works** | Small, auditable, compatible with official Termux tooling |
| Optional Android setup UI using Termux `RUN_COMMAND` | Later | Improves onboarding without sharing Termux's UID |
| Shared-UID add-on APK | Reject | Cannot join arbitrary Termux installs without the same signing key |
| Monolithic Termux + X11 + Steam APK | Reject for MVP | Large maintenance, signing, target-SDK, and executable/JIT burden |
| Bundle Valve/Proton/game payloads | Reject | Users fetch proprietary content from official sources |

## Proven acquisition boundary

| Artifact | Locked identity |
| --- | --- |
| Valve channel | `stable`, `linuxarm64`, build `1785799196` |
| Manifest | 12,579 bytes; SHA-256 `a2ad912e...ca91` |
| ARM64 seed | 109,534,844 bytes; SHA-256 `3f282edb...c06` |
| Seed executable | AArch64; 10,044,176 bytes; SHA-256 `72f48fb9...4126` |

[`steam-arm64-bootstrap-lock.json`](../config/steam-arm64-bootstrap-lock.json)
contains the complete URLs and hashes. The safe extractor normalizes Valve's
mixed path separators, rejects traversal/collisions/special files, validates
three relative symlinks, and promotes only a complete verified staging tree.

## Intended user flow

1. Install Termux and the matching Termux:X11 package from one trusted source.
2. Download one signed project release archive.
3. Run one bootstrap command.
4. The bootstrap verifies Android/device prerequisites and free space.
5. It installs open-source helpers transactionally and fetches locked external
   payloads directly from their publishers.
6. It starts Steam; Valve owns update, account login, Steam Guard, Proton, and
   game installation.
7. A doctor command reports actionable pass/fail results without exposing
   credentials.

## Release archive contents

| Include | Exclude |
| --- | --- |
| Project scripts and source | Steam client bytes |
| Dependency and artifact locks | Proton/runtime/game payloads |
| Build recipes and patches | Credentials, cookies, 2FA, userdata |
| Default performance profiles | Device-specific private state |
| Licenses, notices, checksums | Signing keys |
| Installer, verifier, rollback metadata | Unverified caches |

## Generic versus device-specific

| Generic layer | Hardware profile layer |
| --- | --- |
| Steam acquisition and verification | Turnip/Mesa artifact choice |
| Transactional install/update/rollback | CPU topology and affinity masks |
| X11/PulseAudio lifecycle | Resolution/refresh defaults |
| Steam UI fast paths | Game-specific DXVK/FEX profiles |
| Logging and doctor output | Thermal ceilings |

Device profiles must be data, not forks of the installer. Unknown devices start
with conservative defaults and no performance claims.

Game-specific startup tuning follows the same rule. The generic prefetch helper
accepts small reviewed manifests of relative paths, installed sizes, and byte
budgets. Other games can ship different manifests without changing the engine
or weakening its path, symlink, and size checks.

## Release gates

| Gate | Pass condition |
| --- | --- |
| Deterministic build | Same source/lock produces the same archive and checksums |
| Fresh install | Clean supported device reaches rendered authenticated Steam |
| Idempotence | Running setup twice preserves working state |
| Update | Exact old/new identities and transactional promotion |
| Rollback | Injected failure restores every previous tracked artifact |
| Uninstall | Removes project-owned files only; preserves Steam/user libraries by default |
| Security | No credentials in logs; no broad process kills or writable shared secrets |
| Performance | Warm UI and game-launch timings meet published device-profile bounds |
| Documentation | README remains short; detail lives in tables and linked evidence |

The deterministic-archive gate now passes on the real tree: two independent
builds of commit `f71e1b6` produced the same 3,322,952-byte ZIP with 267 payload
files and SHA-256 `08822e3d...31bd`. The manifest truthfully reports that no
license is tracked; selecting one is the remaining owner-controlled publication
gate.

## Next implementation slices

1. One `bootstrap` and one `rollback` entry point; the read-only doctor exists.
2. Fresh-prefix integration test with fake external payloads and doctor output.
3. Hardware validation on the Tab S8+ with exact artifact identity.
4. Project-owner license selection and tracked license text.
5. Signed release process and compatibility matrix.
6. Optional setup UI only after the command-line product is repeatable.

## Research provenance

The focused recall query
`steamclienttermux terse README timing table packaging productization research
document` returned no indexed implementation. This document consolidates the
manifest-locked Valve bootstrap, existing transactional installer patterns,
native Steam timing evidence, and prior Termux/shared-UID architecture research.
