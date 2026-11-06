"""Check a fresh full replay and the two frozen principal table objects."""
from pathlib import Path
import argparse
import json
import sys

HERE = Path(__file__).resolve().parent

def read(path):
    return json.loads(Path(path).read_text())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--tables', type=Path, required=True)
    parser.add_argument('--expected-tables', type=Path, default=HERE / 'example_tables')
    args = parser.parse_args()
    comparison = read(args.replay / 'FROZEN_RESULT_COMPARISON.json')
    receipt = read(args.replay / 'RUN_RECEIPT.json')
    table_checks = {name: read(args.tables / name) == read(args.expected_tables / name)
                    for name in ('MAJOR_TABLES.json', 'PAIRED_BOOTSTRAP.json')}
    result = {
        'status': 'PASS' if comparison.get('status') == 'PASS'
                  and comparison.get('compared') == 730
                  and comparison.get('matched') == 730
                  and comparison.get('mismatches') == []
                  and receipt.get('allocated') == 730
                  and receipt.get('mismatches') == 0
                  and all(table_checks.values()) else 'FAIL',
        'compared': comparison.get('compared'),
        'matched': comparison.get('matched'),
        'table_checks': table_checks,
        'new_model_execution': False,
    }
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
