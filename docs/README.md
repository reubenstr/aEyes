# Workflow

## Eyes

- Edit eye code on `eye1.local`.
- Use `aEyes/scripts/pull-eye-code.sh` to copy code from the eye to the controller.
- Use `aEyes/scripts/sync-eye-code.sh` to copy eye code from the controller to all eyes.
- Commit and push changes to Git as normal.

# Afterthoughts

- Wires run through the pitch rotation axis. Since the pitch angle is typically shallow, there should not be excessive stress on the wires. However, if communication or power issues begin to occur, a slip ring may need to be installed.

- The motors are currently very expensive, and cheaper, more readily available alternatives exist, such as the RobStride EL05 (e.g., available from seeedstudio.com). However, the motor may be too large for the eye's current design. A redesign should be able to accommodate the larger motor without sacrificing too much aesthetically.