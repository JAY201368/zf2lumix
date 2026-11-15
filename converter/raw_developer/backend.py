"""Local independent RAW pipeline; manufacturer data are read, never executed.

Photo-style data currently require the installed LUMIX Lab S5M2 resources.
Phone-image equivalence is not established for all styles/scenes; see README.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

import numpy as np
import rawpy

from jpeg_export import export_jpeg
from platform_support import exiftool_command, run_tool
from .cube_lut import read_cube, metal_buffers
from .inspect_raw_metadata import inspect
from .reference_frontend import f32, front_end_params, pack_params
from .reference_raw_state import s5m2_style_policy, s5m2_wb_outputs, style_weight, PRELUT_ADDRESSES, s5m2_cnv2_brightness
from .reference_style import read_psl1
from .reference_tone import tone_curve
from .reference_cnv2 import pack_neutral_params
from .reference_detail import sharpness_factor
from .reference_nr_parameters import normal_raw_nr_buffers
from .reference_chroma import normal_raw_chroma_params
from .reference_lens import distortion_rate, aberration_rates, pack_lens

HERE = Path(__file__).resolve().parent
STYLES = {
    'standard': (1, '标准'), 'vivid': (2, '鲜艳'), 'natural': (3, '自然'),
    'monochrome': (4, '单色'), 'landscape': (5, '风景'), 'portrait': (6, '人像'),
    'l_monochrome': (8, 'L.单色'), '709like': (11, 'Like709'),
    'l_monochrome_d': (13, 'L.单色D'), 'flat': (14, '平坦'), 'vlog': (15, 'V-Log'),
    'cinelike_d2': (16, '电影风格D2'), 'cinelike_v2': (17, '电影风格V2'),
    'l_monochrome_s': (18, 'L.单色S'), 'l_classicneo': (19, 'L.经典Neo'),
    'leica_monochrome': (20, 'LEICA单色'),
}
FRAMEWORK_SHA = '73eacb857a1c722226a1e1ff8c7c6af5b6535e4e64d0e363a1a6236a081fadc6'


@dataclass(frozen=True)
class LUTLayer:
    path: Path
    strength: float = 1.0


@dataclass(frozen=True)
class RenderOptions:
    photo_style: str = 'standard'
    luts: tuple[LUTLayer, ...] = field(default_factory=tuple)
    sharpness: float = 50.0
    noise_reduction: float = 50.0
    lens_correction: bool = True
    jpeg_quality: int = 95


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _effective_lens_options(source, source_hash, options):
    """Only a content-matching converter audit may override donor lens flags."""
    sidecar = source.with_suffix('.json')
    try:
        report = json.loads(sidecar.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return options, None
    if (isinstance(report, dict) and report.get('converter') == 'Zf2Lumix'
            and report.get('output_sha256') == source_hash
            and report.get('lens_policy') == 'neutral'):
        return replace(options, lens_correction=False), 'verified-neutral-conversion'
    return options, None


def _validate_options(options):
    if options.photo_style not in STYLES:
        raise ValueError('Unknown photo style: ' + str(options.photo_style))
    if len(options.luts) > 2:
        raise ValueError('At most two LUT layers are supported')
    for value in (options.sharpness, options.noise_reduction):
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError('Detail controls must be within 0–100')
    for layer in options.luts:
        if not math.isfinite(layer.strength) or not 0 <= layer.strength <= 1:
            raise ValueError('Each LUT strength must be within 0–1')
    if isinstance(options.jpeg_quality, bool) or not isinstance(options.jpeg_quality, int) or not 1 <= options.jpeg_quality <= 100:
        raise ValueError('JPEG quality must be within 1–100')
    for layer in options.luts:
        read_cube(layer.path)


class Developer:
    """Synchronous backend API suitable for an APP's existing worker thread."""
    def __init__(self, bundle='/Applications/LUMIX Lab.app/Wrapper/LUMIXLab.app', *, cache=None):
        self.bundle = Path(bundle)
        self.cache = Path(cache) if cache else Path.home() / 'Library/Caches/Zf2Lumix/raw-developer'

    def styles(self):
        """Available named styles; absence is explicit, never a fallback filter."""
        directory = self.bundle / 'photoStyleLUT/S5M2'
        return [dict(id=name, name=title) for name, (_, title) in STYLES.items()
                if all((directory / f'lut_{name}{suffix}.bin').is_file() for suffix in ('', '_low', '_high'))]

    def _runner(self):
        if sys.platform != 'darwin':
            raise RuntimeError('Independent RAW rendering currently requires macOS Metal')
        bundled = HERE / 'raw-developer-runner'
        if bundled.is_file():
            return bundled
        compiler = shutil.which('swiftc')
        if not compiler:
            raise RuntimeError('RAW renderer is not built; install the developer tools or build the bundled runner')
        source = HERE / 'runner.swift'
        destination = self.cache / ('runner-' + _sha(source)[:20])
        if destination.is_file():
            return destination
        self.cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='compile-', dir=self.cache) as directory:
            temporary = Path(directory) / 'runner'
            run = subprocess.run([compiler, str(source), '-O', '-o', str(temporary)], capture_output=True, text=True)
            if run.returncode:
                raise RuntimeError('Cannot build RAW renderer: ' + run.stderr)
            os.replace(temporary, destination)
        return destination

    def render(self, source, destination, options=None, *, progress=None):
        """Develop one RW2, apply selected style and 0–2 LUTs, publish JPEG.

        Returns an audit dictionary. No source or existing output is modified.
        Progress receives short stage names; no GUI is accessed from here.
        """
        options = options or RenderOptions()
        source = Path(source).expanduser().resolve(strict=True)
        destination = Path(destination).expanduser().absolute()
        if source.suffix.lower() != '.rw2':
            raise ValueError('The developer accepts RW2; convert NEF with the existing converter first')
        _validate_options(options)
        if destination.suffix.lower() not in ('.jpg', '.jpeg') or not destination.parent.is_dir():
            raise ValueError('Choose a JPEG filename in an existing output directory')
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        notify = progress or (lambda stage: None)
        notify('读取 RAW 与格调')
        metadata = inspect(source)
        options, lens_policy = _effective_lens_options(source, metadata['sha256'], options)
        tags = metadata['root_ifd']
        def tag(number, default=None):
            entry = next((v for k, v in tags.items() if k.startswith(f'0x{number:04x} ')), None)
            return default if entry is None else entry['value']
        if tag(0x110) != 'DC-S5M2':
            raise ValueError('This renderer currently requires S5M2-compatible RW2 metadata')
        home = Path(getattr(sys, '_MEIPASS', HERE.parent))
        read = run_tool(exiftool_command(home) + ['-config', '', '-j', '-n', '-PhotoStyle', str(source)], capture_output=True, timeout=45)
        if read.returncode:
            raise ValueError('Cannot read RAW photo-style metadata: ' + read.stderr)
        source_style = json.loads(read.stdout)[0].get('PhotoStyle')
        if not isinstance(source_style, int) or not 0 <= source_style <= 27:
            raise ValueError('Missing or unsupported source photo-style metadata')
        iso = int(tag(0x37))
        target_id = STYLES[options.photo_style][0]
        policy = s5m2_style_policy(iso, source_style, target_id)
        _, weight = style_weight(ctemp_tag=tag(0x11c))
        directory = self.bundle / 'photoStyleLUT/S5M2'
        paths = [directory / f'lut_{options.photo_style}{suffix}.bin' for suffix in ('', '_low', '_high')]
        gamma, low, high = [read_psl1(path) for path in paths]
        if gamma.kind != 0 or low.kind != 1 or high.kind != 1:
            raise ValueError('Photo-style resources have incorrect roles')
        correction = np.asarray(low.values, dtype=np.float32) * np.float32(1 - weight) + np.asarray(high.values, dtype=np.float32) * np.float32(weight)
        tone = (0., 1.)
        if policy['valid_tone_correct']:
            binary = self.bundle / 'Frameworks/TECHOR_FilterKit.framework/TECHOR_FilterKit'
            if _sha(binary) != FRAMEWORK_SHA:
                raise ValueError('Low-ISO calibration source changed; re-audit its layout before rendering')
            offset = PRELUT_ADDRESSES[policy['prelut_iso_name']] + 196 * target_id
            with binary.open('rb') as stream:
                stream.seek(offset)
                values = struct.unpack('<98H', stream.read(196))
            tone = tone_curve(values[:49], values[49:])
        layers = [(read_cube(layer.path), layer.strength) for layer in options.luts]
        lut_audit = [dict(path=str(Path(layer.path).resolve()), strength=layer.strength, sha256=_sha(layer.path)) for layer in options.luts]
        wr, wb, _, green_gain = s5m2_wb_outputs(iso, source_style, tuple(tag(i) for i in (36, 37, 38)), tuple(tag(i) for i in (24, 25, 26)))
        maxima = tuple(tag(i) for i in (14, 15, 16))
        maximum = int(maxima[1])
        if maximum != 16383:
            raise ValueError('Only the audited 14-bit S5M2 RAW scale is currently supported')
        runner = self._runner()
        with tempfile.TemporaryDirectory(prefix='zf2lumix-render-') as temporary:
            root = Path(temporary)
            notify('解包 RAW')
            with rawpy.imread(str(source)) as raw:
                if raw.raw_pattern is None or bytes(raw.color_desc[i] for i in raw.raw_pattern.flatten()) != b'RGGB':
                    raise ValueError('Only RGGB RAW mosaics are supported')
                height, width = raw.raw_image.shape
                crop = raw.sizes._asdict()
                np.maximum(raw.raw_image.astype(np.int32) - int(tag(29)), 0).astype('<u2').tofile(root / 'input')
            if crop['crop_width'] <= 0 or crop['crop_height'] <= 0:
                raise ValueError('RAW has no valid output crop')
            def put(name, data):
                (root / name).write_bytes(data)
            def floats(name, values):
                np.asarray(values, dtype='<f4').tofile(root / name)
            put('size', struct.pack('<2I', width, height))
            put('front', pack_params(front_end_params(wr, wb, (0, 0, 0), maxima, policy['valid_tone_correct'])))
            put('demosaic', struct.pack('<3fI', 819., f32(math.log(819)), f32((f32(math.log(17199)) - f32(math.log(819))) / 4095), 0))
            put('color', pack_neutral_params(pixel_max=maximum, brightness=s5m2_cnv2_brightness(1., green_gain), wb_r=1., wb_b=1., style_enabled=True,
                                            tone_enabled=bool(policy['valid_tone_correct']), valid_ycc=True, vlog_clip=policy['vlog_clip']))
            floats('gamma', gamma.values)
            cube = correction.reshape(-1, 3)
            floats('style_cube', np.column_stack((cube, np.zeros(len(cube), dtype=np.float32))))
            floats('tone', tone)
            put('chroma', struct.pack('<3f4i', *normal_raw_chroma_params()))
            nr_buffers, nr_info = normal_raw_nr_buffers(iso, options.noise_reduction)
            for name, data in nr_buffers.items():
                put('nr_' + name, data)
            put('sharp', struct.pack('<2f', 4095., sharpness_factor(options.sharpness)))
            lut_params, first, second = metal_buffers(layers, output_max=maximum)
            for name, data in (('lut_params', lut_params), ('lut_first', first), ('lut_second', second)):
                put(name, data)
            jobs = []
            previous = 'input'
            def job(name, kernel, buffers, channels=3, output_index=1):
                nonlocal previous
                jobs.append(dict(name=name, kernel='recovered' + kernel, buffers=buffers,
                                 output=name, outputBufferIndex=output_index, outputBytes=width * height * channels * 2,
                                 pixels=width * height, gridWidth=width, gridHeight=height))
                previous = name
            # FrontEnd uses a linear thread index; the other kernels use uint2.
            job('front_out', 'FrontEnd', [previous, '', 'front', 'size'], 1)
            jobs[-1].pop('gridWidth'); jobs[-1].pop('gridHeight')
            for name, count in (('PreProcess', 7), ('FirstProcess', 3), ('SecondProcess', 3)):
                job(name, name, [previous, '', 'demosaic', 'size'], count)
            job('styled', 'Cnv2Neutral', [previous, '', 'color', 'size', 'gamma', 'style_cube', 'tone'])
            original = previous
            job('chroma_h', 'ChromaH', [previous, '', 'chroma', 'size'])
            job('chroma_v', 'ChromaV', [previous, '', 'chroma', 'size'])
            job('chroma_out', 'ChromaFinish', [previous, original, '', 'chroma', 'size'], output_index=2)
            for name, count in (('First', 7), ('Second', 11), ('HLPF', 10), ('Third', 10), ('Fourth', 12), ('Fifth', 3)):
                buffers = [previous, '', 'nr_' + name.lower()]
                if name in ('Second', 'Fifth'):
                    buffers += ['nr_weightsL', 'nr_weightsC']
                job('nr_out_' + name, 'NR' + name, buffers + ['size'], count)
            if options.sharpness > 0:
                job('sharp_pre', 'SharpPre', [previous, '', 'sharp', 'size'], 6)
                job('sharp_out', 'Sharp', [previous, '', 'sharp', 'size'])
            job('lut_out', 'FileLUT', [previous, '', 'lut_params', 'size', 'lut_first', 'lut_second'])
            lens = {}
            if options.lens_correction:
                ca = tag(0x11b)
                if ca and bytes.fromhex(ca['hex'])[29] == 1:
                    red, blue = aberration_rates(bytes.fromhex(ca['hex']), width, height)
                    floats('ca_red', red); floats('ca_blue', blue)
                    parameters = bytearray(pack_lens(width, height, pixel_max=maximum))
                    struct.pack_into('<i', parameters, 44, 1); put('ca', parameters)
                    job('ca_out', 'LensA', [previous, '', 'ca', 'size', 'ca_red', 'ca_blue'])
                    lens['aberration'] = True
                distortion = tag(0x119)
                if distortion and bytes.fromhex(distortion['hex'])[14] == 1:
                    values = struct.unpack('<16h', bytes.fromhex(distortion['hex']))
                    floats('rates', distortion_rate([values[i] for i in (5, 8, 4, 11)]))
                    put('lens', pack_lens(width, height, pixel_max=maximum))
                    job('lens_out', 'LensD', [previous, '', 'lens', 'size', 'rates'])
                    lens['distortion'] = True
            put('jobs.json', json.dumps(jobs).encode())
            metal_source = '\n'.join((HERE / f'reference_{name}.metal').read_text() for name in ('frontend', 'demosaic', 'color', 'chroma', 'nr', 'sharp', 'lens', 'lut'))
            put('pipeline.metal', metal_source.encode())
            notify('显影、格调与 LUT')
            run = subprocess.run([str(runner), '-', str(root), str(root / 'pipeline.metal'), '--prune-intermediates'], capture_output=True, text=True)
            if run.returncode:
                raise RuntimeError('RAW GPU processing failed: ' + run.stderr)
            pixels = np.memmap(root / previous, dtype='<u2', mode='r', shape=(height, width, 3))
            x, y = crop['crop_left_margin'], crop['crop_top_margin']
            cw, ch = crop['crop_width'], crop['crop_height']
            if x < 0 or y < 0 or x + cw > width or y + ch > height:
                raise ValueError('RAW crop falls outside the decoded image')
            if _sha(source) != metadata['sha256']:
                raise RuntimeError('Source changed during rendering; no JPEG was published')
            notify('保存 JPG')
            output = export_jpeg(pixels[y:y + ch, x:x + cw, ::-1], destination, pixel_max=maximum,
                                 orientation=tag(0x112, 1), quality=options.jpeg_quality)
            del pixels
        return dict(source=str(source), source_sha256=metadata['sha256'], output=str(output), output_sha256=_sha(output),
                    photo_style=options.photo_style, luts=lut_audit, iso=iso, policy=policy, style_high_weight=weight,brightness=s5m2_cnv2_brightness(1.,green_gain),
                    detail=dict(sharpness=options.sharpness, noise_reduction=nr_info), lens=lens, lens_policy=lens_policy, lens_correction_enabled=options.lens_correction, crop=crop,
                    resources={str(p): _sha(p) for p in paths}, gpu=run.stdout.strip(),
                    limitations=['Phone equivalence not established across all inputs/styles', 'Low-ISO phone references not yet supplied',
                                 'Lens active-rectangle lifecycle and final export scale still under verification'])

    def render_file(self, source, output_directory, options=None, *, profile='auto', progress=None):
        """NEF→RW2→JPEG or RW2→JPEG, using the existing neutral converter.

        A successfully converted RW2 remains available if later development
        fails. Existing files and input photos are never replaced.
        """
        source = Path(source).expanduser().resolve(strict=True)
        output_directory = Path(output_directory).expanduser().absolute()
        if not output_directory.is_dir():
            raise ValueError('Choose an existing output directory')
        destination = output_directory / (source.stem + '.jpg')
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        _validate_options(options or RenderOptions())
        conversion = None
        if source.suffix.lower() == '.nef':
            from converter import convert
            rw2, conversion = convert(source, output_directory, mode=profile,
                                      lens_policy='neutral', status=progress or (lambda stage: None))
            options = replace(options or RenderOptions(), lens_correction=False)
        elif source.suffix.lower() == '.rw2':
            rw2 = source
        else:
            raise ValueError('Choose a Nikon Zf NEF or S5M2-compatible RW2')
        result = self.render(rw2, destination, options, progress=progress)
        if conversion is not None:
            result['conversion'] = conversion
            result['nef_source'] = str(source)
        return result
