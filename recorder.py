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
<!DOCTYPE html>
<html>
<head>
    <title>Audio Recorder</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <!-- Include Tailwind CSS from CDN -->
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
</head>
<body class="bg-gray-100 p-4 font-sans">
    <h1 class="text-2xl font-bold text-gray-800">Audio Recorder</h1>
    <label for="device" class="block text-lg text-gray-700 mt-4">Choose a device:</label>
    <select id="device" class="block w-full p-3 mt-2 bg-white border border-gray-300 rounded-md">
        {{ options|safe }}
    </select>
    <label for="channels" class="block text-lg text-gray-700 mt-4">Number of Channels:</label>
    <select id="channels" class="block w-full p-3 mt-2 bg-white border border-gray-300 rounded-md">
        <option value="1" selected>1 (Mono)</option>
        <option value="2">2 (Stereo)</option>
    </select>
    <p id="messages" class="mt-4 text-red-500">
        {% if recording_in_progress %}
            <b>Recording in progress!</b>
        {% endif %}
    </p>
    <button onclick="startRecording()" class="w-full py-3 px-4 mt-4 bg-green-500 text-white rounded-md hover:bg-green-600 focus:outline-none focus:bg-green-600">
        Start Recording
    </button>
    <button onclick="stopRecording()" class="w-full py-3 px-4 mt-4 bg-red-500 text-white rounded-md hover:bg-red-600 focus:outline-none focus:bg-red-600">
        Stop Recording
    </button>
    <h2 class="text-xl font-bold text-gray-800 mt-6">Recorded Files</h2>
    <table class="w-full mt-4 border-collapse border border-gray-300">
        <tr>
            <th class="border border-gray-300 p-2">File Name</th>
            <th class="border border-gray-300 p-2">Action</th>
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
                    document.getElementById('messages').innerHTML = body;
                });
        }
        function stopRecording() {
            fetch('/stop')
                .then((resp) => resp.text())
                .then((body) => {
                    document.getElementById('messages').innerHTML = body;
                });
        }
    </script>
</body>
</html>

    """

# Check if the folder is writable
recordings_folder = os.environ.get('RECORDINGS_PATH', 'recordings')
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
            f'<tr><td>{f}</td><td><a class="text-indigo-500" href="/download/{f}">Download</a></td></tr>'
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
    app.run(host="0.0.0.0", port=8080, debug=True)
