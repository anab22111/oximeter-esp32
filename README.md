# Pulse-oximeter system MAX30102 and ESP32-C6 LCD

System for real-time measurment of oxygen saturation and heartbeat. Data is plotted on a website and an lcd display, while showing numbers of current BPM and SPO2. Website allows user to search history of previous patients.

Link to youtube video:
>https://youtu.be/IwrD5q8MEhw?si=trPSmEghSWtCMKf4

## Setup
- **Sensor:** MAX30102 Pulse Oximeter
- **Microcontroller:** ESP32-C6 
- **Display:** ST7789 SPI LCD Screen
- **Host Gateway:** Laptop with mosquitto broker 
> Installation:
*sudo apt install mosquitto mosquitto-clients*

## Connection
- MAX30102 and ESP32 are connected with wires and the communication is enabled via I2C protocol.
- ESP32-C6 and LCD display communicate via SPI using DMA (Direct Memory Access)
- ESP32 and laptop wireless communicate via local Wi-Fi, passing data packages through MQTT mosquitto broker that was previously installed on laptop.


## MQTT topics
1. **ftn/oksimetar/sirovo** 
    - Publisher: ESP32
    - Subscriber: Laptop (`sub.py`) 
    - used to send single raw IR value for plotting
2. **ftn/oksimetar/binarno** 
    - Publisher: ESP32 
    - Subscriber: Laptop(`sub.py`)
    - used to send a packet of bytes containing BPM, SPO2 and their validation bits
    - Payload:
        - `bpm` (4-byte signed int)
        - `spo2` (4-byte signed int)
        - `ir` (4-byte signed int)
        - `validBPM` (1-byte char)
        - `validSPO` (1-byte char)


## How to run the program
1. Flash `oxi_heartrate.ino` code onto ESP32-C6 using Arduino IDE.
2. Ensure your mosquitto MQTT broker service is running locally on your laptop.
3. On laptop run `sub.py` file from your terminal.

## How it works
When `sub.py` runs user is asked to enter a name for the patient whose pulse and saturation is being measured. When name is entered, a new file `merenje_name.txt` is made and a link to the website is given. 

### Data streaming
- The sensor constantly monitors infrared values. When a valid finger placement is detected (IR >= 20000) a fixed 30-second recording starts. The script streams individual data values directly into the .txt record file along with timestamps.
- The Flask server collects a rolling window of the last 200 raw data entries, passes them through the `neurokit2` digital filter to eliminate high-frequency anomalies, inverts the signal structure sends it straight to the UI.
- LCD display is refreshed every two seconds or instantly when there is no heartbeat.

### Calculations
- ESP32-C6 starts calculating BPM and SPO2 only when the `redBuffer[100]` and `irBUffer[100]` are full. Microcontroller uses the `maxim_heart_rate_and_oxygen_saturation` algorithm to get the correct values. The algorithm is then called every 25 new values.
- Validated statistics are updated over MQTT every 2 seconds.
- For simulation purposes when user removes finger ESP32-C6 logic counts that as 0 BPM and an alarm is started, as the **red flat line** files the LCD screen.