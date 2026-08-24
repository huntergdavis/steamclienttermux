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

Prepared Proton/Wine executables use identity-bound receipts for the common
launch path. Unchanged device/inode/size/time/mode/owner metadata avoids
re-reading large binaries; any change falls back to full ELF and SHA-256
validation. This keeps startup fast without turning a stale stamp into trust.

DXVK state-cache placement is also AppID data. A generic seeder can copy an
existing cache once from a removable game prefix into private internal storage,
record the source hashes, and validate bounded cache shapes on reuse. The
final-game-only selector prevents caller or Steam/CEF environment leakage;
external placement remains the default until a device A/B proves improvement.

Device profiles must be data, not forks of the installer. Unknown devices start
with conservative defaults and no performance claims.

Game-specific startup tuning follows the same rule. The generic prefetch helper
accepts small reviewed manifests of relative paths, installed sizes, and byte
budgets. Other games can ship different manifests without changing the engine
or weakening its path, symlink, and size checks.

First-paint X11 polish is profile data too: snapshot existing windows, keep a
new game-sized surface mapped off-screen, and reveal it only after its declared
`WM_CLASS` is confirmed. This avoids game-specific debug or overlay windows.

Optimized launch selection is data-driven too. `start-steam-game APPID` resolves
the AppID and named mode through a reviewed manifest, then enters that game's
specialized direct launcher. Unknown games and malformed or linked launchers
fail closed; the ordinary Steam route is never selected silently.

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

## License decision

MIT is open source, but it permits a distributor to keep a modified fork
closed. For this user-installed application stack, the recommended license for
new project-owned code is **GPL-3.0-or-later**: anyone distributing a modified
binary must also provide corresponding source. AGPL-3.0 adds a source offer for
software used over a network, which is valuable for hosted services but does
not materially strengthen this local Android launcher.

One root license cannot replace upstream terms. The release manifest and
notices must retain these component boundaries:

| Component | Upstream terms | Release treatment |
| --- | --- | --- |
| Project-owned scripts and tools | Owner choice | GPL-3.0-or-later recommended |
| PRoot-derived patches/binary | GPL-2.0-or-later | Keep GPL notices and corresponding source |
| glibc | LGPL-2.1-or-later | Preserve LGPL notices/source and relinking rights |
| FEX | MIT | Preserve its copyright/license notice |
| DXVK | zlib/libpng | Preserve notice; mark modified source |
| Mesa/Turnip | Mostly MIT, file-specific | Carry the selected files' SPDX licenses/notices |
| Termux and Termux:X11 apps | GPL-3.0 | Separate official installs, or ship compliant source/notices |
| Steam, Proton, games | Mixed/proprietary | Fetch from publishers; never relicense or bundle blindly |

The PRoot patch directory remains under its upstream GPL terms even if the rest
of this repository uses GPL-3.0-or-later. GPL does not compel publication of
private changes or require anyone to submit changes upstream; it requires
source availability when covered builds are distributed. Running or
orchestrating separate programs does not by itself relicense original project
code. Before release, add the chosen root license, SPDX headers,
`THIRD_PARTY_NOTICES.md`, and a component-level SBOM. This is engineering
guidance, not legal advice.

Primary references: [GPLv3 guide](https://www.gnu.org/licenses/quick-guide-gplv3.en.html),
[AGPL network clause](https://www.gnu.org/licenses/agpl-3.0.en.html),
[PRoot GPLv2](https://github.com/termux/proot/blob/master/COPYING),
[glibc LGPLv2.1](https://snapshots.sourceware.org/glibc/trunk/2025-08-04_17-48_1754329681/manual/html_node/Copying.html),
[Termux GPLv3](https://github.com/termux/termux-app/blob/master/LICENSE.md),
[Termux:X11 GPLv3](https://github.com/termux/termux-x11/blob/master/LICENSE),
[FEX MIT](https://github.com/FEX-Emu/FEX/blob/main/LICENSE),
[DXVK zlib](https://github.com/doitsujin/dxvk/blob/master/LICENSE), and
[Mesa licensing](https://docs.mesa3d.org/license.html).

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
