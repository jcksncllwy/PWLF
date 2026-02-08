"""
Generate a rest positions texture from a .ply gaussian splat file.

Outputs a 1024x1024 raw binary file of float32 RGBA pixels.
Each pixel stores one splat's world position (R=X, G=Y, B=Z, A=valid flag).
Pixel at (x, y) = splat index y * 1024 + x.

Load in TouchDesigner with: Movie File In TOP
  - File: rest_positions.raw
  - Pixel Format: 32-bit float (RGBA)
  - Resolution: 1024x1024
  - OR use a Script TOP with numpy to load the .npy variant

Usage:
    python generate_rest_positions.py -i input.ply -o rest_positions
    (generates rest_positions.raw and rest_positions.npy)
"""

import struct
import argparse
import numpy as np

TEX_SIZE = 1024
TOTAL_PIXELS = TEX_SIZE * TEX_SIZE


def read_ply_positions(filepath):
    """Read vertex positions from a binary little-endian PLY file."""
    positions = []

    with open(filepath, 'rb') as f:
        # Parse header
        line = f.readline().decode('ascii').strip()
        if line != 'ply':
            raise ValueError(f"Not a PLY file: {filepath}")

        num_vertices = 0
        properties = []
        in_vertex_element = False

        while True:
            line = f.readline().decode('ascii').strip()
            if line == 'end_header':
                break
            if line.startswith('element vertex'):
                num_vertices = int(line.split()[-1])
                in_vertex_element = True
            elif line.startswith('element '):
                in_vertex_element = False
            elif line.startswith('property') and in_vertex_element:
                parts = line.split()
                prop_type = parts[1]
                prop_name = parts[2]
                properties.append((prop_name, prop_type))

        # Build struct format for one vertex
        type_map = {'float': 'f', 'double': 'd', 'uchar': 'B', 'int': 'i', 'short': 'h'}
        vertex_format = '<'
        x_idx = y_idx = z_idx = -1

        for i, (name, ptype) in enumerate(properties):
            fmt_char = type_map.get(ptype)
            if fmt_char is None:
                raise ValueError(f"Unknown property type: {ptype}")
            vertex_format += fmt_char
            if name == 'x':
                x_idx = i
            elif name == 'y':
                y_idx = i
            elif name == 'z':
                z_idx = i

        if -1 in (x_idx, y_idx, z_idx):
            raise ValueError("PLY file missing x, y, or z properties")

        vertex_size = struct.calcsize(vertex_format)

        # Read all vertices
        for _ in range(num_vertices):
            data = f.read(vertex_size)
            if len(data) < vertex_size:
                break
            vertex = struct.unpack(vertex_format, data)
            positions.append((vertex[x_idx], vertex[y_idx], vertex[z_idx]))

    return positions


def generate_texture(positions, output_path):
    """Write positions to a 1024x1024 RGBA float32 raw binary file."""
    num_splats = len(positions)
    if num_splats > TOTAL_PIXELS:
        print(f"Warning: {num_splats} splats exceeds {TOTAL_PIXELS} texture capacity. Truncating.")
        num_splats = TOTAL_PIXELS

    # Create RGBA float32 texture (initialized to 0)
    texture = np.zeros((TEX_SIZE, TEX_SIZE, 4), dtype=np.float32)

    for i in range(num_splats):
        x = i % TEX_SIZE
        y = i // TEX_SIZE
        texture[y, x, 0] = positions[i][0]  # R = world X
        texture[y, x, 1] = positions[i][1]  # G = world Y
        texture[y, x, 2] = positions[i][2]  # B = world Z
        texture[y, x, 3] = 1.0              # A = valid flag

    # Save as raw binary (flat RGBA float32, row by row)
    raw_path = output_path + '.raw'
    texture.tofile(raw_path)
    print(f"Wrote {raw_path} ({num_splats} splats, {TEX_SIZE}x{TEX_SIZE}, {texture.nbytes / 1024 / 1024:.1f} MB)")

    # Also save as .npy for easy loading in TD Script TOP via numpy
    npy_path = output_path + '.npy'
    np.save(npy_path, texture)
    print(f"Wrote {npy_path}")

    return num_splats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate rest positions texture from PLY file.")
    parser.add_argument("-i", "--input", required=True, help="Input .ply file")
    parser.add_argument("-o", "--output", default="rest_positions", help="Output path (without extension)")
    args = parser.parse_args()

    print(f"Reading positions from {args.input}...")
    positions = read_ply_positions(args.input)
    print(f"Found {len(positions)} vertices")

    generate_texture(positions, args.output)
