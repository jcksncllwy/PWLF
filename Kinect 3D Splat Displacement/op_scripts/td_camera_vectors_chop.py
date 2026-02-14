# Script CHOP callback: extracts camera right/up vectors in world space.
# Paste this into the Script CHOP's callback DAT.
#
# These vectors are used by the physics update shader to convert
# 2D Kinect flow into 3D world-space forces.
#
# Uses the RENDER camera's orientation so that forces are applied relative
# to the viewer's perspective (hand right = splats move right on screen).
# The resulting offset is stored in world space and persists as camera orbits.
#
# Outputs 6 channels: camRightX/Y/Z, camUpX/Y/Z
# Wire this CHOP to the GLSL TOP's uCamRight and uCamUp vec3 uniforms.

def onCook(scriptOp):
    scriptOp.clear()

    cam = op('/GaussianSplatting/cam1')  # render camera
    camMat = cam.worldTransform  # world-from-camera matrix

    # Extract basis vectors (columns of worldTransform)
    # Column 0 = right, Column 1 = up, Column 2 = forward
    for i, name in enumerate(['camRightX', 'camRightY', 'camRightZ']):
        scriptOp.appendChan(name)[0] = camMat[i, 0]

    for i, name in enumerate(['camUpX', 'camUpY', 'camUpZ']):
        scriptOp.appendChan(name)[0] = camMat[i, 1]
