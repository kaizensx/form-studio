---
name: release
description: Hand a finished FORM revision to the user for approval and check existing releases. Use when the user wants the final files, asks to release or ship a design, or asks whether a release still matches the design.
---

# Release

FORM tools: `get_project()`, `run_pipeline()`, `request_release()`, `verify_release()`, `open_bench()`, `open_in()`.

1. Run verify-print first. Every output must be current for the head revision; regenerate anything stale.
2. `request_release()` checks the gate and returns a link. **You cannot approve.** The user approves in the app's
   Make stage (the last tab) after reviewing the checks and acknowledging each warning.
3. Tell the user, plainly: the revision, what is measured versus assumed, the evidence stage (e.g. "sliced and
   inspected, simulated; no physical test yet"), open warnings, and for multi-part designs the parts list and
   assembly order.
4. A release is a frozen copy with a hash manifest. `verify_release(release=...)` re-hashes it and says whether it still
   matches the head. Current hashes prove the files are the ones released, not that the design is correct.

Never mark anything current by hand, never edit released files, never upload or send files anywhere, never start a
print. `open_in()` opens a file in the user's own software on this machine.
