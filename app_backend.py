from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import json
import threading
from death_switch_system import DeathSwitchAI

app = Flask(__name__)
CORS(app)

dsa = DeathSwitchAI("config.json")

@app.route("/")
def index():
    return send_from_directory('.', 'complete_web_interface.html')

@app.route("/status", methods=["GET"])
def get_status():
    last_activity = dsa.db.get_last_activity()
    return jsonify({
        "system": "active",
        "last_activity": str(last_activity),
        "days_remaining": dsa.inactivity_days
    })

@app.route("/record-activity", methods=["POST"])
def record_activity():
    dsa.db.log_activity("manual_check_in", notes="User triggered manual check-in via web UI")
    return jsonify({"status": "success"})

@app.route("/kill-switch", methods=["POST"])
def kill_switch():
    data = request.get_json()
    user_code = data.get("code")
    with open("kill_switch.hash", "r") as f:
        stored_hash = f.read()
    if dsa.security.verify_kill_switch(user_code, stored_hash):
        dsa.trigger_activated = False
        return jsonify({"status": "kill switch accepted"})
    else:
        return jsonify({"status": "invalid code"}), 401

@app.route("/add-recipient", methods=["POST"])
def add_recipient():
    data = request.get_json()
    recipients_path = os.path.join("config", "recipients.json")
    recipients = []
    if os.path.exists(recipients_path):
        with open(recipients_path, "r") as f:
            recipients = json.load(f)
    recipients.append(data)
    with open(recipients_path, "w") as f:
        json.dump(recipients, f, indent=4)
    return jsonify({"status": "recipient added"})

@app.route("/upload-document", methods=["POST"])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    filename = file.filename
    save_path = os.path.join("secure_docs", filename)
    file.save(save_path)
    return jsonify({"status": "file saved", "file": filename})

@app.route("/documents/<filename>", methods=["GET"])
def serve_document(filename):
    return send_from_directory("secure_docs", filename)

@app.route("/start-trigger", methods=["POST"])
def start_trigger():
    thread = threading.Thread(target=dsa.run)
    thread.start()
    return jsonify({"status": "Death switch trigger started"})

if __name__ == '__main__':
    app.run(debug=True)
