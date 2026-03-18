from flask import Flask, jsonify, render_template, request, redirect, session, send_file
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import bcrypt
import numpy as np
import pandas as pd
from scipy.signal import detrend, find_peaks
from scipy.stats import skew, kurtosis
from scipy.integrate import trapezoid
from config import Config
from datetime import datetime, timezone
import requests
import os
import csv
import time
import json

# ---------------- APP INIT ----------------
app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend",
    static_url_path=""
)
CORS(app)
app.config.from_object(Config)
app.secret_key = app.config["SECRET_KEY"]

# ---------------- DATABASE ----------------
client = MongoClient(app.config["MONGO_URI"])
db = client[app.config["DB_NAME"]]

users = db.users
calibration = db.calibration
reports = db.reports

try:
    client.admin.command('ping')
    print("MongoDB Connected Successfully ✅")
except ConnectionFailure:
    print("MongoDB Connection Failed ❌")

# ---------------- GLOBALS ----------------
live_data = []
recording = False
record_buffer = []
label_mode = 0

gsr_data = []
labels = []
WINDOW_SIZE = 50
current_label = 0

# create csv file for continuous recording
dataset_path = os.path.join(os.path.dirname(__file__), "gsr_dataset.csv")
with open(dataset_path, "a", newline="") as f:
    writer = csv.writer(f)
    if f.tell() == 0:
        writer.writerow(["timestamp", "value", "label"])

# ---------------- FEATURE EXTRACTION ----------------
def extract_features(signal):
    signal = np.array(signal)
    features = {}

    features["mean"] = float(np.mean(signal))
    features["std"] = float(np.std(signal))
    features["rms"] = float(np.sqrt(np.mean(signal**2)))
    features["range"] = float(np.max(signal) - np.min(signal))
    features["skew"] = float(skew(signal))
    features["kurtosis"] = float(kurtosis(signal))

    derivative = np.diff(signal)
    features["diff_std"] = float(np.std(derivative))
    features["mean_abs_diff"] = float(np.mean(np.abs(derivative)))

    peaks, _ = find_peaks(signal, prominence=np.std(signal) * 0.2)
    features["peak_count"] = int(len(peaks))

    features["area"] = float(trapezoid(signal))

    return features

# ---------------- CORE ROUTES (app.py) ----------------
@app.route("/")
def home():
    return redirect("/login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        if users.find_one({"email": email}):
            return "User already exists"

        hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

        users.insert_one({
            "name": name,
            "email": email,
            "password": hashed_pw,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        return redirect("/login")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = users.find_one({"email": email})

        if user and bcrypt.checkpw(password.encode("utf-8"), user["password"]):
            session["user_id"] = str(user["_id"])
            return redirect("/dashboard")

        return "Invalid credentials"
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("dashboard.html")

@app.route("/calibration", methods=["GET", "POST"])
def calibration_page():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":
        relaxed_file = request.files.get("relaxed")
        stress_file = request.files.get("stress")

        if not relaxed_file or not stress_file:
            return "Both files required", 400

        relaxed_df = pd.read_csv(relaxed_file)
        stress_df = pd.read_csv(stress_file)

        relaxed_signal = detrend(
            pd.to_numeric(relaxed_df.iloc[:,1], errors="coerce").dropna().values
        )
        stress_signal = detrend(
            pd.to_numeric(stress_df.iloc[:,1], errors="coerce").dropna().values
        )

        relaxed_features = extract_features(relaxed_signal)
        stress_features = extract_features(stress_signal)

        calibration.update_one(
            {"user_id": session["user_id"]},
            {"$set": {
                "relaxed_features": relaxed_features,
                "stress_reference": stress_features,
                "updated_at": datetime.now(timezone.utc)
            }},
            upsert=True
        )
        return redirect("/dashboard")
    return render_template("calibration.html")

@app.route("/check", methods=["GET","POST"])
def check_stress():
    if "user_id" not in session:
        return redirect("/login")

    if request.method=="GET":
        return render_template("check.html")

    cal = calibration.find_one({"user_id": session["user_id"]})

    if not cal:
        return "Please calibrate first."

    # BASELINE
    baseline_source = request.form.get("baseline_source")
    if baseline_source=="saved":
        baseline_features = cal["relaxed_features"]
    else:
        baseline_file = request.files.get("baseline_file")
        if not baseline_file:
            return "Please upload baseline file",400

        df = pd.read_csv(baseline_file)
        signal = detrend(pd.to_numeric(df.iloc[:,1],errors="coerce").dropna().values)
        baseline_features = extract_features(signal)

    # TEST SIGNAL
    source = request.form.get("test_source")
    if source=="file":
        test_file = request.files.get("test")
        if not test_file:
            return "Please upload test CSV",400

        df = pd.read_csv(test_file)
        test_signal = detrend(pd.to_numeric(df.iloc[:,1],errors="coerce").dropna().values)
    else:
        raw_values = request.form.get("live_data")
        if not raw_values:
            return "Live recording missing. Press START first.",400

        values = json.loads(raw_values)
        if len(values) < 20:
            return "Not enough live data collected.",400
        test_signal = detrend(np.array(values))

    # FEATURE EXTRACTION
    test_features = extract_features(test_signal)
    important_features = ["mean", "std", "rms", "peak_count", "area"]
    score = 0

    for key in important_features:
        base = baseline_features[key]
        test = test_features[key]
        delta = abs(test-base)/(abs(base)+1e-6)
        if delta>0.15:
            score+=1

    stress_ratio = score/len(important_features)

    if stress_ratio > 0.85:
        level = "Extreme Stress"
    elif stress_ratio > 0.70:
        level = "High Stress"
    elif stress_ratio > 0.55:
        level = "Elevated Stress"
    elif stress_ratio > 0.40:
        level = "Moderate Stress"
    elif stress_ratio > 0.25:
        level = "Mild Stress"
    elif stress_ratio > 0.10:
        level = "Very Low Stress"
    else:
        level = "Relaxed"

    # SAVE REPORT
    reports.insert_one({
        "user_id":session["user_id"],
        "stress_ratio":float(stress_ratio),
        "level":level,
        "timestamp":datetime.now(timezone.utc)
    })

    return render_template("result.html", index=stress_ratio, level=level)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/calibration_data")
def calibration_data():
    if "user_id" not in session:
        return redirect("/login")

    cal = calibration.find_one({"user_id": session["user_id"]})
    if not cal:
        return "No calibration found"

    return render_template("calibration_data.html", cal=cal)

@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect("/login")

    user_reports = list(reports.find({"user_id": session["user_id"]}).sort("timestamp", -1))
    return render_template("history.html", reports=user_reports)

@app.route("/history_data")
def history_data():
    if "user_id" not in session:
        return {"error": "Unauthorized"}

    data = list(reports.find({"user_id": session["user_id"]}).sort("timestamp", 1))
    timestamps = []
    stress_values = []

    for d in data:
        timestamps.append(d["timestamp"].strftime("%Y-%m-%d %H:%M"))
        stress_values.append(d["stress_ratio"])

    return {"labels": timestamps, "values": stress_values}

@app.route("/variation", methods=["POST"])
def variation():
    if "user_id" not in session:
        return redirect("/login")

    test_file = request.files.get("test")
    if not test_file:
        return "File missing"

    df = pd.read_csv(test_file)
    signal = detrend(pd.to_numeric(df.iloc[:,1], errors="coerce").dropna().values)
    test_features = extract_features(signal)
    cal = calibration.find_one({"user_id": session["user_id"]})
    baseline = cal["relaxed_features"]
    variations = {}

    for key in baseline:
        base = baseline[key]
        test = test_features[key]
        change = (test - base) / (abs(base) + 1e-6)
        variations[key] = round(change, 3)

    return render_template("variation.html", variations=variations)

@app.route("/record_voltage", methods=["POST"])
def record_voltage():
    if "user_id" not in session:
        return {"error": "Unauthorized"}

    data = request.json
    values = data.get("values")
    signal = detrend(np.array(values))
    features = extract_features(signal)

    return {"features": features}

@app.route('/start_record', methods=['POST'])
def start_record():
    global recording, record_buffer, label_mode
    label_mode = request.json["label"]
    record_buffer = []
    recording = True
    return jsonify({"status":"recording"})

@app.route('/stop_record')
def stop_record():
    global recording
    recording = False
    return jsonify({"status":"stopped"})

@app.route('/save_record')
def save_record():
    os.makedirs("recordings", exist_ok=True)
    filename = f"recordings/gsr_{int(time.time())}.csv"

    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp","value","label"])
        writer.writerows(record_buffer)

    signal = np.array([r[1] for r in record_buffer])
    mean = float(np.mean(signal))
    std = float(np.std(signal))
    slope = float(np.polyfit(range(len(signal)),signal,1)[0])
    peaks,_ = find_peaks(signal,distance=5)
    peak_count = int(len(peaks))
    scr = float(np.max(signal)-np.min(signal))

    return jsonify({
        "file": filename,
        "mean": mean,
        "std": std,
        "slope": slope,
        "peaks": peak_count,
        "scr": scr
    })

@app.route("/save_auto_calibration", methods=["POST"])
def save_auto_calibration():
    if "user_id" not in session:
        return jsonify({"error":"not logged in"}),403

    data = request.json
    relaxed_values = np.array(data["relaxed"])
    stress_values = np.array(data["stress"])

    relaxed_signal = detrend(relaxed_values)
    stress_signal = detrend(stress_values)

    relaxed_features = extract_features(relaxed_signal)
    stress_features = extract_features(stress_signal)

    delta_thresholds = {}
    for key in relaxed_features:
        delta_thresholds[key] = abs(stress_features[key] - relaxed_features[key])

    calibration.update_one(
        {"user_id": session["user_id"]},
        {"$set":{
            "relaxed_features": relaxed_features,
            "stress_reference": stress_features,
            "delta_thresholds": delta_thresholds,
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )

    return jsonify({
        "relaxed_features": relaxed_features,
        "stress_reference": stress_features,
        "delta_thresholds": delta_thresholds
    })

@app.route("/breathing")
def breathing():
    return render_template("breathing.html")

# ---------------- RECORD ROUTES (from record.py) ----------------
@app.route('/record')
def record_index():
    return render_template("index.html")

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

    with open(dataset_path, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, value, current_label])

    return jsonify({"status":"ok"})

@app.route('/set_label', methods=['POST'])
def set_label():
    global current_label
    current_label = request.json['label']
    return jsonify({"label":current_label})

@app.route('/get_data')
def get_data():
    return jsonify(gsr_data)

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
    return send_file(dataset_path, as_attachment=True)

@app.route("/gsr_dataset.csv")
def download_dataset():
    file_path = os.path.join(os.path.dirname(__file__), "gsr_dataset.csv")
    return send_file(file_path, as_attachment=True)

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)