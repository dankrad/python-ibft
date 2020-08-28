#!/bin/bash

tmux \
  new-session  "python ibft.py 0 --offline-delayed; read" \; \
  split-window "python ibft.py 1 --online-delayed; read" \; \
  split-window "python ibft.py 2 --online-delayed; read" \; \
  split-window "python ibft.py 3; read" \; \
  split-window "bash start.sh --retry; read" \; \
  select-layout tiled