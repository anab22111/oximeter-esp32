import paho.mqtt.client as mqtt
import os
import time
import pygame

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

# Funkcija koja se aktivira čim stigne poruka sa tvoje pločice
def on_message(client, userdata, message):
    # Dekodiramo bajtove u običan tekst
    payload = message.payload.decode("utf-8")
    topic = message.topic

    # Razvrstavamo podatke prema temama koje si definisala u Arduinu
    if topic == "ftn/oksimetar/bpm":
        if payload == "0.1":
            print("[INFO] Prst registrovan, stabilizacija senzora...")
        elif payload == "0":
            print("Trenutni puls: -- BPM (Čeka se stabilizacija)")
        else:
            print(f"Trenutni puls: {payload} BPM")

    elif topic == "ftn/oksimetar/spo2":
        if payload == "0":
            print("Zasićenost kiseonikom (SpO2): -- % [PODACI NISU VALIDNI - bafer se puni]")
        else:
            print(f"Zasićenost kiseonikom (SpO2): {payload}% [PODACI VALIDNI]")
        
    elif topic == "ftn/oksimetar/ir":
        print(f"Sirovi IR signal: {payload}")
        
    elif topic == "ftn/oksimetar/status":
        print(f"Status senzora: {payload}")

        if "No finger?" in payload:
            print("ALARM UKLJUČEN!")
            
            # Ako muzika već ne svira, pokreni je u beskonačnoj petlji (-1 znači loop)
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.play(-1)
                
        else:
            # Čim se prst vrati, stopiraj reprodukciju zvuka
            pygame.mixer.music.stop()

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
