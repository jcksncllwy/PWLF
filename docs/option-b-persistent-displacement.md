# Option B: Persistent Per-Splat Displacement with Physics

## Overview

Instead of displacing splats instantaneously each frame, we store per-splat offset and velocity in feedback textures. Kinect flow applies forces (relative to the camera plane at the moment of input), but the resulting displacement accumulates in **world space**. A spring pulls splats back to their rest positions, and damping prevents oscillation.

This creates organic drift that persists after movement stops. Because offsets are stored in world space, displaced splats stay displaced in that direction even as the camera rotates — making the 3D nature of the scene visible.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        UPDATE PASS                               │
│                    (GLSL TOP + Feedback)                         │
│                                                                  │
│  Inputs:                                                         │
│    - Previous offset texture (feedback) — world-space XYZ       │
│    - Previous velocity texture (feedback) — world-space XYZ     │
│    - Kinect displacement texture (flow.xy, depth.z)             │
│    - Splat rest positions texture                                │
│    - Camera right/up vectors (uniforms)                          │
│    - Spring/damping/force uniforms                               │
│                                                                  │
│  Outputs:                                                        │
│    - Updated offset texture (world-space XYZ)                   │
│    - Updated velocity texture (world-space XYZ)                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       RENDER PASS                                │
│                 (GLSL MAT vertex shader)                         │
│                                                                  │
│  Inputs:                                                         │
│    - Offset texture (sample world-space offset for this splat)  │
│                                                                  │
│  Output:                                                         │
│    - Displaced splat positions (worldPos += offset)             │
└─────────────────────────────────────────────────────────────────┘
```

## Storage Textures

**Resolution**: 1024 x 1024 = 1,048,576 pixels (enough for ~1M splats)

**Format**: RGBA 32-bit float (x2 textures)

### Texture 1: Offset
- R = offset.x (world space)
- G = offset.y (world space)
- B = offset.z (world space)
- A = unused (or valid flag)

### Texture 2: Velocity
- R = velocity.x (world space)
- G = velocity.y (world space)
- B = velocity.z (world space)
- A = unused

**Index mapping** (same for both textures):
```glsl
// Splat index (0 to numSplats-1) -> texture UV
vec2 indexToUV(int index, vec2 texSize) {
    float x = float(index % int(texSize.x)) + 0.5;
    float y = float(index / int(texSize.x)) + 0.5;
    return vec2(x, y) / texSize;
}

// In vertex shader, with 1024x1024 texture:
vec2 stateUV = indexToUV(instanceIndex, vec2(1024.0));
```

## Physics Model

**Key insight**: Forces are derived from 2D camera-plane flow, but converted to 3D world-space vectors at the moment they're applied. All subsequent physics (spring, damping, integration) happens in world space.

| Uniform | Description | Suggested Starting Value |
|---------|-------------|-------------------------|
| `uForceStrength` | How much Kinect flow accelerates splats | 5.0 - 20.0 |
| `uSpringK` | Spring constant pulling toward origin | 2.0 - 10.0 |
| `uDamping` | Velocity decay per frame (0-1) | 0.95 - 0.98 |
| `uDeltaTime` | Time step | 0.016 (60fps) |
| `uCamRight` | Camera right vector (world space) | from camera matrix |
| `uCamUp` | Camera up vector (world space) | from camera matrix |

**Physics equations** (per frame, all in world space):
```
// Convert 2D flow to 3D world-space force
force3D = (camRight * flow.x + camUp * flow.y) * uForceStrength * depthWeight

// Physics integration (all world space)
velocity += force3D * dt
velocity -= offset * uSpringK * dt    // spring pulls toward origin
velocity *= uDamping                   // friction/drag
offset += velocity * dt
```

## Implementation

### Part 1: Splat Rest Positions Texture

A 1024x1024 texture where each pixel's RGB = splat's rest position in world space.

**Option A**: Pre-baked from PLY data (static)
**Option B**: Generated each frame from POPs (if POP chain moves splats)

Python Script TOP example (run once or when splats change):
```python
def onCook(scriptOp):
    scriptOp.clear()

    pop = op('popnet1/out1')  # adjust path
    points = pop.points

    texSize = 1024
    scriptOp.res = (texSize, texSize)
    scriptOp.format = 'rgba32float'

    pixels = scriptOp.numpyArray(True)

    for i, point in enumerate(points):
        if i >= texSize * texSize:
            break
        x = i % texSize
        y = i // texSize
        pos = point.P
        pixels[y, x, 0] = pos[0]
        pixels[y, x, 1] = pos[1]
        pixels[y, x, 2] = pos[2]
        pixels[y, x, 3] = 1.0  # valid flag

    scriptOp.copyNumpyArray(pixels)
```

### Part 2: Update Shader (GLSL Multi-Output TOP)

This shader updates both offset and velocity textures each frame. In TouchDesigner, you can either:
- Use two separate GLSL TOPs (one for offset, one for velocity)
- Use a single GLSL TOP with multiple render targets (MRT)

Below is the MRT approach (single shader, two outputs):

```glsl
// update_splat_physics.glsl (GLSL TOP pixel shader with 2 outputs)

uniform sampler2D sOffset;      // input 0: previous offset (feedback)
uniform sampler2D sVelocity;    // input 1: previous velocity (feedback)
uniform sampler2D sDisplace;    // input 2: Kinect displacement (flow.xy, depth.z)
uniform sampler2D sRestPos;     // input 3: splat rest positions

uniform mat4 uDisplaceVP;       // for projecting splat pos to Kinect UV
uniform vec3 uCamRight;         // camera right vector (world space)
uniform vec3 uCamUp;            // camera up vector (world space)
uniform float uForceStrength;
uniform float uSpringK;
uniform float uDamping;
uniform float uDeltaTime;
uniform float uDepthFalloff;

layout(location = 0) out vec4 outOffset;
layout(location = 1) out vec4 outVelocity;

void main()
{
    vec2 uv = vUV.st;

    // Read previous state (world space)
    vec3 offset = texture(sOffset, uv).rgb;
    vec3 velocity = texture(sVelocity, uv).rgb;

    // Read this splat's rest position
    vec4 restData = texture(sRestPos, uv);
    vec3 restPos = restData.rgb;
    float valid = restData.a;

    // Skip invalid pixels (no splat here)
    if (valid < 0.5) {
        outOffset = vec4(0.0);
        outVelocity = vec4(0.0);
        return;
    }

    // Current world position (rest + offset)
    vec3 worldPos = restPos + offset;

    // Project into Kinect/displacement texture space
    vec4 clipPos = uDisplaceVP * vec4(worldPos, 1.0);
    vec2 displaceUV = clipPos.xy / clipPos.w * 0.5 + 0.5;

    // Sample Kinect displacement and compute force
    vec3 force = vec3(0.0);
    if (all(greaterThanEqual(displaceUV, vec2(0.0))) &&
        all(lessThanEqual(displaceUV, vec2(1.0))) &&
        clipPos.w > 0.0)
    {
        vec3 displaceSample = texture(sDisplace, displaceUV).rgb;
        vec2 flow = displaceSample.xy;
        float depth = displaceSample.z;
        float depthWeight = exp(-depth * uDepthFalloff);

        // Convert 2D flow to 3D world-space force
        force = (uCamRight * flow.x + uCamUp * flow.y) * uForceStrength * depthWeight;
    }

    // Physics integration (world space)
    float dt = uDeltaTime;

    velocity += force * dt;                 // apply force from Kinect
    velocity -= offset * uSpringK * dt;     // spring pulls toward rest position
    velocity *= uDamping;                   // damping
    offset += velocity * dt;                // integrate

    // Output
    outOffset = vec4(offset, 1.0);
    outVelocity = vec4(velocity, 1.0);
}
```

**TouchDesigner setup for MRT**:
1. Create GLSL TOP, resolution 1024x1024, format RGBA32Float
2. Enable multiple render targets (check TD docs for your version)
3. Wire inputs: feedback offset (0), feedback velocity (1), Kinect displacement (2), rest positions (3)
4. Create two Feedback TOPs, one for each output
5. Use Render Select TOP or similar to route the two outputs

**Alternative: Two separate GLSL TOPs**

If MRT is tricky, use two GLSL TOPs that both read the same inputs but write different outputs. They'd share most of the code but one outputs offset, the other outputs velocity.

### Part 3: Camera Vectors CHOP

The update shader needs `uCamRight` and `uCamUp` as uniforms. Create a Script CHOP:

```python
def onCook(scriptOp):
    scriptOp.clear()

    cam = op('/GaussianSplatting/cameraViewport')
    camInv = tdu.Matrix(cam.worldTransform)  # world-from-camera

    # Extract basis vectors (columns of the matrix)
    right = [camInv[0, 0], camInv[1, 0], camInv[2, 0]]
    up = [camInv[0, 1], camInv[1, 1], camInv[2, 1]]

    for i, name in enumerate(['camRightX', 'camRightY', 'camRightZ']):
        scriptOp.appendChan(name)[0] = right[i]

    for i, name in enumerate(['camUpX', 'camUpY', 'camUpZ']):
        scriptOp.appendChan(name)[0] = up[i]
```

Wire this CHOP to the GLSL TOP's `uCamRight` and `uCamUp` vec3 uniforms.

### Part 4: Modified Vertex Shader

The vertex shader is now simple — just sample the offset and add it to world position.

```glsl
// glslSplat_vertex_persistent.glsl

// ... existing uniforms ...

// Persistent displacement uniforms
uniform sampler2D uSplatOffset;     // world-space offset texture
uniform vec2 uStateTexSize;         // vec2(1024.0, 1024.0)

vec2 indexToUV(int index, vec2 texSize) {
    float x = float(index % int(texSize.x)) + 0.5;
    float y = float(index / int(texSize.x)) + 0.5;
    return vec2(x, y) / texSize;
}

void main()
{
    int instanceIndex = TDInstanceID();
    int index = instanceIndex;
    int cameraIndex = TDCameraIndex();

    vec3 quadCorner = TDPos();
    vec2 uv = quadCorner.xy;
    vec3 conic = vec3(0.);
    vec2 quadExtentNDC = vec2(0.);
    vec4 color = TDInstanceCustomAttrib3(index);

    mat3 m = mat3(1);
    vec3 splatPos = vec3(0.);
    vec4 splatRot = vec4(0.);
    vec3 splatScale = vec3(0.);

    if (color.a > 0.0)
    {
        splatPos = TDInstanceCustomAttrib0(index).xyz;
        splatRot = normalize(TDInstanceCustomAttrib2(index));
        splatScale = TDInstanceCustomAttrib1(index).xyz;
        m = RotScale(splatRot, splatScale, uScale);
        mat3 sigma = transpose(m)*m;
        vec3 cov = Covariance(splatPos.xyz, cameraIndex, sigma);
        float det = cov.x * cov.z - cov.y * cov.y;
        conic = vec3(cov.z,-cov.y,cov.x)/det;

        vec2 wh = 2.*uFocal.xy * uFocal.z;
        vec2 quadExtentScreen = 3.*sqrt(cov.xz);
        quadExtentNDC = 2.*quadExtentScreen / wh * smoothstep(0.0,0.1,uScale);
        uv = quadExtentScreen * quadCorner.xy;
    }
    else
    {
        splatPos *= 0; color *= 0;
    }

    vec4 worldPos = TDDeform(splatPos.xyz);

    // Apply persistent world-space offset
    vec2 stateUV = indexToUV(index, uStateTexSize);
    vec3 offset = texture(uSplatOffset, stateUV).rgb;
    worldPos.xyz += offset;

    vec4 clipPos = TDWorldToProj(worldPos);
    vec3 ndcPos = clipPos.xyz / clipPos.w;

    ndcPos.xy += quadExtentNDC * quadCorner.xy;
    gl_Position = vec4(ndcPos, 1.0);

    Vert.position = ndcPos;
    Vert.color = color;
    Vert.uv = uv;
    Vert.conic = conic;
}

// ... fragment shader unchanged ...
```

## TouchDesigner Network Overview

```
                                    ┌──────────────────┐
                                    │ Camera Vectors   │
                                    │ (Script CHOP)    │
                                    └────────┬─────────┘
                                             │
[Kinect] → [Blur] → [OptFlow] → [Pack RGB]   │
                                      │      │
                                      ▼      ▼
┌─────────────┐    ┌─────────────────────────────────────┐
│ Rest Pos    │───►│         GLSL TOP: Update            │
│ (Script TOP)│    │  (reads offset/velocity feedback,   │
└─────────────┘    │   writes new offset/velocity)       │
                   └──────────────┬──────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
             [Offset Texture]           [Velocity Texture]
                    │                           │
                    ▼                           ▼
             [Feedback TOP] ◄──────────► [Feedback TOP]
                    │
                    ▼
             [GLSL MAT: Render]
                    │
                    ▼
             [Render TOP] → [Output]
```

## Tuning Guide

| Symptom | Adjustment |
|---------|------------|
| Splats barely move | Increase `uForceStrength` |
| Splats fly off forever | Increase `uSpringK`, decrease `uForceStrength` |
| Splats oscillate/bounce | Increase `uDamping` (closer to 1.0) |
| Splats snap back too fast | Decrease `uSpringK` |
| Splats feel sluggish/delayed | Decrease `uDamping` |
| Movement doesn't match hand position | Check `uDisplaceVP` matrix, verify UV mapping |
| Splats drift when camera rotates | This is expected! Offsets are in world space. |

## Verification Steps

1. **Feedback working**: Offset texture should show persistent values even when Kinect input is zero
2. **Spring working**: Offset should decay toward zero when no forces applied
3. **Force direction**: Push right on Kinect → splats move right in world space (relative to camera at that moment)
4. **Camera rotation**: Rotate camera → displaced splats stay displaced in original world direction
5. **Index mapping**: Same splat should sample same UV in both update shader and vertex shader

## Potential Issues & Solutions

**Issue**: Splat indices don't match between POPs and textures
**Solution**: Ensure the rest positions texture is generated from the same point order as the instanced rendering. POPs should maintain point order through the chain.

**Issue**: Offsets explode to infinity
**Solution**: Add a maximum offset clamp: `offset = clamp(offset, vec3(-10.0), vec3(10.0))`

**Issue**: Performance is bad
**Solution**:
- Ensure rest positions texture is static (cook once, not every frame)
- Reduce state texture resolution if fewer splats
- All textures should be GPU-resident
