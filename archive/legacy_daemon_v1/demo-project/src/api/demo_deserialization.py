import json
from flask import Flask, request

app = Flask(__name__)

@app.route('/load_profile', methods=['POST'])
def load_profile():
    data = request.get_json()
    profile = json.loads(data)
    return f"Welcome back, {profile['username']}"
