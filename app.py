from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__)
#Omogućavamo SocketIO i dopuštamo konekcije sa bilo koje adrese
socketio = SocketIO(app, cors_allowed_origins="*")

#1. Ruta koja otvara sajt
@app.route('/')
def index():
    return render_template('index.html')

#2. Slušalac za BPM podatke koji stižu iz sub.py
@socketio.on('update_bpm')
def handle_bpm(data):
    emit('update_bpm', data, broadcast=True)

#3. Slušalac za SpO2 podatke koji stižu iz sub.py
@socketio.on('update_spo2')
def handle_spo2(data):
    emit('update_spo2', data, broadcast=True)

#4. Slušalac za niz tačaka za PPG grafik koji stiže iz sub.py
@socketio.on('new_ppg_data')
def handle_ppg(data):
    emit('new_ppg_data', data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
