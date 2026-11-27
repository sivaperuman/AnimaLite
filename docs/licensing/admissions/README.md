# Execution admission records

An **admission record** is a recorded human decision that a set of pinned
third-party artifacts may be *executed*, for a stated purpose. It is not a hash
check and it is not a licence summary. Those two answer different questions:

| Question | Answered by |
| --- | --- |
| Are these the bytes we pinned? | `animalite runtime status` (digests) |
| What do the upstream terms say? | `docs/licensing.md`, DEC-0013 |
| **May we execute them, for this purpose?** | **an admission record** |

`animalite.admission` enforces the third one. A profile that declares
`learned_temporal_participation=true` cannot be executed — by `render`, by
`benchmark`, by the process-cold child, or by driving the adapter directly —
unless an approved record covers **every** artifact digest the profile declares
**and** the purpose the run declares. Missing, pending and rejected all block.

There is no development bypass flag. Blocking only the qualification evaluator
would not be enforcement: by then the weights have been downloaded, the runtime
has executed and frames have been produced.

## Where records live

```
ANIMALITE_ADMISSION_DIR=/path/to/records   # explicit override
$XDG_DATA_HOME/animalite/admissions        # default
```

One JSON file per record. The directory is *outside* the repository on purpose:
an approval is an operator's decision about their own use, and a record
committed here would make every checkout inherit it.

## What is in this directory

`rife-ncnn-20221029.json` — the **dossier** for the pending RIFE decision. It
names the exact artifacts, states the open questions and lists the purposes
being requested. It carries `"decision": "pending"`, so copying it into the
admission directory installs a block, not a pass; a test asserts that nothing
committed here is ever `approved`.

## Recording a decision

Copy the dossier into the admission directory, then set `decision` to
`approved` and fill in what the schema requires — the record is refused
otherwise, because an approval with these fields blank is the shape a bypass
would take:

* `reviewer` — who decided.
* `reference` — where the reasoning lives (a decision record, an issue).
* `recorded_at` — when.
* `permitted_purposes` — any of `research`, `benchmark`, `production`,
  `redistribution`. Only what was actually decided; each is a separate
  permission.
* `artifact_hashes` — the exact digests covered. Adding or changing an artifact
  invalidates the record rather than inheriting it, which is the point.

Then confirm:

```bash
animalite runtime status --purpose research
animalite runtime status --purpose benchmark --json
```

`decision: rejected` is a first-class outcome and is worth recording: it stops
the question being re-litigated silently, and it blocks exactly like `pending`.
