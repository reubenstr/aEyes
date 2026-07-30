# Workflow

## Eyes

- Edit eye code on eye1.local
- use aEyes/scripts/pull-eye-code.sh to copy code from eye to controller
- use aEyes/scripts/sync-eye-code.sh to copy eye code from the controller to all eyes
- git commit / push as normal

# After Thoughts

Right now wires are running through the pitch rotation, but since pitch angle is typicall shallow there should not be too much stress on the wires. But, if there are communication issues or power issues, then a slip ring will need to be installed.

The motors are currently very expensive and there are alternatives such as RobStride EL05.