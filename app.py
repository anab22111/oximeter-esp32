from flask import Flask, render_template
from flask_socketio import SocketIO, emit

"""
Ovo je uproscena, test verzija web servera bez MQTT logike.
Kompletna verzija se nalazi u sub.py, koja pored web servera 
pokrece i MQTT klijenta, alarm i logiku snimanja u fajl.
Ovaj fajl je koristan za testiranje web interfejsa odvojeno od hardvera.
"""

app = Flask(__name__)

# Omogucavamo SocketIO i dopustamo konekcije sa bilo koje adrese
socketio = SocketIO(app, cors_allowed_origins="*")

# 1. Ruta koja otvara sajt
@app.route('/')
def index():
    return render_template('index.html')

# 2. Slusalac za BPM podatke koji stizu iz sub.py
# Prima 'update_bpm' event i prosledjuje ga svim konektovanim browser-ima (broadcast=True)
@socketio.on('update_bpm')
def handle_bpm(data):
    emit('update_bpm', data, broadcast=True)

# 3. Slusalac za SpO2 podatke koji stizu iz sub.py
# Prima 'update_spo2' event i prosledjuje ga svim konektovanim browser-ima (broadcast=True)
@socketio.on('update_spo2')
def handle_spo2(data):
    emit('update_spo2', data, broadcast=True)

# 4. Slusalac za niz tacaka za PPG grafik koji stize iz sub.py
# # Prima 'new_ppg_data' event sa nizom od 200 filtriranih IR vrednosti 
# i prosledjuje ga svim konektovanim browser-ima (broadcast=True)
@socketio.on('new_ppg_data')
def handle_ppg(data):
    emit('new_ppg_data', data, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
