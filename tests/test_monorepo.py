from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "monorepo.py"
SPEC = importlib.util.spec_from_file_location("monorepo_orchestrator", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
monorepo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monorepo
SPEC.loader.exec_module(monorepo)


class MonorepoOrchestrationTests(unittest.TestCase):
    def test_target_resolution_keeps_component_working_directories(self) -> None:
        max_commands = monorepo.resolve_target("max")
        andromeda_commands = monorepo.resolve_target("andromeda")
        contract_commands = monorepo.resolve_target("contracts")

        self.assertEqual(max_commands[0].cwd, ROOT / "apps" / "max")
        self.assertIn("verify", max_commands[0].argv)
        self.assertEqual(andromeda_commands[0].cwd, ROOT / "services" / "andromeda")
        self.assertIn("full", andromeda_commands[0].argv)
        self.assertEqual(contract_commands[0].cwd, ROOT / "services" / "andromeda")
        self.assertIn("check:andromeda-client-drift", contract_commands[2].argv)

    def test_nonzero_child_status_stops_and_propagates(self) -> None:
        command = monorepo.Command(
            "intentional exit-code fixture",
            (sys.executable, "-c", "raise SystemExit(7)"),
            ROOT,
        )
        status = monorepo.run_commands((command,))
        self.assertEqual(status, 7)

    def test_stack_requires_explicit_fixture_seed_and_preserves_volumes_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit --fixtures"):
            monorepo.resolve_stack_action("up")

        up = monorepo.resolve_stack_action("up", fixtures=True)
        self.assertIn("--wait", up.argv)
        self.assertIn("--build", up.argv)
        self.assertNotIn("--volumes", up.argv)

        down = monorepo.resolve_stack_action("down")
        self.assertNotIn("--volumes", down.argv)
        destructive_down = monorepo.resolve_stack_action("down", volumes=True)
        self.assertIn("--volumes", destructive_down.argv)

    def test_optional_max_profile_is_explicit(self) -> None:
        command = monorepo.resolve_stack_action("up", fixtures=True, max_profile=True)
        self.assertIn("--profile", command.argv)
        self.assertIn("max", command.argv)


if __name__ == "__main__":
    unittest.main()
