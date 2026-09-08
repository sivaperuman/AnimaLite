@AGENTS.md

# Claude Code implementation role
Read the current work package, relevant requirements and linked PR decisions.
Implement the approved scope, run the documented checks and provide reviewable evidence.
Respond to ChatGPT's review in one finding-to-fix table with the tested commit SHA.
Continue routine implementation without repeated permission questions.
Use the shared decision boundaries when a change affects targets, scope, spend or rights.

## Where things are
- Work package definitions: `docs/requirements/AnimaLite_Implementation_Handoff_v0.2.md` §6.
- Current package: A (foundation and measurement). B adds the learned CPU path.
- Durable decisions: `docs/decisions/` — read the index before proposing a change
  to something already settled.
- Requirement → evidence mapping: `docs/verification/package-a-traceability.md`.
- Commands actually run, with output: `docs/verified-commands.md`.

## Before opening or updating a PR
Run the quick checks in AGENTS.md ("Verified commands"), record the tested commit
SHA and working-tree state, and update `docs/verified-commands.md` if any command
or its output changed.
