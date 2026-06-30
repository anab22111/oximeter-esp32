# Pulse-oximeter system MAX30102 and ESP32-C6 LCD

System for real-time meadurment of oxygen saturation and heartbeat. Data is plotted on a website and an lcd display, while showing numbers of current BPM and SPO2. Website allows user to search history of previous patients.

## Architecture


## Setup
- MAX30102 sensor
- ESP32-C6 LCD
- Laptop with mosquitto broker 
>> Installation:
sudo apt install mosquitto mosquitto-clients

## Connection
- MAX30102 and ESP32 are connected with wires and the communication is enabled via I2C protocol.
- Microcontroller on ESP32 uses an SPI communication protocol to send data and commands to the LCD display.
- ESP32 and laptop communicate via MQTT mosquitto broker that was previously installed on laptop.
- Laptop and website

## MQTT topics
1. ftn/oksimetar/sirovo - Publisher: ESP32, Subscriber: Laptop (`sub.py`) - used to send raw data for plotting
2. ftn/oksimetar/binarno - Publisher: ESP32, Subscriber: Laptop(`sub.py`) - used to send a packet of bytes containing BPM, SPO2 and their validation bits


## How to run the program
1. Upload esp_sensor.ino code to ESP-C6 via USB-C cable.
2. On laptop in temrinal run sub.py file

## How it works
>> When `sub.py` runs user is asked to enter a name for the patient whose pulse and saturation is being measured. When name is entered, a new file `merenje_name.txt` is made and a link to the website is given. In the new file `merenje_name.txt` raw IR data from the sensor is being written for first 30 seconds. When 30 seconds pass, average BPM and SPO2 is calculated and written at the end of the file. 