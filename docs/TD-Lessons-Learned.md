# TouchDesigner Lessons Learned

## Script CHOP: Never Force-Cook Other Operators During onCook

**Problem**: Calling `someOp.cook(force=True)` from inside a Script CHOP's `onCook` triggers a cascading cook. Because `scriptOp.clear()` has already removed all output channels, any operator that tries to read this Script CHOP's channels during the cascade will get `None` instead of the expected value.

**Symptom we hit**: A Switch POP's Index parameter was bound to the Script CHOP's `switchIndex` channel. During the cascade, it read `None`, threw `TypeError: float() argument must be a string or a real number, not 'NoneType'`, and fell back to input 0. This meant the rest position texture was always captured from input 0, causing displacement to map to the wrong splats for every scene on input 1.

**Debugging clue**: The bug appeared to be per-file (some scenes had broken displacement, others worked). Mapping the working/broken pattern to the scene rotation order revealed a perfect correlation with the Switch POP input index — every working scene was on input 0, every broken scene on input 1.

**Fix**: Use `run("...", delayFrames=1)` to defer the force-cook to the next frame, after the Script CHOP has finished cooking and all channels are available.

**Fix (partial)**: Use `run("...", delayFrames=1)` to defer force-cooks to the next frame:

```python
# BAD - cascading cook reads cleared channels
def _setRestPositions():
    restScriptTop = op('/path/to/rest_pos_script')
    restScriptTop.storage['dirty'] = True
    restScriptTop.cook(force=True)  # cascade causes Switch POP to get None

# GOOD - deferred cook runs after Script CHOP finishes
def _setRestPositions():
    restScriptTop = op('/path/to/rest_pos_script')
    restScriptTop.storage['dirty'] = True
    run("op('/path/to/rest_pos_script').cook(force=True)", delayFrames=1)
```

**Fix (complete)**: Even with deferred cooks, `scriptOp.clear()` at the top of `onCook` causes problems — ANY operation that reads from operators downstream of this Script CHOP (fingerprinting via `pop.points()`, pulsing feedback resets, loading scene files) can cascade back and hit the missing channels.

The real fix: move `scriptOp.clear()` to the very end of `onCook`, right before creating channels. All computation and side effects run while the old channels are still visible. Extract channel output into a helper:

```python
def _outputChannels(scriptOp, switchIndex, ...):
    # clear + recreate as one tight block — the LAST thing in onCook
    scriptOp.clear()
    scriptOp.appendChan('switchIndex')[0] = switchIndex
    # ... all other channels ...

def onCook(scriptOp):
    # NO scriptOp.clear() here — old channels remain visible during cook
    # ... all computation, side effects, cascading reads ...
    _outputChannels(scriptOp, switchIndex, ...)  # very last line
```
