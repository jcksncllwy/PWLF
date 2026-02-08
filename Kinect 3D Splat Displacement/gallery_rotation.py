# Script CHOP callback: gallery rotation with double-buffered scene loading.
#
# Cycles through PLY splat files in assets/gallery/ every 60 seconds using
# the existing pointfilein2/pointfilein3 + switch1 setup as a double buffer.
#
# Only 2 scenes are loaded at once. While one plays, the next is preloaded
# into the inactive pointfilein. A smooth blend transitions between them.
#
# Timer CHOP setup (wire as input 0 to this Script CHOP):
#   - Length: 60 seconds
#   - On Done: Re-Start
#   - Play: On
#
# Bind this Script CHOP's "switchIndex" channel to switch1's Index parameter.

import os

# --- Configuration ---
GALLERY_DIR = project.folder + '/../assets/gallery'
BLEND_DURATION = 5.0    # seconds of wall-clock time for the blend transition
STORAGE_VERSION = 2     # bump this to force storage re-init (e.g. after loading a TD backup)

# How many frames to wait after loading a PLY before regenerating rest positions
REST_REGEN_DELAY_FRAMES = 3


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


def _smoothstep(t):
	"""Hermite smoothstep for smooth blend curve."""
	t = max(0.0, min(1.0, t))
	return t * t * (3.0 - 2.0 * t)


def onCook(scriptOp):
	scriptOp.clear()

	# --- Read timer input ---
	timerInput = scriptOp.inputs[0] if scriptOp.inputs else None
	if timerInput is None:
		scriptOp.appendChan('switchIndex')[0] = 0.0
		scriptOp.appendChan('sceneIndex')[0] = 0
		scriptOp.appendChan('nextSceneIndex')[0] = 0
		return

	fraction = timerInput['timer_fraction'].eval() if 'timer_fraction' in timerInput.chans() else timerInput[0].eval()

	# --- Get scene list ---
	sceneFiles = _getSceneFiles()
	if len(sceneFiles) < 2:
		scriptOp.appendChan('switchIndex')[0] = 0.0
		scriptOp.appendChan('sceneIndex')[0] = 0
		scriptOp.appendChan('nextSceneIndex')[0] = 0
		return

	numScenes = len(sceneFiles)

	# --- Persistent state via storage ---
	# activeInput: which switch input (0 or 1) is currently showing
	# currentSceneIdx: index into sceneFiles for the currently active scene
	# preloaded: whether the next scene has been loaded into the inactive input
	# regenCountdown: frames remaining before pulsing rest position regeneration
	if scriptOp.storage.get('version') != STORAGE_VERSION:
		scriptOp.storage.clear()
		scriptOp.storage['version'] = STORAGE_VERSION
		scriptOp.storage['activeInput'] = 0       # switch index 0 = pointfilein2
		scriptOp.storage['currentSceneIdx'] = 0
		scriptOp.storage['preloaded'] = False
		scriptOp.storage['regenCountdown'] = -1
		scriptOp.storage['prevFraction'] = 0.0
		scriptOp.storage['blending'] = False
		scriptOp.storage['blendStartTime'] = 0.0
		scriptOp.storage['blendReady'] = False  # must see fraction < 0.5 before first blend

		# Load initial scenes
		_loadScene(0, sceneFiles[0])
		_loadScene(1, sceneFiles[1 % numScenes])
		scriptOp.storage['preloaded'] = True

	activeInput = scriptOp.storage['activeInput']
	currentSceneIdx = scriptOp.storage['currentSceneIdx']
	preloaded = scriptOp.storage['preloaded']
	regenCountdown = scriptOp.storage['regenCountdown']
	prevFraction = scriptOp.storage['prevFraction']
	blending = scriptOp.storage['blending']
	blendReady = scriptOp.storage.get('blendReady', False)
	now = absTime.seconds

	# --- Detect timer reset (fraction wrapped around) ---
	timerReset = fraction < prevFraction - 0.1  # allow small jitter
	scriptOp.storage['prevFraction'] = fraction

	# Don't act on timer reset while blending — the blend controls the swap
	if timerReset and not blending:
		scriptOp.storage['preloaded'] = False
		preloaded = False

	# --- Arm the blend trigger after fraction passes through mid-cycle ---
	if fraction < 0.5:
		scriptOp.storage['blendReady'] = True
		blendReady = True

	# --- Preload next scene into inactive input (early in the cycle) ---
	if not preloaded and not blending and fraction > 0.05:
		inactiveInput = 1 - activeInput
		nextSceneIdx = (currentSceneIdx + 1) % numScenes
		_loadScene(inactiveInput, sceneFiles[nextSceneIdx])
		scriptOp.storage['preloaded'] = True

		# Start rest position regeneration countdown
		scriptOp.storage['regenCountdown'] = REST_REGEN_DELAY_FRAMES

	# --- Handle rest position regeneration delay ---
	if regenCountdown > 0:
		scriptOp.storage['regenCountdown'] = regenCountdown - 1
	elif regenCountdown == 0:
		scriptOp.storage['regenCountdown'] = -1
		_regenerateRestPositions()

	# --- Start blend when timer is near the end (last 10% of cycle) ---
	if not blending and blendReady and fraction >= 0.9 and preloaded:
		scriptOp.storage['blending'] = True
		scriptOp.storage['blendStartTime'] = now
		scriptOp.storage['blendReady'] = False  # disarm until next mid-cycle
		blending = True

	# --- Compute switch index using wall-clock time for blend ---
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
		else:
			blendFraction = _smoothstep(elapsed / BLEND_DURATION)
			inactiveInput = 1 - activeInput
			switchIndex = activeInput + (inactiveInput - activeInput) * blendFraction
	else:
		switchIndex = float(activeInput)

	# --- Output channels ---
	nextSceneIdx = (currentSceneIdx + 1) % numScenes
	scriptOp.appendChan('switchIndex')[0] = switchIndex
	scriptOp.appendChan('sceneIndex')[0] = currentSceneIdx
	scriptOp.appendChan('nextSceneIndex')[0] = nextSceneIdx


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


def _regenerateRestPositions():
	"""Pulse the rest_pos_script's Regenerate parameter to update rest positions."""
	restScriptTop = op('/GaussianSplatting/GaussianSplatPOP/rest_pos_script')

	if restScriptTop is None:
		print("[gallery_rotation] WARNING: Could not find rest_pos_script")
		return

	restScriptTop.storage['dirty'] = True
	restScriptTop.cook(force=True)
	print("[gallery_rotation] Triggered rest_pos_script regeneration")


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
