import paho.mqtt.client as mqtt
import os
import time
import pygame
import struct
import json
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import neurokit2 as nk
import numpy as np

# =====================================================================
# 1. INICIJALIZACIJA FLASK, SOCKETIO I PYGAME ALARMA
# =====================================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'ppg_tajna'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

pygame.mixer.init()
ZVUK_ALARMA = "oxi.mp3"

try:
    trenutni_folder = os.path.dirname(os.path.abspath(__file__))
    putanja_do_zvuka = os.path.join(trenutni_folder, ZVUK_ALARMA)
    
    if os.path.exists(putanja_do_zvuka):
        pygame.mixer.music.load(putanja_do_zvuka)
        print(f"[USPESNO] Ucitan zvucni fajl: {ZVUK_ALARMA}")
    else:
        print(f"[GRESKA] Fajl '{ZVUK_ALARMA}' nije pronađen u folderu: {trenutni_folder}")
except Exception as e:
    print(f"[GRESKA] Neuspesno ucitavanje zvuka: {e}")

# =====================================================================
# 2. SIGNAL PROCESSOR KLASA
# =====================================================================
class SignalProcessor:
    def __init__(self, sampling_rate=50):
        self.sampling_rate = sampling_rate

    def filter_for_plot(self, ir_niz):
        try:
            if max(ir_niz) == min(ir_niz):
                return [0.0] * len(ir_niz)
            
            signal = np.array(ir_niz)
            cleaned = nk.ppg_clean(signal, sampling_rate=self.sampling_rate, method='elgendi')
            norm_signal = (cleaned - np.min(cleaned)) / (np.max(cleaned) - np.min(cleaned))
            
            # Okrećemo signal da na sajtu pikovi idu prema gore
            norm_signal = 1.0 - norm_signal
            return norm_signal.tolist()
        except Exception:
            return []

procesor = SignalProcessor(sampling_rate=50)
moj_bafer = []

# =====================================================================
# 3. VAŠE PROMENLJIVE ZA SNIMANJE KORISNIKA
# =====================================================================
trenutni_korinsik = input("Unesite ime korisnika: ").strip()
ime_fajla = f"merenje_{trenutni_korinsik}.txt"

TRAJANJE_SNIMANJA = 30 
snimanje_zapoceto = False
snimanje_zavrseno = False
vreme_pocetka_snimanja = 0

svi_validni_bpm = []
svi_validni_spo2 = []
detektovan_zastoj = False

# =====================================================================
# 4. POTPUNO USKLAĐENA LOGIKA OBRADE (MQTT -> Ekran + Fajl + Web sajt)
# =====================================================================
def obradi_binarno(client, userdata, message):
    global snimanje_zapoceto, snimanje_zavrseno, vreme_pocetka_snimanja
    global svi_validni_bpm, svi_validni_spo2, detektovan_zastoj

    binary_payload = message.payload
    
    if len(binary_payload) != 14:
        print(f"[GRESKA] Ocekivano 14 bajtova, stiglo {len(binary_payload)}")
        return
    
    bpm, spo2, ir, validBPM, validSPO2 = struct.unpack("<iiibb", binary_payload)

    print(f"Sirovi IR signal: {ir}")

    # 1. Obrada i prikaz Pulsa (BPM) + Slanje sa ključem 'value' (kako HTML i traži)
    if ir < 20000:
        print("Trenutni puls: -- BPM (Nema prsta)")
        socketio.emit('update_bpm', {'value': '--'})  
        if snimanje_zapoceto == True: 
            detektovan_zastoj = True
    elif validBPM == 1:
        print(f"Trenutni puls: {bpm} BPM")
        socketio.emit('update_bpm', {'value': str(bpm)})  
        if ir >= 20000 and not snimanje_zavrseno:
            svi_validni_bpm.append(bpm)
    else:
        print(f"Trenutni puls: {bpm} BPM (Stabilizacija / Proracun...)")
        socketio.emit('update_bpm', {'value': '--'})

    # 2. Obrada i prikaz Kiseonika (SpO2) + Slanje sa ključem 'value'
    if ir < 20000:
        print("Zasicenost kiseonikom (SpO2): -- % (Nema prsta)")
        socketio.emit('update_spo2', {'value': '--'})
    elif validSPO2 == 1:    
        print(f"Zasicenost kiseonikom (SpO2): {spo2}% [PODACI VALIDNI]")
        socketio.emit('update_spo2', {'value': str(spo2)})  # HTML sam radi toFixed(2), šaljemo čist broj/string
        if spo2 < 94:
            print("[UPOZORENJE] Kriticno nizak nivo kiseonika")
        if ir >= 20000 and spo2 > 0 and not snimanje_zavrseno:
            svi_validni_spo2.append(spo2)
    else:
        print("Zasicenost kiseonikom (SpO2): -- % [Ceka se merenje - bafer se puni]")
        socketio.emit('update_spo2', {'value': '--'})

    # 3. Upravljanje Alarmom
    if ir < 20000:
        print("Status senzora: No finger?")
        print("ALARM UKLJUCEN!")
        if not pygame.mixer.music.get_busy():
            pygame.mixer.music.play(-1)
    else:
        print("Status senzora: Prst detektovan / Merenje u toku...")
        pygame.mixer.music.stop()

    # 4. Pokretanje snimanja na osnovu prisustva prsta
    if ir >= 20000 and not snimanje_zapoceto and not snimanje_zavrseno:
        snimanje_zapoceto = True 
        vreme_pocetka_snimanja = time.time()
        print(f"Prst je detektovan. Zapoceto je snimanje za korisnika: {trenutni_korinsik}")
    
    print("-"*40)


def obradi_sirovo(client, userdata, message):
    socketio.emit('update_bpm', {'value':'999'}, namespace='/')
    global snimanje_zapoceto, snimanje_zavrseno, vreme_pocetka_snimanja
    global svi_validni_bpm, svi_validni_spo2, detektovan_zastoj, moj_bafer

    try:
        sirovi_ir = int(message.payload.decode("utf-8"))
    except:
        return 

    # --- WEB PLOT BAFEROVANJE + Slanje sa ključem 'niz' (kako HTML i traži) ---
    if sirovi_ir >= 20000:
        moj_bafer.append(sirovi_ir)
        if len(moj_bafer) > 200:
            moj_bafer.pop(0)

        if len(moj_bafer) == 200:
            try:
                cisti_niz = procesor.filter_for_plot(moj_bafer)
                if cisti_niz:
                    socketio.emit('new_ppg_data', {'niz': cisti_niz})
            except Exception:
                pass

    # --- VAŠA ORIGINALNA LOGIKA ZA KREIRANJE I UPIS U FAJL ---
    if sirovi_ir >= 20000 and not snimanje_zapoceto and not snimanje_zavrseno:
        snimanje_zapoceto = True 
        vreme_pocetka_snimanja = time.time()
        detektovan_zastoj = False
        svi_validni_bpm.clear()
        svi_validni_spo2.clear()
        
        print(f"\n[SISTEM] Prst detektovan! Pravim fajl i počinjem upis za: {trenutni_korinsik}")
        with open(ime_fajla, "w") as file:
            file.write(f"Korisnik: {trenutni_korinsik}\nRelativnoVreme_ms,IR_Signal\n")

    if snimanje_zapoceto and not snimanje_zavrseno:
        trenutno_vreme = time.time()
        preostalo_vreme = TRAJANJE_SNIMANJA - (trenutno_vreme - vreme_pocetka_snimanja)

        if preostalo_vreme > 0:
            vreme_ms = int((trenutno_vreme - vreme_pocetka_snimanja) * 1000)
            with open(ime_fajla, "a") as file:
                file.write(f"{vreme_ms},{sirovi_ir}\n")
        else:
            snimanje_zavrseno = True
            snimanje_zapoceto = False

            konacni_bpm = int(sum(svi_validni_bpm)/len(svi_validni_bpm) if svi_validni_bpm else 0)
            konacni_spo2 = int(sum(svi_validni_spo2)/len(svi_validni_spo2) if svi_validni_spo2 else 0)

            if detektovan_zastoj:
                if svi_validni_bpm and svi_validni_bpm[-1] == 0:
                    with open(ime_fajla, "a") as file:
                        file.write(f"\nStatus: KRITICNO\nKonacan_BPM:0\nKonacan_SpO2:0\n")  
                else:
                    with open(ime_fajla, "a") as file:
                        file.write(f"\nStatus: KRITICNO (ZASTOJ TOKOM MERENJA)\nKonacan_BPM:{konacni_bpm}\nKonacan_SpO2:{konacni_spo2}\n")
            else:
                if konacni_spo2 < 94 and konacni_spo2 > 0:
                    status = "KRITICNO"
                else:
                    status = "NORMALNO"

                with open(ime_fajla, "a") as file:
                    file.write(f"\nStatus: {status}\nKonacan_BPM:{konacni_bpm}\nKonacan_SpO2:{konacni_spo2}\n")
            print(f"\n[SISTEM] Merenje za korisnika {trenutni_korinsik} je zavrseno i uspesno sacuvano!")

# =====================================================================
# 5. POKRETANJE MQTT-A I WEB SERVERA
# =====================================================================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[USPESNO] Laptop je povezan na lokalni MQTT broker!")
        client.subscribe("ftn/oksimetar/binarno")
        client.subscribe("ftn/oksimetar/sirovo")
        print("Slušam podatke sa ESP32 i pokrećem Web sajt...\n")
    else:
        print(f"[GRESKA] Povezivanje neuspesno, kod greske: {rc}")

def pokreni_mqtt_u_pozadini():
    laptop_client = mqtt.Client()
    laptop_client.on_connect = on_connect
    laptop_client.message_callback_add("ftn/oksimetar/binarno", obradi_binarno)
    laptop_client.message_callback_add("ftn/oksimetar/sirovo", obradi_sirovo)
    
    try:
        laptop_client.connect("localhost", 1883, 60)
        laptop_client.loop_start()  
    except Exception as e:
        print(f"Ne mogu da se povežem na broker: {e}")
        exit()

@app.route('/')
def index():
    return render_template('index.html')

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
    pokreni_mqtt_u_pozadini()
    socketio.run(app, host='0.0.0.0', port=5000)