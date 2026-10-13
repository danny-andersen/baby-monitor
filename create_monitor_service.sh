sudo cp baby-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable baby-monitor.service
sudo systemctl restart baby-monitor.service
