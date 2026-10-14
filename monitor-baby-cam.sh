#!/bin/bash

while true
do
    date
    wget http://192.168.1.219:8080 -O - -S -q --timeout=5 2>/dev/null
    if [[ $? -ne 0 ]] 
    then 
        echo "Baby cam Audio DOWN"
    else 
        echo ""
    fi
    ping 192.168.1.240 -c 1 -q >/dev/null
    if [[ $? -eq 0 ]] 
    then 
        echo "Baby cam UP"
    else 
        echo "Baby cam DOWN"
    fi
    sleep 10
done > baby-cam-batt-test.txt

