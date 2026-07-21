# V1.1 archive note

This is the frozen, isolated V1.1 development snapshot from commit
`bb457488653e386b284bef8e1bcb6f45094d8868`, parent V1 commit `a9be230`.

The large derived `data/processed/reliability_v1_1.npz` is not duplicated here.
Its SHA-256 is
`f5dd5ed86e776f9c3ae8efc6e8a2e9f8f1bcce8b0f793dc16115dc7d80494133`.
Rebuild it with `tools/build_v11_dataset.py` after the audited V1 dataset exists.

The artifact is development-only. `candidate_runtime/` is the inherited V1
runtime snapshot and is included only to preserve the parent boundary; V1.1's
249-feature causal runtime and portable export have not yet been implemented.
