import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

SKILL = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("journal_lifecycle", SKILL / "scripts/journal.py")
j = importlib.util.module_from_spec(spec)
spec.loader.exec_module(j)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lifecycle-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "中文 project"
        self.project.mkdir()

    def prepare(self):
        j.init_project(self.project)
        (self.project / j.CONFIG).write_text(json.dumps({"version": 1, "password": "disposable-review-password"}))
        (self.project / j.SKILLDIR).mkdir(parents=True, exist_ok=True)
        (self.project / j.SKILLDIR / "SKILL.md").write_text("Test fixture")

    def event(self, **changes):
        result = dict(event_id=str(uuid4()), session_id=str(uuid4()), task_id=str(uuid4()), turn_id=str(uuid4()),
                      kind="request", tool="other-agent.v2", data={"user_text": "解释一下这里的状态变化", "status": "in_progress"})
        result.update(changes)
        return result

    def test_pending_and_rejection_never_create_events(self):
        self.prepare()
        self.assertEqual(j.status_project(self.project)["status"], "pending")
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, self.event())
        with self.assertRaises(j.JournalError):
            j.enable_project(self.project)
        j.disable_project(self.project)
        self.assertFalse((self.project / j.LOGDIR).exists())
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_install_idempotent_preserves_consent_key_and_history(self):
        self.assertEqual(j.install_project(self.project)["status"], "pending")
        self.assertFalse((self.project / "AGENTS.md").exists())
        j.enable_project(self.project, confirmed=True)
        event = self.event()
        j.append_event(self.project, event)
        key = (self.project / j.CONFIG).read_bytes()
        state = (self.project / j.STATE).read_bytes()
        rules = (self.project / "AGENTS.md").read_bytes()
        log = j.event_path(self.project, event["session_id"], event["event_id"]).read_bytes()
        j.install_project(self.project)
        self.assertEqual((self.project / j.CONFIG).read_bytes(), key)
        self.assertEqual((self.project / j.STATE).read_bytes(), state)
        self.assertEqual((self.project / "AGENTS.md").read_bytes(), rules)
        self.assertEqual(j.event_path(self.project, event["session_id"], event["event_id"]).read_bytes(), log)
        j.disable_project(self.project)
        self.assertFalse(j.install_project(self.project)["enabled"])

    def test_rule_merge_preserves_bom_crlf_and_unrelated_rules(self):
        self.prepare()
        original = b"\xef\xbb\xbf# Existing\r\nKeep my rules.\r\n"
        (self.project / "AGENTS.md").write_bytes(original)
        (self.project / "CLAUDE.md").write_text("# Custom Claude\nKeep this too.\n")
        first = j.enable_project(self.project, confirmed=True)
        content = (self.project / "AGENTS.md").read_bytes()
        self.assertTrue(content.startswith(original))
        self.assertIn(b"@AGENTS.md", (self.project / "CLAUDE.md").read_bytes())
        j.enable_project(self.project)
        self.assertEqual(content, (self.project / "AGENTS.md").read_bytes())
        self.assertEqual(first["consented_at"], j.status_project(self.project)["consented_at"])

    def test_corrupt_rule_markers_leave_both_files_and_state_unchanged(self):
        self.prepare()
        (self.project / "AGENTS.md").write_text("keep")
        (self.project / "CLAUDE.md").write_text("<!-- ai-dev-journal:start -->broken")
        with self.assertRaises(j.JournalError):
            j.enable_project(self.project, confirmed=True)
        self.assertEqual((self.project / "AGENTS.md").read_text(), "keep")
        self.assertFalse(j.status_project(self.project)["enabled"])

    def test_rule_write_failure_rolls_back_first_file(self):
        self.prepare()
        (self.project / "AGENTS.md").write_text("existing")
        original = j.atomic_write
        def fail_second(path, content):
            if path.name == "CLAUDE.md":
                raise PermissionError("test")
            original(path, content)
        with patch.object(j, "atomic_write", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                j.enable_project(self.project, confirmed=True)
        self.assertEqual((self.project / "AGENTS.md").read_text(), "existing")
        self.assertFalse(j.status_project(self.project)["enabled"])

    def test_disable_resume_and_new_disclosure_confirmation(self):
        self.prepare()
        enabled = j.enable_project(self.project, confirmed=True)
        j.disable_project(self.project)
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, self.event())
        self.assertEqual(j.enable_project(self.project)["consented_at"], enabled["consented_at"])
        with patch.object(j, "DISCLOSURE_VERSION", 2):
            self.assertFalse(j.status_project(self.project)["enabled"])
            with self.assertRaises(j.JournalError):
                j.enable_project(self.project)
            self.assertTrue(j.enable_project(self.project, confirmed=True)["enabled"])

    def test_stop_can_recover_corrupt_state_without_password(self):
        (self.project / j.STATE).write_text("broken")
        with self.assertRaises(j.JournalError):
            j.status_project(self.project)
        self.assertFalse(j.disable_project(self.project)["enabled"])
        self.assertTrue(j.status_project(self.project)["consent_required"])

    def test_legacy_ciphertext_readable_without_consent_but_append_requires_it(self):
        self.prepare()
        event = self.event(tool="codex")
        payload = dict(event, recorded_at=datetime.now(timezone.utc).isoformat())
        dest = j.event_path(self.project, event["session_id"], event["event_id"])
        dest.parent.mkdir(parents=True)
        dest.write_bytes(j.encrypt(payload, j.password_for(self.project)))
        before = dest.read_bytes()
        self.assertEqual(len(j.read_events(self.project)), 1)
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, self.event())
        j.enable_project(self.project, confirmed=True)
        self.assertEqual(dest.read_bytes(), before)

    def test_tracked_state_or_key_rejected(self):
        if not shutil.which("git"):
            self.skipTest("Git unavailable")
        self.prepare()
        subprocess.run(["git", "init", str(self.project)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.project), "add", "-f", j.CONFIG], check=True, capture_output=True)
        with self.assertRaises(j.JournalError):
            j.enable_project(self.project, confirmed=True)
        self.assertFalse(j.status_project(self.project)["enabled"])

    def test_facts_preserve_attribution_and_do_not_invent_observation(self):
        self.prepare()
        j.enable_project(self.project, confirmed=True)
        facts = [
            dict(actor="user", summary="用户说懂了", source="user_statement", reference="本轮用户消息：懂了"),
            dict(actor="agent", summary="Agent 修正自己写错的选择器", source="artifact", reference="src/main.js:12"),
            dict(actor="unknown", summary="测试工具未能启动，未验证作品", source="tool_result", reference="命令退出码 127"),
        ]
        event = self.event(data={"user_text": "懂了", "facts": facts})
        j.append_event(self.project, event)
        self.assertEqual(j.read_events(self.project)[0]["data"]["facts"], facts)
        for field, value in (("actor", "student_is_expert"), ("source", "guess"), ("reference", "")):
            bad = copy.deepcopy(event)
            bad["data"]["facts"][0][field] = value
            with self.assertRaises(j.JournalError):
                j.validate(bad)

    def test_multi_turn_new_session_and_explicit_task_continuation(self):
        self.prepare()
        j.enable_project(self.project, confirmed=True)
        request = self.event()
        result = dict(request, event_id=str(uuid4()), kind="result", data={"status": "in_progress", "checks": [{"name": "代码测试", "status": "not_run", "evidence": "本轮仅讨论"}]})
        correction = self.event(task_id=request["task_id"], kind="correction", data={"user_feedback": "你刚才的解释不对", "related_event_ids": [result["event_id"]]})
        for event in (request, result, correction):
            j.append_event(self.project, event)
        rows = j.read_events(self.project)
        self.assertEqual(rows[0]["turn_id"], rows[1]["turn_id"])
        self.assertNotEqual(rows[1]["session_id"], rows[2]["session_id"])
        self.assertEqual(rows[0]["task_id"], rows[2]["task_id"])
        self.assertEqual(rows[2]["data"]["related_event_ids"], [result["event_id"]])

    def test_redaction_does_not_corrupt_fact_metadata(self):
        self.prepare()
        (self.project / j.CONFIG).write_text(json.dumps({"version": 1, "password": "user"}))
        j.enable_project(self.project, confirmed=True)
        event = self.event(data={"user_text": "user is a test credential", "facts": [
            dict(actor="user", summary="user supplied a test value", source="user_statement", reference="当前消息")
        ]})
        j.append_event(self.project, event)
        data = j.read_events(self.project)[0]["data"]
        self.assertEqual(data["facts"][0]["actor"], "user")
        self.assertEqual(data["facts"][0]["source"], "user_statement")
        self.assertNotIn("user", data["user_text"])

    def test_logs_only_skips_secrets_dependencies_state_and_pending_files(self):
        self.prepare()
        j.enable_project(self.project, confirmed=True)
        event = self.event()
        j.append_event(self.project, event)
        for name in (".env", "node_modules/x.js", "src/private.txt", "ai-dev-journal.local.json.bak"):
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fake-test-value")
        (self.project / j.LOGDIR / ".pending-test").write_text("unfinished")
        archive = self.base / "logs.zip"
        j.pack(self.project, archive, logs_only=True)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.namelist(), [str(j.LOGDIR / event["session_id"] / (event["event_id"] + ".enc")).replace("\\", "/")])

    def test_empty_or_damaged_logs_do_not_produce_submission(self):
        self.prepare()
        with self.assertRaises(j.JournalError):
            j.pack(self.project, self.base / "empty.zip", logs_only=True)
        self.assertFalse((self.base / "empty.zip").exists())
        j.enable_project(self.project, confirmed=True)
        event = self.event()
        j.append_event(self.project, event)
        j.event_path(self.project, event["session_id"], event["event_id"]).write_text("damaged")
        with self.assertRaises(j.JournalError):
            j.pack(self.project, self.base / "bad.zip", logs_only=True)
        self.assertFalse((self.base / "bad.zip").exists())

    def test_disable_waits_for_inflight_publication_then_rejects_writes(self):
        self.prepare()
        j.enable_project(self.project, confirmed=True)
        started, release = threading.Event(), threading.Event()
        original = j.encrypt
        def slow_encrypt(event, password):
            started.set()
            release.wait(5)
            return original(event, password)
        with patch.object(j, "encrypt", side_effect=slow_encrypt), ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(j.append_event, self.project, self.event())
            self.assertTrue(started.wait(5))
            stopper = pool.submit(j.disable_project, self.project)
            self.assertFalse(stopper.done())
            release.set()
            self.assertTrue(writer.result()["saved"])
            self.assertFalse(stopper.result()["enabled"])
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, self.event())
        self.assertEqual(len(j.read_events(self.project)), 1)

    def test_cli_from_subdirectory_and_status_never_echo_key(self):
        self.prepare()
        nested = self.project / "src"
        nested.mkdir()
        args = [sys.executable, str(SKILL / "scripts/journal.py")]
        result = subprocess.run(args + ["enable", "--project", str(self.project), "--confirm"], cwd=nested, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = subprocess.run(args + ["status", "--project", str(self.project)], cwd=nested, capture_output=True)
        self.assertTrue(json.loads(status.stdout)["enabled"])
        self.assertNotIn(b"disposable-review-password", status.stdout + status.stderr)
        stopped = subprocess.run(args + ["disable", "--project", str(self.project)], cwd=nested, capture_output=True)
        self.assertFalse(json.loads(stopped.stdout)["enabled"])


if __name__ == "__main__":
    unittest.main()
