#!/bin/bash
#System should be ready now
#Wait a bit more to ensure all services are up, including networking and display manager
sleep 10
export DISPLAY=:0
source venv/bin/activate
python baby-monitor.py
