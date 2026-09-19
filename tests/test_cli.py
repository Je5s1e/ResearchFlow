"""Run the real CLI command handler with offline model/search and terminal input."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from researchflow import __main__ as cli
from researchflow.config import Settings
from researchflow.storage import Store
from tests.helpers import FakeModel, FakeSearch

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="researchflow-cli-test-")
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(Path(self.temp.name).resolve(), "offline-key", model="offline")
        self.model = FakeModel()
        self.output = io.StringIO()
        patches = [
            patch.object(cli.Settings, "load", return_value=self.settings),
            patch.object(cli, "Model", return_value=self.model),
            patch.object(cli, "SearchMCP", side_effect=FakeSearch),
            patch.object(cli, "console", Console(file=self.output, markup=False, width=120)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def command(self, *args, answers=()):
        with (
            patch.object(sys, "argv", ["researchflow", *args]),
            patch("builtins.input", side_effect=answers),
        ):
            cli.main()

    def session(self):
        paths = list(self.settings.sessions.glob("*/session.json"))
        self.assertEqual(len(paths), 1)
        return Store(paths[0].parent)

    def test_run_quit_resume_and_completed_resume(self):
        self.command("run", "--topic", "离线CLI测试", answers=["approve", "quit"])
        store = self.session()
        self.assertEqual(store.read_json("session.json")["stage"], "waiting_approval")
        self.assertFalse((store.path / "report.md").exists())
        self.command("resume", "--id", store.path.name, answers=["approve"])
        self.assertEqual(store.read_json("session.json")["stage"], "completed")
        self.assertTrue((store.path / "report.md").is_file())
        self.command("resume", "--id", store.path.name)
        self.assertEqual(self.model.calls["Report"], 1)
        self.assertEqual(self.model.calls["Plan"], 1)
        events = [
            json.loads(line) for line in (store.path / "logs/events.jsonl").read_text().splitlines()
        ]
        ids = [e["event_id"] for e in events if e["type"] == "message"]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.command("status", "--id", store.path.name)
        self.command("list")
        self.assertIn("completed", self.output.getvalue())

    def test_retry_failed_search_completes_original_session(self):
        def fail_once(store):
            client = FakeSearch(store)
            client.failures = 1
            return client

        with patch.object(cli, "SearchMCP", side_effect=fail_once):
            with self.assertRaises(SystemExit) as error:
                self.command("run", "--topic", "离线重试测试", answers=["approve"])
        self.assertEqual(error.exception.code, 1)
        store = self.session()
        self.assertEqual(store.read_json("session.json")["stage"], "failed")
        self.command("retry", "--id", store.path.name, answers=["approve"])
        self.assertEqual(store.read_json("session.json")["stage"], "completed")
        self.assertEqual(self.model.calls["Plan"], 1)
        self.assertEqual(self.model.calls["Report"], 1)
        self.assertEqual(self.session().path, store.path)

    def test_retry_cannot_bypass_pending_approval(self):
        self.command("run", "--topic", "离线审批测试", answers=["quit"])
        store = self.session()
        with self.assertRaises(SystemExit) as error:
            self.command("retry", "--id", store.path.name)
        self.assertEqual(error.exception.code, 1)
        self.assertIn("当前等待审批，请使用 resume", self.output.getvalue())
        self.assertEqual(self.model.calls["Selection"], 0)
        self.assertEqual(self.model.calls["Report"], 0)
        self.command("resume", "--id", store.path.name, answers=["approve", "approve"])
        self.assertEqual(store.read_json("session.json")["stage"], "completed")


class ProcessTests(unittest.TestCase):
    def run_process(self, *args):
        result = subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_module_entrypoint_help(self):
        output = self.run_process("-m", "researchflow", "--help")
        self.assertIn("resume", output)
        self.assertIn("retry", output)

    def test_new_process_resumes_plan_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="researchflow-process-test-") as root:
            self.run_process("-m", "tests.checkpoint_worker", "prepare", root, "plan")
            self.run_process("-m", "tests.checkpoint_worker", "finish", root, "plan")

    def test_new_process_resumes_material_checkpoint(self):
        with tempfile.TemporaryDirectory(prefix="researchflow-process-test-") as root:
            self.run_process("-m", "tests.checkpoint_worker", "prepare", root, "material")
            self.run_process("-m", "tests.checkpoint_worker", "finish", root, "material")
