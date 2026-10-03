# Record audio from the ESP32 baby cam and save it to a file
timeout 10 wget http://192.168.1.219/audio -O audio.pcm

#Playback the audio file using ffplay
ffplay -f s16le -ar 16000 -ac 1 audio.pcm
