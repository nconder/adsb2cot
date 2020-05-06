#!/usr/bin/python -u

# ADS-B to Cursor-on-target (CoT) converter
# Copyright (c) 2020 by Alec Murphy, MIT licensed
#
# Reads air traffic data from an ADS-B receiver (like dump1090)
#   and re-transmits it in real time to a CoT network (like TAK)
# No special software or plugins required on the mobile terminals

import logging
import os
import socket
import xml.etree.ElementTree as ET
from time import time, gmtime, strftime

# ADS-B data source - default to dump1090 on localhost
ADSB_HOST = os.getenv('ADSB_HOST', '127.0.0.1')
ADSB_PORT = int(os.getenv('ADSB_PORT', '30003'))

# COT destination - default to TAK multicast network
ATAK_HOST = os.getenv('ATAK_HOST', '239.2.3.1')
ATAK_PORT = int(os.getenv('ATAK_PORT', '6969'))

# Validity period of CoT events, for setting "stale" attribute
PLANE_EVT_TTL = 120  # seconds

# Event type (use "fixed wing" aircraft for simplicity)
# MS2525c: WAR.AIRTRK.CVL.FIXD S * A * CF -- -- ** ** * FIXED WING
TYPE_PLANE = 'a-f-A-C-F'

# We want the CoT UIDs to be fairly collision-proof yet deterministic
#   (same aircraft same UID across all systems)
# We use a fixed 10-byte part (root) and vary the last 6-bytes (node)
# ${UUID_ROOT}-1ca000XXXXXX where XXXXXX is the 24-bit aircraft HEX ID
UUID_ROOT = '7ea452c5-a1ec-ad5b-a7ac'


def plane2CoT(plane):
    """
    Generate a CoT XML object from our internal aircraft representation
    (a key-value dict based on ADSB data), performing unit conversions
    where necessary
    """

    # Generate UUID based on plane ICAO
    uuid = UUID_ROOT + '-1ca0' + '00' + plane['aircraft_id'].lower()

    # Generate remark field, for now "ICAO:HEX_ID"
    remark = 'ICAO:' + plane['aircraft_id']

    # Event "how" (how the coordinates were generated)
    #ev_how = 'h-g-i-g-o'
    EV_HOW = 'm-g'  # presumably GPS

    TIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

    # Event fields
    event_attr = {
        'version': '2.0',
        'uid': uuid,
        'time': strftime(TIME_FORMAT, gmtime()),
        'start': strftime(TIME_FORMAT, gmtime()),
        'stale': strftime(TIME_FORMAT, gmtime(time()+PLANE_EVT_TTL)),
        'type': TYPE_PLANE,
        'how': EV_HOW
    }

    # Point fields
    point_attr = {
        'lat': plane['lat'],
        'lon': plane['lon'],
        # UNIT CONVERT: altitude ft to meters
        'hae': '%.2f' % (0.3048 * int(plane['altitude'])),
        'ce': '9999999.0',  # unspec
        'le': '9999999.0',  # unspec
    }

    # Mandatory schema, "event" element at top level, with
    #   sub-elements "point" and "detail"
    cot = ET.Element('event', attrib=event_attr)
    ET.SubElement(cot, 'point', attrib=point_attr)
    det = ET.SubElement(cot, 'detail')

    # Optional subelement "track" - include if data available
    try:
        track_attr = {
            'course': plane['ground_track'],  # in 360 degrees
            # UNIT CONVERT: speed from knots to m/s
            'speed': '%.4f' % (0.5144 * int(plane['ground_speed'])),
        }
        ET.SubElement(det, 'track', attrib=track_attr)
    except KeyError:
        pass

    ET.SubElement(det, 'contact', attrib={'callsign': plane['callsign']})
    ET.SubElement(det, 'remarks').text = remark

    cotXML = '<?xml version="1.0" standalone="yes"?>'.encode('utf-8')
    cotXML += ET.tostring(cot)

    return(cotXML)


if __name__ == '__main__':

    planes = {}

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)

    i_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        conn = i_sock.connect((ADSB_HOST, ADSB_PORT))
    except socket.error as exc:
        logger.debug('ADSB connection to %s:%d failed: %s' %
                     (ADSB_HOST, ADSB_PORT, exc))
        exit()

    logger.info('adsb2cot running')

    while True:
        # Read a line, blocking
        try:
            adsbLine = i_sock.recv(1024)
        except:
            logger.debug('adsb2cot exiting')
            break

        if (len(adsbLine) == 0):
            logger.debug('zero length read')
            break

        # Mailbox flag, indicates that a CoT update is necessary
        updateCoT = False

        # Input is in "SBS-1 BaseStation port 30003" format (CSV)
        adsbData = adsbLine.rstrip().decode('utf-8').split(',')

        try:
            hexID = adsbData[4]
        except IndexError:
            # bad adsb line
            continue

        if hexID not in planes:
            # create aircraft record if not found
            planes[hexID] = {}
            planes[hexID]['aircraft_id'] = hexID

            # use ICAO HEX as temporary callsign / label
            planes[hexID]['callsign'] = 'x' + hexID

        # 1-4 are the messages we want; ignore the rest
        if (int(adsbData[1]) > 4):
            continue

        # DEBUG DUMP 1 of 3 - ADSB data
        logger.debug(adsbData)

        if (adsbData[1] == '1'):  # ES_IDENT_AND_CATEGORY
            # Only interesting information is callsign
            planes[hexID]['callsign'] = adsbData[10]

        elif (adsbData[1] == '4'):  # ES_AIRBORNE_VEL
            planes[hexID]['ground_speed'] = adsbData[12]  # in knots
            planes[hexID]['ground_track'] = adsbData[13]
            planes[hexID]['vertical_rate'] = adsbData[16]

        elif (adsbData[1] == '3'):  # ES_AIRBORNE_POS
            planes[hexID]['lat'] = adsbData[14]
            planes[hexID]['lon'] = adsbData[15]
            # Not always present
            if int(adsbData[11]) > 0:
                planes[hexID]['altitude'] = adsbData[11]
            # Send update to ATAK
            updateCoT = True

        # DEBUG DUMP 2 of 3 - internal representation
        logger.debug(planes[hexID])

        if updateCoT:
            # Construct CoT message from recorded data
            cotMsg = plane2CoT(planes[hexID])

            # DEBUG DUMP 3 of 3 - CoT message
            logger.debug('CoT: ' + cotMsg.decode('utf-8'))

            # Send CoT message to ATAK
            o_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            o_sock.sendto(cotMsg, (ATAK_HOST, ATAK_PORT))
            o_sock.close()
            logger.debug('Sent to %s:%d\n' % (ATAK_HOST, ATAK_PORT))

            planes[hexID]['last_sent'] = time()

        planes[hexID]['last_seen'] = time()
