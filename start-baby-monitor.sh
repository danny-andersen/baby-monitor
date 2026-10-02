#!/bin/bash
while $(sleep 10); do
  echo "waiting for systemd to finish booting..."
  if systemctl is-system-running | grep -qE "running|degraded"; then
    break
  fi
done
#System should be ready now
#Wait a bit more to ensure all services are up, including networking and display manager
sleep 10
export DISPLAY=:0
source venv/bin/activate
python baby-monitor.py
