#install dependenciesportaudio19-dev
sudo apt install python3-dev portaudio19-dev 
pip install pyaudio

#List audio devices
aplay -l
wpctl status
wpctl set-volume 35 2.0

# Record audio from the ESP32 baby cam and save it to a file
timeout 10 wget http://192.168.1.219/audio -O audio.pcm

#Playback the audio file using ffplay
ffplay -f s16le -ar 16000 audio.pcm
