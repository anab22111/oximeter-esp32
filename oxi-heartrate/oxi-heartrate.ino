#include <Wire.h>
#include "MAX30105.h"
#include <PubSubClient.h>
#include "spo2_algorithm.h"
#include <WiFi.h>

// ================= MREZNA podesavanje =================
const char* ssid = "FTN_wifi";
const char* password = "ftn12345";
const char* mqtt_server = "10.1.146.123"; 

WiFiClient espClient;
PubSubClient client(espClient);

long lastMsg = 0;
const int sendInterval = 2000; 

// ================= SENZOR podesavanja =================
struct __attribute__((packed)) Oksimetar {
  int32_t bpm;       // 4 bajta (heartRate / lastValidBPM)
  int32_t spo2;      // 4 bajta (spo2)
  int32_t ir;        // 4 bajta (irValue)
  int8_t validBPM;   // 1 bajt  (validHeartRate: 0 ili 1)
  int8_t validSPO2;  // 1 bajt  (validSPO2: 0 ili 1)
};

MAX30105 particleSensor;

#define BUFFER_SIZE 100
uint32_t irBuffer[BUFFER_SIZE]; 
uint32_t redBuffer[BUFFER_SIZE]; 
int32_t bufferIndex = 0;
bool bufferFull = false;

// Izlazne promenljive iz algoritma
int32_t spo2 = 0; 
int8_t validSPO2 = 0; 
int32_t heartRate = 0; 
int8_t validHeartRate = 0;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Inicijalizacija sistema...");

  setup_wifi();

  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  Wire.begin(0, 1);
  
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 nije pronađen!");
    while (1);
  }
  Serial.println("Sistem spreman. Postavite prst stabilno.");

  // podesavanja optimalna za sakupljanje SpO2 bafera
  byte ledBrightness = 60;  
  byte sampleAverage = 1;   // Smanjeno na 1 da dobijemo sirovije i brze uzorke za m_algorithm
  byte ledMode = 2;         // 2 = Red + IR
  byte sampleRate = 100;    
  int pulseWidth = 411;     
  int adcRange = 4096;      

  particleSensor.setup(ledBrightness, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();    

  // citamo sirove vrednosti
  long irValue = particleSensor.getIR();
  long redValue = particleSensor.getRed();

  // slanje ir vrednosti za plotovanje
  if (irValue >= 20000) {
    char irString[12];
    ltoa(irValue, irString, 10);
    client.publish("ftn/oksimetar/sirovo", irString); 
  }

  // blaga provera za prisustvo prsta (samo ako je skroz skinut resetujemo)
  if (irValue < 20000) { 
    spo2 = 0;
    validSPO2 = 0;
    heartRate = 0;
    validHeartRate = 0;
    bufferIndex = 0;
    bufferFull = false;
  } else {
    
    if (!bufferFull) {           // ako nije pun ne vrsi se merenje
      // punjnje bafera sa 100 uzoraka
      redBuffer[bufferIndex] = redValue;
      irBuffer[bufferIndex] = irValue;
      bufferIndex++;

      if (bufferIndex >= BUFFER_SIZE) {
        bufferFull = true;
        // Prvi proračun nad prvih 100 uzoraka
        maxim_heart_rate_and_oxygen_saturation(irBuffer, BUFFER_SIZE, redBuffer, &spo2, &validSPO2, &heartRate, &validHeartRate);
      }
    } 
    else {
      
      // cekamo da senzor javi da ima nov uzorak na I2C
      while (particleSensor.available() == false) {
        particleSensor.check();
      }

      // pomeramo svih 75 starih uzoraka ka pocetku niza (brisemo 25 najstarijih)
      for (byte i = 25; i < BUFFER_SIZE; i++) {
        redBuffer[i - 25] = redBuffer[i];
        irBuffer[i - 25] = irBuffer[i];
      }

      // sakupljane novih 25 uzoraka
      for (byte i = 75; i < BUFFER_SIZE; i++) {
        while (particleSensor.available() == false) {
          particleSensor.check();
        }
        redBuffer[i] = particleSensor.getRed();
        irBuffer[i] = particleSensor.getIR();
        particleSensor.nextSample(); // pomeranje unutrasnjeg pointer senzora za sl krug
      }

      // odmah racunanje sa noivm podacima
      maxim_heart_rate_and_oxygen_saturation(irBuffer, BUFFER_SIZE, redBuffer, &spo2, &validSPO2, &heartRate, &validHeartRate);
    }
  }

  // ================= MQTT SLANJE PODATAKA (BINARNO) =================
  long now = millis();
  if (now - lastMsg > sendInterval) {
    lastMsg = now;
  
    Oksimetar paket;
    memset(&paket, 0, sizeof(paket));

    // za pamcenje prethdih vrendsit
    static int32_t lastValidBPM = 75;

    // ako algoritam vrati validan prst upisi ga, inace posalji 0
    if (validHeartRate == 1 && heartRate > 40 && heartRate < 180 && irValue > 20000) {
      lastValidBPM = (lastValidBPM * 0.7) + (heartRate * 0.3);  // 70% stare 30% nove
      //ltoa(lastValidBPM, tempStringBPM, 10);
      paket.bpm = lastValidBPM;
      paket.validBPM = 1;
    }else {
      // Ako je prst tu ali trenutno računa, zadrži poslednji dobar puls umesto nule
      if (irValue > 20000 && lastValidBPM > 0) {
        //ltoa(lastValidBPM, tempStringBPM, 10);
        paket.bpm = lastValidBPM;
        paket.validBPM = 0;
      } else {
        //strcpy(tempStringBPM, "0");
        paket.bpm = 0;
        paket.validBPM = 0;
      }
    }
    // ako algoritam vrati validan SpO2
    if (validSPO2 == 1 && spo2 > 70 && spo2 <= 100 && irValue > 20000) {
      //ltoa(spo2, tempStringSPO2, 10);
      paket.spo2 = spo2;
      paket.validSPO2 = 1;
    } else {
      //strcpy(tempStringSPO2, "0");
      paket.spo2 = 0;
      paket.validSPO2 = 0;
    }
    
    //ltoa(irValue, tempStringIR, 10);
    paket.ir = irValue;

    if (irValue < 20000) {
      paket.bpm = 0;
      paket.spo2 = 0;
      paket.validBPM = 0;
      paket.validSPO2 = 0;

      client.publish("ftn/oksimetar/binarno", (uint8_t*)&paket, sizeof(paket));
      Serial.println("MQTT: Nema prsta (Poslat prazan binarni paket).");
    } else {
      client.publish("ftn/oksimetar/binarno", (uint8_t*)&paket, sizeof(paket));
      
      Serial.print("MQTT Poslato -> ");
      Serial.print("BPM: "); Serial.print(paket.bpm);
      Serial.print(" | SpO2: "); Serial.print(paket.spo2);
      Serial.print("% | Validnost (HR/SpO2): "); 
      Serial.print(validHeartRate); 
      Serial.print("/"); 
      Serial.println(validSPO2);
    }
  }

  particleSensor.check(); 
  delay(10);
}

void setup_wifi(){
  delay(10);
  Serial.println();
  Serial.print("Povezujem se na ");
  Serial.println(ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi uspesno povezan!");
}

void callback(char* topic, byte* message, unsigned int length) {}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Pokusavam MQTT povezivanje...");
    String clientId = "ESP32C6Client-" + String(random(0xffff), HEX);
    
    if (client.connect(clientId.c_str())) {
      Serial.println("povezan na broker!");
    } else {
      Serial.print("greska, rc=");
      Serial.print(client.state());
      Serial.println(" nova proba za 5 sekundi");
      delay(5000);
    }
  }
}