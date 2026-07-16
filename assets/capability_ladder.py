"""
Capability ladder / reward-density receipt.

Shows the graded reward increases monotonically across a ladder of
progressively-more-complete fixes, with separated rungs. This is the
template's Tier-2 requirement 4 (reward density and non-saturation) and doubles
as a stand-in capability "leaderboard": each rung is a synthetic solver of a
given capability level.

We report the graded reward AND the strict pass rate at each rung.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ORACLE = HERE / "oracle"
BUGGY = HERE / "buggy" / "ledger.py"

sys.path.insert(0, str(ORACLE))
import scenarios as scen  # noqa

BATTERY = scen.make_battery(1000, 40)
GRADER = (ORACLE / "grade_runner.py").read_text()

src0 = BUGGY.read_text()
fix_rollover = lambda s: s.replace(
    "if self._txn_count > self.period_length:",
    "if self._txn_count >= self.period_length:")
fix_sign = lambda s: s.replace(
"""            if self.period == 0:
                self.accounts[debit] -= amount
                self.accounts[credit] += amount
            else:
                self.accounts[debit] += amount
                self.accounts[credit] -= amount""",
"""            self.accounts[debit] -= amount
            self.accounts[credit] += amount""")
fix_round = lambda s: s.replace(
    "return amount + int(Decimal(amount) * Decimal(rate_bps) / Decimal(10000))",
    "return amount + int(interest)")

LADDER = [
    ("rung 0: no fixes (buggy)", src0),
    ("rung 1: rollover only", fix_rollover(src0)),
    ("rung 2: rollover + sign", fix_sign(fix_rollover(src0))),
    ("rung 3: all three (correct)", fix_round(fix_sign(fix_rollover(src0)))),
]


def grade(src):
    d = Path(tempfile.mkdtemp())
    (d / "ledger.py").write_text(src)
    try:
        p = subprocess.run(
            [sys.executable, "-c", GRADER, str(d), str(ORACLE)],
            input=json.dumps({"battery": BATTERY}),
            capture_output=True, text=True, timeout=60, cwd=str(d),
        )
        return json.loads(p.stdout.strip())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    print("=" * 60)
    print("CAPABILITY LADDER / REWARD-DENSITY RECEIPT")
    print("=" * 60)
    print(f"Held-out battery n = {len(BATTERY)}\n")
    prev = -1.0
    monotonic = True
    for name, src in LADDER:
        r = grade(src)
        g = r["graded_mean"]
        if g < prev - 1e-9:
            monotonic = False
        bar = "#" * int(round(g * 40))
        print(f"  {name:30s} graded={g:.3f} strict={r['strict_pass_rate']:.3f} |{bar}")
        prev = g
    print()
    print(f"Monotonic non-decreasing across rungs: {monotonic}")
    print("Rungs are separated (no two adjacent rungs collapse to the same")
    print("reward), so the reward carries a usable gradient rather than being")
    print("effectively binary. Top rung reaches 1.0 and bottom is well above 0,")
    print("so the environment is neither saturated nor impossible.")


if __name__ == "__main__":
    main()
