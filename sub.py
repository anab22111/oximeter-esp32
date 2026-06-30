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

# Flask servus HTML stranice, SocketIO omogucava real-time komunikaciju sa browser-om,
# bez potrebe sa osvezavanjem stranice

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ppg_tajna'
socketio = SocketIO(app, cors_allowed_origins="*")  # '*' browser se moze konektovati sa bilo koje IP adrese

# Inicijalizacija pygame zbog zvuka alarma
pygame.mixer.init()
ZVUK_ALARMA = "oxi.mp3"

try:
    # Dobijamo tacnu putanju do foldera u kom se nalazi skripta

    # os.path.abspath(__file__) -> vraca punu putanju do ovog Python fajla
    # dirname() -> daje folder u kom se nalazi
    # alarm.mp3 na taj nacin moze da se nalazi pored skripte, bez obzira odakle se skripta pokrece

    trenutni_folder = os.path.dirname(os.path.abspath(__file__))
    putanja_do_zvuka = os.path.join(trenutni_folder, ZVUK_ALARMA)
    
    if os.path.exists(putanja_do_zvuka):
        pygame.mixer.music.load(putanja_do_zvuka)
        print(f"[USPESNO] Ucitan zvucni fajl: {ZVUK_ALARMA}")
    else:
        print(f"[GRESKA] Fajl '{ZVUK_ALARMA}' nije pronadjen u folderu: {trenutni_folder}")
except Exception as e:
    print(f"[GRESKA] Neuspesno ucitavanje zvuka: {e}")

# =====================================================================
# 2. SIGNAL PROCESSOR KLASA (Sa normalizacijom i okretanjem za sajt)
# =====================================================================
class SignalProcessor:
    def __init__(self, sampling_rate=50):

        # Frekvencija uzorkovanja senzora je 50 Hz (50 ocitavanja u sekundi)
        # Bitno za neurokit2 -> algoritmi za filtriranje zavise od toga koliko cesto stizu uzorci

        self.sampling_rate = sampling_rate

    def filter_for_plot(self, ir_niz):
        """
        Prima niz sirovih IR vrednosti i vraca ociscen, normalizovan signal 
        spreman za prikaz na grafikonu (vrednosti 0.0 - 1.0)
        """

        try:
            # Ako je signal konstantan (flatline), nema sta da se filtrira
            if max(ir_niz) == min(ir_niz):
                return [0.0] * len(ir_niz)
            
            signal = np.array(ir_niz)

            # nk.ppg_clean -> uklanja visokofrekventni sum iz PPG signala
            # method='elgendi' -> metoda optimizovana za pulsne oksimetre 
            cleaned = nk.ppg_clean(signal, sampling_rate=self.sampling_rate, method='elgendi')
            
            # Sve vrednosti se skaliraju na opseg [0, 1]
            norm_signal = (cleaned - np.min(cleaned)) / (np.max(cleaned) - np.min(cleaned))
            
            # Senzor vraca vece vrednosti kada je manje krvi,
            # pa invertujemo signal da pikovi na grafikonu idu gore (intuitivnije je za prikaz)
            norm_signal = 1.0 - norm_signal

            return norm_signal.tolist()
        except Exception:
            return []
    
    
# Globalna instanca procesora, koristi se i za real-time i za istorijske podatke
procesor = SignalProcessor(sampling_rate=50)

# Klizajuci bafer od 200 uzoraka za real-time grafik 
moj_bafer = []


# =====================================================================
# 3. PROMENLJIVE ZA SNIMANJE KORISNIKA
# =====================================================================
trenutni_korinsik = input("Unesite ime korisnika: ").strip()

# Fajl u koji se upisuje merenje, nazvan po pacijentu
ime_fajla = f"merenje_{trenutni_korinsik}.txt"

TRAJANJE_SNIMANJA = 30
snimanje_zapoceto = False           
snimanje_zavrseno = False
vreme_pocetka_snimanja = 0

svi_validni_bpm = []
svi_validni_spo2 = []
detektovan_zastoj = False

# =====================================================================
# 4. LOGIKA OBRADE (MQTT -> Ekran + Fajl + Web sajt)
# =====================================================================
def obradi_binarno(client, userdata, message):
    """
    Callback za MQTT temu: 'ftn/oksimetar/binarno'

    ESP32 salje paket od tacno 14 bajtova koji sadrzi izracunate vrednosti:
    - bpm       (int, 4 bajta)
    - spo2      (int, 4 bajta)
    - ir        (int, 4 bajta) -> sirova vrednost IR-a (za detekciju prsta)
    - validBPM  (byte, 1 bajt) -> 1 (BPM vrednost je pouzdana), 0 (jos uvek se stabilizuje)
    - validSPO2 (byte, 1 bajt) -> a (SpO2 vrednost je pouzdana), 0 (bafer nije pun)

    '<iiibb' -> little endian, tri int-a i dva signed char-a
    """

    global snimanje_zapoceto, snimanje_zavrseno, vreme_pocetka_snimanja
    global svi_validni_bpm, svi_validni_spo2, detektovan_zastoj

    binary_payload = message.payload
    
    if len(binary_payload) != 14:
        print(f"[GRESKA] Ocekivano 14 bajtova, stiglo {len(binary_payload)}")
        return
    
    # Raspakivanje binarnog paketa prema dogovorenom formatu
    bpm, spo2, ir, validBPM, validSPO2 = struct.unpack("<iiibb", binary_payload)

    print(f"Sirovi IR signal: {ir}")

    # Slanje vrednosti na sajt u realnom vremenu
    socketio.emit('update_bpm', {'value': bpm if ir >= 20000 else '--'})
    socketio.emit('update_spo2', {'value': f"{spo2}" if (validSPO2 == 1 and ir >= 20000) else '--'})

    # 1. Obrada i prikaz pulsa (BPM)
    if ir < 20000:
        print("Trenutni puls: -- BPM (Nema prsta)")
        # Ako merenje tece, a prst je skinut, belezi se zastoj
        if snimanje_zapoceto == True: 
            detektovan_zastoj = True
    elif validBPM == 1:
        print(f"Trenutni puls: {bpm} BPM")
    else:
        # Prikuplja se dovoljno podataka za pouzdan rezultat
        print(f"Trenutni puls: {bpm} BPM (Stabilizacija / Proracun...)")

    # 2. Obrada i prikaz kiseonika (SpO2)
    if ir < 20000:
        print("Zasicenost kiseonikom (SpO2): -- % (Nema prsta)")
    elif validSPO2 == 1:    
        print(f"Zasicenost kiseonikom (SpO2): {spo2}% [PODACI VALIDNI]")
        if spo2 < 94:
            print("[UPOZORENJE] Kriticno nizak nivo kiseonika")
    else:
        print("Zasicenost kiseonikom (SpO2): -- % [Ceka se merenje - bafer se puni]")

    # 3. Upravljanje alarmom
    if ir < 20000:
        print("Status senzora: No finger?")
        print("ALARM UKLJUCEN!")
        if not pygame.mixer.music.get_busy():
            pygame.mixer.music.play(-1)     # Beskonacno ponavljanje zvuka
    else:
        print("Status senzora: Prst detektovan / Merenje u toku...")
        pygame.mixer.music.stop()

    # 4. Zapisivanje odredjenih vrednosti koje stizu sa senzora
    # Snimanje pocinje tek kad se prst detektovao, ne pre
    if ir >= 20000 and not snimanje_zapoceto and not snimanje_zavrseno:
        snimanje_zapoceto = True 
        vreme_pocetka_snimanja = time.time()
        print(f"Prst je detektovan. Zapoceto je snimanje za korisnika: {trenutni_korinsik}")
    
    if snimanje_zapoceto and not snimanje_zavrseno:
        if ir >= 20000:
            svi_validni_bpm.append(bpm)

        # SpO2 dodajemo samo ako je vrednost validna i pozitivna    
        if validSPO2 == 1 and spo2 > 0:
            svi_validni_spo2.append(spo2)

    print("-"*40)


def obradi_sirovo(client, userdata, message):
    """
    Callback za MQTT temu: 'ftn/oksimetar/sirovo

    ESP32 salje pojedinacnu sirovu IR vrednost kao tekst, na frekvenciji -50 Hz
    Ova tema sluzi za dva cilja:
        1. Punjenje klizajuceg bafera za real-time PPG grafik na web sajtu
        2. Upis sirovih podatak u .txt fajl za kasniju analizu (istorija)
    """

    global snimanje_zapoceto, snimanje_zavrseno, vreme_pocetka_snimanja
    global svi_validni_bpm, svi_validni_spo2, detektovan_zastoj, moj_bafer

    try:
        sirovi_ir = int(message.payload.decode("utf-8"))
    except:
        return      # Ignorisemo losije formirane poruke  

    # WEB PLOT BAFEROVANJE
    moj_bafer.append(sirovi_ir)

    # Bafer drzi samo poslednjih 200 uzoraka (4s prikaza pri 50 Hz)
    # pop(0) -> uklanja najstariji element kada bafer prekoraci granicu
    if len(moj_bafer) > 200:
        moj_bafer.pop(0)

    # Kada je bafer pun, filtrira se i salje se na sajt
    # Na taj nacin, filter uvek dobija dovoljno podataka za dobar rezultat
    if len(moj_bafer) == 200:
        cisti_niz = procesor.filter_for_plot(moj_bafer)
        if cisti_niz:
            socketio.emit('new_ppg_data', {'niz': cisti_niz})

    # LOGIKA ZA KREIRANJE I UPIS U FAJL
    # Snimanje zapocinje cim se prst detektuje, ali samo JEDNOM
    if sirovi_ir >= 20000 and not snimanje_zapoceto and not snimanje_zavrseno:
        snimanje_zapoceto = True 
        vreme_pocetka_snimanja = time.time()
        detektovan_zastoj = False
        svi_validni_bpm.clear()
        svi_validni_spo2.clear()
        
        print(f"\n[SISTEM] Prst detektovan! Pravi se fajl i pocinje upis za: {trenutni_korinsik}")
        
        with open(ime_fajla, "w") as file:
            file.write(f"Korisnik: {trenutni_korinsik}\nRelativnoVreme_ms,IR_Signal\n")

    if snimanje_zapoceto and not snimanje_zavrseno:
        trenutno_vreme = time.time()
        preostalo_vreme = TRAJANJE_SNIMANJA - (trenutno_vreme - vreme_pocetka_snimanja)

        if preostalo_vreme > 0:
            vreme_ms = int((trenutno_vreme - vreme_pocetka_snimanja) * 1000)
            #vrednost_za_upis = sirovi_ir if sirovi_ir >= 20000 else 0
            with open(ime_fajla, "a") as file:
                file.write(f"{vreme_ms},{sirovi_ir}\n")
        else:
            # Merenje je isteklo i racunaju se finalne vrednosti, a fajl se zatvara
            snimanje_zavrseno = True
            snimanje_zapoceto = False

            konacni_bpm = int(sum(svi_validni_bpm)/len(svi_validni_bpm) if svi_validni_bpm else 0)
            konacni_spo2 = int(sum(svi_validni_spo2)/len(svi_validni_spo2) if svi_validni_spo2 else 0)

            if detektovan_zastoj:
                # Prst je skinut tokom merenja -> pouzdanost je umanjena
                if svi_validni_bpm and svi_validni_bpm[-1] == 0:
                    with open(ime_fajla, "a") as file:
                        file.write(f"\nStatus: KRITICNO\nKonacan_BPM:0\nKonacan_SpO2:0\n")  
                else:
                    with open(ime_fajla, "a") as file:
                        file.write(f"\nStatus: KRITICNO (ZASTOJ TOKOM MERENJA)\nKonacan_BPM:{konacni_bpm}\nKonacan_SpO2:{konacni_spo2}\n")
            else:
                # Normalno zavrseno merenje -> status odredjujemo po SpO2
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

@socketio.on('connect')
def handle_connect():
    """
    Poziva se automatski svaki put kad se novi browser konektuje na SocketIO
    Odmah saljemo ime pacijenta koje je uneseno u terminal, kako bi web interfejs
    mogao da ga prikaze bez dodatnih zahteva
    """

    global trenutni_korinsik
    
    # Saljemo signal 'inicijalizuj_pacijenta" sa imenom koje vec imamo u memoriji
    emit('inicijalizuj_pacijenta', {'ime': trenutni_korinsik})
    print(f"[WEB] Pacijent '{trenutni_korinsik}' je uspesno poslat na veb interfejs.")

def on_connect(client, userdata, flags, rc):
    """
    Callback za MQTT
    Poziva se kad se uspostavi konekcija sa brokerom
    rc == 0 -> uspeh, bilo sta drugo je GRESKA
    """

    if rc == 0:
        print("[USPESNO] Laptop je povezan na lokalni MQTT broker!")
        client.subscribe("ftn/oksimetar/binarno")
        client.subscribe("ftn/oksimetar/sirovo")
        print("Slusaju se podaci sa ESP32 i pokrece se Web sajt...\n")
    else:
        print(f"[GRESKA] Povezivanje neuspesno, kod greske: {rc}")

def pokreni_mqtt_u_pozadini():
    """
    Kreira MQTT klijenta, registruje callback-ove i pokrece se asinhrona petlja
    
    loop_start() pokrece MQTT u posebnoj niti, tako da ne blokira Flask nit
    loop_forever() bi blokirala Flask ne bi mogao da servisira HTTP zahteve
    """

    laptop_client = mqtt.Client()
    laptop_client.on_connect = on_connect

    # Svaka tema ima svoju funkciju obrade
    laptop_client.message_callback_add("ftn/oksimetar/binarno", obradi_binarno)
    laptop_client.message_callback_add("ftn/oksimetar/sirovo", obradi_sirovo)
    
    try:
        # Broker mora biti pokrenut lokalno, pri pokretanju same skripte
        laptop_client.connect("localhost", 1883, 60)
        laptop_client.loop_start()      # Asinhrona petlja, ne blokira Flask
    except Exception as e:
        print(f"Nije moguce da se poveze na broker: {e}")
        exit()

@app.route('/')
def index():
    # Real-time monitoring aktivnog pacijenta
    return render_template('index.html')

# Nova stranica koja prikazuje listu svih pacijenata
@app.route('/istorija')
def history_list_page():
    return render_template('history_list.html')

# Stranica koja prikazuje grafikon za izabranog pacijenta (ime dolazi kao URL parametar)
@app.route('/istorija/grafikon')
def history_char_page():
    return render_template('history.html')

# Skenira folder i vraca listu pacijenata za koje postoji .txt fajl merenja
@app.route('/api/pacijenti')
def get_pacijenti():
    pacijenti = []
    trenutni_dir = os.path.dirname(os.path.abspath(__file__))

    # Prolazimo kroz sve fajlove u folderu
    for fajl in os.listdir(trenutni_dir):
        if fajl.startswith("merenje_") and fajl.endswith(".txt"):
            # Izvlacimo ime pacijenta iz naziva
            ime = fajl.replace("merenje_", "").replace(".txt", "")
            if ime:
                pacijenti.append(ime)

    # Imena se sortiraju po abecedi
    pacijenti.sort()
    return json.dumps({"pacijenti": pacijenti}), 200, {'Content-Type': 'application/json'}

# API cita konkretan fajl izabranog pacijenta
@app.route('/api/istorija/<korisnik>')
def get_istorija(korisnik):
    fajl_za_citanje = f"merenje_{korisnik}.txt"

    if not os.path.exists(fajl_za_citanje):
        return json.dumps({"status": "Greska", "poruka": f"Fajl {fajl_za_citanje} ne postoji."}), 404
    
    ir_signali = []
    vreme_ms = []
    status_merenja = "Nepoznato"
    konacan_bpm = "--"
    konacan_spo2 = "--"

    try:
        with open(fajl_za_citanje, "r") as file:
            lines = file.readlines()

        for line in lines:
            line = line.strip()

            if not line:
                continue

            if "," in line and not line.startswith("RelativnoVreme"):
                parts = line.split(",")

                if len(parts) == 2:
                    vreme_ms.append(int(parts[0]))
                    ir_signali.append(int(parts[1]))

            elif line.startswith("Status: "):
                status_merenja = line.split(":")[1].strip()
            elif line.startswith("Konacan_BPM:"):
                konacan_bpm = line.split(":")[1].strip()
            elif line.startswith("Konacan_SpO2:"):
                konacan_spo2 = line.split(":")[1].strip()

        # Filtriramo sacuvani sirovi signal kroz isti procesor kao za real-time prikaz
        if ir_signali:
            cist_signal = procesor.filter_for_plot(ir_signali)
        else:
            cist_signal = []

        return json.dumps({
            "status": "Uspesno",
            "korisnik": korisnik,
            "status_pacijenta": status_merenja,
            "bpm": konacan_bpm,
            "spo2": konacan_spo2,
            "vremena": vreme_ms,
            "signal": cist_signal
        }), 200, {'Content-Type': 'application/json'}
    
    except Exception as e:
        return json.dumps({"status": "Greska", "poruka": str(e)}), 500

if __name__ == '__main__':
    pokreni_mqtt_u_pozadini()

    # '0.0.0.0' -> sajt je dostupan svim uredjajima na lokalnoj mrezi
    socketio.run(app, host='0.0.0.0', port=5000)