"""
ledger_repair — a long-horizon stateful debugging RL environment.

The agent is given a buggy double-entry ledger engine and a set of tools to
read it, run scenarios against it, and patch it. Three interacting,
state-dependent bugs only manifest after transactions cross period boundaries.
The verifier re-runs a HELD-OUT battery of scenarios against the agent's patched
module in a fresh subprocess and scores final balances against an independent
oracle. It never trusts anything the agent reports about itself.

Exposes `load_environment(**kwargs) -> vf.Environment` per the verifiers spec.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import verifiers as vf
from datasets import Dataset

ASSETS = Path(__file__).parent / "assets"
BUGGY = ASSETS / "buggy" / "ledger.py"
ORACLE_DIR = ASSETS / "oracle"

# ---- per-rollout sandbox registry -------------------------------------------
# ToolEnv tools are stateless callables, so we key each rollout's mutable
# working directory by a sandbox id embedded in the prompt/info and thread it
# through the tool arguments. Sandboxes are created lazily and cleaned up by the
# rubric after grading.
_SANDBOXES: dict[str, Path] = {}


def _sandbox_dir(sid: str) -> Path:
    if sid not in _SANDBOXES:
        d = Path(tempfile.mkdtemp(prefix=f"ledger_{sid}_"))
        shutil.copy(BUGGY, d / "ledger.py")
        _SANDBOXES[sid] = d
    return _SANDBOXES[sid]


# ---- tools (bound to a sandbox id) ------------------------------------------
def _make_tools(sid: str):
    def read_file(path: str = "ledger.py") -> str:
        """Read a file from the working directory. Default: the ledger module."""
        d = _sandbox_dir(sid)
        target = (d / path).resolve()
        # confinement: never escape the sandbox
        if not str(target).startswith(str(d.resolve())):
            return "ERROR: path outside working directory is not allowed."
        if not target.exists():
            return f"ERROR: no such file: {path}"
        return target.read_text()

    def write_file(content: str, path: str = "ledger.py") -> str:
        """Overwrite a file in the working directory with new content."""
        d = _sandbox_dir(sid)
        target = (d / path).resolve()
        if not str(target).startswith(str(d.resolve())):
            return "ERROR: path outside working directory is not allowed."
        target.write_text(content)
        return f"wrote {len(content)} bytes to {path}"

    def run_ledger(period_length: int, transactions: str) -> str:
        """
        Run a scenario against the CURRENT ledger.py and return final balances.

        period_length: transactions per accounting period.
        transactions: a JSON list of transaction dicts, e.g.
            '[{"type":"transfer","debit":"cash","credit":"ar","amount":100}]'
        Use this to reproduce the bug and to check your fixes. This runs YOUR
        current ledger.py; it does not reveal the grading battery.
        """
        d = _sandbox_dir(sid)
        try:
            txns = json.loads(transactions)
        except Exception as e:
            return f"ERROR: transactions must be valid JSON list: {e}"
        runner = (
            "import json,sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from ledger import Ledger\n"
            "led = Ledger(int(sys.argv[2]))\n"
            "for t in json.loads(sys.argv[3]):\n"
            "    led.post(t)\n"
            "print(json.dumps(led.balances()))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", runner, str(d), str(period_length), json.dumps(txns)],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            return "ERROR: execution timed out (10s)."
        if proc.returncode != 0:
            return f"ERROR: ledger raised:\n{proc.stderr.strip()}"
        return proc.stdout.strip()

    def submit() -> str:
        """Signal that you believe ledger.py is fixed and ready for grading."""
        return "SUBMITTED. The grader will now run the held-out scenario battery."

    return [read_file, write_file, run_ledger, submit]


# ---- verifier ---------------------------------------------------------------
def _grade_module(module_path: Path, battery: list) -> tuple[float, float, int]:
    """
    Run the held-out battery against the agent's module in a FRESH subprocess.
    Returns (graded_mean, strict_pass_rate, n). Grading is on final balances vs
    an independent oracle. Never reads the agent's claims.
    """
    payload = json.dumps({"battery": battery})
    grader_src = (ORACLE_DIR / "grade_runner.py").read_text()
    proc = subprocess.run(
        [sys.executable, "-c", grader_src, str(module_path.parent), str(ORACLE_DIR)],
        input=payload, capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        # a module that crashes on import/run scores zero, not a pass
        return 0.0, 0.0, len(battery)
    res = json.loads(proc.stdout.strip())
    return res["graded_mean"], res["strict_pass_rate"], res["n"]


def load_environment(
    num_train: int = 24,
    num_eval: int = 24,
    battery_size: int = 40,
    battery_seed: int = 1000,
    max_turns: int = 40,
    **kwargs,
) -> vf.Environment:
    """
    Build the ledger_repair environment.

    num_train/num_eval: dataset rows (each row is an independent repair attempt
        with its own sandbox; the underlying bug is the same, the reproduction
        scenarios the model must discover differ by seed).
    battery_size: number of held-out scenarios used for grading.
    battery_seed: seed for the held-out battery (kept away from the agent).
    max_turns: tool-call budget.
    """
    # import the held-out scenario generator (server-side only)
    sys.path.insert(0, str(ORACLE_DIR))
    import scenarios as _scen  # noqa

    held_out_battery = _scen.make_battery(battery_seed, battery_size)

    task_instruction = (
        "You are debugging a double-entry ledger engine in `ledger.py`.\n\n"
        "The engine processes an ordered stream of transactions and rolls over "
        "balances at the end of each accounting period. It currently produces "
        "WRONG final balances on some scenarios. The bugs only reveal themselves "
        "once transactions cross period boundaries, so you will need to run "
        "multi-period scenarios to reproduce them.\n\n"
        "Tools available: `read_file`, `write_file`, `run_ledger` (execute a "
        "scenario against your current ledger.py and see the balances), and "
        "`submit`. Do NOT change the public API (class name `Ledger`, methods "
        "`post` and `balances`, and their signatures). Amounts are integer cents.\n\n"
        "Work iteratively: reproduce a failure with `run_ledger`, form a "
        "hypothesis, patch with `write_file`, re-run to confirm, and repeat until "
        "the engine is correct across multiple periods and all transaction types. "
        "Call `submit` when done. You will be graded on a held-out battery of "
        "scenarios you cannot see, so fix the underlying logic, not specific cases."
    )

    def _row(i: int) -> dict:
        sid = uuid.uuid4().hex[:12]
        return {
            "question": task_instruction
            + f"\n\n[session:{sid}] Pass this session id as needed.",
            "answer": "correct_ledger",
            "info": {"sandbox_id": sid},
        }

    train_ds = Dataset.from_list([_row(i) for i in range(num_train)])
    eval_ds = Dataset.from_list([_row(i) for i in range(num_eval)])

    # Because tools must bind to a per-row sandbox id, we install a small
    # wrapper env that rebuilds the tool list per rollout from info.sandbox_id.
    class LedgerRepairEnv(vf.ToolEnv):
        async def env_response(self, messages, state, **kw):
            sid = state["info"]["sandbox_id"]
            self.tools = _make_tools(sid)
            self.tool_map = {t.__name__: t for t in self.tools}
            self.oai_tools = [vf.envs.tool_env.convert_func_to_tool_def(t) for t in self.tools]
            return await super().env_response(messages, state, **kw)

    async def ledger_reward(completion, state, **kwargs) -> float:
        """Graded reward: mean per-account correctness over the held-out battery."""
        sid = state["info"]["sandbox_id"]
        d = _sandbox_dir(sid)
        module_path = d / "ledger.py"
        graded, strict, n = _grade_module(module_path, held_out_battery)
        state["strict_pass_rate"] = strict
        state["battery_n"] = n
        # cleanup sandbox after grading
        shutil.rmtree(d, ignore_errors=True)
        _SANDBOXES.pop(sid, None)
        return graded

    rubric = vf.Rubric(funcs=[ledger_reward], weights=[1.0])

    # seed tools with a placeholder; env_response rebinds per rollout
    env = LedgerRepairEnv(
        tools=_make_tools("__init__"),
        max_turns=max_turns,
        dataset=train_ds,
        eval_dataset=eval_ds,
        rubric=rubric,
        system_prompt="You are a careful software engineer. Use the tools to "
        "reproduce, diagnose, and fix the bug. Think step by step.",
        **kwargs,
    )
    return env
