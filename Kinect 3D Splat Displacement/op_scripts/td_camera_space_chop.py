# Script CHOP callback: outputs a fixed Kinect view-projection matrix.
#
# This replaces the render camera VP with a fixed orthographic projection
# representing the Kinect's view of the scene. Since the Kinect is physically
# mounted at the window and doesn't move, this matrix is constant.
#
# The physics shader uses this matrix to project each splat's world position
# into UV coordinates in the Kinect displacement texture:
#   clipPos = uDisplaceVP * vec4(worldPos, 1.0)
#   uv = clipPos.xy / clipPos.w * 0.5 + 0.5
#
# Outputs 16 channels (m00..m33) in column-major order matching the existing
# layout expected by the GLSL TOP uniform binding.

def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Custom')
	return

def onPulse(par):
	return

def onCook(scriptOp):
	scriptOp.clear()

	# --- Kinect orthographic projection parameters ---
	# Adjust these to match the Kinect's view of your scene.

	# Center of the Kinect's view in world space.
	# Set this to roughly the center of your sculpture.
	centerX = 0.0
	centerY = 0.0
	centerZ = 0.0

	# Half-extents of the visible region in world units.
	# Controls how much of the scene the Kinect "sees."
	# Larger values = more of the scene maps to the displacement texture.
	# Negate to flip that axis (e.g., -30.0 flips horizontal).
	halfWidth  = 60.0   # world units visible left-to-right
	halfHeight = 60.0   # world units visible bottom-to-top

	# Which world axes map to the displacement texture U and V.
	# 0 = X, 1 = Y, 2 = Z
	# Default: X = horizontal (U), Y = vertical (V) — Kinect looking along Z.
	# If your scene is oriented differently, swap these.
	uAxis = 0
	vAxis = 1

	# --- Build the orthographic VP matrix ---
	# Maps: world[uAxis] -> clip.x, world[vAxis] -> clip.y, clip.w = 1
	# The shader then converts clip.xy to UV via: uv = clip.xy / clip.w * 0.5 + 0.5

	center = [centerX, centerY, centerZ]

	# 4x4 matrix, row-major: mat[row][col]
	mat = [[0.0]*4 for _ in range(4)]
	mat[0][uAxis] = 1.0 / halfWidth
	mat[1][vAxis] = 1.0 / halfHeight
	mat[0][3] = -center[uAxis] / halfWidth
	mat[1][3] = -center[vAxis] / halfHeight
	mat[3][3] = 1.0  # w = 1 (orthographic)

	# Output in column-major order (matching existing channel layout)
	names = [
		'm00','m01','m02','m03',
		'm10','m11','m12','m13',
		'm20','m21','m22','m23',
		'm30','m31','m32','m33',
	]
	for i, name in enumerate(names):
		row = i % 4
		col = i // 4
		scriptOp.appendChan(name)[0] = mat[row][col]

def onGetCookLevel(scriptOp):
	return CookLevel.AUTOMATIC
