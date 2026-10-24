import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/journal.py"
spec = importlib.util.spec_from_file_location("journal", SCRIPT)
j = importlib.util.module_from_spec(spec)
spec.loader.exec_module(j)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="journal-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        j.init_project(self.project)
        self.password = "disposable-test-password-中文"
        self.configure(self.project, self.password)

    def configure(self, project, password):
        (project / j.CONFIG).write_text(json.dumps({"version": 1, "password": password}), encoding="utf-8")

    def event(self, kind="request", **data):
        return dict(event_id=str(uuid4()), session_id=str(uuid4()), task_id=str(uuid4()),
                    turn_id=str(uuid4()), kind=kind, tool="codex",
                    data=data or {"user_text": "请修复登录提示\n保留接口；`$()` 作为文本", "status": "in_progress"})

    def test_roundtrip_and_no_plaintext(self):
        event = self.event()
        j.append_event(self.project, event)
        events = j.read_events(self.project)
        stamp = events[0].pop("recorded_at")
        self.assertIn("+00:00", stamp)
        self.assertEqual(events, [event])
        raw = j.event_path(self.project, event["session_id"], event["event_id"]).read_bytes()
        self.assertNotIn("请修复".encode(), raw)
        self.assertNotIn(self.password.encode(), raw)
        self.assertNotIn(b"user_text", raw)

    def test_multi_device(self):
        event = self.event()
        j.append_event(self.project, event)
        second = self.base / "second"
        shutil.copytree(self.project, second)
        # Recreate config from remembered password, not cryptographic state from old device.
        (second / j.CONFIG).unlink()
        j.init_project(second)
        self.configure(second, self.password)
        followup = self.event("result", status="in_progress", checks=[{
            "name": "浏览器", "status": "not_run", "evidence": "尚未打开"}])
        followup.update(session_id=event["session_id"], task_id=event["task_id"], turn_id=event["turn_id"])
        j.append_event(second, followup)
        self.assertEqual(len(j.read_events(second)), 2)
        self.assertEqual(len(j.read_events(self.project)), 1)

    def test_duplicate_and_conflict(self):
        event = self.event()
        j.append_event(self.project, event)
        self.assertTrue(j.append_event(self.project, event)["duplicate"])
        changed = copy.deepcopy(event)
        changed["data"]["user_text"] = "不同指令"
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, changed)
        self.assertEqual(len(j.read_events(self.project)), 1)

    def test_concurrent_same_event(self):
        event = self.event()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: j.append_event(self.project, event), range(3)))
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        self.assertEqual(len(j.read_events(self.project)), 1)

    def test_wrong_password_and_tamper(self):
        event = self.event()
        j.append_event(self.project, event)
        self.configure(self.project, "wrong-password")
        with self.assertRaises(j.JournalError):
            j.read_events(self.project)
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, self.event())
        self.configure(self.project, self.password)
        path = j.event_path(self.project, event["session_id"], event["event_id"])
        blob = json.loads(path.read_bytes())
        blob["ciphertext"] = ("A" if blob["ciphertext"][0] != "A" else "B") + blob["ciphertext"][1:]
        path.write_text(json.dumps(blob))
        with self.assertRaises(j.JournalError):
            j.read_events(self.project)

    def test_redaction_and_retry(self):
        event = self.event(user_text=f'password="secret value" Bearer abc.xyz {self.password}')
        j.append_event(self.project, event)
        self.assertTrue(j.append_event(self.project, event)["duplicate"])
        text = json.dumps(j.read_events(self.project), ensure_ascii=False)
        for secret in ("secret value", "abc.xyz", self.password):
            self.assertNotIn(secret, text)
        self.assertIn("REDACTED", text)

    def test_pack_and_ignore(self):
        original = "# original\n!important.txt\n"
        (self.project / ".gitignore").write_text(original)
        j.init_project(self.project)
        self.assertTrue((self.project / ".gitignore").read_text().startswith(original))
        j.append_event(self.project, self.event())
        nested = self.project / "nested"
        nested.mkdir()
        self.configure(nested, "other-test-password")
        repo = self.project / ".git"
        repo.mkdir()
        (repo / "config").write_text("private remote")
        out = self.base / "share.zip"
        j.pack(self.project, out)
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
            self.assertFalse(any(j.CONFIG in name or ".git/" in name for name in names))
            self.assertTrue(any(name.endswith(".enc") for name in names))
        with self.assertRaises(FileExistsError):
            j.pack(self.project, out)
        with self.assertRaises(j.JournalError):
            j.pack(self.project, self.project / "bad.zip")

    def test_invalid_event_leaves_no_log(self):
        event = self.event()
        event["session_id"] = "../../escape"
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, event)
        event = self.event("result", status="completed", checks=[{"name": "test", "status": "maybe", "evidence": ""}])
        with self.assertRaises(j.JournalError):
            j.append_event(self.project, event)
        self.assertFalse((self.project / j.LOGDIR).exists())

    def test_runtime_doctor(self):
        report = j.doctor()
        self.assertTrue(report["ready"])
        self.assertFalse(report["bundled"])
        self.assertFalse((self.project / j.LOGDIR).exists())

    def test_worktree_git_file_not_shared(self):
        (self.project / ".git").write_text("gitdir: private-local-path")
        out = self.base / "worktree.zip"
        j.pack(self.project, out)
        with zipfile.ZipFile(out) as archive:
            self.assertNotIn(".git", archive.namelist())

    def test_pack_excludes_case_variants_of_password_and_git(self):
        (self.project / j.CONFIG.upper()).write_text("private local password")
        nested = self.project / "nested"
        nested.mkdir()
        (nested / j.CONFIG.upper()).write_text("another private password")
        git = self.project / ".GIT"
        git.mkdir()
        (git / "config").write_text("private repo details")
        out = self.base / "case-variants.zip"
        j.pack(self.project, out)
        with zipfile.ZipFile(out) as archive:
            for name in archive.namelist():
                parts = Path(name).parts
                self.assertNotIn(j.CONFIG, [part.casefold() for part in parts])
                self.assertNotIn(".git", [part.casefold() for part in parts])

    def test_junction_detection_without_special_privileges(self):
        from unittest.mock import patch
        with patch.object(Path, "is_junction", return_value=True):
            with self.assertRaises(j.JournalError):
                j.safe_path(self.project, j.CONFIG)

    def test_distinct_parallel_sessions(self):
        events = [self.event() for _ in range(3)]
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda e: j.append_event(self.project, e), events))
        self.assertTrue(all(r["saved"] for r in results))
        self.assertEqual(len(j.read_events(self.project)), 3)

    def test_interrupted_request_remains_unfinished(self):
        event = self.event()
        j.append_event(self.project, event)
        rows = j.read_events(self.project)
        self.assertEqual(rows[0]["data"]["status"], "in_progress")
        self.assertFalse(any(row["kind"] == "result" for row in rows))

    def test_failed_publish_leaves_no_partial_log(self):
        from unittest.mock import patch
        event = self.event()
        with patch.object(j.os, "rename", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                j.append_event(self.project, event)
        self.assertEqual(j.read_events(self.project), [])
        self.assertFalse(list((self.project / j.LOGDIR).glob("*/*.lock")))
        self.assertFalse(list((self.project / j.LOGDIR).glob("*/.pending-*")))

    def test_cli_stdin_and_error_does_not_echo_secret(self):
        event = self.event()
        command = [sys.executable, str(SCRIPT), "append", "--project", str(self.project)]
        proc = subprocess.run(command, input=json.dumps(event, ensure_ascii=False).encode(), capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = subprocess.run(command, input=self.password.encode(), capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn(self.password.encode(), proc.stdout + proc.stderr)

    def test_symlink_rejected(self):
        target = self.base / "outside"
        target.mkdir()
        try:
            (self.project / "linked").symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        with self.assertRaises(j.JournalError):
            j.pack(self.project, self.base / "unsafe.zip")


if __name__ == "__main__":
    unittest.main(verbosity=2)
