"""
A minimal double-entry ledger engine with period rollover.

The engine processes an ordered stream of transactions. Each transaction is
posted to two accounts (a debit and a credit). At the end of each accounting
period, balances "roll over": the period's net movement is closed into a
retained-earnings carry account and the period counter advances.

Public API (do not change signatures):
    Ledger(period_length: int)
    Ledger.post(txn: dict) -> None
    Ledger.balances() -> dict[str, int]   # amounts are in integer cents

Transaction schema:
    {"type": "transfer" | "accrue" | "settle",
     "debit": <account:str>, "credit": <account:str>,
     "amount": <int cents>, "rate_bps": <int, optional, for accrue>}

Semantics the engine is SUPPOSED to implement:
    - "transfer": move `amount` from credit-side to debit-side (debit += amount,
      credit -= amount).
    - "accrue": like transfer, but the posted amount is
      amount + round(amount * rate_bps / 10000) (interest accrual). Rounding is
      banker's rounding to the nearest cent.
    - "settle": the reverse of transfer (debit -= amount, credit += amount).
    - Every `period_length` transactions, close the period: the net movement of
      the period is carried into "retained" and the period index increments.
      After a rollover, "settle" transactions in the NEW period apply against
      the carried balance and MUST keep their normal sign.

Amounts are integer cents everywhere. balances() returns every account that has
been touched, plus "retained" and "__period__".
"""

from decimal import Decimal, ROUND_HALF_EVEN


class Ledger:
    def __init__(self, period_length: int):
        self.period_length = period_length
        self.accounts: dict[str, int] = {}
        self.retained: int = 0
        self.period: int = 0
        self._txn_count: int = 0
        self._period_movement: int = 0

    def _touch(self, acct: str) -> None:
        if acct not in self.accounts:
            self.accounts[acct] = 0

    def _accrued_amount(self, amount: int, rate_bps: int) -> int:
        # banker's rounding to nearest cent
        interest = (Decimal(amount) * Decimal(rate_bps) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
        # BUG 3 (masked rounding accumulation): interest is truncated to int via
        # int() which floors toward zero instead of using the rounded Decimal.
        # For a single small txn this is invisible; across many accruals in a
        # period it accumulates and only shows up in the retained carry.
        return amount + int(Decimal(amount) * Decimal(rate_bps) / Decimal(10000))

    def post(self, txn: dict) -> None:
        ttype = txn["type"]
        debit = txn["debit"]
        credit = txn["credit"]
        amount = txn["amount"]
        self._touch(debit)
        self._touch(credit)

        if ttype == "transfer":
            self.accounts[debit] += amount
            self.accounts[credit] -= amount
            self._period_movement += amount
        elif ttype == "accrue":
            posted = self._accrued_amount(amount, txn.get("rate_bps", 0))
            self.accounts[debit] += posted
            self.accounts[credit] -= posted
            self._period_movement += posted
        elif ttype == "settle":
            # BUG 2 (post-rollover sign flip): in the first period the sign is
            # correct, but the author "simplified" by keying the sign off
            # self.period, which flips it after the first rollover.
            if self.period == 0:
                self.accounts[debit] -= amount
                self.accounts[credit] += amount
            else:
                self.accounts[debit] += amount
                self.accounts[credit] -= amount
            self._period_movement -= amount
        else:
            raise ValueError(f"unknown txn type: {ttype}")

        self._txn_count += 1
        # BUG 1 (rollover off-by-one): rollover fires when the count EXCEEDS the
        # period length rather than when it reaches it, so each period runs one
        # transaction long and the movement carried is for the wrong window.
        if self._txn_count > self.period_length:
            self._close_period()

    def _close_period(self) -> None:
        self.retained += self._period_movement
        self._period_movement = 0
        self.period += 1
        self._txn_count = 0

    def balances(self) -> dict:
        out = dict(self.accounts)
        out["retained"] = self.retained
        out["__period__"] = self.period
        return out
