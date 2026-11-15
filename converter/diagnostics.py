"""Frozen-app smoke test with an explicit JSON result (no console required)."""
import json
import sys
from pathlib import Path
import tempfile
import traceback
from platform_support import encoder_path, exiftool_command, run_tool


def self_test(report_path):
    from converter import HOME, VERSION
    result = {'version': VERSION, 'checks': {}, 'ok': False}
    try:
        import tkinter as tk
        from app import Application, create_root
        from retro_ui import register_fonts
        register_fonts()
        root = create_root()
        try:
            root.withdraw()
            app = Application(root)
            root.update()
            result['checks']['native_drop'] = root.TkdndVersion
            if not root.tk.call('bind', str(app.film), '<<Drop>>'):
                raise RuntimeError('Photo strip is not registered for native file drops')
            result['checks']['fonts'] = app.fonts
            if sys.platform == 'darwin':
                if app.fonts['body'] != 'Heiti SC' or app.fonts['mono'] != 'Menlo':
                    raise RuntimeError('Console interface fonts were not selected')
        finally:
            if 'app' in locals():
                app.close()
            else:
                root.destroy()
        result['checks']['gui'] = True
        for asset in ['assets/profiles.json', 'assets/templates/daylight_800.prefix.z', '使用说明.html']:
            if not (HOME/asset).is_file():
                raise FileNotFoundError(asset)
        result['checks']['assets'] = True
        proc = run_tool(exiftool_command(HOME)+['-config', '', '-ver'], capture_output=True, timeout=45)
        if proc.returncode or not proc.stdout.strip():
            raise RuntimeError('ExifTool: '+proc.stderr)
        result['checks']['exiftool_version'] = proc.stdout.strip()
        with tempfile.TemporaryDirectory(prefix='Zf2Lumix 中文 ') as td:
            td = Path(td)
            (td/'测试.u16').write_bytes(b'\x00\x02'*4)
            (td/'表.txt').write_text(''.join(f'5 {i}\n' for i in range(17)))
            proc = run_tool([str(encoder_path(HOME)), str(td/'测试.u16'), '2', '2', '0', '2',
                str(td/'表.txt'), str(td/'结果.bin'), str(td/'结果.bits')], capture_output=True, timeout=30)
            if proc.returncode:
                raise RuntimeError('Encoder: '+proc.stderr)
            # Four 512 samples: each has category 10, 5 Huffman bits + 10 data bits.
            if (td/'结果.bits').read_text().strip() != '60' or len((td/'结果.bin').read_bytes()) != 16:
                raise RuntimeError('Encoder smoke-test payload mismatch')
        result['checks']['unicode_encoder'] = True
        result['ok'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
