# AnimaLite implementation handoff

Version 0.2 · 8 September 2026 · Companion to requirements v0.12

**Objective:** useful, short video generation from sparse approved frames on CPU or lower-spec hardware, with measured short turnaround. Claude Code implements in GitHub; ChatGPT supplies technical guidance, review findings and decisions in PR comments. The project owner retains scope, target-hardware, budget, licensing and final go/no-go decisions.

This handoff adds engineering instructions. It does not change the requirements, approve the proposed speed targets, or assert that a model has passed them. No repository has been inspected or modified for this handoff; actual setup commands and dependency versions must be verified in the first PR.

**Naming decision:** AnimaLite is the project name. Use `animalite` for the Python package and CLI, and `AnimaLite` or `animalite` for the GitHub repository. These replace the earlier handoff's provisional `framevideo` package name. This handoff version supersedes v0.1; preserve the v0.12 requirement IDs and performance conditions.

**Public distribution decision:** the owner wants public source with commercial-use restrictions. The recommended implementation is the standard PolyForm Noncommercial License 1.0.0 for original AnimaLite software. Put that recommendation into the first PR for review; do not describe it as an already executed legal agreement or permission covering third-party material.

## 0. Repository licensing and publication instructions

Create the public repository with no automatic license template, then add the official PolyForm text as root `LICENSE`. Selecting no template is a setup step, not the finished licensing policy. GitHub supports [manually adding a license file](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/adding-a-license-to-a-repository).

PolyForm permits noncommercial purposes and specified organizational uses, including educational and government institutions irrespective of funding. It is not an absolute prohibition on every revenue-related activity. Keep its text unchanged and preserve its exceptions; a stricter policy needs separately reviewed custom terms. See the [official license](https://polyformproject.org/licenses/noncommercial/1.0.0).

Use **public source-available** in README/metadata. A commercial-use restriction does not meet the [Open Source Definition](https://opensource.org/osd). The SPDX identifier is [`PolyForm-Noncommercial-1.0.0`](https://spdx.org/licenses/PolyForm-Noncommercial-1.0.0.html).

Implement these files alongside the initial code:

| File | Required content |
| --- | --- |
| `LICENSE` | The complete unchanged [official PolyForm Noncommercial 1.0.0 text](https://polyformproject.org/licenses/noncommercial/1.0.0.txt), checked against its publisher. Do not invent an MIT-plus-noncommercial hybrid. |
| `NOTICE` | AnimaLite's copyright notice, using the owner's actual copyright-holder name, and preserved applicable notices. Do not attribute somebody else's code or weights to the owner. |
| `README.md` | Project goal, actual implementation status, license name/link, third-party exclusions and how to request separate commercial permission. Include no invented contact address, commercial price or performance claim. |
| `THIRD_PARTY_NOTICES.md` | Direct dependencies and bundled components, exact versions, license/source references and required notices. Record whether each is used, linked, modified or redistributed. |
| `docs/licensing.md` | Scope of AnimaLite's license, independent model/asset terms, known integration obligations and unresolved licensing decisions. |
| `CONTRIBUTING.md` | Contribution workflow and requirement that contributors have rights to submit their work under the project terms. Preserve contributor attribution. |

Treat a request for commercial permission as an owner decision. Do not promise that the maintainer can commercially relicense all future community contributions: that requires sufficient rights from their holders. Have a lawyer review any commercial agreement or contributor agreement intended to grant those rights. The [GitHub Open Source Guide](https://opensource.guide/legal/#what-if-i-want-to-change-the-license-of-my-project) explains contributor and relicensing considerations.

Apply AnimaLite's restriction only to software for which the necessary rights are held. Upstream RIFE/ncnn code, weights, codecs, dependencies and reference artwork keep their own terms. A noncommercial root license cannot turn an incompatible combination into a compliant one. Record separate code, weight and asset licenses; a model repository's top-level badge is not enough. Do not add AnimaLite headers to copied upstream files or claim exclusive ownership of an unmodified checkpoint.

For the first PR, invoke an explicitly installed FFmpeg executable instead of bundling it. Record the actual build and license configuration. FFmpeg's own terms depend on enabled components; LGPL/GPL obligations remain and a subprocess boundary is not a universal compatibility exemption. Review bundling or linking before distribution. See [FFmpeg's official legal guidance](https://ffmpeg.org/legal.html).

Do not claim that a software license automatically sets copyright ownership or licensing for every generated video. Software use, model terms and input/output rights are separate questions; document them distinctly. This is not a loophole granting commercial use of AnimaLite.

If existing repository content already carries another license, flag its provenance and prior grants in the PR. Do not claim that adding a new file retrospectively revokes earlier permissions. Continue independent implementation work while the affected licensing question is resolved.

## 1. What the requirements already cover

| Topic | Existing coverage | Implementation work still needed |
| --- | --- | --- |
| Architecture and stack | §§6.0–6.2: CPU core, components, proposed Python stack and local execution | Package boundaries, dependency lock, build/install commands |
| Engine interface | §6.3: validate, estimate, submit, status, cancel, collect and capabilities | Typed interfaces, state transitions, error contracts and contract tests |
| Data and interfaces | §§10–11: entities, shot manifests, asset layout and API outline | Executable schemas, migrations when storage is added, compatibility rules |
| CPU acceptance | §12.0, CR-025, MR-018, NFR-028, SM-19, AT-055/056 | Measurement harness, pinned host/profile, evidence files and quality review |
| Reliability and provenance | §§12–14 | Working failure handling, immutable outputs, device and model identity records |
| Delivery and verification | §§15–16 and Appendix E | PR-sized work packages, automated checks, evidence linked to each release clause |
| Agent collaboration | No explicit Claude/ChatGPT workflow | Shared instructions, PR template, decision log and review protocol |
| Development CI | No coding-tool or GitHub Actions policy | Small default checks, benchmark separation and duplicate-run control |

The directories in §10.4 describe **user project assets**, not the source-code repository. Keep those layouts distinct.

## 2. First-stage engineering decisions

Apply these defaults unless the selected repository already has a compatible convention. Claude may resolve routine implementation details and record them in the PR without requesting repeated confirmation.

| Area | Default for the CPU feasibility stage |
| --- | --- |
| Delivery shape | One installable Python package, a CLI, one local worker and a benchmark harness. A synchronous CLI may wait on the common job lifecycle. |
| Python/tooling | Follow §6.2's Python 3.11+ direction; pin one maintained, compatible minor and resolved dependencies in PR 1. Use one formatter/linter, type checker and test runner; recommended defaults are Ruff, mypy and pytest. |
| Application structure | A small modular application. No service fleet, Redis, PostgreSQL, web UI or provider integration is needed for the first CPU proof. |
| Temporal inference | One classical comparator plus one pinned RIFE/ncnn CPU candidate from §6.0. Candidate status does not imply admission. At most one justified optimization variant initially. |
| Model integration | Wrap the native runtime behind the adapter. A small persistent native worker is acceptable if needed to keep the model resident; do not reimplement neural operators in Python. |
| Media | CPU decode, composition and encoding. Fix dimensions, frame indexing, cadence, pixel format and codec profile; include them in the run record. |
| Assets and results | Local files, content hashes and immutable attempt directories. Add SQLite with the integrated project/job workflow when needed, rather than introducing it solely for a timing experiment. |
| Parallelism | One render job at a time on P-L; explicitly budget threads across Python, native inference and the encoder. Stream frames through bounded buffers. |
| Optional capabilities | GPU/NPU inference, cloud generation, model training, 720p qualification and mobile packaging remain separate extensions. They do not close the CPU proof. |

Start repository scaffolding, schema work and synthetic-fixture tests immediately. Keep formal gate status accurate: D-02 and §16.1 still govern target approval and qualification prerequisites. Missing hardware or production-planning evidence does not prevent writing the harness, but it must not be reported as a passed Phase 0 or Phase 1 gate. Timings on a developer or hosted machine are exploratory until the required host and sample are approved.

## 3. Repository layout to establish

These are proposed repository paths, not files that already exist in GitHub. Create directories only when their first implementation needs them.

| Path | Responsibility |
| --- | --- |
| `AGENTS.md` | Short shared engineering and review instructions; starter text below |
| `CLAUDE.md` | Imports the shared instructions and identifies Claude's implementation role |
| `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` | Project licensing and retained third-party notices; follow §0 |
| `CONTRIBUTING.md`, `docs/licensing.md` | Contribution terms, license scope and integration decisions |
| `README.md` | Current capabilities, verified setup/check commands and one small local example |
| `pyproject.toml` and a dependency lock | Package metadata, exact environment and tool configuration |
| `src/animalite/contracts/` | Typed job, profile, asset, capability, result and metric contracts |
| `src/animalite/core/` | Validation, scheduling, attempt lifecycle and resource policy |
| `src/animalite/adapters/` | Classical comparator and learned CPU runtime implementations |
| `src/animalite/media/` | Decode, frame timing, normalization, encode and output validation |
| `src/animalite/cli.py` | Thin CLI over the same application operations used by the harness |
| `tests/` | Focused contract, failure-path and tiny media integration tests |
| `benchmarks/` | Runner, dataset manifests, host/profile definitions and result schemas |
| `docs/requirements/` | The v0.12 source document and a readable, checked requirements reference |
| `docs/decisions/` | Durable implementation decisions, status and originating PR-comment URL |
| `docs/verification/` | Requirement-clause/AT/release mapping and evidence references |
| `.github/PULL_REQUEST_TEMPLATE.md` | Implementation and review handoff template below |

Keep the source document versioned. A Markdown reference should preserve requirement IDs, tables, formula meanings and relevant diagram explanations; an unchecked text extraction is not an authoritative replacement. For the first PR, the readable reference may be a clearly labelled CPU-stage extract with links to the full source. Do not load the entire specification into every agent instruction file.

Ignore model weights, compiled tools, caches, videos, local environments and benchmark outputs in ordinary source commits. Version small dataset manifests and checksums. Store restricted artwork and large evidence in an agreed access-controlled location; the PR must contain stable evidence references and their hashes.

## 4. Implementation rules

1. **Keep inference outside the domain layer.** Core types must not import model-specific packages. Adapters translate the common contract into runtime calls and expose actual capabilities. An unsupported control returns an explicit validation result.
2. **Make behavior explicit.** Validate input count, hashes, dimensions, anchor ordering and frame range. Use versioned JSON-compatible schemas, named units and enums for states/errors. Output-affecting settings must be serialized and hashed. Unknown critical fields must not be silently ignored.
3. **Use one real execution path.** The CLI, benchmark and later API must call the same orchestration and media code. A mock adapter can test the harness, but its output cannot qualify learned synthesis. When FastAPI is introduced, keep inference off its request/event-loop thread.
4. **Manage process lifetime.** Distinguish queued, running, succeeded, failed and cancelled states. Timeout, cancellation and crashes must clean up the worker/encoder process tree, release resources and retain diagnostics. Report unsupported safe cancellation honestly. Retry creates a new attempt linked to its parent.
5. **Protect output integrity.** Write into an attempt-owned temporary location and publish only after encode completion and decode validation. Never overwrite approved inputs, prior attempts or completed output on retry. A partial file is not a successful result.
6. **Bound memory and CPU use.** Do not hold every full-resolution intermediate or duplicate frame array at once. Bound queues, caches and worker count. Record the combined app/worker/encoder memory method; measuring only the Python parent is insufficient.
7. **Keep the CPU claim verifiable.** Select CPU execution explicitly and record runtime/device evidence. Disable automatic accelerator selection and remote fallback. Invoke native tools with argument arrays rather than shell-expanded user paths. Verify the approved binary and weight hashes before use.
8. **Pin reproducibility inputs.** Record code commit, dirty-tree status, binary/build identity, weights, dependency lock, CPU/SIMD, thread settings, encoder settings, inputs and profile revision. Cross-platform floating-point or encoded-bitstream identity must not be assumed; apply the relevant endpoint/reproducibility contract.
9. **Test observable risks.** Prioritize incorrect cadence, missing anchors, invalid output, resource leaks, timeouts, recovery and false benchmark passes. Use tiny fixtures for normal development. Avoid tests that merely repeat constants or mirror private implementation details.
10. **Keep failures visible.** Emit structured logs with attempt ID, stage, duration, device, memory and failure category. Keep stdout machine-readable when returning JSON and diagnostics separate. Never silently skip invalid cases, hide a retry, or emit success after a required stage failed.

## 5. Benchmark implementation contract

Implement the complete §12.0 protocol, not a model-only stopwatch. This summary is an implementation checklist; v0.12 and approved target amendments remain authoritative.

| Area | Required implementation behavior |
| --- | --- |
| Output semantics | 2–4 source anchors; first/last at animation indices 0/71; 72 animation frames at 12 fps; two-frame holds yield 144 delivery frames at 24 fps and exactly 6 seconds. Separately count source, synthesized and duplicated frames. |
| Warm timing | Start on valid-job submission; stop when the encoded output is closed and decodable. Include all job-specific decode, feature preparation, inference, warp, normalization and CPU encode. Only model/runtime residency may carry over. |
| Cold timing | Start before launching/initializing the application and worker. Include model load. Disclose OS file-cache state; do not call process-cold a disk-cold test. |
| Preview | Measure a playable 3-second 320×180 preview independently of the final request. Report combined time if a later user flow requests both. Apply the locked qualification repetition protocol to preview measurements as well as final output. |
| Proposed limits | Warm preview p95 ≤15 s; warm 360p final p95 ≤60 s and every run ≤90 s; process-cold final p95 ≤90 s and every run ≤120 s; peak application group ≤4 GiB on the D-02-approved 4-core/8-GiB host. These remain unmeasured targets. |
| Sample | Freeze 12 in-scope clips: four face/reaction, four bounded gesture/body and four cloth/hair/limited-overlap. At least two use only two anchors. Keep tuning assets separate; withheld interior references are review-only. |
| Repetitions | Three warm runs per clip (36), one process-cold run per clip (12), fixed randomized order, batch size one, no competing workload; plus the continuous 20-minute workload. Record the preview schedule explicitly before timing. |
| Aggregation | Nearest-rank p95 uses sorted index `ceil(0.95 × n)` with one-based indexing. Thus n=36 selects the 35th observation and n=12 selects the maximum. Report n, all observations, median, p95 and maximum. |
| Failure handling | A timeout, invalid output, missing required observation or rejected in-scope case fails the sample. Preserve its ledger entry. Do not calculate a passing score from only successful runs. |
| Quality | All 12 clips require the specified two-reviewer identity/motion scores ≥8/10, no zero dimension, endpoint checks and no severity-2/3 defects. Latency cannot waive quality. |
| Fresh input and limits | Four fresh packs must satisfy ≤5 minutes active preparation and ≤30 s automatic local preprocessing after approved frames exist. Exercise the four unsupported-case categories in §12.0 and the offline/device checks. |

**Preview clarification for the first PR:** v0.12 states a preview p95 but does not separately enumerate preview repetitions. Use 36 independent warm preview requests, three per locked clip, in addition to the final-output runs. Record this as a measurement clarification in the decision log before qualification; it changes no target or sample quality condition.

Automatic local preprocessing is both reported as a stage and included inside the relevant end-to-end timing boundary; it is not a deduction from the reported render time. Source artwork creation, one-time installation/download/compilation and human review are reported separately. An initial compilation or setup operation must not be repeated per job while being excluded from every run.

If a candidate CLI loads weights for every invocation, count that cost. A genuinely warm measurement needs actual model residency across requests. Do not subtract loading from a cold-only executable and label the remainder as the application's warm turnaround.

The runner must refuse a qualification-pass verdict when the required host approval, dataset/profile identity, complete measurements or human quality evidence is missing. It may still generate a clearly labelled exploratory report. For unsupported motion, combine deterministic validation with the explicit capability/preflight workflow; do not claim an automatic unseen-content detector without implementing and validating one.

Persist raw run records and a generated summary containing commit/build identity, exact host and power/thermal configuration, target revision, data/profile/model hashes, timing boundaries, memory method, device/offline evidence, output hashes, reviewer records and failure entries. Any tuning that affects results creates a new profile revision and reruns the complete qualification sample. Do not mark later MVP clauses discharged by a harness-only pass; follow Appendix E.

## 6. PR sequence

These are implementation work packages, not predictions of GitHub PR numbers or proof that earlier phase gates have passed.

| Package | Scope and deliverable | Review exit |
| --- | --- | --- |
| A — Foundation and measurement | Add instructions, package/lock, common schemas, CLI entry point, benchmark/result format, host inventory command and tiny fixture adapter. Add meaningful tests for frame counts, failed-run retention and percentile calculation. | Clean install and quick checks work on the documented development platform; fixture output is labelled non-qualifying; unresolved hardware/approval fields stay open. |
| B — Real CPU path | Integrate one classical comparator and one learned CPU candidate through the common interface; CPU media pipeline, immutable attempts, runtime lifecycle, resource evidence and small real end-to-end examples. | Demonstrates actual learned temporal execution, correct output/cadence, failure cleanup and honest CPU provenance. Speed observations remain exploratory until the qualification protocol is run. |
| C — CPU qualification and decision | Lock prerequisites and execute AT-055/056, quality review, fresh packs, negative cases and thermal/offline checks. Include raw evidence and a concise pass/fail recommendation. | Decide proceed, one bounded optimization, explicitly revise the target/scope, or no-go. Missing hardware/reviewer evidence means pending qualification, not success. |
| D — Integrated MVP | After the CPU proof and applicable Phase 1 exit, add project storage, queue/recovery, local review UI and export in focused feature PRs. Rerun AT-055/056 on the integrated path. | Due MVP requirements have implementation evidence; inherited exploratory results do not close the release. |

The first feasible model experiment is timeboxed to five working days after its required inputs, licenses and target contract are ready. Do not spend that window building an episode-management application or surveying many GPU models.

## 7. Claude Code and ChatGPT review protocol

1. Claude reads the relevant requirements, shared instructions and prior decisions, implements one work package on a branch, runs the necessary local checks and opens or updates its PR.
2. The PR identifies the tested commit SHA, scope, requirement/AT clauses, evidence, limitations and concrete decision questions. Claude offers a recommended option and tradeoff for each genuine unresolved choice.
3. ChatGPT reads the current PR diff, relevant surrounding code, previous comments and available evidence, then posts one consolidated review-and-decision comment. Every finding states its severity, affected location, observed problem, required correction and verification needed. Use inline comments only when they improve precision.
4. Separate **blocking corrections**, **technical decisions** and **non-blocking improvements**. Resolve routine technical choices within the approved scope directly. Scope/target changes, new spend and rights approvals go to the project owner with one concrete recommendation.
5. Claude addresses the complete review batch, updates durable decisions, runs affected checks and posts one response mapping each finding to its commit/evidence. Do not make a commit or start CI merely to answer a question.
6. ChatGPT reviews the latest head and any affected previous findings, checks the applicable tests and returns a clear disposition: ready for the configured merge process, changes required, or implementation acceptable but qualification pending. A discussion comment is not itself a formal GitHub approval or permission to merge/deploy; use the repository's configured review/merge policy.

Preserve decisions in `docs/decisions/` with the PR-comment URL, deciding role, rationale, affected requirements and any superseded decision. Do not repeatedly ask for a choice already settled in the active scope. Do not treat an old comment as approval of unrelated later changes.

This handoff does not configure background monitoring. Once the repository/PR is identified, reviews can be posted there. Automatic detection of later changes requires a separately configured trigger or monitoring task; until then, request a review when the PR is ready.

## 8. CI and test cost rules

- Use one small default PR workflow for install/lock verification, formatting/lint, type checks and focused tests. Avoid duplicating the same suite on both every feature-branch push and its PR event.
- For this public repository, default PR checks to read-only permissions and no secrets. Do not execute untrusted PR code in a privileged `pull_request_target` workflow or on the owner's benchmark host.
- Cancel superseded PR runs using a concurrency group scoped by workflow and PR. GitHub documents the concurrency mechanism and `cancel-in-progress` behavior in its [official workflow guidance](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
- Keep the required workflow observable on every PR; select lightweight jobs inside it for documentation-only changes so required checks are not left indefinitely pending by whole-workflow path skips.
- Keep model downloads and the full CPU qualification matrix out of routine hosted CI. Run tiny media integration checks where practical; run full measurements on the approved P-L host, manually or through an explicitly configured benchmark runner.
- Do not call a hosted runner's timing a P-L result. Record the environment for every performance observation.
- Batch fixes before pushing; do not re-run unchanged green checks without a concrete reason. Pin actions and tools when the workflow is implemented, cache appropriate dependencies, and set finite job timeouts.
- A hardware-dependent test must report not-run/pending when the host or model is unavailable. Mock results may validate the harness only.

## 9. Shared instructions starter — `AGENTS.md`

Copy and adapt this block to the repository root. Add actual verified setup/check commands when Package A implements them; commands below are not assumed to exist yet.

```markdown
# AnimaLite engineering instructions

## Objective and authority
- Project: AnimaLite; Python package and CLI: animalite.
- Prove useful short video from 2–4 approved frames on CPU/low-spec hardware.
- Requirements v0.12 and approved amendments define acceptance.
- Read CPU §§6.0, 6.3, 12.0, AT-055/056 and Appendix E before related work.
- Keep proposed thresholds and unmeasured performance labelled as such.
- Preserve owner authority for scope, hardware, budget, rights and go/no-go.
- Use the recommended PolyForm Noncommercial license for original project software;
  preserve third-party terms and describe the project as source-available.

## Current implementation scope
- Build the CLI, common contracts and benchmark first, then one learned CPU adapter.
- Use one classical comparator; it cannot satisfy learned temporal capability.
- Keep UI, episode services, cloud/GPU branches and training outside the first proof.
- Missing hardware evidence leaves qualification pending; continue useful coding.

## Coding
- Keep domain contracts independent of native model libraries.
- Use typed, versioned schemas; make units, frame indexing and device policy explicit.
- Stream frames with bounded memory; pin total threads and batch size.
- Retain immutable attempts, failure diagnostics and safe process cleanup.
- Use explicit CPU runtime/encoder selection; never silently fall back remotely.
- Keep model weights, secrets, caches and large evidence out of source commits.

## Verification
- CLI and benchmark must call the same real execution path.
- Test observable contract/failure risks with tiny fixtures in default CI.
- Keep failed/timed-out/missing benchmark runs; never turn missing data into a pass.
- Report full timing boundaries, output counts, memory and actual runtime identity.
- A mock pass is not model proof; a harness pass is not integrated MVP acceptance.
- Preserve all quality, preparation and offline conditions in §12.0.

## Collaboration
- Claude Code implements; ChatGPT reviews and records technical decisions in PR comments.
- Work through one consolidated review batch and report evidence against the latest SHA.
- Resolve routine choices within scope; record durable decisions with comment links.
- Do not reopen settled choices or request confirmation for routine reversible work.
- Do not change acceptance targets to make tests pass.
- Follow existing repository merge/release authorization; never infer it from a review comment.
- Keep default CI small, cancel obsolete PR runs and reserve full benchmarks for the target host.

## Verified commands
- Package A must replace this section with commands it has actually run successfully.
- Include environment creation/install, quick checks, a tiny local example and host inventory.
- Clearly label model-dependent and qualification commands, including their prerequisites.
```

## 10. Claude entry point starter — `CLAUDE.md`

Claude Code supports importing shared instructions through `@AGENTS.md`; it does not automatically read `AGENTS.md` as its own project instruction file. The short import avoids maintaining two copies of the rules. See the [official Claude Code memory documentation](https://code.claude.com/docs/en/memory#agentsmd).

```markdown
@AGENTS.md

# Claude Code implementation role
Read the current work package, relevant requirements and linked PR decisions.
Implement the approved scope, run the documented checks and provide reviewable evidence.
Respond to ChatGPT's review in one finding-to-fix table with the tested commit SHA.
Continue routine implementation without repeated permission questions.
Use the shared decision boundaries when a change affects targets, scope, spend or rights.
```

## 11. PR template starter — `.github/PULL_REQUEST_TEMPLATE.md`

```markdown
## Problem and resulting behavior
Explain why this change is needed and what now works.

## Scope and traceability
- Work package:
- Requirement IDs / clauses / due release:
- Acceptance tests addressed:
- Clauses still open or carried forward:

## Implementation and decisions
- Main changes and relevant file paths:
- Decisions applied, with existing comment/decision links:
- Remaining decisions, each with a recommendation and tradeoff:

## Verification
- Tested commit SHA and working-tree state:
- Commands run, outcomes and evidence links:
- Tests not run and concrete reason:
- Model/host/profile identity if inference or performance is affected:
- Measured results versus proposed targets; failures retained:

## Review request
- Specific uncertainties needing review:
- Known limitations and follow-up work:
```

## 12. First instruction to give Claude Code

> Implement AnimaLite using the attached requirements v0.12 and AnimaLite implementation handoff v0.2. Read §13 below as the first-PR assignment and use §§0–11 as implementation rules. Build working Package A code, tests, CLI and a reproducible tiny video example; do not stop at a plan or empty scaffold. Use `animalite` for package/CLI names. Add the recommended PolyForm Noncommercial license and third-party notices for review. Keep formal CPU qualification pending until its prerequisites and measured tests pass. Open one focused PR with the tested SHA, verification evidence, requirement/AT mapping and remaining concrete decisions for ChatGPT review. Continue routine reversible work without repeatedly requesting confirmation.

## 13. Exact first-PR assignment

**Branch:** `feat/animalite-cpu-foundation` or the repository's required branch convention. **Suggested PR title:** `AnimaLite: CPU execution foundation and benchmark harness`.

### Inputs and decisions

Read `Frame_Conditioned_2D_Video_System_Requirements_v0.12.docx` and this handoff wherever they were uploaded in the repository or PR. Preserve the original requirement document and produce a labelled, checked Markdown extract of the CPU-stage clauses for convenient review. Read existing repository instructions and decisions before editing; reconcile compatible conventions instead of overwriting unrelated files.

Make normal package/tooling choices and record them. Follow the proposed Python baseline, verify the actual supported minor and lock the environment. Keep approved naming and public/noncommercial intent; do not silently select MIT, Apache, GPL or AGPL for AnimaLite's own code. If owner contact/copyright information is missing, flag that precise metadata item without inventing it or stopping independent code work.

### Working code to deliver

1. Installable `src/animalite/` package with working CLI entry point and a verified local installation path. Supply `python -m animalite --help` as a fallback entry point.
2. Typed/versioned contracts for input anchors, shot intent, engine profile, job/attempt, output manifest, capabilities, resource estimate and measured results. Separate estimates from observations. Unknown host or memory evidence is null/pending, never zero-as-success.
3. A local execution service exposing the §6.3 lifecycle. The CLI and benchmark call this same service. Implement attempt-owned output directories, explicit states, failure diagnostics, finite timeouts and process cleanup; never publish a partial encode as successful output.
4. A small, clearly named **fixture adapter** that produces actual intermediate frames and passes them through the real CPU media/encode path. A deterministic synthetic animation is sufficient for exercising the harness. Include a reproducible fixture generator so no private artwork, large download or model weight is needed. Label the adapter non-learned and non-qualifying everywhere.
5. A host/environment inventory command recording CPU model/core/thread count, RAM, OS, native tool versions/build flags and available measurement method. Treat it as inventory, not owner approval or proof that an accelerated device was unused.
6. A benchmark runner that records stage and end-to-end timing, run outcomes and process-group memory when supported. Implement median, nearest-rank p95, maximum, failed/missing-run retention and a pass evaluator that refuses qualification when evidence or eligibility is incomplete.
7. A CPU media pipeline that validates decoding, resolution, duration, animation/delivery frame semantics and complete output. Produce a six-second 640×360 fixture with 72 animation frames, delivered as 144 frames at 24 fps. The duration/frame demonstration does not satisfy MR-018.
8. A pinned environment, one quick local check command, small default CI and documentation of the commands that actually worked. Include the license and agent instruction files described above.

Suggested CLI operations to implement are `animalite doctor --json`, `animalite validate`, `animalite render` and `animalite benchmark`. Define and document their precise arguments in the PR; these names describe the required interface, not commands verified by this handoff. Rendering must be explicitly given the fixture profile in the first PR. Never let it silently masquerade as the future learned model.

### Meaningful verification

- Clean install, CLI help and one reproducible end-to-end fixture encode/decode.
- Invalid anchor count/order/timing and unsupported configuration produce actionable errors.
- Frame indexing, holds and exact duration satisfy the stated media contract.
- A child-process failure or timeout leaves no successful output record and no orphan worker; retry preserves the original attempt.
- Percentile behavior is correct for small samples and the planned 36/12 sample sizes.
- A failed, timed-out, missing or incomplete run cannot be removed to make qualification pass.
- A fixture adapter, unapproved host or missing quality/device/memory evidence cannot receive a model-qualification pass.
- Structured run records preserve actual identity/settings and distinguish unavailable observations from measured zero.

Run only checks relevant to these risks. Use development-size fixtures in routine CI; do not run the full model benchmark, download large weights or use paid compute just to establish the harness.

### PR evidence and next step

The PR must include a short implemented-versus-pending table, exact tested commit SHA, successful commands, fixture/output metadata, test results, failure-path evidence and dependency/license notes. Map the work to §6.3 and AT-055/056 assertions while leaving their full qualification and later release clauses open under Appendix E. Report any unavailable tool, host or measurement capability explicitly.

Package A is done when it runs and is reviewable; an empty tree or a plan document alone is insufficient. After review, Package B adds one real learned CPU model and a classical comparator through the same service, with exact upstream code/weight/license checks. No web UI, cloud/GPU path, paid service, training run or broad model survey belongs in the first PR. Do not merge or publish releases unless the owner or existing repository policy authorizes it.
