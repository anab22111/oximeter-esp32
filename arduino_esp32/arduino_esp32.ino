
// koriscenje LovyanGFX biblioteke za prikaz stvari na lcd ekranu
// posto LovyanGFX nema definisanu nasu plocu mi moramo da napravimo klasu i definisemo sve potrebne stavke
// https://github.com/lovyan03/LovyanGFX/blob/master/examples/HowToUse/2_user_setting/2_user_setting.ino - postavka koja se prati
#include <LovyanGFX.hpp>
#include <Wire.h>
#include "MAX30105.h"
#include <PubSubClient.h>
#include "spo2_algorithm.h"
#include <WiFi.h>
#include <Adafruit_NeoPixel.h>

// ================ LED SVETLO PODESAVANJA ==============
#define PIN 8             // rgb control je na gpio8 pinu
#define NUMPIXELS 1       // samo jedna led didoda

// definisanej led diode
Adafruit_NeoPixel rgbLed(NUMPIXELS, PIN, NEO_GRB + NEO_KHZ800);   // prosledjujemo koji pin, koliko dioda
 

// ================= MREZNA podesavanja =================
const char* ssid = "FTN_wifi";
const char* password = "ftn12345";
const char* mqtt_server = "10.1.150.52"; 

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

MAX30105 particleSensor;             // inicijalizacija senzora

// ================= DEFINISANJE PROMENLJIVIH ZA ALGORITAM =================
#define BUFFER_SIZE 100
uint32_t irBuffer[BUFFER_SIZE]; 
uint32_t redBuffer[BUFFER_SIZE]; 
int32_t bufferIndex = 0;
bool bufferFull = false;

// izlazne promenljive iz algoritma
int32_t spo2 = 0; 
int8_t validSPO2 = 0; 
int32_t heartRate = 0; 
int8_t validHeartRate = 0;

// ================= DEFINISANJE PROMENLJIVIH ZA GRAF =================
#define GRAPH_X 0
#define GRAPH_Y 40     // gornjih 40 piksela rezervisano za tekst
#define GRAPH_W 320    // sirina ekrana 
#define GRAPH_H 132    // ostatak visine ekrana za graf (ukupno 172)
#define GRAPH_MID (GRAPH_Y + (GRAPH_H / 2))
static int16_t y_staro = GRAPH_MID; 

// za potrebe crtanja grafa na displeju
long sredisnjaVrednost = 250000; 
static int32_t prikazaniBPM = 0;
static int32_t prikazaniSPO2 = 0;

static int16_t grafPozicija = 0;  // trenutna X pozicija crtanja
static long minIR = 50000;
static long maxIR = 100000;

#define DRAW_EVERY_N 1  // crtaj svaki uzorak
static uint32_t lastDrawTime = 0;

// ================= PRAVLJENJE KLASE ZA  ESP32C6 - LCD =================
class LGFX_ESP32C6 : public lgfx::LGFX_Device  // klasa za nas uredjaj LGFX_ESP32C6
{
  lgfx::Panel_ST7789 _panel_instance;       // definisanje drajvera za ekran
  lgfx::Bus_SPI _bus_instance;              // posto je ekran povezan sa kontrolerom preko spi, potrebno je i to definisati
  lgfx::Light_PWM    _light_instance;       

  public:
    LGFX_ESP32C6(){   // konstruktor i konfiguracija/namestanje raznih podesavanja

      auto bus_cfg = _bus_instance.config();

      bus_cfg.spi_host = SPI2_HOST;      // SPI1 je rezervisan interno za fles memoriju cipa, pa se koristi SPI2

      bus_cfg.spi_mode = 0;              // rezim rada - tacan trenutak takta - rastuca ivica takta

      bus_cfg.freq_write = 27000000;     // frekvencija slanja podataka na ekran

      bus_cfg.freq_read = 16000000;     // frekvencija citanja podataka sa ekrana - nama nije potrebno svejedno sta je

      bus_cfg.spi_3wire = true;      // koriscenje razima bez MISO pina posto nama nije potreban, koristimo samo SCLK, CS, MOSI

      bus_cfg.use_lock = true;          // zakljucavanje transakcija, kako jedan task ne bi prekinuo drugi

      bus_cfg.dma_channel = SPI_DMA_CH_AUTO;    // postavlja DMA kanal koji ce koristiti SPI_DMA_CH_AUTO = automatsko podesavanje, DMA - Direct Memory Access, CPU odmara, DMA salje sliku na ekran u pozadini

      // mapiranje pinova, gpio
      bus_cfg.pin_sclk = 7;
      bus_cfg.pin_mosi = 6;
      bus_cfg.pin_miso = -1;             // posto ne koristimo -1
      bus_cfg.pin_dc = 15;               // data/command, kako bi lcd znao da li mikrokontroler salje podatak(1) ili komandu(0)

      _bus_instance.config(bus_cfg);    
      _panel_instance.setBus(&_bus_instance);

      //**************************//
      // PODESAVANJE LCD EKRANA //
      auto panel_cfg = _panel_instance.config();

      panel_cfg.pin_cs = 14;                  // podesavanje chip select-a, kada esp32 spusti na nulu ovaj pin -> komunikacija sa ekranom
      panel_cfg.pin_rst = 21;                 // reset
      panel_cfg.pin_busy = -1;

      panel_cfg.panel_width = 172; 
      panel_cfg.panel_height = 320;

      panel_cfg.offset_x = 34;  //       pomera sliku u centar memorije drajvera
      panel_cfg.offset_y = 0;

      panel_cfg.offset_rotation  = 0;

      panel_cfg.dummy_read_pixel = 8;     // standardno za ST7789 drajver 
      panel_cfg.dummy_read_bits  = 1;    

      panel_cfg.readable = false;        // nemamo miso zicu tako da ne treba nista

      panel_cfg.invert =  true;          // da pozadina postane crna, a ne plava/bela
      panel_cfg.rgb_order = false;       // false jer se salju 8-bitni paketi
      panel_cfg.bus_shared =  false;

      _panel_instance.config(panel_cfg);

      //********************************//
      // PODESAVANJE POZADISNKOG SVETLA//
      auto light_cfg = _light_instance.config();

      light_cfg.pin_bl = 22;       // broj pina na koji je pozadinsko osvetljenje povezano
      light_cfg.invert = false;
      light_cfg.freq = 44100; 
      light_cfg.pwm_channel = 1; 

      _light_instance.config(light_cfg);
      _panel_instance.setLight(&_light_instance);
       
      setPanel(&_panel_instance);
    }
};

// kreiranje instance pripremljene klase
LGFX_ESP32C6 display;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Inicijalizacija sistema...");
 
  Wire.begin(1, 0);
  Wire.setClock(400000);

  // PODESAVANJA ZA SENZOR //
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 nije pronađen!");
    while (1);
  }
  Serial.println("Sistem spreman. Postavite prst stabilno.");

  setup_wifi();

  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  // podesavanja optimalna za sakupljanje SpO2 bafera
  byte ledBrightness = 60;  
  byte sampleAverage = 1;   // na 1 da dobijemo sirovije i brze uzorke za m_algorithm
  byte ledMode = 2;         // 2 = Red + IR
  byte sampleRate = 100;    
  int pulseWidth = 411;     
  int adcRange = 4096;      

  particleSensor.setup(ledBrightness, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);

  // PODESAVANJA ZA ESP DISPLEJ //
  // inicijalizacija SPI magistrale i panela
  display.init();

  display.setRotation(1);          // okreni horizontalno
  display.setBrightness(200);      // pozadinsko svetlo na umerenoj jacini

  display.fillScreen(TFT_BLACK);   // oboji ekran u crno

  display.setTextSize(2);
  display.setTextColor(TFT_GREEN, TFT_BLACK);
  display.drawString("ECG: 75 BPM", 10, 10);

  // PODESAVANJA ZA LED
  rgbLed.begin();            // inicijalizacija
  rgbLed.setBrightness(200); 
  // postavi inicijalnu boju na zeleno
  rgbLed.setPixelColor(0, rgbLed.Color(0, 255, 0));
  rgbLed.show();
}

void loop() {

  if (!client.connected()) {
    reconnect();
  }
  client.loop();    

  // citamo sirove vrednosti
  long irValue = particleSensor.getIR();
  long redValue = particleSensor.getRed();

  // KONTINUALNO CRTANJE GRAFIKA: crta se jedna tacka u svakom prolazu kroz loop
  uint32_t now_ms = millis();
  if (now_ms - lastDrawTime >= 10) {
    lastDrawTime = now_ms;
    crtajTackuNaEkranu(irValue);
  }


  // slanje ir vrednosti za plotovanje
  if (irValue >= 20000) {
    char irString[12];
    ltoa(irValue, irString, 10);
    client.publish("ftn/oksimetar/sirovo", irString); 
  }
  else{
    irValue = 0;
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
    prikazaniBPM = 0;
    prikazaniSPO2 = 0;
    // postavi boju na crveno
    rgbLed.setPixelColor(0, rgbLed.Color(0, 255, 0));
    rgbLed.show();
    //*************************/
    osveziTekstNaEkranu();
  } else {
    // ukoliko je prethodno bila crvena vrati na zelenu
    rgbLed.setPixelColor(0, rgbLed.Color(255, 0, 0));
    rgbLed.show();

    if (!bufferFull) {           // ako nije pun ne vrsi se merenje
      // punjnje bafera sa 100 uzoraka
      redBuffer[bufferIndex] = redValue;
      irBuffer[bufferIndex] = irValue;
      bufferIndex++;

      if (bufferIndex >= BUFFER_SIZE) {
        bufferFull = true;
        // prvi proracun nad prvih 100 uzoraka
        maxim_heart_rate_and_oxygen_saturation(irBuffer, BUFFER_SIZE, redBuffer, &spo2, &validSPO2, &heartRate, &validHeartRate);
      }
    } 
    else {
      // pomeri prvih 75 uzoraka na pocetak
      for (byte i = 0; i < 75; i++) {
        redBuffer[i] = redBuffer[i + 25];
        irBuffer[i] = irBuffer[i + 25];
      }

      // prikupi novih 25 uzoraka
      for (byte i = 75; i < BUFFER_SIZE; i++) {
        while (particleSensor.available() == false) {
          particleSensor.check();
        }
        
        redBuffer[i] = particleSensor.getRed();
        irBuffer[i] = particleSensor.getIR();
        
        // crtanje tokom punjenja — ne blokira grafik
        crtajTackuNaEkranu(irBuffer[i]);
        
        // MQTT slanje tokom punjenja
        if (irBuffer[i] >= 20000) {
          char irSubString[12];
          ltoa(irBuffer[i], irSubString, 10);
          client.publish("ftn/oksimetar/sirovo", irSubString);
        }
        
        particleSensor.nextSample();
      }

      // racunanje nakon sto su 25 novih uzoraka prikupljeni
      maxim_heart_rate_and_oxygen_saturation(irBuffer, BUFFER_SIZE, redBuffer,
                                            &spo2, &validSPO2, &heartRate, &validHeartRate);
    }
  }

  // ================= MQTT SLANJE PODATAKA (BINARNO) I OSVEŽAVANJE EKRANA =================
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
      paket.bpm = lastValidBPM;
      paket.validBPM = 1;
      prikazaniBPM = lastValidBPM; // prosledjujemo istu validnu i filtriranu vrednost ekranu
    } else {
      // ako je prst tu ali trenutno racuna, zadrzi poslednji dobar puls umesto nule
      if (irValue > 20000 && lastValidBPM > 0) {
        paket.bpm = lastValidBPM;
        paket.validBPM = 0;
        prikazaniBPM = lastValidBPM;
      } else {
        paket.bpm = 0;
        paket.validBPM = 0;
        prikazaniBPM = 0;
      }
    }
    // ako algoritam vrati validan SpO2
    if (validSPO2 == 1 && spo2 > 70 && spo2 <= 100 && irValue > 20000) {
      paket.spo2 = spo2;
      paket.validSPO2 = 1;
      prikazaniSPO2 = spo2; // prosledjujemo stabilan SpO2 ekranu
    } else {
      paket.spo2 = 0;
      paket.validSPO2 = 0;
      if (irValue < 20000) {
        prikazaniSPO2 = 0;
      }
    }
    
    // osvezavamo tekst na ekranu svake 2 sekunde u sinhronizaciji sa MQTT-om
    osveziTekstNaEkranu();

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

// funkcija koja osvezava tekst na vrhu ekrana
void osveziTekstNaEkranu() {
  display.setTextSize(2);
  display.setCursor(10, 10);
  
  if (prikazaniBPM > 0 && prikazaniSPO2 > 0) {
    display.setTextColor(TFT_GREEN, TFT_BLACK);
    display.printf("HR: %d BPM  SpO2: %d%%              ", prikazaniBPM, prikazaniSPO2);
  } else {
    display.setTextColor(TFT_YELLOW, TFT_BLACK);
    display.printf("Racunam... Postavite prst      ");
  }
}

// funkcija za crtanje pulsnog signala
void crtajTackuNaEkranu(long irValue) {
  if (irValue < 20000) {
    display.fillRect(grafPozicija, GRAPH_Y, 8, GRAPH_H, TFT_BLACK);
    display.drawLine(grafPozicija == 0 ? 0 : grafPozicija - 1, 
                     GRAPH_MID, grafPozicija, GRAPH_MID, TFT_RED);
    grafPozicija++;
    if (grafPozicija >= GRAPH_W) grafPozicija = 0;
    return;
  }

  // FIKSNI prozor za srednju vrednost
  // rolling average za sredinu, a FIKSNI opseg
  sredisnjaVrednost = (sredisnjaVrednost * 0.98) + (irValue * 0.02);
  
  // fiksni opseg +-2000 oko srednje vrednosti (podesavanje po potrebi)
  long vizMin = sredisnjaVrednost - 2000;
  long vizMax = sredisnjaVrednost + 2000;

  // map(trenutna_vrednost, donja_granica_trenutnog_signala, gornja_granica_trenutnog_signala, izlazni_min, izlazni_max)
  // funkcija map uzima nasu ir vrednost koja se nalazi u prozoru (vizMin, vizMax) odredjuje njen procenat unutar prozora
  // tj. koliko blizu/daleko vrha ili dna
  // izlazni_min i izlazni_max u kom opsegu piksela zapravo crta
  int16_t y_trenutno = map(irValue, vizMin, vizMax, 
                           (GRAPH_Y + GRAPH_H - 5), (GRAPH_Y + 5));
  y_trenutno = constrain(y_trenutno, GRAPH_Y + 2, GRAPH_Y + GRAPH_H - 2);

  display.fillRect(grafPozicija + 1, GRAPH_Y, 8, GRAPH_H, TFT_BLACK);

  if (grafPozicija > 0) {
    // osnovna linija izmedju tacaka
    display.drawLine(grafPozicija - 1, y_staro, 
                     grafPozicija, y_trenutno, TFT_GREEN);
    
    // vertikalno popuni sve piksele izmedju y_staro i y_trenutno
    // na trenutnoj X poziciji
    int16_t yMin = min(y_staro, y_trenutno);
    int16_t yMax = max(y_staro, y_trenutno);
    for (int16_t y = yMin; y <= yMax; y++) {
      display.drawPixel(grafPozicija, y, TFT_GREEN);
    }
  }

  y_staro = y_trenutno;
  grafPozicija++;
  if (grafPozicija >= GRAPH_W) grafPozicija = 0;
}