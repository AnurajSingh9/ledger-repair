"""
Reference (oracle) implementation of the ledger engine.

Independent, correct implementation used ONLY by the verifier to compute
ground-truth final balances. This file is never placed in the agent's sandbox
and a test asserts the agent cannot read or import it.
"""

from decimal import Decimal, ROUND_HALF_EVEN


class ReferenceLedger:
    def __init__(self, period_length: int):
        self.period_length = period_length
        self.accounts: dict[str, int] = {}
        self.retained = 0
        self.period = 0
        self._txn_count = 0
        self._period_movement = 0

    def _touch(self, a):
        self.accounts.setdefault(a, 0)

    def _accrued(self, amount, rate_bps):
        interest = (Decimal(amount) * Decimal(rate_bps) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
        return amount + int(interest)

    def post(self, txn):
        t = txn["type"]
        d, c, amt = txn["debit"], txn["credit"], txn["amount"]
        self._touch(d)
        self._touch(c)
        if t == "transfer":
            self.accounts[d] += amt
            self.accounts[c] -= amt
            self._period_movement += amt
        elif t == "accrue":
            p = self._accrued(amt, txn.get("rate_bps", 0))
            self.accounts[d] += p
            self.accounts[c] -= p
            self._period_movement += p
        elif t == "settle":
            self.accounts[d] -= amt
            self.accounts[c] += amt
            self._period_movement -= amt
        else:
            raise ValueError(f"unknown txn type: {t}")
        self._txn_count += 1
        if self._txn_count >= self.period_length:
            self.retained += self._period_movement
            self._period_movement = 0
            self.period += 1
            self._txn_count = 0

    def balances(self):
        out = dict(self.accounts)
        out["retained"] = self.retained
        out["__period__"] = self.period
        return out


def run_scenario(period_length, transactions):
    """Run a scenario and return final balances. The canonical grading entry."""
    led = ReferenceLedger(period_length)
    for txn in transactions:
        led.post(txn)
    return led.balances()
