"""Download the pinned public data release, verify it, and extract a new copy."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import shutil
import stat
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/reproducibility')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error('Choose a new output directory; existing data are never overwritten.')
    release = json.loads((ROOT / 'docs/release.json').read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.topoworld-download-', dir=output.parent) as work:
        archive = Path(work) / 'release.zip'
        for attempt in range(3):
            try:
                request = urllib.request.Request(release['url'], headers={'User-Agent': 'TopoWorld-Eval/1.0.0'})
                with urllib.request.urlopen(request, timeout=90) as source, archive.open('wb') as target:
                    total = 0
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        if total > 200 * 1024 * 1024:
                            raise ValueError('Compressed archive exceeds the 200 MiB download limit.')
                        target.write(chunk)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        actual = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
        if actual != release['sha256']:
            raise ValueError('Release SHA-256 mismatch. Nothing was extracted.')
        staging = Path(work) / 'unpacked'
        staging.mkdir()
        prefix = release['archive_root']
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > 6000 or sum(i.file_size for i in infos) > 512 * 1024 * 1024:
                raise ValueError('Archive exceeds the extraction budget.')
            for item in infos:
                name = PurePosixPath(item.filename)
                if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] != prefix:
                    raise ValueError('Unsafe or unexpected archive path.')
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('Archive symlinks are not accepted.')
                relative = name.parts[1:]
                if not relative:
                    continue
                target = staging.joinpath(*relative)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as source, target.open('xb') as destination:
                        shutil.copyfileobj(source, destination)
        if not (staging / 'run_reproduction.py').is_file():
            raise ValueError('Expected public reproduction entry point is absent.')
        staging.rename(output)
    print(json.dumps({'status': 'VERIFIED_AND_EXTRACTED', 'version': release['version'],
                      'sha256': actual, 'output': str(output)}, indent=2))


if __name__ == '__main__':
    main()
