"""Run a synthetic geometry example; this is a software check, not model evidence."""
from pathlib import Path
import hashlib
import importlib.util
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / 'evaluation/evaluator/code/geometry_v4.py'
    spec = importlib.util.spec_from_file_location('topoworld_geometry_221', path)
    geometry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometry)
    case = json.loads((ROOT / 'examples/synthetic_two_rooms_case.json').read_text())
    results = []
    for name, expected in [('synthetic_two_rooms.json', True), ('synthetic_blocked_door.json', False)]:
        world = json.loads((ROOT / 'examples' / name).read_text())
        assessment = geometry.assess(world, case)
        readout = assessment['readouts']['Q01']
        passed = (assessment['schema_validation']['status'] == 'VALID'
                  and readout['status'] == 'DETERMINATE' and readout['value'] is expected)
        results.append({'example': name, 'software_fixture_only': True, 'expected_connection': expected,
                        'readout': readout['value'], 'schema': assessment['schema_validation']['status'],
                        'pass': passed})
    result = {'status': 'PASS' if all(r['pass'] for r in results) else 'FAIL',
              'evaluator': '2.2.1', 'geometry_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'examples': results}
    print(json.dumps(result, indent=2))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
