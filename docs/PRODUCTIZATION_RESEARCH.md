# Productization research

## Objective

Turn the working research stack into a reproducible open-source Steam-on-Android
bootstrap without redistributing Valve software or handling user credentials.

## Product decision

| Shape | Decision | Reason |
| --- | --- | --- |
| Signed/checksummed Termux bootstrap archive | **Archive + Phase-1 setup work** | Small, auditable, compatible with official Termux tooling |
| Optional Android setup UI using Termux `RUN_COMMAND` | **Out of scope** | The Termux CLI/package remains the only product surface |
| Shared-UID add-on APK | Reject | Cannot join arbitrary Termux installs without the same signing key |
| Monolithic Termux + X11 + Steam APK | Reject for MVP | Large maintenance, signing, target-SDK, and executable/JIT burden |
| Bundle Valve/Proton/game payloads | Reject | Users fetch proprietary content from official sources |

## Easiest honest install shape

The release target is **two Android apps plus one Termux command**. The command
is the single source of truth for package installation, verified downloads,
runtime construction, configuration, updates, diagnostics, and rollback.

```sh
python3 scripts/setup-steam-stack.py plan
python3 scripts/setup-steam-stack.py plan --json
```

| Step | Owner | Automation | Current state |
| --- | --- | --- | --- |
| Install Termux APK | User or ADB | Android Package Manager | Manual prerequisite |
| Install Termux:X11 APK | User or ADB | Android Package Manager | Manual prerequisite |
| Install Termux:X11 companion and dependencies | Setup command | `pkg`/locked recipes | Implemented |
| Acquire and receipt Valve's ARM64 seed | Setup command | Locked HTTPS + safe extractor | Implemented |
| Install Turnip | Setup command | Locked upstream archive + safe extractor | Implemented |
| Install glibc, PRoot, launchers and profiles | Setup command | Transactional runtime installer | In progress |
| Steam login and Steam Guard | User | Valve client | Always manual |

This boundary is architectural, not just documentation: the CLI exports the
same map as JSON for packaging and verification. Option A is the current
signed/checksummed archive plus one command. Option B is the long-term signed
Termux repository and `.deb`; both invoke the same setup engine and locks.

| Alternative | Why it is not the MVP |
| --- | --- |
| One ZIP and one pasted command | **Option A now**; fastest honest route to a repeatable release |
| Signed Termux package repository | **Option B goal**; adds package-manager updates and uninstall |
| Thin control-panel APK | Out of scope; the CLI/package is the product surface |
| Shared-UID add-on APK | Cannot join independently signed Termux installations |
| Monolithic Termux/X11 fork | Requires private signing, bootstrap/package rebuilds, and permanent Android maintenance |
| ADB installer | Excellent developer path, too technical as the consumer default |

Official boundaries: [Termux:X11 requires an Android app and companion
package](https://github.com/termux/termux-x11), [RUN_COMMAND requires explicit
permission and `allow-external-apps`](https://github.com/termux/termux-app/wiki/RUN_COMMAND-Intent/7c2a42556426b29e0b5b0d60035fbd538dd7b7e5),
and [Termux add-ons must use compatible signing identities while forks must
rebuild their bootstrap](https://github.com/termux/termux-app/blob/master/README.md).

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
3. Run `scripts/bootstrap-termux-stack.sh` from the verified release; it now
   completes dependencies, Valve seed, Turnip, and native tgcompat.
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

Warm AppID requests also use a generic authenticated singleton handoff. After
matching the exact native Steam PID, start ticks, loader, profile, and immutable
environment, the launcher validates Steam's owner-only private directory and
FIFO and writes one bounded argv packet atomically. It never sends credentials
or account data. If the real FIFO has no reader, the established native-client
fallback remains available; an unsafe path, owner, mode, link count, or inode
change fails closed. This removes redundant Steam process startup for every
reviewed AppID rather than embedding a Tomb Raider special case.

Controller support stays enabled in the general profile. A matched tablet A/B
found no AppID-acceptance benefit from disabling SDL HIDAPI, so packaging must
not trade controller compatibility for an unmeasured or workload-specific
speed claim. The diagnostic selector remains explicit and cold-session-only.

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

The restartable Phase-1 entry point now runs the read-only doctor, acquires the
locked Valve seed, writes an exact inventory receipt, recognizes an unchanged
rerun, recovers an interrupted promotion, and quarantines only an unchanged
receipted seed on rollback. It deliberately does not claim that the glibc,
Turnip, FEX, Proton, or launcher install is one-command yet.
[Install-shape evidence](evidence/steam-stack-install-shape-host-20260824.json)
records the manual/automatic boundary and its CLI contract.

Option A now also has one package-compatible dependency profile. It declares
36 Termux packages in repository-first order, assigns 27 required commands to
their providers, and retains the exact versions observed on the working
Android 16 tablet. `setup-steam-stack.py dependencies` renders install commands;
`--check` is read-only and fails if any package is absent. This same profile is
intended to become the Option-B `.deb` dependency source rather than a second
hand-maintained list.

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

1. Extend the entry point from verified Steam seed to the open-source runtime.
2. Fresh-device, update, rollback, and uninstall tests.
3. Hardware validation on the Tab S8+ with exact artifact identity.
4. Project-owner license selection and tracked license text.
5. Signed release process and compatibility matrix.
6. Publish the same setup engine as a signed-repository `.deb`.

## Research provenance

The focused recall query
`steamclienttermux terse README timing table packaging productization research
document` returned no indexed implementation. This document consolidates the
manifest-locked Valve bootstrap, existing transactional installer patterns,
native Steam timing evidence, and prior Termux/shared-UID architecture research.
