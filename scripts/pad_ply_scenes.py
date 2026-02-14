"""
Pad and normalize Gaussian splat PLY files for Switch POP blending.

All output files will have:
  1. The same vertex count (padded with transparent filler splats)
  2. The same 14-property format (position, scale, color, opacity, rotation)

Also generates:
  - bounds.json: world-space bounding sphere for each scene (after
    GaussianSplatPOP transform: Rx=180, Ry=180, Scale=10)
  - <filename>.restpos.exr: pre-computed 1024x1024 rest position textures
    (in PLY space, matching the physics system's coordinate space)
    Loadable directly by TD's MovieFileIn TOP — no Script TOP needed.

Reads from:  assets/gallery/*.ply  (+ assets/downloaded/*.ply if present)
Writes to:   assets/gallery_padded/

Usage:
    python pad_ply_scenes.py
"""

import json
import math
import os
import struct

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, '..', 'assets')
GALLERY_DIR = os.path.join(ASSETS_DIR, 'gallery')
DOWNLOAD_DIR = os.path.join(ASSETS_DIR, 'downloaded')
OUTPUT_DIR = os.path.join(ASSETS_DIR, 'gallery_padded')

# Rest position texture size (must match TD's rest_pos_script)
TEX_SIZE = 1024

# GaussianSplatPOP transform: Rx=180, Ry=180, Scale=10
# Combined rotation: (x,y,z) -> (-x, -y, z), then scale by 10
GEO_SCALE = 10.0

# Canonical 14-property format (matches the existing gallery scenes).
# Order matters — this defines the binary layout of every output vertex.
TARGET_PROPERTIES = [
    ('float', 'x'),
    ('float', 'y'),
    ('float', 'z'),
    ('float', 'scale_0'),
    ('float', 'scale_1'),
    ('float', 'scale_2'),
    ('float', 'f_dc_0'),
    ('float', 'f_dc_1'),
    ('float', 'f_dc_2'),
    ('float', 'opacity'),
    ('float', 'rot_0'),
    ('float', 'rot_1'),
    ('float', 'rot_2'),
    ('float', 'rot_3'),
]

TARGET_PROP_NAMES = [name for _, name in TARGET_PROPERTIES]

# Default values for a transparent filler splat
PADDING_DEFAULTS = {
    'x': 0.0, 'y': 0.0, 'z': 0.0,
    'scale_0': -100.0, 'scale_1': -100.0, 'scale_2': -100.0,
    'f_dc_0': 0.0, 'f_dc_1': 0.0, 'f_dc_2': 0.0,
    'opacity': -100.0,
    'rot_0': 1.0, 'rot_1': 0.0, 'rot_2': 0.0, 'rot_3': 0.0,
}


def read_ply_header(filepath):
    """Read just the header of a PLY file. Returns (vertex_count, properties)."""
    with open(filepath, 'rb') as f:
        vertex_count = 0
        properties = []
        while True:
            line = f.readline().decode('ascii', errors='ignore').strip()
            if line.startswith('element vertex'):
                vertex_count = int(line.split()[-1])
            elif line.startswith('property'):
                parts = line.split()
                properties.append((parts[1], parts[2]))
            elif line == 'end_header':
                break
    return vertex_count, properties


def read_ply(filepath):
    """Read a binary little-endian PLY file.
    Returns (vertex_count, properties, vertex_data_bytes)."""
    with open(filepath, 'rb') as f:
        vertex_count = 0
        properties = []
        while True:
            line = f.readline().decode('ascii', errors='ignore').strip()
            if line.startswith('element vertex'):
                vertex_count = int(line.split()[-1])
            elif line.startswith('property'):
                parts = line.split()
                properties.append((parts[1], parts[2]))
            elif line == 'end_header':
                break

        bytes_per_vertex = len(properties) * 4
        vertex_data = f.read(bytes_per_vertex * vertex_count)

    return vertex_count, properties, vertex_data


def needs_conversion(source_properties):
    """Check if source properties differ from the target format."""
    source_names = [name for _, name in source_properties]
    return source_names != TARGET_PROP_NAMES


def extract_positions(vertex_count, properties, vertex_data):
    """Extract xyz positions as an (N, 3) numpy array from raw PLY vertex data."""
    n_props = len(properties)
    src_index = {name: i for i, (_, name) in enumerate(properties)}

    all_floats = np.frombuffer(vertex_data, dtype='<f4').reshape(vertex_count, n_props)

    x = all_floats[:, src_index['x']]
    y = all_floats[:, src_index['y']]
    z = all_floats[:, src_index['z']]

    return np.column_stack([x, y, z])


def compute_bounding_sphere(positions):
    """Compute bounding sphere in world space (after GaussianSplatPOP transform).

    GaussianSplatPOP: Rx=180, Ry=180, Rz=0, Scale=10
    Combined rotation (XYZ order): (x, y, z) -> (-x, -y, z)
    Then scale: (-10x, -10y, 10z)

    Returns (center_x, center_y, center_z, radius) in world space.
    """
    # Centroid in PLY space
    centroid = positions.mean(axis=0)

    # Radius in PLY space
    diffs = positions - centroid
    distances = np.sqrt((diffs * diffs).sum(axis=1))
    radius_ply = float(distances.max())

    # Transform to world space
    cx = float(-GEO_SCALE * centroid[0])
    cy = float(-GEO_SCALE * centroid[1])
    cz = float(GEO_SCALE * centroid[2])
    radius = GEO_SCALE * radius_ply

    return (cx, cy, cz, radius)


def generate_rest_positions(positions, output_path):
    """Generate a 1024x1024 RGBA float32 rest position texture as EXR.

    Stored in PLY space (matching the physics system's coordinate space).
    Indexed by point index (= uniqueID in TD).
    Loadable directly by TD's MovieFileIn TOP.
    """
    max_points = TEX_SIZE * TEX_SIZE
    n = min(len(positions), max_points)

    # Build RGBA float32 image
    pixels = np.zeros((TEX_SIZE, TEX_SIZE, 4), dtype=np.float32)

    for i in range(n):
        x_tex = i % TEX_SIZE
        y_tex = i // TEX_SIZE
        pixels[y_tex, x_tex, 0] = positions[i, 0]
        pixels[y_tex, x_tex, 1] = positions[i, 1]
        pixels[y_tex, x_tex, 2] = positions[i, 2]
        pixels[y_tex, x_tex, 3] = 1.0

    # Flip vertically: OpenCV row 0 = top, but TD textures have row 0 = bottom
    pixels = pixels[::-1]
    # OpenCV treats array as BGR(A) — swap R and B so EXR channel names match TD expectations
    pixels_bgra = pixels[:, :, [2, 1, 0, 3]]
    cv2.imwrite(output_path, pixels_bgra,
                [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT])
    return n


def convert_and_pad(filepath, target_count, output_path):
    """Read a PLY, convert to canonical format, pad to target_count, write output."""
    vertex_count, src_properties, vertex_data = read_ply(filepath)
    src_bytes_per_vertex = len(src_properties) * 4
    do_convert = needs_conversion(src_properties)

    # Build the canonical header
    header_lines = [
        'ply',
        'format binary_little_endian 1.0',
        f'element vertex {target_count}',
    ]
    for prop_type, prop_name in TARGET_PROPERTIES:
        header_lines.append(f'property {prop_type} {prop_name}')
    header_lines.append('end_header')
    header = '\n'.join(header_lines) + '\n'

    # Build a mapping from target property names to source property indices
    src_index_map = {}
    for i, (_, name) in enumerate(src_properties):
        src_index_map[name] = i

    # One transparent padding vertex in the target format
    padding_vertex = b''
    for _, name in TARGET_PROPERTIES:
        padding_vertex += struct.pack('<f', PADDING_DEFAULTS.get(name, 0.0))

    with open(output_path, 'wb') as out:
        out.write(header.encode('ascii'))

        if not do_convert:
            # Same format — write vertex data directly
            out.write(vertex_data)
        else:
            # Convert each vertex from source to target format
            for i in range(vertex_count):
                offset = i * src_bytes_per_vertex
                src_floats = struct.unpack_from(f'<{len(src_properties)}f', vertex_data, offset)

                for _, name in TARGET_PROPERTIES:
                    if name in src_index_map:
                        val = src_floats[src_index_map[name]]
                    else:
                        val = PADDING_DEFAULTS.get(name, 0.0)
                    out.write(struct.pack('<f', val))

        # Append padding vertices
        padding_needed = target_count - vertex_count
        if padding_needed > 0:
            out.write(padding_vertex * padding_needed)

    return vertex_count, padding_needed, do_convert


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Collect PLY files from gallery/ and downloaded/
    source_files = {}  # filename -> filepath

    for src_dir in [GALLERY_DIR, DOWNLOAD_DIR]:
        if not os.path.isdir(src_dir):
            continue
        for f in os.listdir(src_dir):
            if f.lower().endswith('.ply'):
                source_files[f] = os.path.join(src_dir, f)

    if not source_files:
        print("No PLY files found!")
        return

    # Read vertex counts and check formats
    file_info = {}
    print(f"Found {len(source_files)} PLY files:\n")
    for filename in sorted(source_files):
        filepath = source_files[filename]
        count, props = read_ply_header(filepath)
        convert = needs_conversion(props)
        file_info[filename] = (count, convert)
        marker = " [will convert to 14-prop format]" if convert else ""
        print(f"  {filename}: {count:,} vertices ({len(props)} props){marker}")

    max_count = max(count for count, _ in file_info.values())
    print(f"\nMax vertex count: {max_count:,}")
    print(f"Target: {max_count:,} vertices, {len(TARGET_PROPERTIES)} properties each\n")

    bounds = {}

    # Process all files
    for filename in sorted(source_files):
        filepath = source_files[filename]
        output_path = os.path.join(OUTPUT_DIR, filename)
        real_count = file_info[filename][0]

        # 1. Pad and normalize the PLY
        original, padded, converted = convert_and_pad(filepath, max_count, output_path)

        # 2. Extract positions for bounds + rest positions (from original, pre-pad data)
        vertex_count, properties, vertex_data = read_ply(filepath)
        positions = extract_positions(vertex_count, properties, vertex_data)

        # 3. Compute world-space bounding sphere
        sphere = compute_bounding_sphere(positions)
        bounds[filename] = {
            'center': [sphere[0], sphere[1], sphere[2]],
            'radius': sphere[3],
        }

        # 4. Generate rest position texture (.npy)
        restpos_path = os.path.join(OUTPUT_DIR, filename + '.restpos.exr')
        generate_rest_positions(positions, restpos_path)

        parts = []
        if converted:
            parts.append("converted")
        if padded > 0:
            parts.append(f"+{padded:,} padding")
        if not parts:
            parts.append("no changes needed")
        print(f"  {filename}: {original:,} -> {max_count:,} ({', '.join(parts)})")
        print(f"    bounds: center=({sphere[0]:.1f}, {sphere[1]:.1f}, {sphere[2]:.1f}) radius={sphere[3]:.1f}")

    # Save bounds
    bounds_path = os.path.join(OUTPUT_DIR, 'bounds.json')
    with open(bounds_path, 'w') as f:
        json.dump(bounds, f, indent=2)

    print(f"\nDone! {len(source_files)} files processed.")
    print(f"  Padded PLYs:        {OUTPUT_DIR}/")
    print(f"  Rest positions:     {OUTPUT_DIR}/*.restpos.exr")
    print(f"  Bounding spheres:   {bounds_path}")


if __name__ == '__main__':
    main()
