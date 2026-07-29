# Wider-candidate offline ICP replay pilot

The replay imports the authoritative candidate relocalization implementation
and only proposes runtime-observable neighborhoods:
`current-2`, `current-1`, `current`, `current+1`, plus historical candidates.
It never inserts the oracle target into the candidate set.

The nine-scene stratified pilot replayed 46 attempts and 157 candidate
records:

| Episode | Historical oracle coverage | Wider coverage |
|---:|---:|---:|
| 1038 | 1/8 | 5/8 |
| 20 | 0/4 | 1/4 |
| 500 | 3/5 | 5/5 |
| 537 | 2/4 | 4/4 |
| 889 | 1/5 | 3/5 |
| 994 | 4/6 | 6/6 |
| 408 | 0/8 | 7/8 |
| 134 | 0/2 | 2/2 |
| 337 | 1/4 | 3/4 |
| total | 12/46 (26.1%) | 36/46 (78.3%) |

The pilot validates bounded wider replay as a data-generation path. The
remaining misses show that fixed `±2` candidates are not a complete rebase
policy; Anchor v2 should propose a bounded rebase neighborhood before ICP
ranking.

The pilot took 153.46 seconds. A full serial replay of all 112,733 rows would
be too expensive. The tool now supports deterministic episode sharding,
selection fingerprints, and safe resume; the next run should use sampled
shards before expanding coverage.

A subsequent four-way sampled run covered 8 episodes and 24 attempts with no
missing frames. Historical oracle-candidate coverage was 6/24 (25.0%) and
wider coverage was 19/24 (79.2%), closely matching the pilot improvement.
