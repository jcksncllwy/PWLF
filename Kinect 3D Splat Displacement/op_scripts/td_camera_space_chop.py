# Script CHOP callback: outputs the render camera's view-projection matrix.
#
# Projects splat world positions into screen-space UV to sample the
# displacement texture. Since the displacement texture is composited
# in screen space, using the render camera's VP ensures exact alignment:
# wherever the displacement appears on screen, those splats get displaced.
#
# The physics shader uses this matrix:
#   clipPos = uDisplaceVP * vec4(worldPos, 1.0)
#   uv = clipPos.xy / clipPos.w * 0.5 + 0.5
#
# Outputs 16 channels (m00..m33) in column-major order matching the existing
# layout expected by the GLSL TOP uniform binding.

# Path to the render camera. Adjust to match your network.
RENDER_CAM_PATH = '/GaussianSplatting/cam1'

# Path to the Render TOP (used to read actual resolution dynamically).
RENDER_TOP_PATH = '/GaussianSplatting/renderPOP'


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Custom')
	return


def onPulse(par):
	return


def onCook(scriptOp):
	scriptOp.clear()

	cam = op(RENDER_CAM_PATH)
	if cam is None:
		print(f"[td_camera_space] WARNING: Render camera not found at {RENDER_CAM_PATH}")
		# Output identity matrix as fallback
		names = [
			'm00','m01','m02','m03',
			'm10','m11','m12','m13',
			'm20','m21','m22','m23',
			'm30','m31','m32','m33',
		]
		for name in names:
			scriptOp.appendChan(name)[0] = 0.0
		return

	# Build VP = projection * view (read actual render resolution)
	renderTop = op(RENDER_TOP_PATH)
	if renderTop is not None:
		w = renderTop.width
		h = renderTop.height
	else:
		w = 1920
		h = 1080
	projMat = cam.projection(w, h)
	viewMat = tdu.Matrix(cam.worldTransform)
	viewMat.invert()
	vpMat = projMat * viewMat

	# Output in column-major order
	names = [
		'm00','m01','m02','m03',
		'm10','m11','m12','m13',
		'm20','m21','m22','m23',
		'm30','m31','m32','m33',
	]
	for i, name in enumerate(names):
		row = i % 4
		col = i // 4
		scriptOp.appendChan(name)[0] = vpMat[row, col]


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
