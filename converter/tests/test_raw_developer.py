import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from raw_developer.backend import _effective_lens_options
from raw_developer import Developer, RenderOptions, LUTLayer


class DeveloperContractTests(unittest.TestCase):
    def test_reject_bad_options_before_nef_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'photo.nef'; source.write_bytes(b'unchanged')
            bad = (RenderOptions(photo_style='missing'), RenderOptions(luts=(LUTLayer(root/'missing', float('nan')),)),
                   RenderOptions(luts=tuple(LUTLayer(root/'missing') for _ in range(3))))
            with patch('converter.convert') as convert:
                for options in bad:
                    with self.assertRaises(ValueError): Developer().render_file(source, root, options)
                convert.assert_not_called()
            self.assertEqual(source.read_bytes(), b'unchanged')
            self.assertEqual(list(root.iterdir()), [source])

    def test_nef_workflow_keeps_neutral_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'photo.nef'; source.write_bytes(b'original')
            raw = root / 'photo.rw2'; options = RenderOptions(photo_style='natural')
            with patch('converter.convert', return_value=(raw, {'verified': True})) as convert, patch.object(Developer, 'render', return_value={'output': 'photo.jpg'}) as render:
                result = Developer().render_file(source, root, options, profile='daylight')
                self.assertEqual(convert.call_args.kwargs['lens_policy'], 'neutral')
                self.assertEqual(convert.call_args.kwargs['mode'], 'daylight')
                self.assertEqual(render.call_args.args[:2], (raw, root/'photo.jpg'))
                self.assertFalse(render.call_args.args[2].lens_correction)
                self.assertEqual(render.call_args.args[2].photo_style, 'natural')
                self.assertTrue(options.lens_correction)
                self.assertTrue(result['conversion']['verified'])

    def test_reopened_neutral_rw2_requires_matching_content_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'renamed.RW2'
            options = RenderOptions()
            sidecar = source.with_suffix('.json')
            report = dict(converter='Zf2Lumix', output_sha256='actual', lens_policy='neutral')
            sidecar.write_text(json.dumps(report))
            effective, reason = _effective_lens_options(source, 'actual', options)
            self.assertFalse(effective.lens_correction)
            self.assertEqual(reason, 'verified-neutral-conversion')
            for value in (dict(report, output_sha256='stale'), dict(report, lens_policy='template'),
                          dict(report, converter='other'), []):
                sidecar.write_text(json.dumps(value))
                self.assertEqual(_effective_lens_options(source, 'actual', options), (options, None))
            sidecar.write_text('invalid')
            self.assertEqual(_effective_lens_options(source, 'actual', options), (options, None))
            sidecar.unlink()
            self.assertEqual(_effective_lens_options(source, 'actual', options), (options, None))

    def test_existing_jpeg_stops_before_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'photo.nef'; source.write_bytes(b'original')
            destination = root/'photo.jpg'; destination.write_bytes(b'keep')
            with patch('converter.convert') as convert:
                with self.assertRaises(FileExistsError): Developer().render_file(source, root)
                convert.assert_not_called()
            self.assertEqual(destination.read_bytes(), b'keep')

    def test_missing_style_assets_do_not_invent_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(Developer(directory).styles(), [])


if __name__ == '__main__': unittest.main()
