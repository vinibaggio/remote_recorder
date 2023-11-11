import argparse
import os
import sys
import threading
import datetime
from flask import Flask, render_template_string, send_from_directory, request
import sounddevice as sd
import numpy as np
import soundfile as sf

# Parse CLI arguments
parser = argparse.ArgumentParser(description="Audio Recorder Web Application")
parser.add_argument("--folder", type=str, default="recordings", help="Folder to store recordings")
args = parser.parse_args()

# Check if the folder is writable
recordings_folder = args.folder
if not os.path.exists(recordings_folder):
    try:
        os.makedirs(recordings_folder)
    except OSError:
        print(f"Cannot create folder: {recordings_folder}")
        sys.exit(1)
elif not os.access(recordings_folder, os.W_OK):
    print(f"Folder is not writable: {recordings_folder}")
    sys.exit(1)

app = Flask(__name__)

# Audio recording parameters
FORMAT = 'float32'  # sounddevice uses float32
CHANNELS = 2
RATE = 44100
CHUNK = 1024
DTYPE = np.float32  # Match the NumPy dtype to the sounddevice format

# Global variables
recording_thread = None
stop_event = None
frames = []

def get_input_devices():
    devices = sd.query_devices()
    input_devices = [(i, device['name'], device['max_input_channels']) for i, device in enumerate(devices) if device['max_input_channels'] > 0]
    return input_devices

def record_audio(device_index, channels):
    global frames, stop_event
    frames = []
    # silence_threshold = 0.001  # Define a threshold for silence (this might need adjustment)
    # max_silence_duration = 3600  # 1 hour in seconds
    # silence_duration = 0

    def callback(indata, frame_count, time, status):
        global silence_duration
        if status:
            print(status)
        if stop_event.is_set():
            raise sd.CallbackAbort

        # rms_value = np.sqrt(np.mean(indata**2))
        # if rms_value < silence_threshold:
        #     silence_duration += frame_count / RATE
        #     if silence_duration >= max_silence_duration:
        #         print("Silence detected for 1 hour, stopping recording.")
        #         stop_event.set()
        #         raise sd.CallbackAbort
        # else:
        #     silence_duration = 0
        frames.append(indata.copy())

    with sd.InputStream(device=device_index, channels=channels, samplerate=RATE, callback=callback):
        while not stop_event.is_set():
            sd.sleep(1000)  # Wait for a second at a time; this can be adjusted

@app.route('/', methods=['GET'])
def index():
    devices = get_input_devices()
    options = ''.join([f'<option value="{i}">{name} (Max Channels: {channels})</option>' for i, name, channels in devices])
    recording_in_progress = False
    if recording_thread is not None and recording_thread.is_alive():
        recording_in_progress = True
    files = [f for f in os.listdir(recordings_folder) if f.endswith('.wav')]
    files_table = ''.join([f'<tr><td>{f}</td><td><a href="/download/{f}">Download</a></td></tr>' for f in files])
    return render_template_string('''
    <html>
        <body>
            <h1>Audio Recorder</h1>
            <label for="device">Choose a device:</label>
            <select id="device">
                {{ options|safe }}
            </select>
            <label for="channels">Number of Channels:</label>
            <select id="channels">
                <option value="1">1 (Mono)</option>
                <option value="2" selected>2 (Stereo)</option>
            </select>
            {% if recording_in_progress %}
            <p>
                <b>Recording in progress!</b>
            </p>
            {% endif %}
            <p>
            <button onclick="startRecording()">Start Recording</button>
            <button onclick="stopRecording()">Stop Recording</button>
            </p>
            <h2>Recorded Files</h2>
            <table>
                <tr>
                    <th>File Name</th>
                    <th>Action</th>
                </tr>
                {{ files_table|safe }}
            </table>
            <script>
                function startRecording() {
                    var device = document.getElementById('device').value;
                    var channels = document.getElementById('channels').value;
                    fetch(`/start?device=${device}&channels=${channels}`);
                }
                function stopRecording() {
                    fetch('/stop')// .then(() => window.location.reload());
                }
            </script>
        </body>
    </html>
    ''', options=options, files_table=files_table, recording_in_progress=recording_in_progress)

@app.route('/start', methods=['GET'])
def start():
    global recording_thread, stop_event
    device_index = int(request.args.get('device', 0))
    channels = int(request.args.get('channels', 2))
    print(recording_thread)
    if recording_thread is None or not recording_thread.is_alive():
        stop_event = threading.Event()
        recording_thread = threading.Thread(target=record_audio, args=(device_index,channels,))
        recording_thread.start()
        return render_template_string('<html><body><h1>Recording Started</h1></body></html>')
    else:
        return render_template_string('<html><body><h1>Recording is already in progress</h1></body></html>')

@app.route('/stop', methods=['GET'])
def stop():
    global frames, stop_event, recording_thread
    if recording_thread and recording_thread.is_alive():
        stop_event.set()  # Signal the thread to stop
        recording_thread.join()  # Wait for the recording thread to finish
        recording_thread = None  # Reset the thread variable

        # Save the recording
        file_name = os.path.join(recordings_folder, datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".wav")
        sf.write(file_name, np.concatenate(frames), RATE)
        frames = []  # Clear frames to free memory
        return render_template_string('<html><body><h1>Recording Stopped</h1></body></html>')
    else:
        return render_template_string('<html><body><h1>No active recording to stop</h1></body></html>')

@app.route('/download/<filename>', methods=['GET'])
def download(filename):
    return send_from_directory(recordings_folder, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)

