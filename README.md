# python-ibft
Python implementation of Istanbul BFT algorithm using Flask. Experimental

## Requirements

Needs python3, flask, tmux (for ```run*.sh``` scripts)

## Testing

Run
```bash
./run.sh
```
to try it out; tmux required.
Several scripts to experiment with defective parties are included in ```run*.sh```.

## More info

Implements the Istanbul BFT algorithm according to this paper: https://arxiv.org/abs/2002.03613