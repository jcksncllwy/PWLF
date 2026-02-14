# Script CHOP callback: gallery rotation with double-buffered scene loading.
#
# Cycles through PLY splat files in assets/gallery_padded/ every 60 seconds
# using the existing pointfilein2/pointfilein3 + switch1 setup as a double buffer.
#
# Only 2 scenes are loaded at once. While one plays, the next is preloaded
# into the inactive pointfilein. A smooth blend transitions between them.
#
# Also outputs camera framing channels (pivotX/Y/Z, pivotDistance) based on
# pre-computed bounding spheres in bounds.json. These smoothly interpolate
# during transitions so the camera tracks each scene's size.
#
# Timer CHOP setup (wire as input 0 to this Script CHOP):
#   - Length: 60 seconds
#   - On Done: Re-Start
#   - Play: On
#
# Bind this Script CHOP's channels:
#   - "switchIndex" -> switch1's Index parameter
#   - "camTx" -> camera Translate X
#   - "camTy" -> camera Translate Y
#   - "camTz" -> camera Translate Z
#   - "camRx" -> camera Rotate X (pitch down)
#   - "camRy" -> camera Rotate Y (orbit angle)

import json
import math
import os
import random

# --- Configuration ---
GALLERY_DIR = project.folder + '/../assets/gallery_padded'
BLEND_DURATION = 5.0    # seconds of wall-clock time for the blend transition
STORAGE_VERSION = 14    # bump this to force storage re-init

# Path to the Camera COMP (used to read FOV for proper framing)
CAMERA_PATH = '/GaussianSplatting/cam1'

# Extra margin around the bounding sphere (0.1 = 10% padding)
FRAMING_MARGIN = 0.01

# Camera elevation angle in degrees (0 = eye level, positive = looking down)
CAMERA_ELEVATION = 20.0

# Camera orbit speed in degrees per second
ORBIT_SPEED = 10.0

# How much to scale the bounding sphere radius for displacement reach
# 1.0 = exact bounds, 1.5 = 50% larger, 0 = unlimited
DISPLACE_RADIUS_SCALE = 1.5

# Fallback bounding sphere if bounds.json is missing
DEFAULT_SPHERE = {'center': [0.0, 0.0, 0.0], 'radius': 50.0}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Custom')
	return


def onPulse(par):
	return


def _getSceneFiles():
	"""Return sorted list of PLY files in the gallery directory."""
	try:
		files = sorted([
			f for f in os.listdir(GALLERY_DIR)
			if f.lower().endswith('.ply')
		])
		return files
	except FileNotFoundError:
		print(f"[gallery_rotation] Gallery dir not found: {GALLERY_DIR}")
		return []


def _loadBounds():
	"""Load pre-computed bounding spheres from bounds.json."""
	bounds_path = f'{GALLERY_DIR}/bounds.json'
	try:
		with open(bounds_path, 'r') as f:
			return json.load(f)
	except (FileNotFoundError, json.JSONDecodeError) as e:
		print(f"[gallery_rotation] WARNING: Could not load bounds: {e}")
		return {}


def _getSphere(bounds, filename):
	"""Get bounding sphere for a scene file, with fallback."""
	return bounds.get(filename, DEFAULT_SPHERE)


def _smoothstep(t):
	"""Hermite smoothstep for smooth blend curve."""
	t = max(0.0, min(1.0, t))
	return t * t * (3.0 - 2.0 * t)


def _lerpSphere(a, b, t):
	"""Linearly interpolate between two sphere dicts."""
	ac, bc = a['center'], b['center']
	return {
		'center': [ac[i] + (bc[i] - ac[i]) * t for i in range(3)],
		'radius': a['radius'] + (b['radius'] - a['radius']) * t,
	}


def _outputChannels(scriptOp, switchIndex, sceneIdx, nextSceneIdx, cameraSphere):
	"""Clear and recreate all output channels.

	IMPORTANT: This must be the LAST thing called in onCook.  scriptOp.clear()
	immediately removes channels — if any cascading cook happens after clear()
	but before appendChan(), other operators reading our channels get None.
	By doing clear + append as one atomic block at the very end, we minimize
	the window where channels are missing.
	"""
	vFov = scriptOp.storage.get('vFov', 26.0)
	radius = cameraSphere['radius']
	dist = radius / math.tan(math.radians(vFov / 2.0)) * (1.0 + FRAMING_MARGIN)
	elev = math.radians(CAMERA_ELEVATION)
	orbitDeg = (absTime.frame * ORBIT_SPEED / me.time.rate) % 360.0
	orbit = math.radians(orbitDeg)
	horizDist = dist * math.cos(elev)

	center = cameraSphere['center']

	scriptOp.clear()
	scriptOp.appendChan('switchIndex')[0] = switchIndex
	scriptOp.appendChan('sceneIndex')[0] = sceneIdx
	scriptOp.appendChan('nextSceneIndex')[0] = nextSceneIdx
	scriptOp.appendChan('camTx')[0] = horizDist * math.sin(orbit)
	scriptOp.appendChan('camTy')[0] = dist * math.sin(elev)
	scriptOp.appendChan('camTz')[0] = horizDist * math.cos(orbit)
	scriptOp.appendChan('camRx')[0] = -CAMERA_ELEVATION
	scriptOp.appendChan('camRy')[0] = orbitDeg
	scriptOp.appendChan('sceneCenterX')[0] = center[0]
	scriptOp.appendChan('sceneCenterY')[0] = center[1]
	scriptOp.appendChan('sceneCenterZ')[0] = center[2]
	scriptOp.appendChan('sceneRadius')[0] = radius * DISPLACE_RADIUS_SCALE


def onCook(scriptOp):
	# NOTE: scriptOp.clear() is NOT called here — old channels remain visible
	# to other operators during this cook. Channels are rebuilt at the very end
	# via _outputChannels() to avoid cascading-cook TypeError on Switch POP.

	# --- Read timer input ---
	timerInput = scriptOp.inputs[0] if scriptOp.inputs else None
	if timerInput is None:
		_outputChannels(scriptOp, 0.0, 0, 0, DEFAULT_SPHERE)
		return

	fraction = timerInput['timer_fraction'].eval() if 'timer_fraction' in timerInput.chans() else timerInput[0].eval()

	# --- Get scene list ---
	sceneFiles = _getSceneFiles()
	if len(sceneFiles) < 2:
		_outputChannels(scriptOp, 0.0, 0, 0, DEFAULT_SPHERE)
		return

	# --- Persistent state via storage ---
	if scriptOp.storage.get('version') != STORAGE_VERSION:
		# Shuffle scene order (re-shuffles each time TD restarts or version bumps)
		random.shuffle(sceneFiles)
		numScenes = len(sceneFiles)
		scriptOp.storage.clear()
		scriptOp.storage['version'] = STORAGE_VERSION
		scriptOp.storage['sceneFiles'] = sceneFiles
		scriptOp.storage['activeInput'] = 0
		scriptOp.storage['currentSceneIdx'] = 0
		scriptOp.storage['preloaded'] = False
		scriptOp.storage['prevFraction'] = 0.0
		scriptOp.storage['blending'] = False
		scriptOp.storage['blendStartTime'] = 0.0
		scriptOp.storage['blendReady'] = False
		scriptOp.storage['waitingForSceneChange'] = False
		scriptOp.storage['oldSceneFingerprint'] = None
		# Cache camera vertical FOV (read once to avoid cook loop)
		cam = op(CAMERA_PATH)
		renderTop = op('/GaussianSplatting/renderPOP')
		if cam is not None:
			hFov = cam.par.fov.eval()
			if renderTop is not None:
				aspect = renderTop.width / max(renderTop.height, 1)
			else:
				aspect = 16.0 / 9.0
			scriptOp.storage['vFov'] = 2.0 * math.degrees(math.atan(math.tan(math.radians(hFov / 2.0)) / aspect))
		else:
			scriptOp.storage['vFov'] = 26.0

		# Load bounds data
		bounds = _loadBounds()
		scriptOp.storage['bounds'] = bounds

		# Load initial scenes
		_loadScene(0, sceneFiles[0])
		_loadScene(1, sceneFiles[1 % numScenes])
		scriptOp.storage['preloaded'] = True

		# Load rest positions for the initial active scene
		_setRestPositions()

		# Initialize camera framing from first scene's bounds
		activeSphere = _getSphere(bounds, sceneFiles[0])
		scriptOp.storage['activeSphere'] = activeSphere
		nextSphere = _getSphere(bounds, sceneFiles[1 % numScenes])
		scriptOp.storage['targetSphere'] = nextSphere

	# Use the stored shuffled scene list from init
	sceneFiles = scriptOp.storage['sceneFiles']
	numScenes = len(sceneFiles)

	activeInput = scriptOp.storage['activeInput']
	currentSceneIdx = scriptOp.storage['currentSceneIdx']
	preloaded = scriptOp.storage['preloaded']
	prevFraction = scriptOp.storage['prevFraction']
	blending = scriptOp.storage['blending']
	blendReady = scriptOp.storage.get('blendReady', False)
	activeSphere = scriptOp.storage['activeSphere']
	targetSphere = scriptOp.storage['targetSphere']
	now = absTime.seconds

	# --- Apply deferred rest position update (wait until null1 has new data) ---
	if scriptOp.storage.get('waitingForSceneChange', False):
		fingerprint = _getSceneFingerprint()
		oldFingerprint = scriptOp.storage.get('oldSceneFingerprint')
		if fingerprint != oldFingerprint:
			scriptOp.storage['waitingForSceneChange'] = False
			_setRestPositions()
			print(f"[gallery_rotation] Scene data changed, regenerated rest positions")

	# --- Detect timer reset (fraction wrapped around) ---
	timerReset = fraction < prevFraction - 0.1
	scriptOp.storage['prevFraction'] = fraction

	# Don't act on timer reset while blending
	if timerReset and not blending:
		scriptOp.storage['preloaded'] = False
		preloaded = False

	# --- Arm the blend trigger after fraction passes through mid-cycle ---
	if fraction < 0.5:
		scriptOp.storage['blendReady'] = True
		blendReady = True

	# --- Preload next scene into inactive input (early in the cycle) ---
	waiting = scriptOp.storage.get('waitingForSceneChange', False)
	if not preloaded and not blending and not waiting and fraction > 0.05:
		inactiveInput = 1 - activeInput
		nextSceneIdx = (currentSceneIdx + 1) % numScenes
		_loadScene(inactiveInput, sceneFiles[nextSceneIdx])
		scriptOp.storage['preloaded'] = True

		# Pre-compute target sphere for the upcoming transition
		bounds = scriptOp.storage.get('bounds', {})
		scriptOp.storage['targetSphere'] = _getSphere(bounds, sceneFiles[nextSceneIdx])
		targetSphere = scriptOp.storage['targetSphere']

	# --- Start blend when timer is near the end (last 10% of cycle) ---
	if not blending and blendReady and fraction >= 0.9 and preloaded:
		scriptOp.storage['blending'] = True
		scriptOp.storage['blendStartTime'] = now
		scriptOp.storage['blendReady'] = False
		blending = True

	# --- Compute switch index and camera framing ---
	if blending:
		elapsed = now - scriptOp.storage['blendStartTime']
		if elapsed >= BLEND_DURATION:
			# Blend complete — swap active/inactive
			activeInput = 1 - activeInput
			currentSceneIdx = (currentSceneIdx + 1) % numScenes
			scriptOp.storage['activeInput'] = activeInput
			scriptOp.storage['currentSceneIdx'] = currentSceneIdx
			scriptOp.storage['blending'] = False
			scriptOp.storage['preloaded'] = False
			switchIndex = float(activeInput)
			# Snap camera to new scene
			scriptOp.storage['activeSphere'] = targetSphere
			cameraSphere = targetSphere
			_resetFeedbackTextures()
			# Capture fingerprint of old scene, then wait for null1 to show new data
			scriptOp.storage['oldSceneFingerprint'] = _getSceneFingerprint()
			scriptOp.storage['waitingForSceneChange'] = True
		else:
			blendFraction = _smoothstep(elapsed / BLEND_DURATION)
			inactiveInput = 1 - activeInput
			switchIndex = activeInput + (inactiveInput - activeInput) * blendFraction
			# Smoothly interpolate camera framing
			cameraSphere = _lerpSphere(activeSphere, targetSphere, blendFraction)
	else:
		switchIndex = float(activeInput)
		cameraSphere = activeSphere

	# --- Output channels (clear + recreate as the very last step) ---
	nextSceneIdx = (currentSceneIdx + 1) % numScenes
	_outputChannels(scriptOp, switchIndex, currentSceneIdx, nextSceneIdx, cameraSphere)


def _loadScene(inputIndex, filename):
	"""Load a PLY file into the specified pointfilein (0=pointfilein2, 1=pointfilein3)."""
	opName = 'pointfilein2' if inputIndex == 0 else 'pointfilein3'
	popOp = op(f'/GaussianSplatting/GaussianSplatPOP/{opName}')
	if popOp is None:
		print(f"[gallery_rotation] Could not find {opName}")
		return

	filepath = f'{GALLERY_DIR}/{filename}'
	popOp.par.file = filepath
	print(f"[gallery_rotation] Loaded {filename} into {opName}")


def _getSceneFingerprint():
	"""Sample a few point positions from null1 as a scene identity check."""
	pop = op('/GaussianSplatting/GaussianSplatPOP/null1')
	if pop is None or pop.numPoints == 0:
		return None
	positions = pop.points('P')
	n = len(positions)
	# Sample first, middle, and a point near the end
	indices = [0, n // 2, min(n - 1, 1000)]
	return tuple((int(positions[i][0] * 1000), int(positions[i][1] * 1000), int(positions[i][2] * 1000)) for i in indices)


def _setRestPositions():
	"""Regenerate rest positions via the Script TOP (reads live from null1).

	IMPORTANT: This must NOT call cook(force=True) synchronously, because it's
	called during the Script CHOP's onCook after scriptOp.clear() has removed
	all channels.  A synchronous force-cook cascades into the Switch POP, which
	tries to read the (now-missing) switchIndex channel → None → TypeError,
	causing the Switch to fall back to input 0 and capturing rest positions
	from the wrong scene.

	Instead we defer the force-cook by one frame using run(), so all Script CHOP
	channels are fully output before the rest-position texture regenerates.
	"""
	restScriptTop = op('/GaussianSplatting/GaussianSplatPOP/rest_pos_script')
	if restScriptTop is not None:
		restScriptTop.storage['dirty'] = True
		run("op('/GaussianSplatting/GaussianSplatPOP/rest_pos_script').cook(force=True)", delayFrames=1)
		print("[gallery_rotation] Scheduled rest position regeneration (next frame)")


def _resetFeedbackTextures():
	"""Reset offset and velocity feedback TOPs to clear stale displacement from the previous scene."""
	for name in ('offset_feedback', 'velocity_feedback'):
		fb = op(f'/GaussianSplatting/GaussianSplatPOP/{name}')
		if fb is not None:
			fb.par.resetpulse.pulse()
	print("[gallery_rotation] Reset feedback textures")


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
