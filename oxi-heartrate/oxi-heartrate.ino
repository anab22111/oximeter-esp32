/*
  Optical Heart Rate Detection (PBA Algorithm) using the MAX30105 Breakout
  By: Nathan Seidle @ SparkFun Electronics
  Date: October 2nd, 2016
  https://github.com/sparkfun/MAX30105_Breakout

  This is a demo to show the reading of heart rate or beats per minute (BPM) using
  a Penpheral Beat Amplitude (PBA) algorithm.

  It is best to attach the sensor to your finger using a rubber band or other tightening
  device. Humans are generally bad at applying constant pressure to a thing. When you
  press your finger against the sensor it varies enough to cause the blood in your
  finger to flow differently which causes the sensor readings to go wonky.

  Hardware Connections (Breakoutboard to Arduino):
  -5V = 5V (3.3V is allowed)
  -GND = GND
  -SDA = A4 (or SDA)
  -SCL = A5 (or SCL)
  -INT = Not connected

  The MAX30105 Breakout can handle 5V or 3.3V I2C logic. We recommend powering the board with 5V
  but it will also run at 3.3V.
*/

#include <Wire.h>
#include "MAX30105.h"
#include <PubSubClient.h>
#include "heartRate.h"

#include <WiFi.h>
const char* ssid = "FTN_wifi";
const char* password = "ftn12345";

const char* mqtt_server = "broker.hivemq.com";    // koristimo javni mqtt broker

WiFiClient espClient;              // iz Wifi.h biblioteke, koristi se da otvori vezu i slaj esiorve podatke preko interneta
PubSubClient client(espClient);    // iz Pubsubclient.h biblioteke, PubSubClient pravi klijenta koji na MQTT protokol, ali nema pristup wifi, tako da mu se prosledjuje WiFiCLient
long lastMsg = 0;
char msg[50];
int value = 0;

MAX30105 particleSensor;

const byte RATE_SIZE = 10; //Increase this for more averaging. 4 is good.
byte rates[RATE_SIZE]; //Array of heart rates
byte rateSpot = 0;
long lastBeat = 0; //Time at which the last beat occurred

float beatsPerMinute;
int beatAvg;

void setup()
{
  Serial.begin(115200);
  Serial.println("Initializing...");

  setup_wifi();    // povezi se na wifi

  client.setServer(mqtt_server, 1883);        // postavi servera za esp32 da bude mqtt server koji je gore definisan
  client.setCallback(callback);               //  postavljanje funkcije koja ce se pozivati kad stigne poruka

  Wire.begin(0,1);
  // Initialize sensor
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) //Use default I2C port, 400kHz speed
  {
    Serial.println("MAX30105 was not found. Please check wiring/power. ");
    while (1);
  }
  Serial.println("Place your index finger on the sensor with steady pressure.");

  // particleSensor.setup(); //Configure sensor with default settings
  // particleSensor.setPulseAmplitudeRed(0x0A); //Turn Red LED to low to indicate sensor is running
  // particleSensor.setPulseAmplitudeGreen(0); //Turn off Green LED
  byte ledBrightness = 50;  // Umerena jacina svetla (ne zaslepljuje senzor)
  byte sampleAverage = 4;   // Usrednjavanje 4 uzorka unutar samog senzora (smanjuje sum)
  byte ledMode = 2;         // 2 = Red + IR
  byte sampleRate = 100;    // 100 uzoraka u sekundi
  int pulseWidth = 411;     
  int adcRange = 4096;      

  particleSensor.setup(ledBrightness, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);
}

void loop()
{

  if (!client.connected()) {
    reconnect();                 // ukoliko klijent nije povezan, pozovi reconnect
  }
  client.loop();      // pokreni klijenta da slusa poruke

  long irValue = particleSensor.getIR();

  if (checkForBeat(irValue) == true)
  {
    //We sensed a beat!
    long delta = millis() - lastBeat;
    lastBeat = millis();

    beatsPerMinute = 60 / (delta / 1000.0);

    if (beatsPerMinute < 255 && beatsPerMinute > 20)
    {
      rates[rateSpot++] = (byte)beatsPerMinute; //Store this reading in the array
      rateSpot %= RATE_SIZE; //Wrap variable

      //Take average of readings
      beatAvg = 0;
      for (byte x = 0 ; x < RATE_SIZE ; x++)
        beatAvg += rates[x];
      beatAvg /= RATE_SIZE;
    }
  }

  // slanje poruke
  long now = millis();
  if(now - lastMsg > sendInterval){
    lastMsg = now;
    
    // priprema stringova za slanje
    char tempStringBPM[8];
    char tempStringAvg[8];
    char tempStringIR[12];

    // pretvaranje brojeva u char array (tekst) posto pubsubclient salje samo karaktere 
    dtostrf(beatsPerMinute, 1, 2, tempStringBPM);    // decimal to string
    dtostrf(beatAvg, 1, 0, tempStringAvg);             // 1 je minimalna sirina celog niza karaktera, 2 je koliko decmala
    ltoa(irValue, tempStringIR, 10);             // mora ascii psoto je long prevelik, 10 je osnovni dekadni sistem

    if (irValue < 50000) {
      // ako nema prsta, salje se poruka gde su vrednosti nula
      client.publish("ftn/oksimetar/bpm", "0");
      client.publish("ftn/oksimetar/avg_bpm", "0");
      client.publish("ftn/oksimetar/status", "No finger?");
      Serial.println("MQTT: Nema prsta.");
    } else {
      // ako je prst tu, posalji sve vrednosti
      client.publish("ftn/oksimetar/bpm", tempStringBPM);
      client.publish("ftn/oksimetar/avg_bpm", tempStringAvg);
      client.publish("ftn/oksimetar/ir", tempStringIR);
      client.publish("ftn/oksimetar/status", "Izmereno");
      
      Serial.print("MQTT Poslato");
      Serial.print("IR=");
      Serial.print(irValue);
      Serial.print(", BPM=");
      Serial.print(beatsPerMinute);
      Serial.print(", Avg BPM=");
      Serial.print(beatAvg);

    }
  }

  Serial.println();

  particleSensor.nextSample(); 
  delay(10);
}

void setup_wifi(){   // funkcija za pvoezivanje na wifi
  delay(10);

  Serial.println();
  Serial.print("Povezujem se na ");
  Serial.println(ssid);

  // stavi u mode klijenta
  WiFi.mode(WIFI_STA);

  // probaj da se konektujes na ftn wifi
  WiFi.begin(ssid, password);

  // dokle god se ne poveze nemoj nista raditi
   while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.print("Povezan na WiFi. ");
}



void callback(char* topic, byte* message, unsigned int length){      // za sad ne znamo sta bi esp mogao da prima od poruka
  Serial.print("Message arrived on topic: ");
  Serial.print(topic);
  Serial.print(". Message: ");
  String messageTemp;

  for (int i = 0; i < length; i++) {
    Serial.print((char)message[i]);
    messageTemp += (char)message[i];
  }
  Serial.println();
}

void reconnect(){               // povezivanje esp32 na mqtt broker
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");

    String clientId = "ESP32C6Client";
     // Attempt to connect
    if (client.connect("clientId")) {      // posto je server postavljen u setup-u, klijent se povezuje nna njega - mqtt broker //  povezuje se na server sa id ESP32C6Client
      Serial.println("connected");
      client.subscribe("esp32/output");     // ne mora jer jos ne znamo koje poruke ce s aprima
    }else{
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      // Wait 5 seconds before retrying
      delay(5000);
    }
  }
}



