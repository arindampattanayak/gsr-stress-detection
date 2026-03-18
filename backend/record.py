from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import numpy as np
import csv
import time
from flask import send_file
from scipy.signal import find_peaks
from flask import send_file
import os

app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend",
    static_url_path=""
)
CORS(app)

gsr_data = []
labels = []

WINDOW_SIZE = 50
current_label = 0

# create csv file
with open("gsr_dataset.csv","a",newline="") as f:
    writer = csv.writer(f)
    if f.tell()==0:
        writer.writerow(["timestamp","value","label"])


@app.route('/')
def index():
    return render_template("index.html")


# receive sensor data
@app.route('/data', methods=['POST'])
def receive_data():

    global current_label

    value = request.json['value']
    timestamp = request.json['time']

    gsr_data.append(value)
    labels.append(current_label)

    if len(gsr_data)>500:
        gsr_data.pop(0)
        labels.pop(0)

    # save csv
    with open("gsr_dataset.csv","a",newline="") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp,value,current_label])

    return jsonify({"status":"ok"})


# set label
@app.route('/set_label', methods=['POST'])
def set_label():

    global current_label

    current_label = request.json['label']

    return jsonify({"label":current_label})


# send signal
@app.route('/get_data')
def get_data():
    return jsonify(gsr_data)


# feature extraction
@app.route('/get_features')
def get_features():

    if len(gsr_data)<WINDOW_SIZE:
        return jsonify({})

    window = np.array(gsr_data[-WINDOW_SIZE:])

    mean = float(np.mean(window))
    std = float(np.std(window))
    slope = float(np.polyfit(range(len(window)),window,1)[0])

    peaks,_ = find_peaks(window,distance=5)

    peak_count = int(len(peaks))

    rise_time = float(peaks[0]) if peak_count>0 else 0

    scr = float(np.max(window)-np.min(window))

    return jsonify({
        "mean":mean,
        "std":std,
        "slope":slope,
        "peak_count":peak_count,
        "rise_time":rise_time,
        "scr":scr
    })


@app.route("/download")
def download():
    return send_file("gsr_dataset.csv", as_attachment=True)


@app.route("/gsr_dataset.csv")
def download_dataset():
    return send_file("gsr_dataset.csv", as_attachment=True)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port)
