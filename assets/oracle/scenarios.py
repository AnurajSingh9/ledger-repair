"""
Deterministic scenario generator. Produces ordered transaction streams that
cross multiple period boundaries and mix transaction types, so that all three
bugs manifest. Seeded for reproducibility.
"""

import random

ACCOUNTS = ["cash", "ar", "ap", "revenue", "expense"]
TYPES = ["transfer", "accrue", "settle"]


def make_scenario(seed: int, n_txns: int, period_length: int) -> dict:
    rng = random.Random(seed)
    txns = []
    for _ in range(n_txns):
        t = rng.choice(TYPES)
        d, c = rng.sample(ACCOUNTS, 2)
        amount = rng.randint(1, 5000)  # cents
        txn = {"type": t, "debit": d, "credit": c, "amount": amount}
        if t == "accrue":
            txn["rate_bps"] = rng.choice([25, 50, 125, 333, 750])
        txns.append(txn)
    return {"period_length": period_length, "transactions": txns}


def make_battery(seed_base: int, count: int) -> list:
    """A battery of scenarios spanning short and long periods."""
    battery = []
    for i in range(count):
        # vary length and period so some scenarios cross 1 boundary, some 3+
        n = 8 + (i % 5) * 6          # 8..32 txns
        pl = 3 + (i % 4)             # period length 3..6
        battery.append(make_scenario(seed_base + i, n, pl))
    return battery
