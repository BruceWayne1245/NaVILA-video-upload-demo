# Old collection stop and queue audit — 2026-08-01

## Accounting at cancellation

The old Route 2 collection50 was stopped after 24 clean completed rows. Its
summary ended with 25 rows: 24 `exit_code=0` completions and ep581 as a
nonzero/incomplete row. Ep961 briefly began while the old unit was being
terminated because the transient service's kill behavior did not initially
cover every descendant; the whole cgroup was then terminated.

- ep581 retained about 60 MB of partial artifacts and no valid completion;
- ep961 retained only about 20 KB and no completion record;
- neither partial episode is eligible to be treated as a completed capture or
  silently admitted into training.

The partial directories and append-only logs were preserved as audit evidence.
They were not deleted or rewritten.

## Clean-stop checks

After termination:

- the old cgroup was empty;
- the old unit retained only failed/timeout history and no live worker;
- the old Route 1 waiter and planned Terminal active-evidence40 waiter were
  removed;
- there was no matching old evaluator, VLM, scorer or queue process;
- no process held an open handle into the old live result directories;
- old ports 54581 and 54961 were closed;
- stale lock files, where present, were unheld and consumed no GPU or memory;
- the development24 lock was held only by the new Route 2 chain.

Resource checks before the new launch found about 111 GB host memory available,
negligible swap use, 63 GB shared-memory capacity, about 1.8 TB free on SSD4T
and about 141 GB free on the root filesystem. The GPU contained only the newly
started VLM and evaluator after launch; no old collection process occupied GPU
memory.

No OOM, port, lock, artifact-SHA or capture-integrity error was found in the
new chain at the audit boundary.

## Final queue order

The obsolete Terminal active-evidence40 queue was not retained because it was
built on the incorrect V1.1-off architecture. The final explicitly authorized
order is:

```text
Route 2 Core development24
        -> Route 2 Core locked-validation20
        -> existing Route 1 quarantine-veto30
```

The Route 1 workload remains separate in code, provenance and analysis. This
queue preservation is an operational ordering decision, not Route 2 ownership
of Route 1.
