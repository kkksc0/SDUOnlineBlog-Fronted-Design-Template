"""Encrypted, append-only development events. No plaintext log files."""
import argparse
import base64
import json
import os
from contextlib import contextmanager
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
STATE = "ai-dev-journal.state.local.json"
CONTROL_LOCK = ".ai-dev-journal.control.lock"
SKILLDIR = Path(".agents/skills/ai-dev-journal")
DISCLOSURE_VERSION = 1
PACKAGE_VERSION = "2.0.0"
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
    if not isinstance(event["tool"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", event["tool"]):
        raise JournalError("Invalid tool")
    data = event["data"]
    if not isinstance(data, dict) or set(data) - TEXT - LIST - {"checks", "status", "facts"}:
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
    facts = data.get("facts", [])
    if not isinstance(facts, list):
        raise JournalError("facts must be a list")
    for fact in facts:
        if (not isinstance(fact, dict) or set(fact) != {"actor", "summary", "source", "reference"}
                or not all(isinstance(x, str) and x.strip() for x in fact.values())
                or fact["actor"] not in ("user", "agent", "unknown")
                or fact["source"] not in ("user_statement", "tool_result", "artifact")):
            raise JournalError("Each fact requires actor, summary, source, reference")
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


def redact_data(data, password):
    clean = redact(data, password)
    # Only free text is sensitive payload; schema enums and UUID references are metadata.
    for key in ("status", "related_event_ids"):
        if key in data:
            clean[key] = data[key]
    for original, updated in zip(data.get("checks", []), clean.get("checks", [])):
        updated["status"] = original["status"]
    for original, updated in zip(data.get("facts", []), clean.get("facts", [])):
        updated["actor"], updated["source"] = original["actor"], original["source"]
    return clean


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
    # Serialize disable with publication: once disable returns, no earlier writer can publish.
    with control_lock(project):
        state = load_state(project)
        if state["status"] != "enabled" or not current_consent(state):
            raise JournalError("记录尚未启用或已停用；请先告知用户并确认，或按用户要求恢复记录。")
        return _append_event(project, event)


def _append_event(project, event):
    validate(event)
    password = password_for(project)
    # Catch a mistyped/replaced password before mixing incompatible events in a project.
    logroot = safe_path(project, LOGDIR)
    first = next(logroot.glob("*/*.enc"), None) if logroot.exists() else None
    if first is not None:
        safe_path(project, first.relative_to(Path(project).resolve()))
        decrypt(first, password)
    # Redact text payload only; identifiers and enums must remain stable.
    clean = dict(event, data=redact_data(event["data"], password))
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


def init_project(project, template=None):
    root = Path(project).resolve(strict=True)
    cfg = safe_path(root, CONFIG)
    ignore = safe_path(root, ".gitignore")
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "--", CONFIG, STATE],
                                capture_output=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            raise JournalError("本地口令或授权状态已被 Git 跟踪；请先取消跟踪，再初始化。")
    except FileNotFoundError:
        pass
    if not cfg.exists():
        content = json.loads(Path(template).read_text(encoding="utf-8-sig")) if template else {"version": 1, "password": ""}
        with cfg.open("x", encoding="utf-8") as handle:
            json.dump(content, handle, ensure_ascii=False)
        if os.name != "nt":
            cfg.chmod(0o600)
    # Appended last: override any earlier negation. Not an archive exclusion.
    current = ignore.read_text(encoding="utf-8-sig") if ignore.exists() else ""
    rule = ("\n# AI journal: local password, consent and runtime\n" + CONFIG + "\n" + STATE + "\n"
            + CONTROL_LOCK + "/\n.agents/skills/ai-dev-journal/.venv/\n")
    if not current.endswith(rule):
        with ignore.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(rule)
    return {"initialized": True, "config": CONFIG, "password_configured": bool(json.loads(cfg.read_text(encoding="utf-8-sig")).get("password"))}


def pack(project, output, logs_only=False):
    root = Path(project).resolve(strict=True)
    output = Path(output).resolve()
    if output.is_relative_to(root):
        raise JournalError("Archive must be outside project")
    files = []
    walkroot = safe_path(root, LOGDIR) if logs_only else root
    if logs_only:
        events = read_events(root)  # authenticate before creating a submission
        if not events:
            raise JournalError("没有可提交的加密日志；不会创建空的日志包。")
    for directory, dirs, names in os.walk(walkroot, followlinks=False):
        dirs[:] = [d for d in dirs if d.casefold() != ".git"]
        for name in dirs + names:
            path = safe_path(root, (Path(directory) / name).relative_to(root))
            if (name.casefold() not in (CONFIG, STATE, ".git") and path.is_file()
                    and (not logs_only or path.suffix == ".enc")):
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
    return {"packed": True, "files": len(files), "logs_only": logs_only, "excluded": [CONFIG, STATE, ".git"]}


def package_root():
    return Path(sys.executable).resolve().parents[2] if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


@contextmanager
def control_lock(project):
    lock = safe_path(project, CONTROL_LOCK)
    deadline = time.monotonic() + 10
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise JournalError("日志状态正被占用；确认没有记录进程后检查项目根目录的 control.lock 空目录。")
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.rmdir()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def load_state(project):
    path = safe_path(project, STATE)
    if not path.exists():
        return {"version": 1, "status": "pending", "disclosure_version": None, "consented_at": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        if (not isinstance(state, dict) or state.get("version") != 1
                or state.get("status") not in ("pending", "enabled", "disabled")):
            raise ValueError()
        for key in ("consented_at", "updated_at"):
            if state.get(key) is not None and datetime.fromisoformat(state[key]).tzinfo is None:
                raise ValueError()
        return state
    except (ValueError, TypeError, KeyError):
        raise JournalError("本地授权状态无效；不会默认启用，请重新告知并确认。") from None


def current_consent(state):
    return state.get("disclosure_version") == DISCLOSURE_VERSION and bool(state.get("consented_at"))


def atomic_write(path, content):
    fd, name = tempfile.mkstemp(prefix=".journal-update-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save_state(project, state):
    state = dict(state, version=1, updated_at=timestamp())
    atomic_write(safe_path(project, STATE), json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))


def status_project(project):
    state = load_state(project)
    cfg = safe_path(project, CONFIG)
    configured = False
    if cfg.exists():
        try:
            password_for(project)
            configured = True
        except JournalError:
            pass
    return {"status": state["status"], "enabled": state["status"] == "enabled" and current_consent(state) and configured,
            "consent_required": not current_consent(state), "disclosure_version": DISCLOSURE_VERSION,
            "consented_at": state.get("consented_at"), "password_configured": configured,
            "skill_installed": safe_path(project, SKILLDIR / "SKILL.md").is_file(),
            "scope": "current_project_conversations", "package_version": PACKAGE_VERSION}


def managed_content(original, body):
    start, end = "<!-- ai-dev-journal:start -->", "<!-- ai-dev-journal:end -->"
    block = start + "\n" + body.strip() + "\n" + end
    if start in original or end in original:
        if original.count(start) != 1 or original.count(end) != 1 or original.index(start) > original.index(end):
            raise JournalError("项目指令的日志托管区块不完整；请修复标记后重试，不覆盖其他规则。")
        left = original.index(start)
        right = original.index(end) + len(end)
        return original[:left] + block + original[right:]
    return original + ("\n\n" if original and not original.endswith("\n\n") else "") + block + "\n"


def merge_rules(project):
    prepared = []
    for name in ("AGENTS", "CLAUDE"):
        target = safe_path(project, name + ".md")
        original = target.read_bytes() if target.exists() else None
        # Preserve existing line endings and bytes outside our marked block.
        text = original.decode("utf-8-sig") if original is not None else ""
        body = (package_root() / "assets" / (name + ".block.md")).read_text(encoding="utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        updated = managed_content(text, body).replace("\r\n", "\n").replace("\n", newline)
        if original is not None and original.startswith(b"\xef\xbb\xbf"):
            updated = "\ufeff" + updated
        prepared.append((target, original, updated.encode("utf-8")))
    changed = []
    try:
        for target, original, updated in prepared:
            if original != updated:
                atomic_write(target, updated)
                changed.append((target, original))
    except OSError:
        for target, original in reversed(changed):
            if original is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write(target, original)
        raise


def enable_project(project, confirmed=False):
    with control_lock(project):
        state = load_state(project)
        if not current_consent(state) and not confirmed:
            raise JournalError("需要先展示 references/notice.md 并取得用户确认，再执行 enable --confirm。")
        if not safe_path(project, SKILLDIR / "SKILL.md").is_file():
            raise JournalError("请先运行 install 为当前项目安装完整 skill。")
        init_project(project)  # retain Git tracking protection on every activation
        password_for(project)
        read_events(project)  # refuse activation with a key that cannot read existing history
        doctor()
        merge_rules(project)
        if not current_consent(state):
            state.update(disclosure_version=DISCLOSURE_VERSION, consented_at=timestamp())
        state.update(status="enabled")
        save_state(project, state)  # activation is last, after both instruction files succeed
    return status_project(project)


def disable_project(project):
    with control_lock(project):
        try:
            state = load_state(project)
        except JournalError:
            state = {"version": 1, "disclosure_version": None, "consented_at": None}
        state["status"] = "disabled"
        save_state(project, state)
    return {"status": "disabled", "enabled": False, "history_preserved": True}


def install_project(project):
    source = package_root()
    destination = safe_path(project, SKILLDIR)
    # Only ship runtime resources, never source-checkout logs, tests, caches or consent.
    members = ("SKILL.md", "requirements.txt", "scripts", "references", "agents", "assets", "bin")
    copies = []
    for member in members:
        base = safe_path(source, member)
        if not base.exists():
            raise JournalError("分发包不完整；请重新获取完整仓库或发布包。")
        for directory, dirs, files in os.walk(base) if base.is_dir() else []:
            dirs[:] = [name for name in dirs if name not in ("__pycache__", ".venv")]
            for name in dirs + files:
                item = safe_path(source, (Path(directory) / name).relative_to(source))
                if item.is_file() and item.suffix != ".pyc":
                    copies.append((item, safe_path(project, SKILLDIR / item.relative_to(source))))
        if base.is_file():
            copies.append((base, safe_path(project, SKILLDIR / member)))
    doctor()
    with control_lock(project):
        state = load_state(project)
        init_project(project, source / "assets/course-config.json")
        if destination != source:
            for src, dest in copies:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists() or src.read_bytes() != dest.read_bytes():
                    atomic_write(dest, src.read_bytes())
        if not safe_path(project, STATE).exists():
            save_state(project, state)
        if state["status"] == "enabled" and current_consent(state):
            merge_rules(project)
    report = status_project(project)
    report.update(installed=True, notice=str(destination / "references/notice.md"))
    return report


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
    for command in ("init", "install", "enable", "disable", "status", "append", "read", "verify", "pack"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--project", required=True)
        if command in ("read", "verify"):
            cmd.add_argument("--session")
        if command == "pack":
            cmd.add_argument("--output", required=True)
            cmd.add_argument("--logs-only", action="store_true")
        if command == "enable":
            cmd.add_argument("--confirm", action="store_true", help="仅在已展示告知且用户明确确认后使用；此参数本身不是用户同意的证据")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "init":
            result = init_project(args.project)
        elif args.command == "install":
            result = install_project(args.project)
        elif args.command == "enable":
            result = enable_project(args.project, args.confirm)
        elif args.command == "disable":
            result = disable_project(args.project)
        elif args.command == "status":
            result = status_project(args.project)
        elif args.command == "append":
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise JournalError("Event exceeds 2 MiB limit")
            result = append_event(args.project, json.loads(raw.decode("utf-8-sig")))
        elif args.command in ("read", "verify"):
            events = read_events(Path(args.project).resolve(), args.session)
            result = events if args.command == "read" else {"verified": True, "events": len(events)}
        else:
            result = pack(args.project, args.output, args.logs_only)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except JournalError as error:
        # These are fixed application messages, never interpolated user input or secrets.
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError):
        # Never echo input, password, plaintext, or a library exception containing secrets.
        print("日志操作未完成：请检查本地密码配置、事件格式、写入权限及密文完整性。没有转存明文。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
