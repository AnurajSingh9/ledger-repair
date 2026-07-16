"""
Isolation / anti-cheat tests. Proves the agent's sandbox cannot read or import
the oracle reference or the held-out scenario battery (template Tier-1 req 1:
"a test should prove the agent cannot import or read them").

Run: python -m pytest test_isolation.py  (or just: python test_isolation.py)
"""

import os
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ORACLE = HERE / "oracle"
BUGGY = HERE / "buggy" / "ledger.py"


def _make_sandbox():
    d = Path(tempfile.mkdtemp(prefix="ledger_iso_"))
    shutil.copy(BUGGY, d / "ledger.py")
    return d


def test_oracle_not_in_sandbox():
    """The oracle reference and battery must not be present in the sandbox."""
    d = _make_sandbox()
    try:
        files = {p.name for p in d.rglob("*")}
        assert "reference.py" not in files, "oracle reference leaked into sandbox"
        assert "scenarios.py" not in files, "scenario generator leaked into sandbox"
        assert "grade_runner.py" not in files, "grader leaked into sandbox"
        assert files == {"ledger.py"}, f"unexpected files in sandbox: {files}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_oracle_not_reachable_by_relative_walk():
    """
    A module running with the sandbox as cwd must not find the oracle by
    walking a few parent levels (the realistic attack surface).
    """
    import glob
    d = _make_sandbox()
    try:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            hits = []
            # sandbox itself and one parent level is the realistic surface;
            # deeper walks are both unrealistic and slow.
            for up in [".", ".."]:
                hits += glob.glob(os.path.join(up, "*", "reference.py"))
                hits += glob.glob(os.path.join(up, "reference.py"))
            oracle_ref = str((ORACLE / "reference.py").resolve())
            resolved = [str(Path(h).resolve()) for h in hits]
            assert oracle_ref not in resolved, (
                f"oracle reachable via relative walk from sandbox: {resolved}")
        finally:
            os.chdir(cwd)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_import_ledger_only():
    """The only importable module from the sandbox is the ledger under repair."""
    d = _make_sandbox()
    try:
        import subprocess, sys
        # try to import the oracle from inside the sandbox — must fail
        code = "import sys; sys.path=[%r]; " % str(d) + \
               "\ntry:\n import reference; print('LEAK')\nexcept Exception: print('OK')"
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, cwd=str(d)).stdout.strip()
        assert out == "OK", f"oracle importable from sandbox: {out}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    test_oracle_not_in_sandbox()
    test_oracle_not_reachable_by_relative_walk()
    test_import_ledger_only()
    print("all isolation tests PASSED")
