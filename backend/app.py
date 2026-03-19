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
from zoneinfo import ZoneInfo

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
# ---------------- QUICK CHECK BASELINE (REAL DATA BASED) ----------------
QUICK_RELAXED = {
    "mean": 1.640662914168287e-16,
    "std": 0.013799393413754833,
    "rms": 0.013799393413754833,
    "range": 0.058143224790888626,
    "mean_abs_diff": 0.003267960868277482,
    "peak_rate": 0.17777777777777778,
    "area": -6.034567901218251e-05
}

QUICK_STRESS = {
    "mean": 1.4124504035508935e-16,
    "std": 0.05865590802078477,
    "rms": 0.05865590802078476,
    "range": 0.27455273434365246,
    "mean_abs_diff": 0.006118999479430791,
    "peak_rate": 0.06111111111111111,
    "area": 0.0005547716049384125
}
# create csv file for continuous recording
dataset_path = os.path.join(os.path.dirname(__file__), "gsr_dataset.csv")
with open(dataset_path, "a", newline="") as f:
    writer = csv.writer(f)
    if f.tell() == 0:
        writer.writerow(["timestamp", "value", "label"])

# ---------------- FEATURE EXTRACTION ----------------
def extract_features(signal):
    if len(signal) == 0:
        return {key: 0 for key in ["mean","std","rms","range","mean_abs_diff","peak_rate","area"]}
    signal = np.array(signal)
    features = {}

    features["mean"] = float(np.mean(signal))
    features["std"] = float(np.std(signal))
    features["rms"] = float(np.sqrt(np.mean(signal**2)))
    features["range"] = float(np.max(signal) - np.min(signal))

    derivative = np.diff(signal)
    features["mean_abs_diff"] = float(np.mean(np.abs(derivative)))

    peaks, _ = find_peaks(signal, prominence=np.std(signal) * 0.2)
    peak_count = len(peaks)

    # 🔥 Normalize (VERY IMPORTANT)
    features["peak_rate"] = float(peak_count / len(signal))
    features["area"] = float(trapezoid(signal) / len(signal))

    return features
def window_features(signal, window_size=200, step=100):
    if len(signal) < 10:
        return extract_features(signal)
    features_list = []

    for i in range(0, len(signal) - window_size + 1, step):
        window = signal[i:i+window_size]
        features_list.append(extract_features(window))

    if not features_list:
        return extract_features(signal)

    # average features
    avg_features = {}
    for key in features_list[0]:
        avg_features[key] = float(np.mean([f[key] for f in features_list]))

    return avg_features
# ---------------- CORE ROUTES (app.py) ----------------
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return render_template("home.html")   # 👈 NEW PAGE

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
            "created_at": datetime.now(ZoneInfo("Asia/Kolkata")),
            "updated_at": datetime.now(ZoneInfo("Asia/Kolkata"))
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

        relaxed_features = window_features(relaxed_signal)
        stress_features = window_features(stress_signal)

        calibration.update_one(
            {"user_id": session["user_id"]},
            {"$set": {
                "relaxed_features": relaxed_features,
                "stress_reference": stress_features,
                "updated_at": datetime.now(ZoneInfo("Asia/Kolkata"))
            }},
            upsert=True
        )
        return redirect("/dashboard")
    return render_template("calibration.html")

@app.route("/check", methods=["GET", "POST"])
def check_stress():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "GET":
        return render_template("check.html")

    cal = calibration.find_one({"user_id": session["user_id"]})

    if not cal:
        return "Please calibrate first."

    # ---------------- BASELINE ----------------
    baseline_source = request.form.get("baseline_source")

    if baseline_source == "saved":
        relaxed = cal.get("relaxed_features")
        stress = cal.get("stress_reference")

        if not relaxed or not stress:
            return "Calibration incomplete. Please recalibrate.", 400

    else:
        baseline_file = request.files.get("baseline_file")
        if not baseline_file:
            return "Please upload baseline file", 400

        df = pd.read_csv(baseline_file)
        signal = detrend(
            pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna().values
        )

        relaxed = window_features(signal)

        stress = cal.get("stress_reference")
        if not stress:
            return "Stress reference missing. Please calibrate properly.", 400

    # ---------------- TEST SIGNAL ----------------
    source = request.form.get("test_source")

    if source == "file":
        test_file = request.files.get("test")
        if not test_file:
            return "Please upload test CSV", 400

        df = pd.read_csv(test_file)
        test_signal = detrend(
            pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna().values
        )

    else:
        raw_values = request.form.get("live_data")
        if not raw_values:
            return "Live recording missing. Press START first.", 400

        values = json.loads(raw_values)
        if not values or len(values) < 20:
            return "Not enough live data collected.", 400

        test_signal = detrend(np.array(values))

    # ---------------- FEATURE EXTRACTION ----------------
    test_features = window_features(test_signal)

    important_features = [
        "mean",
        "std",
        "rms",
        "peak_rate",
        "area",
        "mean_abs_diff"
    ]

    score = 0

    for key in important_features:
        r = relaxed.get(key, 0)
        s = stress.get(key, 0)
        test_val = test_features.get(key, 0)

        eps = 1e-6
        dist_relaxed = abs(test_val - r) + eps
        dist_stress = abs(test_val - s) + eps

        # ✅ CORRECT LOGIC
        score += dist_stress / (dist_relaxed + dist_stress)

    stress_ratio = score / len(important_features)
    stress_ratio = round(stress_ratio, 3)

    # ---------------- CLASSIFICATION ----------------
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
    trigger_breathing = False

    if stress_ratio >= 0.40:
     trigger_breathing = True
    # ---------------- SAVE REPORT ----------------
    reports.insert_one({
        "user_id": session["user_id"],
        "stress_ratio": float(stress_ratio),
        "level": level,
        "timestamp": datetime.now(ZoneInfo("Asia/Kolkata"))
    })

    return render_template("result.html", index=stress_ratio, level=level, trigger_breathing=trigger_breathing)
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
        return "File missing", 400

    # ---------------- LOAD & CLEAN ----------------
    df = pd.read_csv(test_file)
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna().values

    if len(values) == 0:
        return "Invalid or empty signal", 400

    signal = detrend(values)

    # ---------------- FEATURES ----------------
    test_features = window_features(signal)

    cal = calibration.find_one({"user_id": session["user_id"]})

    if not cal or "relaxed_features" not in cal:
        return "Calibration missing. Please calibrate first.", 400

    baseline = cal["relaxed_features"]

    variations = {}

    # ---------------- COMPUTE VARIATION ----------------
    for key in baseline:
        base = baseline.get(key, 0)
        test = test_features.get(key, 0)

        change = (test - base) / (abs(base) + 1e-6)
        variations[key] = round(change, 3)

    return render_template("variation.html", variations=variations)

@app.route("/record_voltage", methods=["POST"])
def record_voltage():
    if "user_id" not in session:
        return {"error": "Unauthorized"}, 403

    data = request.json

    if not data:
        return {"error": "No data received"}, 400

    values = data.get("values")

    if not values or not isinstance(values, list):
        return {"error": "Invalid values"}, 400

    if len(values) < 5:
        return {"error": "Not enough data"}, 400

    try:
        signal = detrend(np.array(values, dtype=float))
    except:
        return {"error": "Invalid numeric data"}, 400

    features = window_features(signal)

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
        return jsonify({"error": "not logged in"}), 403

    data = request.json

    # ---------------- VALIDATION ----------------
    if not data or "relaxed" not in data or "stress" not in data:
        return jsonify({"error": "Invalid data"}), 400

    relaxed_values = data.get("relaxed")
    stress_values = data.get("stress")

    if not isinstance(relaxed_values, list) or not isinstance(stress_values, list):
        return jsonify({"error": "Data must be lists"}), 400

    if len(relaxed_values) < 10 or len(stress_values) < 10:
        return jsonify({"error": "Not enough data"}), 400

    # ---------------- SAFE CONVERSION ----------------
    try:
        relaxed_values = np.array(relaxed_values, dtype=float)
        stress_values = np.array(stress_values, dtype=float)
    except:
        return jsonify({"error": "Invalid numeric values"}), 400

    # ---------------- SIGNAL PROCESSING ----------------
    relaxed_signal = detrend(relaxed_values)
    stress_signal = detrend(stress_values)

    # ---------------- FEATURE EXTRACTION ----------------
    relaxed_features = window_features(relaxed_signal)
    stress_features = window_features(stress_signal)

    # ---------------- DELTA (OPTIONAL USE) ----------------
    delta_thresholds = {}
    for key in relaxed_features:
        delta_thresholds[key] = abs(
            stress_features.get(key, 0) - relaxed_features.get(key, 0)
        )

    # ---------------- SAVE ----------------
    calibration.update_one(
        {"user_id": session["user_id"]},
        {"$set": {
            "relaxed_features": relaxed_features,
            "stress_reference": stress_features,
            "delta_thresholds": delta_thresholds,
            "updated_at": datetime.now(ZoneInfo("Asia/Kolkata"))
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

    data = request.json

    # ---------------- VALIDATION ----------------
    if not data:
        return jsonify({"error": "No data received"}), 400

    if "value" not in data or "time" not in data:
        return jsonify({"error": "Missing fields"}), 400

    value = data.get("value")
    timestamp = data.get("time")

    # ---------------- TYPE CHECK ----------------
    try:
        value = float(value)
    except:
        return jsonify({"error": "Invalid value"}), 400

    # ---------------- STORE IN MEMORY ----------------
    gsr_data.append(value)
    labels.append(current_label)

    # limit buffer size
    if len(gsr_data) > 500:
        gsr_data.pop(0)
        labels.pop(0)

    # ---------------- SAVE TO CSV ----------------
    try:
        with open(dataset_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, value, current_label])
    except Exception as e:
        return jsonify({"error": "File write failed"}), 500

    return jsonify({"status": "ok"})
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
@app.route("/quick_check", methods=["GET", "POST"])
def quick_check():

    if request.method == "GET":
        return render_template("quick_check.html")

    # -------- LIVE DATA ONLY --------
    raw_values = request.form.get("live_data")

    if not raw_values:
        return "No live data received", 400

    values = json.loads(raw_values)

    if len(values) < 20:
        return "Not enough data collected", 400

    signal = detrend(np.array(values))

    # -------- FEATURES --------
    test_features = window_features(signal)

    relaxed = QUICK_RELAXED
    stress = QUICK_STRESS

    important_features = [
        "mean","std","rms","range",
        "peak_rate","area","mean_abs_diff"
    ]

    score = 0

    for key in important_features:
        r = relaxed.get(key, 0)
        s = stress.get(key, 0)
        t = test_features.get(key, 0)

        d_r = abs(t - r) + 1e-6
        d_s = abs(t - s) + 1e-6

        score += d_s / (d_r + d_s)

    stress_ratio = round(score / len(important_features), 3)

    # -------- CLASSIFICATION --------
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

    return render_template(
        "quick_result.html",
        index=stress_ratio,
        level=level
    )
# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)