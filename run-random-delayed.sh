#!/bin/bash

tmux \
  new-session  "python ibft.py 0 --random-values --input-value 'decide this'; read" \; \
  split-window "python ibft.py 1 --online-delayed --input-value 'decide this'; read" \; \
  split-window "python ibft.py 2 --input-value 'decide this'; read" \; \
  split-window "python ibft.py 3 --input-value 'decide this'; read" \; \
  split-window "bash wait.sh; read" \; \
  select-layout tiled