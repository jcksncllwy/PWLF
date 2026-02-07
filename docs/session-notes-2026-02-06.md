# Session Notes — 2026-02-06

## What We Did

### 1. Fixed rest positions sort-order bug (RESOLVED)
- **Problem**: Kinect displacement affected splats all over the model instead of localized areas
- **Cause**: `script_top_gen_rest_pos.py` wrote positions in POP sorted order, but the vertex shader reads offsets by `uniqueID`. Positions and offsets were mismatched.
- **Fix**: Changed Script TOP to index by `uniqueID` instead of iteration order. Uses `pop.points('uniqueID')` alongside `pop.points('P')`.
- **File**: `Kinect 3D Splat Displacement/script_top_gen_rest_pos.py`
- **Detailed writeup**: `docs/rest-positions-sort-fix.md`

### 2. Fixed displacement VP matrix — which splats get hit (RESOLVED)
- **Problem**: The `uDisplaceVP` matrix (used by physics shader to project splats into Kinect displacement texture UV space) was derived from the orbiting render camera, causing different splats to be displaced depending on camera angle
- **Cause**: `/GaussianSplatting/cameraSpace` Script CHOP computed VP from `cameraViewport` (render camera)
- **Fix**: Created `td_camera_space_chop.py` — outputs a fixed orthographic projection matrix representing the Kinect's view. Parameters: `centerX/Y/Z` (scene center), `halfWidth/halfHeight` (world extents), `uAxis/vAxis` (axis mapping)
- **File**: `Kinect 3D Splat Displacement/td_camera_space_chop.py`
- **Note**: The camera vectors (force direction) should still come from the render camera — only the VP matrix (which splats get hit) should be fixed to the Kinect

### 3. Fixed camera vectors row/column extraction (RESOLVED)
- **Problem**: Force direction was inconsistent — worked from some camera angles, inverted from others. Specifically: from overhead, left-right worked but up-down was inverted. Rotating 180 while still overhead fixed it.
- **Cause**: `td_camera_vectors_chop.py` extracted **rows** of `worldTransform` instead of **columns**. In a transformation matrix, basis vectors (right, up, forward) are stored in columns. Rows only match columns for trivial rotations (identity, simple axis-aligned). For arbitrary rotations, rows give a mix of basis vector components.
- **Fix**: Changed `camMat[0, i]` → `camMat[i, 0]` and `camMat[1, i]` → `camMat[i, 1]`
- **File**: `Kinect 3D Splat Displacement/td_camera_vectors_chop.py`
- **Key insight**: The forces SHOULD come from the render camera (so hand-right = splats-right on screen). The VP matrix SHOULD be fixed to the Kinect (so the same physical splats are hit regardless of view angle).

### 4. Added offset direction tinting (VISUAL FEATURE)
- Displaced splats are tinted based on their world-space offset direction
- `normalize(offset) * 0.5 + 0.5` maps direction to RGB
- Mixed at 30% with original splat color (`mix(color.rgb, offsetDir, 0.3)`)
- **File**: `Kinect 3D Splat Displacement/glslSplat_vertex.glsl`

## Debugging Techniques Used
- **Script TOP debug prints**: `pop.pointAttributes` to discover available POP attributes and their names
- **Physics shader debug pixel**: Wrote `uCamRight` to pixel (0,0) of offset buffer to confirm GPU was receiving updated uniform values
- **Vertex shader debug tint**: Tinted splats by offset direction to visualize what the vertex shader was actually reading — confirmed physics output was correct and problem was in force direction, not data path
- **Network export tool**: `export_network.py` recursively serializes TD network to JSON using `TDJSON.serializeTDData` for parameters, with manual connection/children traversal. Run via `exec(op('textDATname').text)`. Outputs ~24MB JSON for full project.
- **Zeroing uniforms**: Multiplied cameraSpace CHOP by 0 via Math CHOP to confirm the uniform binding was actually connected (displacement stopped = binding works)

## Architecture Summary

### What's fixed to the Kinect (constant):
- `uDisplaceVP` — orthographic projection mapping splat world positions to Kinect UV space (determines WHICH splats are affected)
- `td_camera_space_chop.py` outputs 16-channel mat4 in column-major order

### What follows the render camera (dynamic):
- `uCamRight` / `uCamUp` — camera basis vectors for converting 2D Kinect flow to 3D world-space forces (determines DIRECTION of displacement)
- `td_camera_vectors_chop.py` extracts columns 0 and 1 from `cameraViewport.worldTransform`

### Data flow:
```
Kinect → flip1 → cross1/feedback1 → blur1 → opticalflow1 → blur2
                                                                ↓
thresh1 → blur3 → figureMask → comp3 (masks flow) → comp1 → cross2/feedback2 → null4
                                                                                  ↓
                                                                          [displacement texture]
                                                                                  ↓
Inside GaussianSplatPOP:
  script1 (rest pos) → cache1 ─────────────────────────┐
  offset_feedback ──────────────────────────────────────┤
  velocity_feedback ────────────────────────────────────┤
  displacement (from null4) ────────────────────────────┤
                                                        ↓
                                                  physics_update (glslmulti TOP)
                                                        ↓
                                                  offset_tex → vertex shader (via uSplatOffset)

  POP chain: pointfilein → transform → glsl_color → attcombine → math3 → sort1 → null1
  Vertex shader (glslSplat1): reads offset by uniqueID, applies world-space offset + direction tint
```

## Key Files
- `script_top_gen_rest_pos.py` — Script TOP: generates rest positions texture indexed by uniqueID
- `td_camera_vectors_chop.py` — Script CHOP: render camera right/up vectors (columns of worldTransform)
- `td_camera_space_chop.py` — Script CHOP: fixed Kinect orthographic VP matrix
- `glslSplat_vertex.glsl` — Vertex shader: applies offsets using uniqueID, direction tint
- `update_splat_physics.glsl` — GLSL TOP: spring-damper physics with Kinect flow forces
- `export_network.py` — Network export utility

## Tuning Notes (for td_camera_space_chop.py)
- `centerX/Y/Z`: aim at sculpture center in world space
- `halfWidth/halfHeight`: how many world units the Kinect sees (start at 30)
- `uAxis/vAxis`: which world axes map to Kinect horizontal/vertical (default X=0, Y=1)
- Negate halfWidth/halfHeight to flip an axis
- Swap uAxis/vAxis if displacement affects the wrong axis
