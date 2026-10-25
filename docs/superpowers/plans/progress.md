# SDD ledger — plan: docs/superpowers/plans/2026-10-25-dybrowser.md

Execution: native, authorized by user. No Git repository exists; work stays in requested directory.

Ruling: Keep a persistent ledger with the plan rather than Git-only workspace tooling — no repository exists, and creating one was not requested.

Interface scan: tasks 1→2/3/4 share ToolError and validation; tasks 2→3 share Session/page registry; tasks 2/3→4 share manager.dispatch. Normalize all public operations through manager.dispatch(method, path, payload).

Environment: initial ensurepip failed because sandbox TEMP was unwritable; retry with project-local .tmp, preserving the requested .venv location.

Task 1: complete — protocol tests RED→GREEN, 2/2; Playwright 1.64.1 installed in .venv.
Task 2: complete — Session integration tests RED→GREEN, isolation/restore/popup/browser close passed in full run.
Task 3: complete — action tests RED→GREEN, 4/4 passed in full run. Regression found upstream ARIA exposing password; redacted values without modifying DOM. Fixed fixture label so select has an unambiguous accessible name.
Task 4: in progress — cross-process CLI flow passed up to screenshot; test HTTP helper shadowed its import and prevented cleanup, now corrected with graceful shutdown in finally.

Task 4 verification: initial full suite 9/9 passed; setup.ps1 repeat succeeds, pip check clean, compileall clean. artifacts/verification.png visually checked. No project browser/service process remained.

Final review: independent gpt-6-astra reviewer identified three Important issues, no Critical/minor findings. No second review dispatch.
Final: fixed empty page/frame target fallback — test_empty_explicit_targets_cannot_fall_back_to_current_page RED→GREEN.
Final: fixed retained closed Session clearing a newer profile lock — test_old_closed_session_cannot_unlock_new_profile_owner RED→GREEN; intermediate full suite 11/11.
Final: fixed ignored locator constraints — test_ignored_target_constraints_are_rejected RED→GREEN; action-specific field allowlists and modifier dependencies. HTTP regression checks rejected click leaves button counter unchanged.

Ruling: The planned manager.dispatch was replaced with worker.route plus manager.action — transport routing stays separate from browser logic; cost if wrong is an internal method rename, with no public protocol difference.

Final verification found intermittent Windows TCP reset on oversized request: existing test_service failed while reading JSON. Fixed response flush + graceful write half-close and bounded input drain; rerun service test and repeat oversized requests five times before final suite. This is part of the same fix pass; no completion until the suite is green.

Task 4: complete — final full suite 12/12 passed in 46.844 seconds. Oversized-request rejection repeated five times with intact structured JSON. Independent CLI create/goto/snapshot/ref click/screenshot/close/stop verified. pip check and compileall clean; setup script rerun successful.
Final: fixed all three independent-review Important findings and the Windows transport regression; no deferred minor findings. User-facing API follows the approved spec. No Git commits or worktrees were created; permanent docs/ledger retained for this non-Git directory.
