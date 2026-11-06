#!/usr/bin/env python3
"""Build this public technical report with an existing TeX installation."""
from pathlib import Path
import argparse
import shutil
import subprocess
ROOT = Path(__file__).resolve().parent

def tool(name):
    executable = shutil.which(name)
    if executable is None:
        raise SystemExit(f"Missing {name}; prepare an existing TeX distribution first.")
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30).stdout
    return [executable] + (["-disable-installer"] if "MiKTeX" in version else [])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    name = "main" if (ROOT / "main.tex").is_file() else "supplementary"
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    for filename in ["references.bib", "ieeenat_fullname.bst"]:
        if (ROOT / filename).exists():
            shutil.copy2(ROOT / filename, build / filename)
    tex = tool("pdflatex") + ["-interaction=nonstopmode", "-halt-on-error", "-output-directory=" + str(build), name + ".tex"]
    commands = [(tex, ROOT), (tool("bibtex") + [name], build)] + [(tex, ROOT)] * 3
    for index, (command, cwd) in enumerate(commands):
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=180)
        (build / f"build_{index + 1}.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise SystemExit(f"Build failed; inspect {build / ('build_' + str(index + 1) + '.txt')}")
    output = args.output.resolve() if args.output else ROOT / (name + ".pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / (name + ".pdf"), output)
    print(output)
if __name__ == "__main__":
    main()
