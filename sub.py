import paho.mqtt.client as mqtt
import os
import time

# Funkcija koja se aktivira čim stigne poruka sa tvoje pločice
def on_message(client, userdata, message):
    # Dekodiramo bajtove u običan tekst
    payload = message.payload.decode("utf-8")
    topic = message.topic

    # Razvrstavamo podatke prema temama koje si definisala u Arduinu
    if topic == "ftn/oksimetar/bpm":
        print(f"Trenutni puls: {payload} BPM")
        
    elif topic == "ftn/oksimetar/avg_bpm":
        print(f"Prosečan puls: {payload} BPM")
        
    elif topic == "ftn/oksimetar/ir":
        print(f"Sirovi IR signal: {payload}")
        
    elif topic == "ftn/oksimetar/status":
        print(f"Status senzora: {payload}")
        print("-" * 40) # Linija za razdvajanje radi preglednosti

# Funkcija koja potvrđuje da se laptop uspešno povezao na HiveMQ
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[USPEŠNO] Laptop je povezan na HiveMQ broker!")
        # Laptop se pretplaćuje na sve tvoje teme odjednom koristeći džoker znak '#'
        # 'ftn/oksimetar/#' znači: "Slušaj sve što počinje sa ftn/oksimetar/"
        client.subscribe("ftn/oksimetar/#")
        print("Slušam i čekam podatke sa ESP32-C6... (Pritisni Ctrl+C za prekid)\n")
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
