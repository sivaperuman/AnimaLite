# DEC-0017 — Bounded provisioning, non-executing status, and the thread allocation

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** handoff rules 7 and 8, §12.0 resource envelope, NFR-028, B-2
* **Raised by:** PR-2 review, findings B-R4 and B-R5

Three related decisions about the runtime: how it is installed, how it is
reported on, and how many threads it is allowed.

## 1. `runtime status` never executes the runtime

`status` called `version_probe()` whenever the executable file existed —
including after its digest had failed. Review demonstrated it with a harmless
test executable that writes a marker: status reported `binary_verified=false`,
exited 3, **and still ran the file**. The command that exists to say "these
bytes cannot be trusted" was executing them to print a banner.

Status now inspects bytes instead of running them:

* the ELF header gives class, machine and endianness — enough to say whether
  this is a 64-bit Linux executable for this architecture;
* the dynamic section gives `DT_NEEDED`, so a missing `libvulkan` is reported as
  a named missing library rather than as a mysterious startup failure.

`ldd` is deliberately not used: it works by invoking the dynamic loader on the
target, which runs code from the file whose trustworthiness is the question.

A probe is still available behind `--probe`, and `version_probe()` itself
refuses unless the digests verified — the refusal is in the method, not only in
its caller, so a future caller cannot forget it. When it does run, it runs
through the same supervised capture as every other native call.

Four states are reported separately, because a single `usable` flag hid three of
them: **installed** (present), **hash-verified** (the right bytes),
**platform-compatible** (runnable here), **execution-admitted** (permitted at
all, DEC-0016). `usable` is the conjunction, and it is not a claim any one of
them can make alone.

## 2. `runtime fetch --install` is a real, bounded install

B-2 authorised an actual explicit fetch. The command only printed instructions —
and the instructions never defined `TARGET`, did not stop after a failed
checksum (`sha256sum -c -` on its own line, its exit status discarded), and said
nothing about safe extraction.

`animalite.adapters.rife_provision` implements the install with a cap on every
axis that can be attacker- or accident-controlled:

| Risk | Control |
| --- | --- |
| Unbounded transfer | 600 MB byte cap, 1800 s wall clock, 60 s socket timeout |
| Tampered or truncated archive | SHA-256 checked **before** any member is extracted |
| Path traversal (`../../`), absolute paths | member list refused before extraction |
| Symlink members | refused (`S_IFLNK` in the external attributes) |
| Decompression bomb | expansion cap, checked against the *declared* size first and the *written* bytes while writing, because the declared size is part of the archive |
| Unwanted files | only the executable and the selected model directory are extracted |
| A failed install destroying a good one | staged in a sibling directory, every digest verified there, then swapped; restored on failure |

Instructions-only remains the default; `--install` is the explicit action.
Nothing else calls it — no automatic fetch during render, validation or tests.
The tests drive the real code path with a few-hundred-byte synthetic archive and
an injected transport, so none of this needs the 431 MB release or a network.

## 3. The thread allocation, and what it actually accounts for

`-j 1:2:1` was passed while the profile declared a 4-thread total, with the
Python parent and the encoder unaccounted for. Reading the pinned wrapper's
[CPU setup](https://github.com/nihui/rife-ncnn-vulkan/blob/a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7/src/main.cpp#L788)
makes the real shape clear:

* `jobs_load` and `jobs_save` each become that many threads, capped at
  `cpu_count`;
* on the CPU path (`gpuid == -1`) the wrapper creates **one** proc thread and
  passes `jobs_proc` as ncnn's `num_threads` for the model instance — so
  `jobs_proc` is intra-op parallelism, not a thread count of its own.

So `-j load:proc:save` on CPU means roughly `load + proc + save` runnable
threads inside that one process. `rife_job_spec()` derives it from the budget
with `load = save = 1` and `proc` capped so the sum never exceeds
`total_threads`; a test asserts that, so the profile cannot drift into
over-allocating.

The Python parent and the encoder are accounted for by *when* they run: during
an inference the parent is blocked in `select` and the encoder is blocked on its
stdin, so neither is runnable while the runtime's threads are. The environment
pins `OMP_NUM_THREADS` and friends for every child, so the host's own value
cannot leak in.

**This is a declared allocation enforced by argv and environment, not a
measurement.** Actual thread occupancy and CPU use are later evidence, on the
D-02-approved host. The distinction is the point: `-j 1:2:1` was previously
presented as though it were proof the pipeline stayed inside four threads, and
it was never that.
