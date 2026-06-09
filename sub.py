import paho.mqtt.client as mqtt
import os
import time
import pygame
import struct
from socketio import Client
import numpy as np
import neurokit2 as nk


class SignalProcessor:
    def __init__(self, sampling_rate = 50):
        self.sampling_rate = sampling_rate

    def filter_for_plot(self, ir_niz):
        try:
            if max(ir_niz) == min(ir_niz):
                return[0.0]*len(ir_niz)
            signal = np.array(ir_niz)
            cleaned = nk.ppg_clean(signal, sampling_rate=self.sampling_rate, method='elgendi')
            norm_signal = (cleaned - np.min(cleaned)) / (np.max(cleaned) - np.min(cleaned))

            return norm_signal.tolist()

        except Exception:
            return []
        
processor = SignalProcessor(sampling_rate=50)
ir_buffer = []
MAX_BUFFER_POINTS = 100        

pygame.mixer.init()
ZVUK_ALARMA = "oxi.mp3"

try:
    # Dobijamo tačnu apsolutnu putanju do foldera u kom se nalazi skripta
    trenutni_folder = os.path.dirname(os.path.abspath(__file__))
    putanja_do_zvuka = os.path.join(trenutni_folder, ZVUK_ALARMA)
    
    if os.path.exists(putanja_do_zvuka):
        pygame.mixer.music.load(putanja_do_zvuka)
        print(f"[USPEŠNO] Učitan zvučni fajl: {ZVUK_ALARMA}")
    else:
        print(f"[GREŠKA] Fajl '{ZVUK_ALARMA}' nije pronađen u folderu: {trenutni_folder}")
except Exception as e:
    print(f"[GREŠKA] Neuspešno učitavanje zvuka: {e}")


sio = Client()
try:
    sio.connect('http://localhost:5000')
    print("[USPEŠNO] Povezan na Flask SocketIO server.")
except Exception as e:
    print(f"[UPOZORENJE] Flask server nije dostupan: {e}")


# Funkcija koja se aktivira čim stigne poruka sa tvoje pločice
def on_message(client, userdata, message):
    topic = message.topic
    global ir_buffer

    if topic == "ftn/oksimetar/binarno":
        binary_payload = message.payload
    
        if len(binary_payload) != 14:
            print(f"[GREŠKA] Očekivano 14 bajtova, stiglo {len(binary_payload)}")
            return
        
        bpm, spo2, ir, validBPM, validSPO2 = struct.unpack("<iiibb", binary_payload)


        #Slanje podataka na sajt:
        try:
            if ir < 20000:
                sio.emit('update_bpm', {'value': '--'})
                sio.emit('update_spo2', {'value': '0.00'})
                ir_buffer = []
            else:
                if validBPM == 1:
                    sio.emit('update_bpm', {'value': str(bpm)})
                else:
                    sio.emit('update_bpm', {'value': '--'})

                if validSPO2 == 1:
                    sio.emit('update_spo2', {'value': str(spo2)})
                else:
                    sio.emit('update_spo2', {'value': '0.00'})

                ir_buffer.append(float(ir))
                if len(ir_buffer) > MAX_BUFFER_POINTS:
                    ir_buffer.pop(0)

                if len(ir_buffer) >= 20:
                    filtriran_niz = processor.filter_for_plot(ir_buffer)
                    sio.emit('new_ppg_data', {'niz': filtriran_niz})
        except Exception:
            pass


        #Ispis u terminalu:
        print(f"Sirovi IR signal: {ir}")

        # 1. Obrada i prikaz Pulsa (BPM)
        if ir < 20000:
            print("Trenutni puls: -- BPM (Nema prsta)")
        elif validBPM == 1:
            print(f"Trenutni puls: {bpm} BPM")
        else:
            print(f"Trenutni puls: {bpm} BPM (Stabilizacija / Proračun...)")

        # 2. Obrada i prikaz Kiseonika (SpO2)
        if ir < 20000:
            print("Zasićenost kiseonikom (SpO2): -- % (Nema prsta)")
        elif validSPO2 == 1:
            print(f"Zasićenost kiseonikom (SpO2): {spo2}% [PODACI VALIDNI]")
        else:
            print("Zasićenost kiseonikom (SpO2): -- % [Čeka se merenje - bafer se puni]")

        # 3. Upravljanje Alarmom (Logika zasnovana na prisustvu prsta / IR signalu)
        if ir < 20000:
            print("Status senzora: No finger?")
            print("ALARM UKLJUČEN!")
            
            # Ako muzika već ne svira, pokreni je u beskonačnoj petlji
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.play(-1)
        else:
            print("Status senzora: Prst detektovan / Merenje u toku...")
            # Čim se prst vrati, stopiraj reprodukciju zvuka
            pygame.mixer.music.stop()

        print("-" * 40)    


# Funkcija koja potvrđuje da se laptop uspešno povezao na HiveMQ
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[USPEŠNO] Laptop je povezan na HiveMQ broker!")
        # Laptop se pretplaćuje na sve tvoje teme odjednom koristeći džoker znak '#'
        # 'ftn/oksimetar/#' znači: "Slušaj sve što počinje sa ftn/oksimetar/"
        client.subscribe("ftn/oksimetar/binarno")
        print("Slušam binarni stream sa ESP32-C6... (Pritisni Ctrl+C za prekid)\n")
    else:
        print(f"[GREŠKA] Povezivanje neuspešno, kod greške: {rc}")

# Inicijalizacija MQTT klijenta na laptopu
laptop_client = mqtt.Client()

# Dodeljujemo funkcije za rukovanje događajima
laptop_client.on_connect = on_connect
laptop_client.on_message = on_message

# Povezivanje na javni server koji si izabrala u Arduinu
try:
    laptop_client.connect("localhost", 1883, 60)
except Exception as e:
    print(f"Ne mogu da se povežem na broker: {e}")
    exit()

# Pokretanje beskonačne petlje koja drži skriptu aktivnom i sluša mrežu
laptop_client.loop_forever()



#analitika prikaz za ssvakog korisnika da li su kriticni podaci plot 
