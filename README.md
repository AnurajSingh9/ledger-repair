# ledger_repair — a long-horizon stateful debugging RL environment

Repair a double-entry ledger engine whose bugs only surface once transactions
cross accounting-period boundaries. Built in the `verifiers` format
(`load_environment` + wheel). Targets a **named** frontier-model weakness:
long-horizon stateful debugging, where the symptom is far from the cause and the
fix requires maintaining a model of accumulated state across many steps.

Everything here is original work written for this environment. It runs, and
every number below regenerates from the commands given.

## What the agent sees

A working directory containing a single file, `ledger.py` (the buggy engine),
and four tools:

- `read_file(path="ledger.py")` — read a file in the working dir
- `write_file(content, path="ledger.py")` — patch a file
- `run_ledger(period_length, transactions)` — run a scenario against the
  *current* `ledger.py` and see the resulting balances (this is how the agent
  reproduces and confirms fixes; it does **not** reveal the grading battery)
- `submit()` — signal ready for grading

The agent never sees the oracle or the held-out scenario battery.

## The task

`ledger.py` has three interacting, state-dependent bugs:

1. **Rollover off-by-one** — period closes one transaction late.
2. **Post-rollover sign flip** — `settle` transactions invert sign after the
   first period boundary (the sign is keyed off the period index).
3. **Masked rounding accumulation** — accrual interest is floored instead of
   banker's-rounded; invisible on a single txn, accumulates across a period.

None is visible from reading a single function in isolation; all require
crossing period boundaries with the right transaction mix to reproduce.

## Grading (sound by construction)

The verifier re-runs a **held-out battery of 40 scenarios** against the agent's
patched module in a fresh subprocess and compares final balances to an
independent oracle (`assets/oracle/reference.py`). It computes the verdict from
ground truth only — it never reads the agent's stdout, self-reported success, or
test results. Reward is graded (mean per-account correctness), not binary.

## Install & run

```bash
# from this directory
pip install -e .          # or: pip install dist/ledger_repair-0.1.0-py3-none-any.whl

# evaluate a model through the verifiers harness (needs an OpenAI-compatible endpoint)
uv run vf-eval ledger_repair -m <model> -b <base_url> -k <api_key_env> -n 8 -r 3
```

## Reproduce every receipt (no API key needed)

```bash
cd assets
python soundness_receipt.py     # false-accept / false-reject with Wilson 95% CIs
python capability_ladder.py     # monotonic graded-reward ladder across fix stages
python test_isolation.py        # proves the agent cannot read/import the oracle
```

Latest run is saved in `assets/RECEIPTS.md`. Headline numbers:

- **Soundness:** 5 cheat classes (hardcoded, constant, shape-forgery,
  oracle-read, reward-report-forgery) all rejected; 2 honest controls accepted.
  False-accept 0/5 (Wilson 95% CI [0.000, 0.434]); false-reject 0/2
  (CI [0.000, 0.658]).
- **Reward density:** graded reward 0.160 → 0.264 → 0.471 → 1.000 across the
  four-rung fix ladder; monotonic, separated rungs.
- **Isolation:** oracle and battery provably unreachable from the sandbox.

## Files

```
ledger_repair.py                 # load_environment, tools, per-rollout sandbox, verifier
pyproject.toml                   # verifiers package manifest
assets/buggy/ledger.py           # the engine under repair (ships to the agent)
assets/oracle/reference.py       # independent oracle (never shipped to agent)
assets/oracle/scenarios.py       # held-out scenario generator (server-side only)
assets/oracle/grade_runner.py    # subprocess grader (stdout-isolated, timeout-bounded)
assets/soundness_receipt.py      # cheat battery + honest controls + Wilson CIs
assets/capability_ladder.py      # reward-density ladder
assets/test_isolation.py         # anti-cheat isolation tests
assets/RECEIPTS.md               # last regenerated receipts
```

## Known limits (honest)

- The capability panel uses synthetic rung-solutions as stand-in "models"
  because this build was produced without live model API keys. The harness path
  for real models works (`vf-eval` above); real base-model pass rates and a
  multi-model leaderboard need keys and are the first thing to add.
- Sandboxing here is subprocess + wall-clock timeout + working-dir confinement,
  which is enough to defeat the cheat battery. A production deployment should
  add OS-level isolation (Docker + seccomp, or gVisor) for untrusted code at
  scale; the grader is already structured to run under it unchanged.
```
