# DEC-0001 — Licensing baseline

* **Status:** Proposed. Adoption is an owner decision.
* **Deciding role:** implementation (recommendation) → owner (adoption)
* **Comment URL:** _pending first review_
* **Affects:** handoff v0.2 §0, C-04, MR-012, MR-014, D-06

## Decision

AnimaLite's own source code carries the **PolyForm Noncommercial License 1.0.0**,
SPDX `PolyForm-Noncommercial-1.0.0`, with the publisher's text used verbatim as
the root `LICENSE`. The project is described everywhere as **source-available**,
never as open source.

## Why

The handoff records that the owner wants public source with commercial-use
restrictions, and recommends the standard PolyForm text as the implementation.
Using the published text unchanged avoids inventing bespoke terms, and PolyForm's
own exceptions — noncommercial purposes plus specified organisational uses,
including educational and government institutions irrespective of funding — are
preserved rather than narrowed.

"Source-available" is used because a commercial-use restriction does not satisfy
the Open Source Definition. Describing the project as open source would be
inaccurate in package metadata and in any release note.

## What was rejected

* **An MIT/Apache/GPL/AGPL licence.** The handoff explicitly forbids silently
  selecting one of these for AnimaLite's own code.
* **A hand-modified "MIT plus noncommercial" hybrid.** Explicitly forbidden, and
  it would create terms nobody has reviewed.
* **Adding restrictions on top of PolyForm.** A stricter policy needs separately
  reviewed custom terms, which do not exist.
* **A PyPI-publishable classifier set.** There is no trove classifier for
  PolyForm Noncommercial. `pyproject.toml` uses
  `License :: Other/Proprietary License` (with a comment explaining that this
  does not mean OSI open source) and `Private :: Do Not Upload`, because
  publishing to PyPI has not been authorized.

## Open items this decision does not resolve

* **LIC-01, the copyright-holder name.** `NOTICE` carries the placeholder
  `<COPYRIGHT-HOLDER-PENDING>`. It was deliberately not filled with a guessed
  personal or company name. This is the one precise metadata item the
  implementation cannot supply.
* **Commercial permission terms (LIC-02) and a contributor agreement (LIC-03).**
  Both are owner decisions needing legal review. `CONTRIBUTING.md` states plainly
  that accepting a contribution does not grant the maintainer commercial
  relicensing rights.
* **D-06 licence policy** — permissive-only production versus allowing custom
  community licences — remains open and is due before the model shortlist locks.

## Reversal

Changing AnimaLite's licence later requires the owner's decision and, once other
people have contributed, sufficient rights from those contributors. It is not a
routine reversible change, which is why adoption sits with the owner.
