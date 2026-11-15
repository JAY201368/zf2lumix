"""Read selected RW2 tags without decoding or changing image data."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

SIZES = {1:1, 2:1, 3:2, 4:4, 5:8, 7:1, 9:4, 10:8, 11:4, 12:8}
ROOT_TAGS = {0x1:'raw_version', 0xa:'raw_bits', 0xe:'sampling_max_r', 0xf:'sampling_max_g', 0x10:'sampling_max_b',
             0x17:'analog_gain',
             0x18:'digital_gain_r', 0x19:'digital_gain_g', 0x1a:'digital_gain_b',
             0x1c:'black_r', 0x1d:'black_g', 0x1e:'black_b',
             0x24:'wb_r', 0x25:'wb_g', 0x26:'wb_b', 0x37:'root_iso',
             0x112:'orientation', 0x119:'distortion_info', 0x11b:'aberration_info', 0x110:'model', 0x11c:'ctemp_position'}


def inspect(path):
    # Bounded seek reads: no embedded previews or Bayer data are interpreted.
    with path.open('rb') as stream:
        size = path.stat().st_size
        def read(offset, count):
            if offset < 0 or count < 0 or offset + count > size:
                raise ValueError('Tag outside file bounds')
            stream.seek(offset)
            data = stream.read(count)
            if len(data) != count:
                raise ValueError('Short read')
            return data
        header = read(0, 8)
        if header[:4] != b'IIU\0':
            raise ValueError('Expected little-endian Panasonic RW2')
        def directory(offset):
            count = struct.unpack('<H', read(offset, 2))[0]
            if count > 4096:
                raise ValueError('Excessive IFD entries')
            entries = {}
            for i in range(count):
                pos = offset + 2 + 12*i
                tag, kind, n, pointer = struct.unpack('<HHII', read(pos, 12))
                if kind in SIZES:
                    length = n*SIZES[kind]
                    entries[tag] = (kind, n, pos+8 if length <= 4 else pointer, length)
            return entries
        def value(entry):
            kind, n, pos, length = entry
            if length > 4096:
                raise ValueError('Selected tag unexpectedly large')
            raw = read(pos, length)
            if kind == 2:
                decoded = raw.rstrip(b'\0').decode('ascii', errors='replace')
            elif kind in (3, 4, 9):
                values = struct.unpack('<' + {3:'H',4:'I',9:'i'}[kind]*n, raw)
                decoded = values[0] if n == 1 else list(values)
            else:
                decoded = {'hex':raw.hex()}
            return {'type':kind, 'count':n, 'value':decoded}
        root = directory(struct.unpack_from('<I', header, 4)[0])
        selected = {f'0x{tag:04x} {name}':value(root[tag]) if tag in root else None
                    for tag, name in ROOT_TAGS.items()}
        exif = directory(value(root[0x8769])['value']) if 0x8769 in root else {}
        selected_exif = {f'0x{tag:04x} {name}':value(exif[tag]) if tag in exif else None
                         for tag, name in {0x8827:'iso', 0xa001:'colorspace'}.items()}
    # Identity only; no image payload is stored in the report.
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'file':str(path), 'bytes':size, 'sha256':digest,
            'root_ifd':selected, 'exif_ifd':selected_exif}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    report = {'scope':'Selected metadata only; no rendered-image validation',
              'files':[inspect(path) for path in args.files]}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(f'Inspected {len(report["files"])} RW2 files; originals opened read-only')


if __name__ == '__main__':
    main()
