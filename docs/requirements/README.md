# Requirements sources

The authoritative documents live here, unmodified. Nothing in this repository
supersedes them.

| File | SHA-256 | Bytes |
| --- | --- | --- |
| `Frame_Conditioned_2D_Video_System_Requirements_v0.12.docx` | `4c03613718954c0cdde2d5aa45e63d1963aeb2ae18942e275606dd6e50a70b23` | 287288 |
| `AnimaLite_Implementation_Handoff_v0.2.md` | `85f5409d1639833962d2edfdcd103f8a5ddd8fcf7f08d096e36fc381f013b053` | 36988 |

## The Markdown extract

`cpu-stage-extract.md` is a **labelled CPU-stage extract** of the clauses this
work package acts on. It exists so a reviewer can read the governing text
alongside the code without opening the .docx.

It is not an authoritative replacement for the source document:

* it covers the CPU-stage clauses only — §§6.0, 6.3, 6.4, 8.7 (selected), 9
  (selected), 12.0, 12.3 (referenced), 13, 15.2 (referenced), AT-055, AT-056 and
  Appendix E.1;
* it preserves requirement IDs, table structure, numeric thresholds and units
  verbatim, and marks every place where text was abridged;
* where the extract and the .docx disagree, **the .docx governs**.

The extract was produced by reading the document's XML directly (no format
conversion tool was involved) and then checked clause by clause against the
source. Regenerate the raw text with:

```bash
python tools/extract_requirements.py \
    docs/requirements/Frame_Conditioned_2D_Video_System_Requirements_v0.12.docx
```

That script emits an unchecked mechanical extraction. It is a reading aid for
producing or reviewing the checked extract — not the extract itself.
