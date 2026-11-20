import json
import os
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize(
    "args,pip_args,exit_code,stdin",
    (
        (
            [
                "install",
                "--upgrade",
                "--editable",
                "./plugin source",
                "--force-reinstall",
                "--no-cache-dir",
                "--pre",
                "first-plugin",
                "second-plugin>=1",
            ],
            [
                "install",
                "--upgrade",
                "--editable",
                "./plugin source",
                "--force-reinstall",
                "--no-cache-dir",
                "--pre",
                "first-plugin",
                "second-plugin>=1",
            ],
            0,
            "",
        ),
        (["install", "first-plugin"], ["install", "first-plugin"], 23, ""),
        (["uninstall", "first-plugin"], ["uninstall", "first-plugin"], 0, "y\n"),
        (
            ["uninstall", "--yes", "first-plugin", "second-plugin"],
            ["uninstall", "first-plugin", "second-plugin", "-y"],
            23,
            "",
        ),
    ),
)
def test_pip_runs_in_child_process(tmp_path, args, pip_args, exit_code, stdin):
    # A fake pip exercises the actual process boundary without installing packages.
    pip_directory = tmp_path / "pip stub"
    package = pip_directory / "pip"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "__main__.py").write_text(
        textwrap.dedent("""
            import json
            import os
            import sys
            from pathlib import Path

            record = {
                "pid": os.getpid(),
                "executable": sys.executable,
                "args": sys.argv[1:],
            }
            if sys.argv[1] == "uninstall" and "-y" not in sys.argv:
                record["answer"] = input("Proceed (Y/n)? ")
            Path(os.environ["LLM_TEST_PIP_RECORD"]).write_text(json.dumps(record))
            os.environ["LLM_TEST_PIP_MUTATED"] = "yes"
            print("pip stdout")
            print("pip stderr", file=sys.stderr)
            sys.exit(int(os.environ["LLM_TEST_PIP_EXIT_CODE"]))
            """),
        "utf-8",
    )
    driver = tmp_path / "run_llm.py"
    driver.write_text(
        textwrap.dedent("""
            import atexit
            import json
            import os
            import sys
            from pathlib import Path
            from llm.cli import cli

            original_argv = sys.argv[:]

            @atexit.register
            def record_parent():
                Path(os.environ["LLM_TEST_PARENT_RECORD"]).write_text(json.dumps({
                    "pid": os.getpid(),
                    "executable": sys.executable,
                    "original_argv": original_argv,
                    "argv": sys.argv,
                    "pip_imported": "pip" in sys.modules,
                    "pip_mutated": os.environ.get("LLM_TEST_PIP_MUTATED"),
                }))

            cli()
            """),
        "utf-8",
    )
    pip_record = tmp_path / "pip.json"
    parent_record = tmp_path / "parent.json"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, (str(pip_directory), os.environ.get("PYTHONPATH")))
        ),
        "LLM_LOAD_PLUGINS": "",
        "LLM_TEST_PIP_RECORD": str(pip_record),
        "LLM_TEST_PARENT_RECORD": str(parent_record),
        "LLM_TEST_PIP_EXIT_CODE": str(exit_code),
    }
    env.pop("LLM_TEST_PIP_MUTATED", None)
    result = subprocess.run(
        [sys.executable, str(driver), *args],
        check=False,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == exit_code, result.stderr
    assert "pip stdout" in result.stdout
    assert "pip stderr" in result.stderr
    pip = json.loads(pip_record.read_text())
    parent = json.loads(parent_record.read_text())
    assert pip["pid"] != parent["pid"]
    assert pip["executable"] == parent["executable"] == sys.executable
    assert pip["args"] == pip_args
    if stdin:
        assert pip["answer"] == "y"
    assert parent["argv"] == parent["original_argv"]
    assert not parent["pip_imported"]
    assert parent["pip_mutated"] is None
