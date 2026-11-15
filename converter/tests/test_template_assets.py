import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rw2 import IFD, codec_parameters, root
from template_assets import MAKER_PRIVATE, STANDARD_PRIVATE, sanitize_templates

ASSETS = Path(__file__).resolve().parents[1] / 'assets/templates'


class TemplatePrivacyTests(unittest.TestCase):
    def test_all_shipped_templates_are_clean_and_keep_codec_and_offsets(self):
        prefixes = sorted(ASSETS.glob('*.prefix.z'))
        self.assertEqual(len(prefixes), 16)
        for path in prefixes:
            with self.subTest(template=path.name):
                prefix = zlib.decompress(path.read_bytes())
                exif = zlib.decompress(path.with_name(path.name.replace('.prefix.', '.exif.')).read_bytes())
                clean_prefix, clean_exif = sanitize_templates(prefix, exif)
                self.assertEqual((clean_prefix, clean_exif), (prefix, exif))
                self.assertEqual(codec_parameters(clean_prefix), codec_parameters(prefix))
                a = root(exif, 6)
                thumb = IFD(exif, 6 + a.next, 6)
                offset, size = 6 + thumb.get(0x201), thumb.get(0x202)
                self.assertFalse(any(exif[offset:offset + size]))

    def test_injected_donor_fields_are_erased_without_relocating_metadata(self):
        prefix = bytearray(zlib.decompress((ASSETS / 'daylight_800.prefix.z').read_bytes()))
        exif = bytearray(zlib.decompress((ASSETS / 'daylight_800.exif.z').read_bytes()))
        p = root(prefix)
        a = root(exif, 6)
        ep = IFD(prefix, p.get(0x8769))
        ea = IFD(exif, 6 + a.get(0x8769), 6)
        maker = IFD(exif, ea.tags[0x927c][3] + 12, 6)
        ep.set(0xa431, 'DONOR-SERIAL-123')
        ea.set(0xa431, 'DONOR-SERIAL-123')
        ea.set(0x9003, '2026:10:16 12:34:56')
        maker.set(0x52, 'LENS-123456')
        for d, tags in [(p, STANDARD_PRIVATE), (maker, MAKER_PRIVATE)]:
            for tag in tags & d.tags.keys():
                _, typ, count, pos, size = d.tags[tag]
                if typ in (1, 2, 7):
                    d.b[pos:pos + size] = (b'PRIVATE-DONOR-' * (size // 14 + 1))[:size]
        thumb = IFD(exif, 6 + a.next, 6)
        pos, size = 6 + thumb.get(0x201), thumb.get(0x202)
        exif[pos:pos + size] = b'\xff' * size
        before_codec = codec_parameters(prefix)
        clean_prefix, clean_exif = sanitize_templates(prefix, exif)
        self.assertEqual((len(clean_prefix), len(clean_exif)), (len(prefix), len(exif)))
        self.assertEqual(codec_parameters(clean_prefix), before_codec)
        for marker in [b'DONOR-SERIAL-123', b'2026:10:16 12:34:56', b'LENS-123456', b'PRIVATE-DONOR-']:
            self.assertNotIn(marker, clean_prefix + clean_exif)
        self.assertFalse(any(clean_exif[pos:pos + size]))
        self.assertEqual(sanitize_templates(clean_prefix, clean_exif), (clean_prefix, clean_exif))


if __name__ == '__main__':
    unittest.main()
