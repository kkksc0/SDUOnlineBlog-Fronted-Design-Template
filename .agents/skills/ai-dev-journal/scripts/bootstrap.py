"""Standard-library installer bootstrap; never activates recording or changes system Python."""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description="Prepare the project-local journal runtime; no consent is assumed.")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = Path(args.project).resolve(strict=True)
    skill = Path(__file__).resolve().parents[1]
    if os.name == "nt" and platform.machine().lower() in ("amd64", "x86_64"):
        exe = skill / "bin/windows-x64/journal.exe"
        if not exe.is_file():
            print("Windows 运行包缺失，请重新获取完整分发包。", file=sys.stderr)
            return 1
        return subprocess.run([str(exe), "install", "--project", str(project)], check=False).returncode
    if sys.version_info < (3, 12):
        print("需要 Python 3.12+；尚未启用记录，也没有修改系统 Python。", file=sys.stderr)
        return 1
    # Refuse redirected installation paths before creating the local environment.
    destination = project / ".agents/skills/ai-dev-journal"
    current = project
    for part in (".agents", "skills", "ai-dev-journal", ".venv"):
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            print("安装路径包含链接，请选择项目内实际目录。", file=sys.stderr)
            return 1
    environment = destination / ".venv"
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        ignore = project / ".gitignore"
        if ignore.is_symlink() or (hasattr(ignore, "is_junction") and ignore.is_junction()):
            raise OSError("Linked ignore file")
        existing = ignore.read_text(encoding="utf-8-sig") if ignore.exists() else ""
        rule = ".agents/skills/ai-dev-journal/.venv/"
        if rule not in existing.splitlines():
            with ignore.open("a", encoding="utf-8") as handle:
                handle.write("\n" + rule + "\n")
        if not interpreter.is_file():
            venv.EnvBuilder(with_pip=True).create(environment)
        check = subprocess.run([str(interpreter), "-c", "import sys, cryptography; assert sys.version_info >= (3,12); assert 44 <= int(cryptography.__version__.split('.')[0]) < 47"], capture_output=True)
        if check.returncode:
            subprocess.run([str(interpreter), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(skill / "requirements.txt")], check=True)
        subprocess.run([str(interpreter), str(skill / "scripts/journal.py"), "doctor"], check=True)
        subprocess.run([str(interpreter), str(skill / "scripts/journal.py"), "install", "--project", str(project)], check=True)
    except (OSError, subprocess.CalledProcessError):
        print("项目内运行环境准备失败；检查 Python venv/pip、网络及写入权限。未执行启用，请修复后重试。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
