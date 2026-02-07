# Rest Positions Texture: Sort-Order Bug Fix

## Date: 2026-02-06

## Problem

After re-opening the project, moving in front of the Kinect displaced splats **all over the model** instead of only the splats localized to the area of movement in the displacement map. The splats themselves rendered correctly — only the physics-driven displacement was wrong.

## Root Cause

The rest positions texture (used by the physics update shader to project each splat into Kinect UV space) was being written in **sorted order** — whatever order the POP chain happened to output points at the time the Script TOP cooked. But the vertex shader looks up offsets using `originalIndex` from `CustomAttrib4`, which is the splat's `uniqueID` (its original, stable index that doesn't change with sorting).

This meant:
1. Physics shader computed an offset for pixel N based on the rest position of whichever splat was sorted to position N at capture time
2. Vertex shader applied pixel N's offset to the splat with `uniqueID=N` — a completely different splat
3. Localized Kinect displacement got scattered across random splats all over the model

This is the same class of issue as the earlier sorting mismatch that led to adding `uniqueID` as `CustomAttrib4` in the first place.

## Fix

Changed `script_top_gen_rest_pos.py` to index the texture by `uniqueID` instead of sorted iteration order.

**Before** (sorted order — broken):
```python
positions = pop.points('P')
for i in range(min(numPoints, texSize * texSize)):
    x = i % texSize
    y = i // texSize
    pos = positions[i]
    pixels[y, x] = [pos[0], pos[1], pos[2], 1.0]
```

**After** (uniqueID order — correct):
```python
positions = pop.points('P')
uniqueIDs = pop.points('uniqueID')
for i in range(min(numPoints, texSize * texSize)):
    uid = int(uniqueIDs[i])
    if uid >= texSize * texSize:
        continue
    x = uid % texSize
    y = uid // texSize
    pos = positions[i]
    pixels[y, x] = [pos[0], pos[1], pos[2], 1.0]
```

Now the rest position at pixel N belongs to the splat with `uniqueID=N`, which is the same pixel the vertex shader reads when it does `indexToUV(originalIndex, uStateTexSize)`.

## Verification

After the fix, unlocking the Script TOP and re-caching produces a rest positions texture that is **stable across frames** regardless of camera rotation. The sorting no longer affects which pixel a splat's position lands in.

## TouchDesigner POP Python API Notes

Learned through trial and error:

- `pop.points` is a **method**, not a property. Calling it with no args (`pop.points()`) throws `td.tdError: Attribute Name required`.
- `pop.points('P')` returns an `AttribList` of position tuples (x, y, z)
- `pop.points('uniqueID')` returns an `AttribList` of single float values
- Available attributes can be listed via `pop.pointAttributes` (not `pointAttribs` or `pointAttribNames`)
- The `pointAttributes` output format: `(uniqueID: 1 <class 'float'>, P: 3 <class 'float'>, scale: 3 <class 'float'>, Color: 4 <class 'float'>, rot: 4 <class 'float'>)`
- POP null operators are of type `td.nullPOP`

## Key Principle

Any texture that maps splat data by index **must** use `uniqueID` as the index, not the iteration order from the POP chain. The POP chain sorts by depth every frame for correct alpha blending, so iteration order is unstable. This applies to:
- Rest positions texture (Script TOP)
- Offset texture lookups (vertex shader)
- Velocity texture lookups (vertex shader, if ever needed)
