import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OrganContractTests(unittest.TestCase):
    def test_contract_validator_passes(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/validate_organ_contract.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_contract_declares_deny_by_default(self) -> None:
        contract = json.loads((ROOT / "contracts/organ_contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["private_admission"]["access_plane"], "none")
        self.assertEqual(contract["private_admission"]["current_state"], "no_record_by_design")
        self.assertEqual(contract["private_admission"]["default_admission"], "deny")

    def test_contract_keeps_execution_authority_outside(self) -> None:
        contract = json.loads((ROOT / "contracts/organ_contract.json").read_text(encoding="utf-8"))
        excluded = set(contract["constitutional_boundary"]["does_not_own"])
        self.assertIn("actor_creation_master_wake_or_action_execution", excluded)
        self.assertIn("proof_review_or_eval_verdicts", excluded)

    def test_reusable_handoff_contract_has_no_task_instance_thread(self) -> None:
        contract = json.loads((ROOT / "contracts/organ_contract.json").read_text(encoding="utf-8"))
        self.assertNotIn("master_thread_id", contract["handoff"])


if __name__ == "__main__":
    unittest.main()
