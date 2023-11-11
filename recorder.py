import argparse
import asyncio
import datetime
import logging
import os
import sys
from threading import Thread

import numpy as np
import sounddevice as sd
import soundfile as sf
from flask import Flask, render_template_string, request, send_from_directory

TEMPLATE = """
    <html>
        <body>
            <h1>Audio Recorder</h1>
            <label for="device">Choose a device:</label>
            <select id="device">
                {{ options|safe }}
            </select>
            <label for="channels">Number of Channels:</label>
            <select id="channels">
                <option value="1" selected>1 (Mono)</option>
                <option value="2">2 (Stereo)</option>
            </select>
            <p id="messages">
                {% if recording_in_progress %}
                    <b>Recording in progress!</b>
                {% endif %}
            </p>
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
                    fetch(`/start?device=${device}&channels=${channels}`)
                        .then((resp) => resp.text())
                        .then((body) => {
                            document.getElementById('messages').innerHTML = body
                        });
                }
                function stopRecording() {
                    fetch('/stop')
                        .then((resp) => resp.text())
                        .then((body) => {
                            document.getElementById('messages').innerHTML = body
                        });
                }
            </script>
        </body>
    </html>
    """

# Parse CLI arguments
parser = argparse.ArgumentParser(description="Audio Recorder Web Application")
parser.add_argument(
    "--folder", type=str, default="recordings", help="Folder to store recordings"
)
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

# Global variables
RATE = 44100
async_recorder = None
loop = asyncio.new_event_loop()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("recorder")


class AsyncAudioRecorder:
    def __init__(self, channels, device_index, samplerate=44100, buffer_size=1024):
        self.filename = generate_filename()
        self.samplerate = samplerate
        self.channels = channels
        self.buffer_size = buffer_size
        self.recording = False
        self.device_index = device_index
        self.buffer = []

    async def record(self):
        self.recording = True
        with sf.SoundFile(
            self.filename,
            mode="w",
            samplerate=self.samplerate,
            channels=self.channels,
            format="FLAC",
        ) as file:
            with sd.InputStream(
                device=self.device_index,
                samplerate=self.samplerate,
                channels=self.channels,
                callback=self.audio_callback,
            ):
                while self.recording:
                    await asyncio.sleep(0.1)
                    if len(self.buffer) >= self.buffer_size:
                        data = np.concatenate(self.buffer, axis=0)
                        file.write(data)
                        self.buffer = []

    def audio_callback(self, indata, frames, time, status):
        self.buffer.append(indata.copy())

    def stop(self):
        self.recording = False


def get_input_devices():
    devices = sd.query_devices()
    input_devices = [
        (i, device["name"], device["max_input_channels"])
        for i, device in enumerate(devices)
        if device["max_input_channels"] > 0
    ]
    return input_devices


def generate_filename():
    now = datetime.datetime.now()
    return os.path.join(
        recordings_folder,
        now.strftime("%Y%m%d_%H%M%S") + ".flac",
    )


@app.route("/", methods=["GET"])
def index():
    global async_recorder
    devices = get_input_devices()
    options = "".join(
        [
            f'<option value="{i}">{name} (Max Channels: {channels})</option>'
            for i, name, channels in devices
        ]
    )

    recording_in_progress = False
    if async_recorder is not None and async_recorder.recording:
        recording_in_progress = True

    files = [f for f in os.listdir(recordings_folder) if f.endswith(".flac")]
    files_table = "".join(
        [
            f'<tr><td>{f}</td><td><a href="/download/{f}">Download</a></td></tr>'
            for f in files
        ]
    )
    return render_template_string(
        TEMPLATE,
        options=options,
        files_table=files_table,
        recording_in_progress=recording_in_progress,
    )


@app.route("/start", methods=["GET"])
def start():
    global async_recorder

    device_index = int(request.args.get("device", 0))
    channels = int(request.args.get("channels", 2))

    if async_recorder and async_recorder.recording:
        return render_template_string("<b>Recording is already in progress</b>")

    try:
        async_recorder = AsyncAudioRecorder(
            channels=channels, device_index=device_index
        )

        t = Thread(target=loop.run_until_complete, args=(async_recorder.record(),))
        t.start()

        return render_template_string("<b>Recording Started</b>")
    except Exception as e:
        logger.exception(e)
        return render_template_string("<b>" + str(e) + "</b>")


@app.route("/stop", methods=["GET"])
def stop():
    global async_recorder
    if async_recorder is not None:
        async_recorder.stop()
        async_recorder = None

        return render_template_string("<b>Recording Stopped</b>")
    else:
        return render_template_string("<b>No active recording to stop</b>")


@app.route("/download/<filename>", methods=["GET"])
def download(filename):
    return send_from_directory(recordings_folder, filename)


if __name__ == "__main__":
    asyncio.set_event_loop(loop)
    app.run(host="0.0.0.0", port=8080)
