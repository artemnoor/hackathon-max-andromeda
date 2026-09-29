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

    def test_e2e_uses_a_unique_fixture_stack_and_always_cleans_it_up(self) -> None:
        calls: list[tuple[list[str], dict[str, object]]] = []

        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[object]:
            calls.append((argv, kwargs))
            result = subprocess.CompletedProcess(argv, 7 if len(calls) == 2 else 0)
            return result

        self.assertEqual(monorepo.run_e2e(runner=runner), 7)
        self.assertEqual(len(calls), 4)
        up, integration, catalog_diagnostic, cleanup = calls
        self.assertIn("--project-name", up[0])
        self.assertIn("--wait", up[0])
        self.assertIn("andromeda", up[0])
        self.assertIn("redis", up[0])
        self.assertEqual(up[1]["cwd"], monorepo.ROOT)
        self.assertIn("test:integration", integration[0])
        self.assertIn("MAX_E2E_ANDROMEDA_URL", integration[1]["env"])
        self.assertIn("exec", catalog_diagnostic[0])
        self.assertIn("andromeda", catalog_diagnostic[0])
        self.assertIn("UniversityModel", catalog_diagnostic[0][-1])
        self.assertIn("--volumes", cleanup[0])
        self.assertIn("andromeda-max-e2e-", cleanup[0][3])


if __name__ == "__main__":
    unittest.main()
