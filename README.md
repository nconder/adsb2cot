# adsb2cot

ADS-B to Cursor-on-target (CoT) converter

Reads air traffic data from an ADS-B receiver (like dump1090) and re-transmits it in real time to a CoT-capable endpoint or network (like TAK)

## installation
The adsb2cot program is self-contained and can run from any location. Uses standard Python libraries only.

In the default configuration, it reads the ADS-B data from localhost port 30003 (default for dump1090) and sends the CoT messages to multicast address 239.2.3.1 port 6969 (default ATAK P2P network).

## configuration
adsb2cot has no configuration file nor command-line arguments; instead, its behaviour is controlled by environment variables.

| env var | description | default |
|---|---|---|
|ADSB_HOST|ADS-B server address|127.0.0.1|
|ADSB_PORT|ADS-B server port|30003|
|ATAK_HOST|CoT destination address|239.2.3.1|
|ATAK_PORT|CoT destination port|6969|
|DEBUG|Enable debugging output|0|

## references
MIL-STD 2525C http://www.mapsymbs.com/ms2525c.pdf


---
Copyright (c) 2020 by Alec Murphy - MIT licensed