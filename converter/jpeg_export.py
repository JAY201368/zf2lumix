"""Safe sRGB JPEG publication for the independent RAW development backend.

Input is already developed, display-encoded RGB, not Bayer or linear RGB.
This module does not choose a photo style or silently develop RAW files.
"""
from pathlib import Path
import os
import tempfile

import numpy as np
from PIL import Image, ImageCms


def export_jpeg(rgb, destination, *, pixel_max=255, orientation=1, quality=95):
    """Encode, verify, and publish without replacing an existing file.

    Accept uint8/uint16 RGB with an explicit code maximum. Apply EXIF
    orientation physically, then mark orientation 1. Embed sRGB and encode
    4:4:4 chroma. A same-directory temporary file is atomically hard-linked
    into place, matching the converter's no-overwrite publication policy.
    Returns the absolute destination Path.
    """
    pixels = np.asarray(rgb)
    if pixels.dtype not in (np.dtype('uint8'), np.dtype('uint16')):
        raise ValueError('JPEG input must be uint8 or uint16 RGB')
    if pixels.ndim != 3 or pixels.shape[2] != 3 or not all(pixels.shape[:2]):
        raise ValueError('JPEG input must be a nonempty H×W×3 RGB image')
    if isinstance(pixel_max, bool) or not isinstance(pixel_max, int) or not 1 <= pixel_max <= np.iinfo(pixels.dtype).max:
        raise ValueError('Invalid input code maximum')
    if pixels.max() > pixel_max:
        raise ValueError('Input exceeds the declared code maximum')
    if isinstance(orientation, bool) or not isinstance(orientation, int) or orientation not in range(1, 9):
        raise ValueError('EXIF orientation must be 1–8')
    if isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100:
        raise ValueError('JPEG quality must be 1–100')
    destination = Path(destination).expanduser().absolute()
    if destination.suffix.lower() not in ('.jpg', '.jpeg'):
        raise ValueError('JPEG destination must end in .jpg or .jpeg')
    # lexists also rejects a dangling destination symlink.
    if os.path.lexists(destination):
        raise FileExistsError(destination)
    if not destination.parent.is_dir():
        raise FileNotFoundError(destination.parent)
    if pixels.dtype != np.uint8 or pixel_max != 255:
        pixels = np.rint(pixels.astype(np.float32) * np.float32(255 / pixel_max)).astype(np.uint8)
    image = Image.fromarray(pixels)
    transpose = {
        2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }.get(orientation)
    if transpose is not None:
        image = image.transpose(transpose)
    exif = Image.Exif()
    exif[274] = 1
    exif[34665] = {40961: 1}  # ExifIFD ColorSpace = sRGB
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.zf2lumix-jpeg-', suffix='.tmp', dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            image.save(stream, format='JPEG', quality=quality, subsampling=0,
                       icc_profile=profile, exif=exif)
            stream.flush()
            os.fsync(stream.fileno())
        with Image.open(temporary) as check:
            check.load()
            if check.format != 'JPEG' or check.mode != 'RGB' or check.size != image.size:
                raise OSError('JPEG read-back validation failed')
            if check.info.get('icc_profile') != profile or check.getexif().get(274) != 1:
                raise OSError('JPEG color/orientation validation failed')
        # Fail safely on collisions (including a concurrent publisher) or a
        # filesystem that cannot provide no-overwrite hard-link publication.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        image.close()
    return destination
