#!/usr/bin/env python3
"""Generate the POC test documents using only the Python standard library.

Outputs (written next to this script):
  sample_with_image.docx - two text paragraphs with a 400x300 PNG embedded
                           between them (a real OOXML inline drawing).
  sample_scanned.pdf     - a one-page PDF with NO text layer; the page content
                           is a single embedded 400x300 image XObject
                           (FlateDecode raw RGB), i.e. a "scanned" document.

Both files embed the same deterministic PNG/pixel pattern so the image the
mock VLM receives can be matched by size/hash.
"""

import os
import struct
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH, HEIGHT = 400, 300


def make_pixels():
    """A deterministic RGB test pattern: colored quadrants + border + stripes."""
    rows = []
    for y in range(HEIGHT):
        row = bytearray()
        for x in range(WIDTH):
            if x < 8 or x >= WIDTH - 8 or y < 8 or y >= HEIGHT - 8:
                r, g, b = 20, 20, 20  # dark border
            elif (x // 25 + y // 25) % 2 == 0:
                r, g, b = (220, 60, 60) if x < WIDTH // 2 else (60, 60, 220)
            else:
                r, g, b = (250, 210, 60) if y < HEIGHT // 2 else (60, 200, 90)
            row += bytes((r, g, b))
        rows.append(bytes(row))
    return rows


def make_png(rows):
    def chunk(tag, data):
        payload = tag + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))

    raw = b"".join(b"\x00" + row for row in rows)  # filter type 0 per scanline
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def make_docx(png_bytes, path):
    # EMU sizing: 9525 EMU per pixel at 96 DPI.
    cx, cy = WIDTH * 9525, HEIGHT * 9525
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/image1.png"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>"
        "<w:p><w:r><w:t>This paragraph appears BEFORE the embedded image. "
        "The quick brown fox jumps over the lazy dog.</w:t></w:r></w:p>"
        "<w:p><w:r><w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:docPr id="1" name="Picture 1" descr="POC test pattern"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="1" name="image1.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/>"
        f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline>"
        "</w:drawing></w:r></w:p>"
        "<w:p><w:r><w:t>This paragraph appears AFTER the embedded image. "
        "Sphinx of black quartz, judge my vow.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("word/media/image1.png", png_bytes)


def make_pdf(rows, path):
    """One-page PDF whose only content is an embedded RGB image XObject."""
    rgb = b"".join(rows)
    compressed = zlib.compress(rgb, 9)
    page_w, page_h = 612, 792

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /XObject << /Im1 4 0 R >> /ProcSet [/PDF /ImageC] >> "
        b"/Contents 5 0 R >>"
    )
    objects.append(
        b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
        b"/Length %d >>\nstream\n" % (WIDTH, HEIGHT, len(compressed))
        + compressed
        + b"\nendstream"
    )
    # Draw the image scaled to fill most of the page (no text operators at all).
    content = b"q\n500 0 0 375 56 208 cm\n/Im1 Do\nQ\n"
    objects.append(
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref_pos)
    )
    with open(path, "wb") as fh:
        fh.write(bytes(out))


def main():
    rows = make_pixels()
    png = make_png(rows)
    png_path = os.path.join(HERE, "embedded_image.png")
    with open(png_path, "wb") as fh:
        fh.write(png)
    make_docx(png, os.path.join(HERE, "sample_with_image.docx"))
    make_pdf(rows, os.path.join(HERE, "sample_scanned.pdf"))
    print(f"wrote embedded_image.png       ({len(png)} bytes, reference copy of the embedded PNG)")
    print("wrote sample_with_image.docx   (text + embedded PNG)")
    print("wrote sample_scanned.pdf       (image-only page, no text layer)")


if __name__ == "__main__":
    main()
