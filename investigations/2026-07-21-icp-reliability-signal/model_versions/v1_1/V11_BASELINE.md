# Reliability V1.1 development baseline

- Independent repository: `/home/teambruce/navila-reliability-v1_1`
- Parent frozen Reliability V1 commit: `a9be230`
- Parent V1 tag: `reliability-v1-offline-audit-8f2097ec`
- Private GitHub baseline previously verified on 2026-07-21:
  `c1d40e079a53dfb3efca895e19d17db991f0ffb6`
- V1 source dataset SHA-256:
  `8f2097ec50287d6c4b4bca71adba9563275483fee020e608e65f0d8ac6028b78`
- V1.1 NPZ dataset SHA-256:
  `f5dd5ed86e776f9c3ae8efc6e8a2e9f8f1bcce8b0f793dc16115dc7d80494133`
- Development artifact SHA-256:
  `5f23aba46a45d564131dccd093b1e76160a513162910709503ac8c0a49cb35ce`
- Selected model for all heads: `hgb_full_temporal`

The V1.1 repository has distinct working-tree inodes from V1. It reads the
historical raw evaluation logs but does not modify them. Claude's separate
capture implementation and the authoritative live navigation directory are
outside this repository and are not imported or edited here.
