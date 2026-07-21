# V1 archive note

This is the frozen, isolated V1 source/report/artifact snapshot from commit
`a9be230a2b38dd52dd308648e899911041ad91d4`.

The large derived `data/processed/reliability_v1.csv` is not duplicated here.
Its SHA-256 is
`8f2097ec50287d6c4b4bca71adba9563275483fee020e608e65f0d8ac6028b78`.
Rebuild it with `tools/build_dataset.py` against the raw log paths recorded in
`reports/dataset_manifest.json`.

`candidate_runtime/` contains only the relevant files from the separate
candidate navigation copy. It is shadow-only and must not be overlaid onto the
authoritative runtime.
