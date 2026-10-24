"""Exercise the Windows bundle with Python removed from the child environment."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import uuid4
import zipfile

SKILL = Path(__file__).resolve().parents[1]
BUNDLE = SKILL / "bin/windows-x64"
spec = importlib.util.spec_from_file_location("journal_source", SKILL / "scripts/journal.py")
j = importlib.util.module_from_spec(spec)
spec.loader.exec_module(j)


@unittest.skipUnless(os.name == "nt" and (BUNDLE / "journal.exe").exists(), "Windows portable bundle not built")
class PortableTests(unittest.TestCase):
    def test_relocated_bundle_without_python(self):
        with tempfile.TemporaryDirectory(prefix="portable-test-", dir=Path(__file__).parent) as temp:
            base = Path(temp)
            relocated = base / "另一台设备 skill"
            for member in ("SKILL.md", "requirements.txt", "assets", "agents", "references", "scripts", "bin"):
                src, dest = SKILL / member, relocated / member
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
                else:
                    shutil.copy2(src, dest)
            exe = relocated / "bin/windows-x64/journal.exe"
            project = base / "业务项目"
            project.mkdir()
            env = os.environ.copy()
            env.update(PATH="", PYTHONHOME=str(base / "no-python"), PYTHONPATH=str(base / "no-packages"))
            env.pop("VIRTUAL_ENV", None)

            def run(*args, data=None, success=True):
                result = subprocess.run([str(exe), *args], cwd=project, env=env,
                                        input=json.dumps(data, ensure_ascii=False).encode() if data else None,
                                        capture_output=True, timeout=30)
                if success:
                    self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
                    return json.loads(result.stdout)
                self.assertNotEqual(result.returncode, 0)
                return result

            check = run("doctor")
            self.assertTrue(check["ready"])
            self.assertTrue(check["bundled"])
            pending = run("install", "--project", str(project))  # no Git or Python on PATH
            self.assertFalse(pending["enabled"])
            self.assertFalse((project / "AGENTS.md").exists())
            run("enable", "--project", str(project), success=False)
            password = "temporary-portable-test-passphrase"
            (project / j.CONFIG).write_text(json.dumps({"version": 1, "password": password}), encoding="utf-8")
            run("enable", "--project", str(project), "--confirm")
            original = dict(event_id=str(uuid4()), session_id=str(uuid4()), task_id=str(uuid4()),
                            turn_id=str(uuid4()), kind="request", tool="codex",
                            data={"user_text": "源码版原有中文日志，跨设备继续", "status": "in_progress"})
            j.append_event(project, original)
            rows = run("read", "--project", str(project))
            rows[0].pop("recorded_at")
            self.assertEqual(rows, [original])
            followup = dict(original, event_id=str(uuid4()), kind="result", tool="claude-code",
                            data={"status": "completed", "changes": ["免安装版继续记录"],
                                  "checks": [{"name": "浏览器检查", "status": "not_run", "evidence": "仅测试记录流程"}]})
            self.assertTrue(run("append", "--project", str(project), data=followup)["saved"])
            self.assertTrue(run("append", "--project", str(project), data=followup)["duplicate"])
            self.assertEqual(len(j.read_events(project)), 2)  # source reads bundled output
            self.assertEqual(run("verify", "--project", str(project))["events"], 2)
            run("disable", "--project", str(project))
            run("append", "--project", str(project), data=dict(followup, event_id=str(uuid4())), success=False)
            self.assertEqual(len(run("read", "--project", str(project))), 2)
            self.assertTrue(run("enable", "--project", str(project))["enabled"])
            out = base / "share.zip"
            nested = project / "nested"
            nested.mkdir()
            (nested / j.CONFIG.upper()).write_text("excluded-test-secret")
            (project / ".env").write_text("FAKE_TEST_SECRET=not-real")
            run("pack", "--project", str(project), "--output", str(out), "--logs-only")
            with zipfile.ZipFile(out) as archive:
                self.assertNotIn(j.CONFIG, archive.namelist())
                self.assertFalse(any(j.CONFIG in name.casefold() for name in archive.namelist()))
                self.assertTrue(any(n.endswith(".enc") for n in archive.namelist()))
                self.assertTrue(all(n.endswith(".enc") for n in archive.namelist()))
            (project / j.CONFIG).write_text(json.dumps({"version": 1, "password": "incorrect"}), encoding="utf-8")
            failure = run("read", "--project", str(project), success=False)
            self.assertEqual(failure.stdout, b"")
            self.assertNotIn(password.encode(), failure.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
