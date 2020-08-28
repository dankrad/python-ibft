#!/bin/bash

sleep 5

for i in `seq 5000 5003`; do 
    curl http://localhost:$i/start -d '{"lambda":0, "value": "decide this"}' -H "Content-Type: application/json"
done


if [[ "$1" == "--retry" ]] ; then
    echo 'Will retry after 61 seconds'
    sleep 61

    for i in `seq 5000 5003`; do 
        curl http://localhost:$i/start -d '{"lambda":0, "value": "decide this"}' -H "Content-Type: application/json"
    done
fi

read

tmux kill-session