# Third-party components

## Project license scope

The project's original source code is licensed under the MIT License in the repository-root `LICENSE` (copyright notice: Zf2Lumix contributors). Third-party code, fonts and other third-party components retain their own licenses and notices below; the project MIT License does not replace them.

The source selection includes `assets/profiles.json`, the project's sample-fitted color matrices and numeric white-balance references, as project calibration data under MIT. It also includes sanitized RW2 compatibility templates in `assets/templates/`, as described below. This does not grant a license to manufacturer software or other third-party works.

The source release does not include `raw_developer/nr-parameter-curves.json`, original photographs, or manufacturer photo-style/framework resources. These excluded assets are not newly licensed under MIT by the project. Their current local-use provenance and runtime roles remain described below. Selecting MIT for the original source does not replace third-party license obligations or resolve the outstanding provenance review for the RAW development backend.

## Bundled dependencies

These local macOS / Windows bundles include Python, NumPy, Pillow, OpenCV (headless), rawpy/LibRaw, Tcl/Tk, and the PyInstaller bootloader. Package-provided license notices are in `licenses/`; Python and Tcl/Tk notices also accompany their runtime files where supplied. The RAW encoder is independently written, informed by the public RawFormat 8 decoder and metadata interpretation in LibRaw by Alex Tutubalin and contributors.

- rawpy 0.27.1: https://github.com/letmaik/rawpy (MIT). LibRaw 0.22.1: https://github.com/LibRaw/LibRaw (LGPL 2.1 / CDDL alternatives; see supplied LICENSE.LibRaw). LibRaw is dynamically linked; the bundle may be rebuilt with a compatible replacement library.
- NumPy: https://numpy.org/ (BSD and bundled third-party notices).
- Pillow: https://python-pillow.org/ (MIT-CMU and bundled dependency notices).
- OpenCV: https://opencv.org/ (Apache 2.0 and third-party notices).
- ExifTool 13.00 (macOS) / 13.59 (Windows) by Phil Harvey: https://exiftool.org/; distributed under the same terms as Perl (Artistic License or GPL). Its unmodified Perl source is bundled in `vendor/`; each module includes attribution. The macOS system Perl runs version 13.00, with user configuration disabled. The Windows build bundles the official ExifTool 13.59 x64 launcher and complete `exiftool_files` runtime (including Perl and its notices); it does not use a system Perl. User configuration is disabled on both platforms.
- Python: https://www.python.org/ (PSF license).
- Tcl/Tk: https://www.tcl-lang.org/ (BSD-style license).
- PyInstaller: https://pyinstaller.org/ (GPL with bootloader distribution exception).
- LXGW WenKai Mono Regular 1.530 by LXGW: https://github.com/lxgw/LxgwWenKai (SIL Open Font License 1.1; `licenses/fonts/LXGWWenKai-OFL.txt`). Bundled unchanged, loaded only in the application process.
- VT323 by Peter Hull: https://github.com/google/fonts/tree/main/ofl/vt323 (SIL Open Font License 1.1; `licenses/fonts/VT323-OFL.txt`). Bundled unchanged for the display title.
- tkinterdnd2 0.6.1: https://github.com/Eliav2/tkinterdnd2 (MIT); includes TkDND 2.10.1 by George Petasis (permissive Tcl-style license). The native extension matching the build platform is bundled for offline file drops. Notices: `licenses/tkinterdnd2/`.

S5M2 structural templates were derived from the supplied RW2 samples for format compatibility. The release templates contain no donor RAW, preview or thumbnail pixels. They have been reconstructed from referenced metadata spans with donor serial numbers, timestamps, free-text fields, XMP, opaque DataDump and face/location containers removed; unused allocation bytes are zeroed. Generic camera/lens names, format structure, numeric calibration and encoder parameters remain. `template_assets.py` applies this cleaning during private asset preparation. The release manifest pins the cleaned compressed-file hashes so regenerating or changing a template requires reviewing and approving its new hash before export. No manufacturer firmware, photo-style table or executable is included in these templates, and no new license over third-party software is asserted.

No Nikon or Panasonic affiliation or endorsement is implied.

## Local RAW development resources

`raw_developer` contains independently implemented Python/Swift/Metal processing. It reads photo-style resources from the user's installed LUMIX Lab and, for the audited low-ISO path, reads calibration values from a hash-checked data region of TECHOR_FilterKit. It does not load or execute Panasonic's framework or include its executable binaries or Metal library. `raw_developer/nr-parameter-curves.json` contains calibration values derived during local analysis; no new redistribution license is asserted for these data or the manufacturer style resources. These inputs remain local-use resources excluded from the source release. The original software is not affiliated with or endorsing this implementation.
