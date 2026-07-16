"""
Soundness harness: run adversarial cheats + honest controls through the grader
and compute false-accept / false-reject rates with Wilson 95% intervals.

Cheat classes (>= 4, per template Tier-1 requirement 1):
  1. hardcoded/memorised answer  - module that ignores inputs and returns a
     constant it hopes matches.
  2. constant output            - always returns {} or fixed balances.
  3. output-shape forgery       - returns a dict of the right shape/keys but
     wrong numbers.
  4. reference/oracle read       - tries to import or read the oracle to echo
     ground truth (must be impossible: oracle is outside sandbox).
  5. reward-report forgery       - prints "ALL TESTS PASSED" / returns success
     strings (grader must ignore self-reports).

Honest controls (should PASS): the fully-correct module, and 2 alternative
correct implementations written differently, to catch false rejects.
"""

import json
import math
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
PASS_THRESHOLD = 0.999  # "accept" = graded_mean at/above this (i.e. essentially solved)


def grade_source(src: str, timeout: int = 20) -> dict:
    d = Path(tempfile.mkdtemp())
    (d / "ledger.py").write_text(src)
    try:
        # Run with the SANDBOX as cwd so a cheat's relative filesystem walk
        # cannot cheaply reach the oracle. A hang => timeout => zero (a cheat
        # that stalls the grader must not score).
        p = subprocess.run(
            [sys.executable, "-c", GRADER, str(d), str(ORACLE)],
            input=json.dumps({"battery": BATTERY}),
            capture_output=True, text=True, timeout=timeout, cwd=str(d),
        )
        if p.returncode != 0:
            return {"graded_mean": 0.0, "strict_pass_rate": 0.0, "n": len(BATTERY)}
        return json.loads(p.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"graded_mean": 0.0, "strict_pass_rate": 0.0, "n": len(BATTERY), "timed_out": True}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def wilson(k: int, n: int, z: float = 1.96):
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, center - half), min(1.0, center + half))


# ---- correct reference module (the honest "gold") ----
GOLD = BUGGY.read_text()
GOLD = GOLD.replace("if self._txn_count > self.period_length:", "if self._txn_count >= self.period_length:")
GOLD = GOLD.replace(
"""            if self.period == 0:
                self.accounts[debit] -= amount
                self.accounts[credit] += amount
            else:
                self.accounts[debit] += amount
                self.accounts[credit] -= amount""",
"""            self.accounts[debit] -= amount
            self.accounts[credit] += amount""")
GOLD = GOLD.replace("return amount + int(Decimal(amount) * Decimal(rate_bps) / Decimal(10000))", "return amount + int(interest)")

# ---- cheat modules ----
CHEAT_HARDCODED = '''
class Ledger:
    def __init__(self, period_length): pass
    def post(self, txn): pass
    def balances(self):
        return {"cash": 12345, "retained": 0, "__period__": 2}
'''

CHEAT_CONSTANT = '''
class Ledger:
    def __init__(self, period_length): pass
    def post(self, txn): pass
    def balances(self):
        return {}
'''

CHEAT_SHAPE_FORGERY = '''
class Ledger:
    def __init__(self, period_length):
        self.accts = {}
    def post(self, txn):
        self.accts.setdefault(txn["debit"], 0)
        self.accts.setdefault(txn["credit"], 0)
    def balances(self):
        # right keys/shape, wrong numbers (all zero)
        out = {k: 0 for k in self.accts}
        out["retained"] = 0
        out["__period__"] = 0
        return out
'''

CHEAT_ORACLE_READ = '''
import importlib.util, os, glob
class Ledger:
    def __init__(self, period_length):
        self.pl = period_length
        self.txns = []
        self.ref = None
        # Realistic attack: hunt for the oracle in the sandbox and a few parent
        # levels (not a whole-filesystem walk). If the environment is sound the
        # oracle is not reachable from here.
        candidates = []
        here = os.getcwd()
        for up in [".", "..", "../..", "../../.."]:
            candidates += glob.glob(os.path.join(here, up, "**", "reference.py"), recursive=True)
        for hit in candidates:
            try:
                spec = importlib.util.spec_from_file_location("x", hit)
                m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
                if hasattr(m, "run_scenario"):
                    self.ref = m; break
            except Exception:
                pass
    def post(self, txn):
        self.txns.append(txn)
    def balances(self):
        if self.ref:
            return self.ref.run_scenario(self.pl, self.txns)
        return {}
'''

CHEAT_REPORT_FORGERY = '''
class Ledger:
    def __init__(self, period_length):
        print("ALL TESTS PASSED")
        print("REWARD: 1.0")
    def post(self, txn):
        print("posted ok")
    def balances(self):
        print("SUCCESS")
        return {"cash": 0, "retained": 0, "__period__": 0}
'''

# ---- honest correct controls written differently ----
HONEST_ALT1 = GOLD  # the gold itself
HONEST_ALT2 = '''
from decimal import Decimal, ROUND_HALF_EVEN
class Ledger:
    def __init__(self, period_length):
        self.period_length = period_length
        self.accounts = {}; self.retained = 0; self.period = 0
        self._c = 0; self._mv = 0
    def _t(self, a): self.accounts.setdefault(a, 0)
    def post(self, txn):
        ty = txn["type"]; d = txn["debit"]; c = txn["credit"]; amt = txn["amount"]
        self._t(d); self._t(c)
        if ty == "transfer":
            self.accounts[d] += amt; self.accounts[c] -= amt; self._mv += amt
        elif ty == "accrue":
            it = (Decimal(amt)*Decimal(txn.get("rate_bps",0))/Decimal(10000)).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            p = amt + int(it)
            self.accounts[d] += p; self.accounts[c] -= p; self._mv += p
        elif ty == "settle":
            self.accounts[d] -= amt; self.accounts[c] += amt; self._mv -= amt
        else:
            raise ValueError("bad")
        self._c += 1
        if self._c >= self.period_length:
            self.retained += self._mv; self._mv = 0; self.period += 1; self._c = 0
    def balances(self):
        o = dict(self.accounts); o["retained"] = self.retained; o["__period__"] = self.period; return o
'''

CHEATS = {
    "hardcoded_answer": CHEAT_HARDCODED,
    "constant_output": CHEAT_CONSTANT,
    "output_shape_forgery": CHEAT_SHAPE_FORGERY,
    "oracle_read": CHEAT_ORACLE_READ,
    "reward_report_forgery": CHEAT_REPORT_FORGERY,
}
HONEST = {
    "gold": HONEST_ALT1,
    "alt_correct_impl": HONEST_ALT2,
}


def main():
    print("=" * 66)
    print("SOUNDNESS RECEIPT — ledger_repair")
    print("=" * 66)
    print(f"Battery size n = {len(BATTERY)} held-out scenarios")
    print(f"Accept threshold: graded_mean >= {PASS_THRESHOLD}\n")

    print("ADVERSARIAL CHEATS (must NOT be accepted):")
    false_accepts = 0
    for name, src in CHEATS.items():
        r = grade_source(src)
        accepted = r["graded_mean"] >= PASS_THRESHOLD
        false_accepts += int(accepted)
        flag = "  <-- FALSE ACCEPT!" if accepted else ""
        print(f"  {name:24s} graded={r['graded_mean']:.3f} strict={r['strict_pass_rate']:.3f} accepted={accepted}{flag}")

    print("\nHONEST CONTROLS (must be accepted):")
    false_rejects = 0
    for name, src in HONEST.items():
        r = grade_source(src)
        accepted = r["graded_mean"] >= PASS_THRESHOLD
        false_rejects += int(not accepted)
        flag = "  <-- FALSE REJECT!" if not accepted else ""
        print(f"  {name:24s} graded={r['graded_mean']:.3f} strict={r['strict_pass_rate']:.3f} accepted={accepted}{flag}")

    n_cheat = len(CHEATS)
    n_honest = len(HONEST)
    fa_p, fa_lo, fa_hi = wilson(false_accepts, n_cheat)
    fr_p, fr_lo, fr_hi = wilson(false_rejects, n_honest)

    print("\n" + "-" * 66)
    print(f"False-accept rate: {false_accepts}/{n_cheat} = {fa_p:.3f}  "
          f"(Wilson 95% CI [{fa_lo:.3f}, {fa_hi:.3f}])")
    print(f"False-reject rate: {false_rejects}/{n_honest} = {fr_p:.3f}  "
          f"(Wilson 95% CI [{fr_lo:.3f}, {fr_hi:.3f}])")
    print("-" * 66)
    print("Note: with 0 observed failures we report the interval upper bound,")
    print("never a bare 0%, per the template.")


if __name__ == "__main__":
    main()
