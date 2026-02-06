# Script CHOP callback: extracts camera right/up vectors in world space.
# Paste this into the Script CHOP's callback DAT.
#
# These vectors are used by the physics update shader to convert
# 2D Kinect flow into 3D world-space forces.
#
# Outputs 6 channels: camRightX/Y/Z, camUpX/Y/Z
# Wire this CHOP to the GLSL TOP's uCamRight and uCamUp vec3 uniforms.

def onCook(scriptOp):
    scriptOp.clear()

    cam = op('/GaussianSplatting/cameraViewport')  # adjust path to your camera
    camMat = cam.worldTransform  # world-from-camera matrix

    # Extract basis vectors (rows of worldTransform)
    # Row 0 = right, Row 1 = up, Row 2 = forward
    for i, name in enumerate(['camRightX', 'camRightY', 'camRightZ']):
        scriptOp.appendChan(name)[0] = camMat[0, i]

    for i, name in enumerate(['camUpX', 'camUpY', 'camUpZ']):
        scriptOp.appendChan(name)[0] = camMat[1, i]
