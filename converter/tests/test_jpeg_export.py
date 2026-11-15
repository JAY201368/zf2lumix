import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch

import numpy as np
from PIL import Image, JpegImagePlugin
from jpeg_export import export_jpeg


class JPEGExportTests(unittest.TestCase):
    def test_orientation_and_color(self):
        pixels = np.zeros((12, 24, 3), dtype=np.uint16)
        pixels[:, :12, 0] = 16383
        pixels[:, 12:, 2] = 16383
        before = pixels.copy()
        with tempfile.TemporaryDirectory() as directory:
            path = export_jpeg(pixels, Path(directory) / 'test.jpg', pixel_max=16383, orientation=6, quality=100)
            with Image.open(path) as im:
                self.assertEqual(im.size, (12, 24))
                self.assertEqual(im.getexif().get(274), 1)
                self.assertEqual(im.getexif().get_ifd(34665)[40961], 1)
                self.assertGreater(len(im.info['icc_profile']), 100)
                self.assertEqual(JpegImagePlugin.get_sampling(im), 0)
                actual = np.asarray(im)
                self.assertGreater(actual[3, 6, 0], 250)
                self.assertGreater(actual[20, 6, 2], 250)
            np.testing.assert_array_equal(pixels, before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_no_overwrite_including_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.jpg'
            path.write_bytes(b'original')
            pixels = np.zeros((2, 2, 3), dtype=np.uint8)
            with self.assertRaises(FileExistsError): export_jpeg(pixels, path)
            self.assertEqual(path.read_bytes(), b'original')
            dangling = Path(directory) / 'link.jpg'
            dangling.symlink_to(Path(directory) / 'missing.jpg')
            with self.assertRaises(FileExistsError): export_jpeg(pixels, dangling)
            self.assertTrue(dangling.is_symlink())

    def test_publication_failure_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.jpg'
            with patch('jpeg_export.os.link', side_effect=OSError('unsupported')):
                with self.assertRaises(OSError): export_jpeg(np.zeros((2, 2, 3), dtype=np.uint8), path)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_input_has_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.jpg'
            for pixels, kwargs in ((np.zeros((2, 2), dtype=np.uint8), {}),
                                   (np.zeros((2, 2, 3), dtype=np.float32), {}),
                                   (np.full((2, 2, 3), 256, dtype=np.uint16), {}),
                                   (np.zeros((2, 2, 3), dtype=np.uint8), {'orientation': 0})):
                with self.assertRaises(ValueError): export_jpeg(pixels, path, **kwargs)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__': unittest.main()
