"""Verify a built Windows app in a relocated folder with spaces and Chinese names."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--sample', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='Zf2Lumix Windows 中文 ') as td:
        td = Path(td)
        folder = td/'移动后的应用'
        shutil.copytree(args.app.resolve().parent, folder)
        app = folder/args.app.name
        report = td/'smoke.json'
        subprocess.run([str(app), '--self-test', str(report)], check=True, timeout=120)
        smoke = json.loads(report.read_text(encoding='utf-8'))
        if not smoke['ok']:
            raise RuntimeError(smoke)
        if args.sample:
            sample = td/'测试 照片.NEF'
            shutil.copy2(args.sample, sample)
            output = td/'中文 输出'
            # Twice: exercise conversion, full RAW readback and collision handling.
            for _ in range(2):
                subprocess.run([str(app), '--cli', str(sample), '-o', str(output)], check=True, timeout=900)
            reports = sorted(output.glob('*.json'))
            if len(reports) != 2:
                raise RuntimeError('Expected two output audit files')
            for path in reports:
                result = json.loads(path.read_text(encoding='utf-8'))
                if result['raw_roundtrip_mismatch_count'] != 0 or result['decoded_samples'] != 24080064:
                    raise RuntimeError('RAW verification failed')
            import hashlib
            if hashlib.sha256(sample.read_bytes()).digest() != hashlib.sha256(args.sample.read_bytes()).digest():
                raise RuntimeError('Input modified')
        record = {'smoke': smoke, 'full_nef_conversion': bool(args.sample),
            'relocated_unicode_path': True}
        (args.app.resolve().parent/'windows-validation.json').write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
