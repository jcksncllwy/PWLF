# Interactive Installation - Planning Doc

## Project Overview

Street-facing rear-projection installation. A Kinect v2 captures a depth map of pedestrians on the sidewalk. TouchDesigner renders gaussian splat (and/or point cloud) scenes of sculptures from around town. When people move in front of the window, their movement displaces the splats/points in the rendered scene.

## Interaction Design

- **Input**: Kinect v2 depth map of viewers on the sidewalk
- **Output**: Rear-projected splat/pointcloud scene, distorted by viewer movement
- **Behavior**: Movement (not mere presence) causes displacement. Standing still = no effect. Gesturing/walking = distortion of the scene.
- **Depth scaling**: Closer people cause stronger displacement. Someone far across the street has negligible impact. This naturally handles "occlusion" concerns without an explicit depth test.
- **Displacement direction**: Screen-plane of the camera. Splats shift laterally based on the direction of movement, not pushed in/out along depth.

## Technical Pipeline

```
Kinect v2 depth map (TOP)
        |
        v
Optical Flow TOP (built-in TD operator, extracts 2D motion vectors from depth changes)
        |
        v
Combine/Pack TOP (pack flow XY + depth into RGB channels as a displacement map)
        |
        v
  [fed as uniform sampler to the vertex shader]

Point File In POP (loads .ply gaussian splat)
        |
        v
POP chain (artistic effects: noise, twist, trails, feedback loops, thinning, etc.)
        |
        v
Gaussian Splat GLSL Vertex Shader (renders splats; THIS is where we inject Kinect displacement)
        |
        v
Render TOP -> projector output
```

## Key Architectural Decision: Where Displacement Happens

We considered several options and settled on a hybrid approach (Option D):

### POPs handle artistic effects
The POP chain stays clean for creative manipulation — noise, twist, trails, feedback loops, math mix blending, thinning, proximity/plexus effects. This is what Lake Heckaman's component is built for and POPs excel at.

### GLSL vertex shader handles Kinect displacement
The Kinect-driven interactive displacement is added in the existing gaussian splat vertex shader. Reasons:
- Texture sampling is native and trivial on the GPU
- No per-particle Python or awkward POP-based texture lookups for 1M+ splats
- Separates interactive behavior from art direction
- Small modification (~10-15 lines added to existing shader)

### What the shader modification needs to do
1. Accept the flow+depth TOP as a uniform sampler2D
2. Accept the Kinect projection matrix as a uniform mat4
3. For each splat vertex: project its world position into Kinect UV space
4. Sample the displacement texture at that UV
5. Read the flow vector (XY) and depth (Z) from the sample
6. Offset the splat's screen-space position by: flow_vector * f(depth)
   - Where f(depth) maps closer = stronger displacement, farther = weaker

## Gaussian Splat POPs Component

**Location**: `C:\Users\jcksn\Desktop\PWLF\Gaussian Splat POPs\`
- `GaussianSplat_POPViewer.toe` — TouchDesigner project file (binary, needs TD to inspect)
- `gs_Bust 2.ply` — Sample gaussian splat model (1,044,408 vertices, 248 MB)

**PLY format** (binary little-endian):
- Position: x, y, z
- Normals: nx, ny, nz
- Spherical harmonics: f_dc_0/1/2 (base RGB), f_rest_0 through f_rest_44
- Opacity: single float
- Scale: scale_0, scale_1, scale_2
- Rotation: rot_0, rot_1, rot_2, rot_3 (quaternion)

**Component internals** (from Lake Heckaman's tutorial):
- Based on Tim Gerritsen's original component, adapted for POPs
- Point File In loads PLY, extracts attributes (color, rotation, scale, position)
- POP chain manipulates positions; attributes survive through the chain
- GLSL vertex shader at the end renders actual splats
- Key POPs used: Math Mix, Noise, Twist, Delete (thin random + boundary), Trail, Proximity, Feedback loops
- Attributes visible in POP chain: color, length, rotation, scale

**Reference video**: https://www.youtube.com/watch?v=t2ixnJ7vWjk (Lake Heckaman)
- Transcript saved at: `Gaussian Splat POPs\yt-transcript.txt`

## Completed Steps

1. **Extract the GLSL vertex shader** — Done. Extracted from GaussianSplat_POPViewer.toe and saved to `Gaussian Splat POPs\glslSplat_vertex.glsl`. Combined vertex+pixel shader file.

2. **Understand the existing shader** — Done. Key findings:
   - Per-splat attributes passed via instancing: position (`CustomAttrib0`), scale (`CustomAttrib1`), rotation quaternion (`CustomAttrib2`), color+alpha (`CustomAttrib3`)
   - `RotScale()` builds combined rotation/scale matrix from quaternion + log-scale
   - `Covariance()` projects 3D gaussian into 2D screen-space ellipse (conic) for the fragment shader
   - Projection flow: `TDDeform(posData)` → `TDWorldToProj()` → perspective divide → add quad corner offset → `gl_Position`
   - Fragment shader evaluates gaussian falloff via conic, does alpha threshold, premultiplies alpha

3. **Write the shader modification** — Done. Added to `glslSplat_vertex.glsl`:
   - 4 new uniforms: `uKinectDisplace` (sampler2D), `uKinectVP` (mat4), `uDisplaceStrength` (float), `uDepthFalloff` (float)
   - ~15 lines inserted after perspective divide, before quad corner expansion
   - Projects each splat's world position into Kinect UV space via `uKinectVP`
   - Samples flow+depth displacement texture, applies `exp(-depth * falloff)` weighting
   - Offsets splat center in NDC before billboard expansion
   - Safe when Kinect is disconnected (zero uniforms = no displacement)
   - **Important**: displacement texture must use float format (16/32-bit) in the Combine TOP, not 8-bit, to preserve signed optical flow values

## Next Steps

4. **Test shader modification with fake inputs** (no Kinect needed)

   Goal: verify the displacement code path works before wiring up real Kinect data.

   **a. Create a fake displacement texture (TOP network):**
   1. Create a Noise TOP (or Ramp TOP for a more predictable test)
      - Set resolution to something modest (e.g., 512x512)
      - **Critical**: Set pixel format to **32-bit float (RGBA32)** — the shader reads signed flow values, 8-bit will clamp negatives to zero
      - R channel = fake flow X (horizontal displacement direction)
      - G channel = fake flow Y (vertical displacement direction)
      - B channel = fake depth (0 = close/strong effect, 1 = far/weak effect)
   2. Suggested starting configs:
      - **Ramp TOP** (predictable): left-to-right gradient in R, zero in G, constant ~0.2 in B. This should push all splats sideways with a visible gradient across the scene.
      - **Noise TOP** (organic): animated noise for a turbulent distortion effect. Good for stress-testing the visual result.
   3. Optionally, use a Constant TOP (B=0.2) combined with the Noise/Ramp via a Composite TOP to control channels independently.

   **b. Set up the Kinect VP matrix uniform:**
   - Simplest approach: use an **identity matrix** for `uKinectVP`. This makes the shader use each splat's world position directly as the UV lookup — not physically accurate, but enough to confirm displacement is working.
   - Better approach: use the **render camera's own View-Projection matrix** (from a Camera COMP → Object CHOP or via GLSL uniform binding). This maps each splat to its screen position in the displacement texture, which is closer to the final behavior.

   **c. Wire uniforms into the GLSL MAT:**
   1. On the GLSL MAT's **Samplers** page, bind the fake displacement TOP to `uKinectDisplace`
   2. On the **Vectors** page (or via custom uniform parameters):
      - `uKinectVP`: 4x4 identity matrix (or pull from Camera COMP)
      - `uDisplaceStrength`: start at `0.05`–`0.2` (units are NDC, so 1.0 = full screen width)
      - `uDepthFalloff`: start at `2.0`–`5.0` (controls how quickly displacement fades with depth)

   **d. What to look for:**
   - With a Ramp TOP: splats should shift laterally across the scene in a smooth gradient
   - With a Noise TOP: splats should jitter/warp in a turbulent pattern
   - With all uniforms at zero (or identity matrix + zero strength): render should be identical to unmodified shader — no displacement
   - If nothing happens: check that the displacement TOP is actually 32-bit float and that the sampler binding name matches `uKinectDisplace` exactly

5. **Set up the Kinect + Optical Flow chain** in TOPs.
6. **Wire it together** — pass the displacement TOP and Kinect projection matrix as uniforms to the modified shader. The Kinect VP matrix comes from a Camera COMP matching the Kinect's physical position/orientation. Simpler alternative for testing: skip the matrix and use the splat's own screen-space position as the UV lookup (works if Kinect and render camera are roughly aligned).
7. **Tune** — adjust depth-to-magnitude mapping, flow smoothing, radius of effect, etc.

## Practical Notes

- **TouchDesigner licensing**: Commercial license expired (2 years out of date, $300/yr to renew). Non-commercial version (free, 1280x720 cap) being installed for development. Will need commercial for final install — projection window is ~8x6 feet, needs higher resolution.
- **Coordinate mapping shortcut**: If the Kinect and render camera end up roughly co-located behind the window, a simple scale+offset on the splat's screen UV may work instead of the full Kinect VP matrix. Good enough for early testing.

## Open Questions

- What Kinect TD operator to use (Kinect Azure TOP vs Kinect v2 TOP vs third-party)
- Optical Flow TOP parameters (resolution, smoothing, threshold) — will need tuning for depth data specifically
- Whether to add temporal smoothing to the displacement (so it doesn't feel jittery)
- What sculptures / splat files will be used and whether they need preprocessing (thinning, cropping, centering)
