"""Re-score retained responses, regenerate tables, and check frozen agreement."""
from pathlib import Path
import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tables', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    package = args.package.resolve()
    output, tables = args.output.resolve(), args.tables.resolve()
    if output.exists() or tables.exists():
        parser.error('Replay and table output directories must both be new.')
    if output == tables or output.is_relative_to(tables) or tables.is_relative_to(output):
        parser.error('Use separate replay and table directories.')
    commands = [
        [sys.executable, '-B', str(package / 'run_reproduction.py'), '--output', str(output), '--workers', str(args.workers)],
        [sys.executable, '-B', str(package / 'build_tables.py'), '--results', str(output / 'REPLAY_RESULTS.json'), '--output', str(tables)],
        [sys.executable, '-B', str(package / 'verify_replay.py'), '--replay', str(output), '--tables', str(tables)],
    ]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    for command in commands:
        subprocess.run(command, check=True, env=env)


if __name__ == '__main__':
    main()
