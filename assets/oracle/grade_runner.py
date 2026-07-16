"""
Grader runner. Executed as a fresh subprocess by the verifier.

argv[1] = directory containing the agent's patched ledger.py
argv[2] = oracle directory (reference.py + scenarios.py)
stdin   = JSON {"battery": [ {period_length, transactions}, ... ]}
stdout  = JSON {"graded_mean", "strict_pass_rate", "n"}

Grading rule (SOUND):
  - We import the AGENT'S ledger.py and the ORACLE reference separately.
  - For each held-out scenario we run both and compare final balances.
  - graded score per scenario = fraction of accounts (incl. retained &
    __period__) that match the oracle exactly.
  - strict pass = 1.0 only if ALL accounts match.
  - We never read stdout, self-reports, or test results from the agent. The
    verdict is computed here from ground truth.
  - If the agent module changed the public API or crashes, the scenario scores
    zero (a broken module is not a pass).
"""

import json
import sys
import os
import io
import contextlib
import importlib.util


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    agent_dir = sys.argv[1]
    oracle_dir = sys.argv[2]
    data = json.loads(sys.stdin.read())
    battery = data["battery"]

    ref = _load(f"{oracle_dir}/reference.py", "oracle_ref")

    # Redirect the agent module's stdout/stderr to devnull for the entire
    # load+run so a cheat that prints "ALL TESTS PASSED" cannot pollute the
    # result channel. We compute the verdict from ground truth only, and emit
    # the JSON result on the real fd 1 AFTER restoring it.
    real_stdout = os.dup(1)
    sink = os.open(os.devnull, os.O_WRONLY)
    os.dup2(sink, 1)

    result = {"graded_mean": 0.0, "strict_pass_rate": 0.0, "n": len(battery)}
    try:
        try:
            agent = _load(f"{agent_dir}/ledger.py", "agent_ledger")
            Ledger = agent.Ledger
        except Exception:
            _emit(real_stdout, result)
            return

        graded_total = 0.0
        strict_total = 0
        for s in battery:
            pl = s["period_length"]
            txns = s["transactions"]
            exp = ref.run_scenario(pl, txns)
            try:
                led = Ledger(pl)
                for t in txns:
                    led.post(t)
                got = led.balances()
            except Exception:
                continue
            if not isinstance(got, dict):
                continue
            keys = set(exp) | set(got)
            correct = sum(1 for k in keys if got.get(k) == exp.get(k))
            graded_total += correct / len(keys)
            if got == exp:
                strict_total += 1

        n = len(battery)
        result = {
            "graded_mean": graded_total / n if n else 0.0,
            "strict_pass_rate": strict_total / n if n else 0.0,
            "n": n,
        }
    finally:
        os.dup2(real_stdout, 1)
        os.close(sink)
        os.close(real_stdout)
    _emit(1, result)


def _emit(fd, obj):
    os.write(fd, (json.dumps(obj) + "\n").encode())


if __name__ == "__main__":
    main()
