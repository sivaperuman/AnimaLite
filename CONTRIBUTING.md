# Contributing to AnimaLite

Thank you for your interest. Please read this before opening a pull request —
particularly the rights section, which is short but binding.

## Rights in what you submit

By submitting a contribution you confirm that:

1. **You have the right to submit it.** The work is yours, or you have permission
   from whoever holds the rights (including your employer, where applicable).
2. **It may be distributed under this project's terms.** AnimaLite's own source
   code is licensed under the
   [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
   (see `LICENSE`). Your contribution is offered under those same terms.
3. **You have not copied incompatible material into it.** Do not paste code,
   assets or model weights from a source whose licence conflicts with the above,
   and do not strip an upstream notice.

Your attribution is preserved: authorship stays in the git history, and
`NOTICE` / `THIRD_PARTY_NOTICES.md` are updated rather than overwritten.

**What this does *not* grant.** Accepting a contribution does not give the
maintainer the right to relicense it commercially. That would require sufficient
rights from you, obtained through a separate, legally reviewed contributor
agreement. No such agreement exists today, and this file does not create one. See
`docs/licensing.md` (LIC-03).

If a contribution includes third-party material you are entitled to submit, say
so in the pull request and add it to `THIRD_PARTY_NOTICES.md` with its exact
version, licence and whether it is linked, invoked, modified or redistributed.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]" -c constraints/dev-linux-cpython311.txt
```

You also need an externally installed FFmpeg providing `ffmpeg` and `ffprobe`.
Nothing is bundled. `animalite doctor` reports what it found.

## Checks to run before opening a PR

```bash
ruff check . && ruff format --check .
mypy
pytest -m "not slow"     # contract, failure-path and statistics tests
pytest                   # adds the tiny end-to-end media integration tests
```

Media tests report *pending* rather than passing when FFmpeg is unavailable.
`docs/verified-commands.md` records the commands last executed and their output;
update it if you change a command or its behaviour.

## Engineering rules

`AGENTS.md` is the shared engineering and review instruction file, and it is
binding for human and agent contributors alike. In particular:

* keep the domain layer free of model-specific imports;
* keep contracts typed, versioned and closed to unknown fields;
* never let an absent measurement render as zero;
* never delete, weaken or skip a failing test, benchmark run or quality
  condition to make a check pass;
* never change an acceptance target to make a test pass — targets are owner
  decisions recorded in the requirements.

Durable implementation decisions belong in `docs/decisions/`, one file per
decision, with the rationale and the affected requirement IDs.

## Scope

The project is at the CPU-feasibility stage. A pull request that adds a web UI,
cloud or GPU execution, model training, or a broad model survey is out of scope
right now and will be asked to wait — see `docs/requirements/AnimaLite_Implementation_Handoff_v0.2.md`
section 6 for the work-package sequence.

## Reporting a problem

Open a GitHub issue. If it concerns licensing or rights, say so in the title so
it reaches the project owner rather than being triaged as an ordinary bug.
