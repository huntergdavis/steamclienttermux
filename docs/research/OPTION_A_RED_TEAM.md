# Option-A red-team review

The product default is one private internal install. Advanced storage and
per-game tuning are optional profiles.

| Finding | Product rule | Status |
| --- | --- | --- |
| Developer checkout paths leaked into launchers | Use `$STEAM_ARM64_BASE/tgcompat/current` | Fixed |
| Unknown AppIDs were rejected | Launch every AppID generically; profiles only optimize | Fixed |
| Generic games required Tomb Raider/GTA IV helpers | Validate a tuning helper only for its matching AppID | Fixed |
| Caller build variables could change tgcompat | Sanitize compiler, preload, Make, and Git overrides | Fixed |
| Setup plan omitted completed tgcompat work | Keep the plan and doctor source inventory executable | Fixed |
| SD-card behavior complicates locks and executable mappings | Default to Termux private storage | Fixed policy |
| Patched glibc and PRoot still require research commands | Add locked installers and receipts | Open |
| Launchers are installed by a large developer script | Replace with a minimal manifest transaction | Open |
| First launch requires X11/audio knowledge | Add one `steam-arm64` entry and actionable doctor | Open |
| Only Tomb Raider has a measured optimized profile | Use the next user-selected game as acceptance test | Open |

## New-game acceptance flow

1. Install the game normally in Steam's internal library.
2. Run `start-steam-game APPID`; the generic route must launch without edits.
3. Capture the first failing boundary and a timing profile.
4. Add only proven compatibility settings to the AppID manifest.
5. Keep game-specific performance tuning optional and data-driven.

The required `deja` query found no indexed implementation. This review reuses
the existing AppID manifest, generic Steam `--appid` route, doctor, and locked
runtime receipts.
