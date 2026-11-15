"""Command-line access to the same backend API available to the desktop APP."""
import argparse
import json
from pathlib import Path
import sys
from .backend import Developer, RenderOptions, LUTLayer, STYLES


def main():
    parser = argparse.ArgumentParser(description='NEF/RW2 → 照片格调 → 双 LUT → JPG')
    parser.add_argument('source', type=Path)
    parser.add_argument('-o', '--output', type=Path, required=True, help='Existing output directory')
    parser.add_argument('--style', choices=STYLES, default='standard')
    parser.add_argument('--lut', action='append', type=Path, default=[])
    parser.add_argument('--strength', action='append', type=float, default=[], help='0..1 per LUT; defaults to 1')
    parser.add_argument('--sharpness', type=float, default=50)
    parser.add_argument('--noise-reduction', type=float, default=50)
    parser.add_argument('--quality', type=int, default=95)
    parser.add_argument('--profile', choices=('auto', 'daylight', 'lowlight'), default='auto', help='NEF conversion profile')
    parser.add_argument('--no-lens-correction', action='store_true')
    parser.add_argument('--bundle', type=Path, default=Path('/Applications/LUMIX Lab.app/Wrapper/LUMIXLab.app'))
    args = parser.parse_args()
    if len(args.lut) > 2 or (args.strength and len(args.lut) != len(args.strength)):
        parser.error('Use at most two --lut options and one --strength per LUT')
    levels = args.strength or [1.] * len(args.lut)
    options = RenderOptions(photo_style=args.style, luts=tuple(LUTLayer(p, s) for p, s in zip(args.lut, levels)),
                            sharpness=args.sharpness, noise_reduction=args.noise_reduction,
                            jpeg_quality=args.quality, lens_correction=not args.no_lens_correction)
    try:
        result = Developer(args.bundle).render_file(args.source, args.output, options, profile=args.profile,
                                                    progress=lambda message: print(message, file=sys.stderr, flush=True))
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
