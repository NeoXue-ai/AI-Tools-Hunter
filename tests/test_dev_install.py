from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _scaffold(repository: Path) -> None:
    """Write a minimal installable project into *repository*."""
    repository.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().parents[1] / "dev_install.sh"
    shutil.copy2(script, repository / "dev_install.sh")
    (repository / "pyproject.toml").write_text(
        """\
[project]
name = "domainhunter"
version = "0.0.0"
requires-python = ">=3.12"

[project.scripts]
domainhunter = "domainhunter.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
"""
    )
    package = repository / "src" / "domainhunter"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text('__version__ = "0.0.0"\n')
    (package / "cli.py").write_text(
        'import sys\n\ndef main() -> None:\n    print(" ".join(sys.argv[1:]) or "ready")\n'
    )


def _run_install(repository: Path, *, env: dict[str, str] | None = None):
    """Invoke the script the documented way: from the project root."""
    return subprocess.run(
        ["bash", "dev_install.sh"],
        cwd=repository,
        capture_output=True,
        text=True,
        env=env,
    )


def test_dev_install_uses_the_directory_containing_the_script_as_the_project_root(
    tmp_path: Path,
) -> None:
    """The documented root-level invocation installs the package successfully."""
    repository = tmp_path / "domain hunter"
    _scaffold(repository)
    subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=repository, check=True)

    result = _run_install(repository)

    assert result.returncode == 0, result.stderr
    assert "ok:" in result.stdout

    cli_result = subprocess.run(
        [str(repository / ".venv" / "bin" / "domainhunter"), "first-pass"],
        cwd=repository,
        capture_output=True,
        text=True,
    )
    assert cli_result.returncode == 0, cli_result.stderr
    assert cli_result.stdout == "first-pass\n"

    if sys.platform == "darwin":
        site_packages = subprocess.check_output(
            [
                str(repository / ".venv" / "bin" / "python"),
                "-c",
                "import sysconfig; print(sysconfig.get_paths()['purelib'])",
            ],
            text=True,
        ).strip()
        subprocess.run(["chflags", "hidden", f"{site_packages}/domainhunter.pth"], check=True)

        recovered_result = subprocess.run(
            [str(repository / ".venv" / "bin" / "domainhunter"), "recovered"],
            cwd=repository,
            capture_output=True,
            text=True,
        )
        assert recovered_result.returncode == 0, recovered_result.stderr
        assert recovered_result.stdout == "recovered\n"

        reinstall_result = _run_install(repository)
        assert reinstall_result.returncode == 0, reinstall_result.stderr

        refreshed_result = subprocess.run(
            [str(repository / ".venv" / "bin" / "domainhunter"), "refreshed"],
            cwd=repository,
            capture_output=True,
            text=True,
        )
        assert refreshed_result.returncode == 0, refreshed_result.stderr
        assert refreshed_result.stdout == "refreshed\n"


def test_dev_install_falls_back_to_pip_when_uv_cannot_build(tmp_path: Path) -> None:
    """A broken ``uv`` editable build must not leave a half-installed venv.

    ``uv`` runs build backends in-process, and uv 0.12.10 + setuptools 84.0.0
    fails an *editable* build with ``EEXIST`` from ``build_editable`` while the
    non-editable build succeeds — reproducibly, and independently of whether the
    project path contains a space. pip runs the backend in a subprocess and is
    unaffected, so the script retries with pip.
    """
    repository = tmp_path / "domainhunter"
    _scaffold(repository)
    subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=repository, check=True)

    # A ``uv`` that always fails, first on PATH so the script picks it up.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    failing_uv = fake_bin / "uv"
    failing_uv.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"error: EEXIST: file already exists, mkdir '/tmp/builds-v0/.tmp123'\" >&2\n"
        "exit 1\n"
    )
    failing_uv.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = _run_install(repository, env=env)

    assert result.returncode == 0, result.stderr
    assert "retrying with pip" in result.stderr
    assert "ok:" in result.stdout

    cli_result = subprocess.run(
        [str(repository / ".venv" / "bin" / "domainhunter"), "after-fallback"],
        cwd=repository,
        capture_output=True,
        text=True,
    )
    assert cli_result.returncode == 0, cli_result.stderr
    assert cli_result.stdout == "after-fallback\n"
