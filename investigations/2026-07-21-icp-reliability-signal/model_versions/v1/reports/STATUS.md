# Implementation status

| Plan step | Result |
|---|---|
| 1. Rebuild dataset | Complete: 91,003 readings, three labels, logged interval, direct anchor world-pose labels, episode-balanced weights |
| 2. Train and calibrate bundle | Complete: logistic bearing head; HistGBDT distance and pose heads |
| 3. Offline replay | Complete: 13 pinned and 8 missed-stop cases |
| 3a. Offline validity audit | Complete: 100/100 raw labels and 89/89 attempt schedules passed; episode/scene macro metrics, 1,000-sample cluster CIs, risk-coverage curves, and scalar ICP baselines reported |
| 4. Shadow integration | Complete in isolated candidate; live smoke produced 402 records with zero enforced actions |
| 5. Hint-arbiter enforcement | Withheld: trusted bearing bad-rate gate failed |
| 6. Stop-gate enforcement | Withheld: trusted distance bad-rate and 0/8 recovery gates failed |
| 7. Promotion/current enforcement | Withheld pending prospective validation of the replay-tuned policy |
| 8. Tests and next-data plan | Complete: 269 passed, 14 skipped; see `POINTCLOUD_TCN_DATA_PLAN.md` |

No file in the authoritative live directory was edited.

The 2026-07-21 episode-20 smoke run loaded the dependency-free JSON artifact
inside Isaac Python and completed with exit code 0. Across 201 calls and 402
candidates, mean inference was 2.278 ms/call (1.139 ms/candidate), maximum
2.480 ms/call. This is runtime-parity evidence only; the deliberately shortened
return phase is not an outcome benchmark or a prospective acceptance batch.

The offline audit confirms useful ranking but not safe trusted-set calibration.
At the deployed thresholds, episode-balanced trusted bad rates are 25.7%,
13.6%, and 12.9% for bearing, distance, and pose. See
`OFFLINE_AUDIT_REPORT.md`; all enforcement remains locked.
