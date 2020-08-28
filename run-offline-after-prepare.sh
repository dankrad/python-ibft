#!/bin/bash

tmux \
  new-session  "python ibft.py 0 --offline-after-prepare; read" \; \
  split-window "python ibft.py 1 --online-delayed; read" \; \
  split-window "python ibft.py 2; read" \; \
  split-window "python ibft.py 3; read" \; \
  split-window "bash start.sh --retry; read" \; \
  select-layout tiled