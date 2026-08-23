import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseSurfaceTests(unittest.TestCase):
    def test_owner_release_check_passes(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/release_check.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("v0.1.0", completed.stdout)


if __name__ == "__main__":
    unittest.main()
