"""Remove donor-specific metadata without relocating RW2 compatibility fields.

Only referenced directory/payload bytes survive. Preview/RAW pointers in the
prefix are placeholders rewritten by assemble(); no donor pixels are copied.
"""
import struct

from rw2 import IFD, root

STANDARD_PRIVATE = {0x02bc, 0x83bb, 0x8649, 0x8773, 0x9286, 0xc65d}
MAKER_PRIVATE = {
    0x21, 0x25, 0x29, 0x2b, 0x36, 0x3a, 0x3f, 0x4d, 0x4e,
    0x52, 0x54, 0x61, 0x63, *range(0x65, 0x72), *range(0x80, 0x86),
    0x8c, 0x8d, 0x8e, 0x90, 0x91, 0x2003, 0x8008,
}


def _clean(data, base, *, prefix=False):
    original = bytearray(data)
    clean = bytearray(len(original))
    visited = set()

    def copy(start, size):
        if start < 0 or start + size > len(original):
            raise ValueError('Template metadata payload is outside its allocation')
        clean[start:start + size] = original[start:start + size]

    def directory(start, kind='standard'):
        if start in visited:
            raise ValueError('Cyclic template metadata directory')
        visited.add(start)
        d = IFD(original, start, base)
        # Panasonic MakerNote directories have no next-IFD word.
        copy(start, 2 + 12 * len(d.tags) + (0 if kind == 'maker' else 4))
        if 0x8825 in d.tags and kind != 'maker':
            raise ValueError('Unexpected GPS directory: audit this new template before release')
        for tag, (entry, typ, count, position, size) in d.tags.items():
            if prefix and start == root(original, base).start and tag in (0x2e, 0x127):
                # External previews are absent in the compact prefix.
                continue
            if kind != 'maker' and tag in (0x8769, 0xa005):
                directory(base + d.get(tag), 'interop' if tag == 0xa005 else 'standard')
                continue
            if kind != 'maker' and tag == 0x927c:
                if original[position:position + 12] != b'Panasonic\0\0\0':
                    raise ValueError('Unsupported template MakerNote')
                copy(position, 12)
                directory(position + 12, 'maker')
                continue
            private = tag in (MAKER_PRIVATE if kind == 'maker' else STANDARD_PRIVATE)
            # Retain only generic camera/lens names and the interoperability ID.
            if typ == 2:
                allowed = {0x51} if kind == 'maker' else ({1} if kind == 'interop' else {0x10f, 0x110})
                private = private or tag not in allowed
            # Embedded thumbnail storage must stay available for new NEF previews.
            if kind == 'thumbnail' and tag == 0x201:
                thumb = base + d.get(tag)
                length = d.get(0x202)
                if thumb < 0 or thumb + length > len(clean):
                    raise ValueError('Invalid template thumbnail allocation')
            if private:
                if position < 0 or position + size > len(clean):
                    raise ValueError('Invalid private template payload')
                clean[position:position + size] = b'\0' * size
                if typ in (5, 10):
                    for index in range(count):
                        struct.pack_into('<I', clean, position + 8 * index + 4, 1)
            else:
                copy(position, size)
        if kind != 'maker' and d.next:
            directory(base + d.next, 'thumbnail')

    first = root(original, base).start
    # RW2 has a fixed 16-byte format signature between its TIFF header and IFD.
    copy(0, first)
    directory(first)
    return clean


def sanitize_templates(prefix, exif):
    """Return same-length, offset-stable templates with donor metadata removed."""
    if not exif.startswith(b'Exif\0\0'):
        raise ValueError('Invalid EXIF template header')
    return _clean(prefix, 0, prefix=True), _clean(exif, 6)
