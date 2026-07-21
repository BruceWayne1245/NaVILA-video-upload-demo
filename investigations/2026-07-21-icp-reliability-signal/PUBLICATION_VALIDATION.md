# Publication validation

Validation performed before committing this archive to the authoritative
private repository:

- refreshed remote `main` and README at
  `f2a61a9b5cc94624e1126ccbcf674d58139ef59d`;
- confirmed both isolated model repositories were clean;
- full V1.1/inherited candidate suite: **278 passed, 14 skipped**;
- V1.1 artifact/schema/leakage/probability validation: passed;
- isolation check: passed, zero symlinks, frozen/live hashes unchanged, and
  candidate files have distinct inodes;
- V1 sklearn artifact SHA-256:
  `3fc7c2ebc6f2732ab787c137c31d1e54b2883c658858daafb5a82a78eef0eab2`;
- V1 portable artifact SHA-256:
  `b6bdd0cda5a414a61fbcad27912d6edab8790846d73c5cb84f3a1433ff40d9c2`;
- V1.1 development artifact SHA-256:
  `5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce`;
- all files in each version snapshot passed its committed
  `SOURCE_MANIFEST.sha256` check;
- no symbolic links are present in `model_versions/`;
- no derived 54-60 MiB training dataset was committed;
- no GitHub credential or access token is present in the archive.

These checks establish archive integrity and offline reproducibility. They do
not constitute prospective model validation or authorization for enforcement.
