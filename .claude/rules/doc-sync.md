# Doc-Sync Rule

When modifying source code or infrastructure, update the corresponding documentation:

| Change type | Update |
|-------------|--------|
| Source file in a child project (`.py`, `.js`) | That project's `CLAUDE.md` (code map, exports, signatures) |
| Architecture/infrastructure change | `docs/ARCHITECTURE.md` or `docs/CURRENT_STATE.md` |
| Windmill flow/script change | Root `CLAUDE.md` pipeline section |
| New file added to any project | Root `CLAUDE.md` code map + child `CLAUDE.md` |
| Endpoint contract change | Root `CLAUDE.md` + child `CLAUDE.md` endpoint section |

Always commit doc changes alongside code changes to GitHub (`BeastofOne/rrg-server`).
