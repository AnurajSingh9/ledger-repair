# RECEIPTS — regenerated 2026-07-16T16:48:13Z

## Environment: python 3.12.3, verifiers 0.2.0

```
==================================================================
SOUNDNESS RECEIPT — ledger_repair
==================================================================
Battery size n = 40 held-out scenarios
Accept threshold: graded_mean >= 0.999

ADVERSARIAL CHEATS (must NOT be accepted):
  hardcoded_answer         graded=0.029 strict=0.000 accepted=False
  constant_output          graded=0.000 strict=0.000 accepted=False
  output_shape_forgery     graded=0.000 strict=0.000 accepted=False
  oracle_read              graded=0.000 strict=0.000 accepted=False
  reward_report_forgery    graded=0.000 strict=0.000 accepted=False

HONEST CONTROLS (must be accepted):
  gold                     graded=1.000 strict=1.000 accepted=True
  alt_correct_impl         graded=1.000 strict=1.000 accepted=True

------------------------------------------------------------------
False-accept rate: 0/5 = 0.000  (Wilson 95% CI [0.000, 0.434])
False-reject rate: 0/2 = 0.000  (Wilson 95% CI [0.000, 0.658])
------------------------------------------------------------------
Note: with 0 observed failures we report the interval upper bound,
never a bare 0%, per the template.

============================================================
CAPABILITY LADDER / REWARD-DENSITY RECEIPT
============================================================
Held-out battery n = 40

  rung 0: no fixes (buggy)       graded=0.160 strict=0.000 |######
  rung 1: rollover only          graded=0.264 strict=0.050 |###########
  rung 2: rollover + sign        graded=0.471 strict=0.100 |###################
  rung 3: all three (correct)    graded=1.000 strict=1.000 |########################################

Monotonic non-decreasing across rungs: True
Rungs are separated (no two adjacent rungs collapse to the same
reward), so the reward carries a usable gradient rather than being
effectively binary. Top rung reaches 1.0 and bottom is well above 0,
so the environment is neither saturated nor impossible.

## Isolation tests
all isolation tests PASSED
```
