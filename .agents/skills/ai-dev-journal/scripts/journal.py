"""Encrypted, append-only development events. No plaintext log files."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from uuid import UUID
import zipfile

if sys.version_info < (3, 12):
    raise SystemExit("源码版需要 Python 3.12+；Windows 用户可直接运行包内 bin/windows-x64/journal.exe，无需安装 Python。")

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
except ImportError:
    raise SystemExit("源码版缺少加密依赖；Windows 用户请运行包内 bin/windows-x64/journal.exe。其他平台需安装 requirements.txt 中的依赖。") from None

CONFIG = "ai-dev-journal.local.json"
LOGDIR = Path("docs/engineering/ai-worklog")
AAD = b"ai-dev-journal:v1:scrypt-32768-8-1:aes256gcm"
MAX_BYTES = 2 * 1024 * 1024
TOP = {"event_id", "session_id", "task_id", "turn_id", "kind", "tool", "data"}
TEXT = {"user_text", "understanding", "user_feedback"}
LIST = {"assumptions", "changes", "decisions", "failures", "open_items", "redactions", "related_event_ids"}


class JournalError(Exception):
    pass


def uuid_text(value):
    if not isinstance(value, str):
        raise JournalError("Identifiers must be UUID strings")
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except ValueError:
        raise JournalError("Identifiers must be canonical lowercase UUIDs") from None
    return value


def validate(event):
    if not isinstance(event, dict) or set(event) != TOP:
        raise JournalError("Event requires exactly event/session/task/turn IDs, kind, tool, data")
    for key in ("event_id", "session_id", "task_id", "turn_id"):
        uuid_text(event[key])
    if event["kind"] not in ("request", "progress", "correction", "result"):
        raise JournalError("Invalid event kind")
    if event["tool"] not in ("codex", "claude-code", "deepseek-harness", "other"):
        raise JournalError("Invalid tool")
    data = event["data"]
    if not isinstance(data, dict) or set(data) - TEXT - LIST - {"checks", "status"}:
        raise JournalError("Unknown data fields")
    for key, value in data.items():
        if key in TEXT and not isinstance(value, str):
            raise JournalError("Text fields must be strings")
        if key in LIST:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise JournalError("List fields must contain strings")
            if key == "related_event_ids":
                for item in value:
                    uuid_text(item)
    if "status" in data and data["status"] not in ("in_progress", "completed", "blocked", "cancelled"):
        raise JournalError("Invalid task status")
    if event["kind"] == "request" and not data.get("user_text", "").strip():
        raise JournalError("request requires user_text")
    if event["kind"] == "result" and "status" not in data:
        raise JournalError("result requires status")
    checks = data.get("checks", [])
    if not isinstance(checks, list):
        raise JournalError("checks must be a list")
    for item in checks:
        if (not isinstance(item, dict) or set(item) != {"name", "status", "evidence"}
                or not all(isinstance(x, str) for x in item.values())
                or item["status"] not in ("passed", "failed", "not_run")):
            raise JournalError("Each check requires name, status, evidence")
    if len(json.dumps(event, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise JournalError("Event exceeds 2 MiB limit")


def safe_path(root, relative):
    """Reject links/junctions anywhere under the selected project."""
    root = Path(root).resolve(strict=True)
    path = root
    for part in Path(relative).parts:
        if part in ("..", ".") or Path(part).is_absolute():
            raise JournalError("Unsafe path")
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise JournalError("Links/junctions are not allowed in journal paths")
    if not path.resolve().is_relative_to(root):
        raise JournalError("Path escapes project")
    return path


def password_for(project):
    path = safe_path(project, CONFIG)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise JournalError("Missing or invalid local config; configure it locally, never paste it into chat") from None
    if not isinstance(cfg, dict) or set(cfg) != {"version", "password"} or cfg["version"] != 1:
        raise JournalError("Unsupported local config")
    password = cfg["password"]
    if not isinstance(password, str) or not password or password in ("CHANGE_ME", "在本机填入你自己的长口令"):
        raise JournalError("Configure a nonempty password locally")
    return password


def derive(password, salt):
    return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode("utf-8"))


def redact(value, password):
    if isinstance(value, str):
        value = value.replace(password, "[REDACTED]")
        value = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", value)
        value = re.sub(r'''(?i)(\b(?:password|passwd|api[_-]?key|token|secret)\b["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''', r"\1[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [redact(x, password) for x in value]
    if isinstance(value, dict):
        return {k: redact(v, password) for k, v in value.items()}
    return value


def event_path(project, session_id, event_id):
    return safe_path(project, LOGDIR / uuid_text(session_id) / (uuid_text(event_id) + ".enc"))


def encrypt(event, password):
    salt, nonce = os.urandom(16), os.urandom(12)
    plaintext = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(derive(password, salt)).encrypt(nonce, plaintext, AAD)
    return json.dumps({"version": 1, "salt": base64.b64encode(salt).decode(),
                       "nonce": base64.b64encode(nonce).decode(),
                       "ciphertext": base64.b64encode(ciphertext).decode()}, separators=(",", ":")).encode()


def decrypt(path, password):
    try:
        if path.stat().st_size > MAX_BYTES * 3:
            raise ValueError()
        blob = json.loads(path.read_bytes())
        if set(blob) != {"version", "salt", "nonce", "ciphertext"} or blob["version"] != 1:
            raise ValueError()
        salt, nonce, ciphertext = (base64.b64decode(blob[k], validate=True) for k in ("salt", "nonce", "ciphertext"))
        if len(salt) != 16 or len(nonce) != 12:
            raise ValueError()
        event = json.loads(AESGCM(derive(password, salt)).decrypt(nonce, ciphertext, AAD))
        stamp = event.pop("recorded_at")
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp).tzinfo is None:
            raise ValueError()
        validate(event)
        if event["session_id"] != path.parent.name or event["event_id"] != path.stem:
            raise ValueError()
        event["recorded_at"] = stamp
        return event
    except (ValueError, TypeError, KeyError, AttributeError, InvalidTag, JournalError):
        raise JournalError("Wrong password, damaged ciphertext, or invalid event; nothing decrypted") from None


def append_event(project, event):
    validate(event)
    password = password_for(project)
    # Catch a mistyped/replaced password before mixing incompatible events in a project.
    logroot = safe_path(project, LOGDIR)
    first = next(logroot.glob("*/*.enc"), None) if logroot.exists() else None
    if first is not None:
        safe_path(project, first.relative_to(Path(project).resolve()))
        decrypt(first, password)
    # Redact text payload only; identifiers and enums must remain stable.
    clean = dict(event, data=redact(event["data"], password))
    if clean["data"] != event["data"]:
        clean["data"].setdefault("redactions", []).append("自动替换了明确凭据或本地口令")
    validate(clean)
    dest = event_path(project, clean["session_id"], clean["event_id"])

    def existing():
        old = decrypt(dest, password)
        old.pop("recorded_at")
        if old != clean:
            raise JournalError("Event ID already exists with different content; append a new correction")
        return {"saved": True, "duplicate": True, "event_id": clean["event_id"]}

    dest.parent.mkdir(parents=True, exist_ok=True)
    lock = safe_path(project, dest.relative_to(Path(project).resolve()).with_suffix(".lock"))
    deadline = time.monotonic() + 5
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise JournalError("Event is locked; retry later. A crashed writer may require lock inspection")
            time.sleep(0.05)
    temp = None
    try:
        if dest.exists():
            return existing()
        clean["recorded_at"] = datetime.now(timezone.utc).isoformat()
        encoded = encrypt(clean, password)
        # Serialize writers and publish a complete ciphertext using same-directory rename.
        fd, temp = tempfile.mkstemp(prefix=".pending-", dir=dest.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temp, dest)
    finally:
        if temp is not None:
            Path(temp).unlink(missing_ok=True)
        lock.rmdir()
    return {"saved": True, "duplicate": False, "event_id": clean["event_id"]}


def read_events(project, session=None):
    password = password_for(project)
    root = safe_path(project, LOGDIR)
    if session:
        root = safe_path(project, LOGDIR / uuid_text(session))
    if not root.exists():
        return []
    paths = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            safe_path(project, (Path(directory) / name).relative_to(Path(project).resolve()))
        paths.extend(Path(directory) / name for name in files if name.endswith(".enc"))
    # Authenticate every event before displaying anything; no partial plaintext on failure.
    events = [decrypt(path, password) for path in sorted(paths)]
    return sorted(events, key=lambda e: (e["recorded_at"], e["event_id"]))


def init_project(project):
    root = Path(project).resolve(strict=True)
    cfg = safe_path(root, CONFIG)
    ignore = safe_path(root, ".gitignore")
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "--", CONFIG],
                                capture_output=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            raise JournalError("Local config is tracked by Git; resolve that before initialization")
    except FileNotFoundError:
        pass
    if not cfg.exists():
        with cfg.open("x", encoding="utf-8") as handle:
            json.dump({"version": 1, "password": ""}, handle)
        if os.name != "nt":
            cfg.chmod(0o600)
    # Appended last: override any earlier negation. Not an archive exclusion.
    current = ignore.read_text(encoding="utf-8-sig") if ignore.exists() else ""
    rule = "\n# Local AI journal password (not for sharing)\nai-dev-journal.local.json\n"
    if not current.endswith(rule):
        with ignore.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(rule)
    return {"initialized": True, "config": CONFIG, "password_configured": bool(json.loads(cfg.read_text(encoding="utf-8-sig")).get("password"))}


def pack(project, output):
    root = Path(project).resolve(strict=True)
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise JournalError("Archive must be outside project")
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d.casefold() != ".git"]
        for name in dirs + names:
            path = safe_path(root, (Path(directory) / name).relative_to(root))
            if name.casefold() not in (CONFIG, ".git") and path.is_file():
                files.append(path)
    # Never follow links, never replace an existing archive. Remove incomplete output on failure.
    created = False
    try:
        with output.open("xb") as stream:
            created = True
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(files):
                    safe_path(root, path.relative_to(root))
                    archive.write(path, path.relative_to(root))
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    return {"packed": True, "files": len(files), "excluded": [CONFIG, ".git"]}


def doctor():
    """Self-test the shipped runtime without reading project config or writing files."""
    salt, nonce = os.urandom(16), os.urandom(12)
    key = derive("disposable-runtime-selftest", salt)
    aes = AESGCM(key)
    if aes.decrypt(nonce, aes.encrypt(nonce, b"journal-selftest", AAD), AAD) != b"journal-selftest":
        raise JournalError("Encryption self-test failed")
    return {"ready": True, "bundled": bool(getattr(sys, "frozen", False)),
            "python": sys.version.split()[0], "message": "运行环境和加密自检通过"}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="AI 开发日志：加密记录、读取、校验与安全打包。Windows 免安装版已自带运行环境。")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查运行环境和加密能力，不读取密码或写入日志")
    for command in ("init", "append", "read", "verify", "pack"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--project", required=True)
        if command in ("read", "verify"):
            cmd.add_argument("--session")
        if command == "pack":
            cmd.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "init":
            result = init_project(args.project)
        elif args.command == "append":
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise JournalError("Event exceeds 2 MiB limit")
            result = append_event(args.project, json.loads(raw.decode("utf-8-sig")))
        elif args.command in ("read", "verify"):
            events = read_events(Path(args.project).resolve(), args.session)
            result = events if args.command == "read" else {"verified": True, "events": len(events)}
        else:
            result = pack(args.project, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (JournalError, OSError, ValueError, TypeError):
        # Never echo input, password, plaintext, or a library exception containing secrets.
        print("日志操作未完成：请检查本地密码配置、事件格式、写入权限及密文完整性。没有转存明文。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
