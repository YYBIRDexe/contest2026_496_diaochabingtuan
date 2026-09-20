#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XWD -> PNG（纯 Python）。

设备上没有 ImageMagick，`import`/`convert` 都没有，只有 xwd。
X11 的 XWD 头是 25 个 big-endian uint32 + 窗口名（4 字节对齐）+ ncolors 个颜色表项，
之后才是像素。这里只处理 depth=24 / 32bpp 这一种（X3M 上 xwd 就输出这种）。
"""
import struct
import sys

from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
with open(src, "rb") as fh:
    data = fh.read()

hdr = struct.unpack(">25I", data[:100])
header_size, version = hdr[0], hdr[1]
pixmap_format, depth = hdr[2], hdr[3]
width, height = hdr[4], hdr[5]
bpp, bpl = hdr[11], hdr[12]
ncolors = hdr[19]
red_mask, green_mask, blue_mask = hdr[14], hdr[15], hdr[16]

if depth < 24:
    raise SystemExit("只支持 depth>=24，这个文件是 depth=%d" % depth)

# 像素起点 = 头 + 窗口名（4 字节对齐，至少 4 字节）+ 颜色表。
# 头里的 header_size 字段各版本含义不完全一致，所以直接用「文件必须装得下」反推：
#   pixels_at = len(data) - line * height
line = bpl if bpl else width * ((bpp + 7) // 8)
pixels_at = len(data) - line * height
if pixels_at < header_size:
    # 兜底：按头部字段算
    name = data[header_size:]
    nul = name.find(b"\x00")
    name_len = ((nul + 1 + 3) // 4) * 4 if nul >= 0 else 4
    pixels_at = header_size + name_len + ncolors * 12
print("depth=%d %dx%d bpp=%d bpl=%d ncolors=%d pixels@%d 文件%d字节"
      % (depth, width, height, bpp, line, ncolors, pixels_at, len(data)))

need = pixels_at + line * height
if len(data) < need:
    raise SystemExit("文件比声明的短：需要 %d，实际 %d" % (need, len(data)))

img = Image.frombytes("RGBA", (width, height), data[pixels_at:need], "raw", "BGRA")
img.convert("RGB").save(dst)
print("saved", dst, img.size)
