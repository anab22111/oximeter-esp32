import paho.mqtt.client as mqtt
import os
import time
import pygame
import struct

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


trenutni_korinsik = input("Unesite ime korisnika: ").strip()
ime_fajla = f"merenje_{trenutni_korinsik}.txt" # Napravi fajl za upisivanje vrednosti datog korisnika

# Definisanje promenljivih koje ce se koristiti pri snimanju podataka korisnika
TRAJANJE_SNIMANJA = 30 # koliko sekundi cemo snimati korisnicke podatke
snimanje_zapoceto = False
snimanje_zavrseno = False
vreme_pocetka_snimanja = 0

# Kreiranje lista gde ce se cuvati bpm i spo2 kako bi se posle izracunao prosek
svi_validni_bpm = []
svi_validni_spo2 = []
detektovan_zastoj = False

# Funkcija koja se aktivira čim stigne poruka sa tvoje pločice
def on_message(client, userdata, message):
    topic = message.topic

    global snimanje_zapoceto, snimanje_zavrseno, vreme_pocetka_snimanja
    global svi_validni_bpm, svi_validni_spo2, detektovan_zastoj

    if topic == "ftn/oksimetar/binarno":
        binary_payload = message.payload
    
        if len(binary_payload) != 14:
            print(f"[GREŠKA] Očekivano 14 bajtova, stiglo {len(binary_payload)}")
            return
        
        bpm, spo2, ir, validBPM, validSPO2 = struct.unpack("<iiibb", binary_payload)

        print(f"Sirovi IR signal: {ir}")

        # 1. Obrada i prikaz Pulsa (BPM)
        if ir < 20000:
            print("Trenutni puls: -- BPM (Nema prsta)")
            // Ukoliko je snimanje zapoceto i detektovano je da nema prsta - simulacija da nema otkucaja
            // Postavi flag da je detektovan zastoj
            if snimanje_zapoceto == True: 
                detektovan_zastoj = True

        elif validBPM == 1:
            print(f"Trenutni puls: {bpm} BPM")
        else:
            print(f"Trenutni puls: {bpm} BPM (Stabilizacija / Proračun...)")

        # 2. Obrada i prikaz Kiseonika (SpO2)
        if ir < 20000:
            print("Zasićenost kiseonikom (SpO2): -- % (Nema prsta)")
        elif validSPO2 == 1:    
            print(f"Zasićenost kiseonikom (SpO2): {spo2}% [PODACI VALIDNI]")
            if spo2 < 94:
                print("[UPOZORENJE] Kriticno nizak nivo kiseonika")
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

          

        # 4. Zapisivanje odredjenih vrednosti koje stizu da senzora
        # Pokreni snimanje cim je detektovan prst
        if ir >= 20000 and not snimanje_zapoceto and not snimanje_zavrseno:
            snimanje_zapoceto = True 
            vreme_pocetka_snimanja = time.time()
            print(f"Prst je detektovan. Zapoceto je snimanje za korisnika: {trenutni_korinsik}")
        

        if snimanje_zapoceto and not snimanje_zavrseno:
            trenutno_vreme = time.time()

            # Izmeri koliko vremena je preostalo za snimanje
            preostalo_vreme = TRAJANJE_SNIMANJA - (trenutno_vreme - vreme_pocetka_snimanja)

            # Ukoliko jos ima vremena nastavi snimanje
            if preostalo_vreme > 0:

                #if validBPM == 1 and bpm > 0:
                svi_validni_bpm.append(bpm)
                if validSPO2 == 1 and spo2 > 0:
                    svi_validni_spo2.append(spo2)

                # Otvori korisnikov fajl i upisi vrednosti
                with open(ime_fajla, "a") as file:
                    file.write(f"{vreme_ms},{ir}\n")
            else:
                # U suprotonom zaustavi snimanje
                snimanje_zavrseno = True
                snimanje_zapoceto = False

                konacni_bpm = int(sum(svi_validni_bpm)/len(svi_validni_bpm) if svi_validni_bpm else 0)
                konacni_spo2 = int(sum(svi_validni_spo2)/len(svi_validni_spo2) if svi_validni_spo2 else 0)
                print(f"\n Uspešno snimljen fiksni uzorak od {TRAJANJE_SNIMANJA_SEKUNDE}s u '{ime_fajla}'.")
                
                status = ""
                # Ukoliko je detektovan zastoj prilikom snimanja
                if detektovan_zastoj:
                    if svi_validni_bpm[-1] == 0:
                        # ukoliko je psolednji sacuvani bpm bio 0 onda znaci da je bpm 0
                        with open(ime_fajla, "a") as file:
                            file.write(f"\nStatus: KRITICNO\nKonacan_BPM:0\nKonacan_SpO2:0\n")  
                else:
                    
                    if konacni_spo2 < 94 and konacni_spo2 > 0:
                        status = "KRITICNO"
                    else:
                        status = "NORMALNO"

                    with open(ime_fajla, "a") as file:
                            file.write(f"\nStatus: {status}\nKonacan_BPM:{konacni_bpm}\nKonacan_SpO2:{konacni_spo2}\n") 
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
