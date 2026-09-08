# Licensing scope and open questions

This document records what AnimaLite's licence does and does not cover, the
known third-party obligations, and the licensing questions that are **not yet
resolved**. It is an engineering record for review, not legal advice, and
nothing here is an executed agreement or a granted permission.

## 1. AnimaLite's own software

| Item | Position |
| --- | --- |
| Licence | PolyForm Noncommercial License 1.0.0 |
| SPDX identifier | `PolyForm-Noncommercial-1.0.0` |
| Licence text | Root `LICENSE`, the complete unmodified publisher text from <https://polyformproject.org/licenses/noncommercial/1.0.0.txt> (sha256 `ffcca38841adb694b6f380647e15f17c446a4d1656fed51a1e2041d064c94cc8`, 4563 bytes, retrieved 2026-09-08) |
| Description to use | **source-available**, not open source |
| Copyright holder | **OPEN** — `<COPYRIGHT-HOLDER-PENDING>` in `NOTICE` |

The licence text is used verbatim. There is no MIT-plus-noncommercial hybrid and
no added restriction: PolyForm Noncommercial permits noncommercial purposes and
certain organisational uses — including educational and government institutions
irrespective of funding — and those exceptions are preserved. A stricter policy
would need separately reviewed custom terms, which do not exist.

"Source-available" is the accurate description. A commercial-use restriction does
not satisfy the [Open Source Definition](https://opensource.org/osd), so the
project must not be described as open source in the README, package metadata or
any release note. PyPI has no trove classifier for PolyForm Noncommercial;
`pyproject.toml` uses `License :: Other/Proprietary License` as the closest
accurate classifier, with a comment saying so, and carries
`Private :: Do Not Upload` because publishing to PyPI is not an authorized action.

**Scope.** This licence covers the original AnimaLite software in this
repository. It does not and cannot cover third-party dependencies, the separately
installed FFmpeg, or any model code or weights added later. A noncommercial root
licence cannot make an otherwise incompatible combination compliant.

## 2. Third-party terms

Recorded in `THIRD_PARTY_NOTICES.md`, with exact versions, the licence each
publisher declares, and whether AnimaLite links, invokes, modifies or
redistributes it. Current position:

* nothing is redistributed or modified — no vendored source, binary or weight;
* run-time Python dependencies are `pydantic` (MIT, with its transitive MIT/PSF
  dependencies) and `numpy` (a BSD-3-Clause-led conjunction);
* the only MPL-2.0 component, `pathspec`, is a development-only transitive
  dependency of `mypy`;
* FFmpeg is invoked as an explicitly installed external executable.

### FFmpeg

FFmpeg's own terms depend on the components enabled in the installed build, and
this is the single most likely source of a licensing surprise. The build used
for the recorded checks is configured `--enable-gpl --enable-libx264
--enable-libx265`, which makes **that build GPL**, not LGPL.

For the current stage:

* AnimaLite does **not** bundle, vendor, statically link or dynamically link
  FFmpeg. It resolves `ffmpeg`/`ffprobe` from `PATH` (or `ANIMALITE_FFMPEG` /
  `ANIMALITE_FFPROBE`) and runs them as separate processes with an argument
  array;
* `animalite doctor` records the resolved path, version and full `configuration:`
  string of the build actually present, and warns when the build is
  GPL-configured;
* a subprocess boundary is a relevant fact, **not** a universal compatibility
  exemption. Any future packaging that ships an FFmpeg build alongside AnimaLite,
  or links `libav*`, needs review before distribution.

Distributing output produced with a `--enable-nonfree` build carries its own
restrictions. No such build is required or used here. See
<https://ffmpeg.org/legal.html>.

## 3. Model code, weights and assets — not yet applicable

Package A integrates no learned model, so no model licence has been evaluated.
The requirements treat this as a gate, not a formality: C-04 forbids a profile
entering production without a recorded licence review and approved use case, and
MR-012 requires weights, code, dependencies and derived-model obligations to be
reviewable *before use*.

When Package B integrates a candidate (a pinned RIFE/ncnn CPU model is named
first in requirements section 9.1), record **separately**:

1. the upstream **source code** licence;
2. the **weights / checkpoint** licence, with any territorial or field-of-use
   restriction. A model repository's top-level badge is not evidence: code and
   weights are routinely licensed differently in the same repository;
3. licences of components the runtime links (ncnn, BLAS kernels, codecs);
4. whether AnimaLite links, invokes, modifies or redistributes each artifact;
5. the requirements section 14.2 / CR-024 mapping to rights disposition,
   `use_eligible` and `eligibility_block_kind`.

Do not add AnimaLite copyright headers to copied upstream files, and do not claim
exclusive ownership of an unmodified upstream checkpoint.

## 4. Generated output is a separate question

A software licence does not automatically determine copyright ownership or the
licensing of a video the software produces. Three questions are distinct and must
be documented separately:

1. **software use** — governed by `LICENSE` (and the third-party terms above);
2. **model terms** — governed by whatever licence the weights carry, which may
   restrict output use independently of the software licence;
3. **input and output rights** — governed by the rights in the source artwork,
   references and any generated inputs, per requirements section 14.3 and CR-020
   / CR-022.

Nothing in this section is a loophole permitting commercial use of AnimaLite.

## 5. Commercial permission

Granting commercial permission is a **project-owner decision**. It is not
delegated to the implementation, and this repository contains no contact address,
price, or standard commercial terms — none exist. Requests are made by opening a
GitHub issue titled `Commercial use request`.

Two constraints the owner should be aware of before any such arrangement:

* the maintainer **cannot** unilaterally relicense contributions made by other
  people. Doing so requires sufficient rights from each contributor, obtained
  through a contributor licence agreement or equivalent. `CONTRIBUTING.md`
  states the current position and does not claim those rights;
* a commercial arrangement, and any CLA intended to enable one, needs a lawyer's
  review. See the
  [GitHub Open Source Guide on relicensing](https://opensource.guide/legal/#what-if-i-want-to-change-the-license-of-my-project).

## 6. Open licensing items

| ID | Item | Status | Owner |
| --- | --- | --- | --- |
| LIC-01 | Legal copyright-holder name for `NOTICE` and package metadata | **Open** — placeholder `<COPYRIGHT-HOLDER-PENDING>`, deliberately not guessed | Project owner |
| LIC-02 | Whether a commercial-permission route is offered at all, and on what terms | **Open** | Project owner + legal |
| LIC-03 | Contributor licence agreement, if inbound contributions are to be relicensable | **Open** | Project owner + legal |
| LIC-04 | D-06 licence policy: permissive-only production, or custom community licences allowed | **Open** (requirements D-06, due before model shortlist lock) | Project owner / legal |
| LIC-05 | Model code + weight licence evaluation for the Package B candidate | **Not started** — no model integrated | Technical lead + legal |
| LIC-06 | FFmpeg distribution position if AnimaLite is ever packaged with a build | **Open** — not required at this stage | Technical lead + legal |
| LIC-07 | Rights records for the frozen 12-clip qualification sample artwork | **Not started** — sample not yet frozen | Project owner + creative lead |

## 7. Pre-existing repository content

Before this branch, the repository contained the two owner-supplied requirement
documents and no licence file. Adding `LICENSE` now sets the terms for
AnimaLite's source code going forward. It does **not** retrospectively revoke any
permission previously granted to anyone who obtained the earlier content, and it
does not change the status of the owner's own documents. If the repository was
made public before this change, the effect of that earlier state is a question
for the owner and their legal reviewer; independent implementation work continues
in the meantime.
