import subprocess
import signal
import string
import random
import re
import json
import time
import os
import socket
import requests

from flask import Flask, request, send_from_directory, jsonify, render_template, redirect
app = Flask(__name__, static_url_path='')


currentdir = os.path.dirname(os.path.abspath(__file__)) # get our current working directory
os.chdir(currentdir)

ssid_list = [] # create the list of wifi networks

def getssid():
    global ssid_list # make the list variable global
    if len(ssid_list) > 0: return ssid_list 
    ssid_list = []
    get_ssid_list = subprocess.check_output(('iw', 'dev', 'wlan0', 'scan', 'ap-force'))
    
    # for every wifi name, add it to our list
    ssids = get_ssid_list.splitlines() 
    for s in ssids:
        s = s.strip().decode('utf-8')
        if s.startswith("SSID"):
            a = s.split(": ")
            try: ssid_list.append(a[1])
            except: pass
    print(ssid_list)
    ssid_list.append("join hotspot without choosing a network")
    ssid_list = sorted(list(set(ssid_list)))
    return ssid_list


def id_generator(size=10, chars=string.ascii_lowercase + string.digits):
    """Generates a unique ID"""
    return ''.join(random.choice(chars) for _ in range(size))

wpa_conf = """country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
network={
    ssid="%s"
    %s
}"""

wpa_conf_default = """country=US
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
"""

@app.route('/')
def main():
    """Opens index.html"""
    piid = open('pi.id', 'r').read().strip()
    return render_template('index.html', ssids=getssid(), message="Once connected please go to: <a href='https://snaptext.live/{}' target='_blank'>snaptext.live/{}</a> to find the router's IP address.".format(piid,piid))

# Captive portal when connected with iOS or Android
@app.route('/generate_204')
def redirect204():
    """Redirects Devices"""
    return redirect("http://210.17.04.204", code=302) # used to be 192.168.4.1

@app.route('/hotspot-detect.html')
def applecaptive():
    """Redirects Apple Devices"""
    return redirect("http://210.17.04.204", code=302)

# Not working for Windows, needs work!
@app.route('/ncsi.txt')
def windowscaptive():
    return redirect("http://210.17.04.204", code=302)

def check_cred(ssid, password):
    '''Validates ssid and password and returns True if valid and False if not valid'''
    wpadir = currentdir + '/wpa/'
    testconf = wpadir + 'test.conf'
    wpalog = wpadir + 'wpa.log'
    wpapid = wpadir + 'wpa.pid'

    if not os.path.exists(wpadir): os.mkdir(wpadir) # if the wpa directory doesnt exist, make it

    for _file in [testconf, wpalog, wpapid]: if os.path.exists(_file): os.remove(_file) # remove old files

    # Generate temp wpa.conf
    result = subprocess.check_output(['wpa_passphrase', ssid, password])
    with open(testconf, 'w') as f:
        f.write(result.decode('utf-8'))

    def stop_ap(stop):
        if stop: print(subprocess.check_output(['systemctl', "stop", "hostapd", "dnsmasq", "dhcpcd"])) # Services need to be stopped to free up wlan0 interface
        else:
            print(subprocess.check_output(['systemctl', "restart", "dnsmasq", "dhcpcd"]))
            time.sleep(15)
            print(subprocess.check_output(['systemctl', "restart", "hostapd"]))

    # Sentences to check for
    fail = "pre-shared key may be incorrect"
    success = "WPA: Key negotiation completed"

    stop_ap(True)

    result = subprocess.check_output(['wpa_supplicant', "-Dnl80211", "-iwlan0", "-c/" + testconf, "-f", wpalog, "-B", "-P", wpapid])

    checkwpa = True # set our "check for wifi"
    while checkwpa:
        with open(wpalog, 'r') as f:
            content = f.read()
            if success in content:
                valid_psk = True
                checkwpa = False
            elif fail in content:
                valid_psk = False
                checkwpa = False
            else:
                continue

    # Kill wpa_supplicant to stop it from setting up dhcp, dns
    with open(wpapid, 'r') as p:
        pid = p.read()
        pid = int(pid.strip())
        os.kill(pid, signal.SIGTERM)

    stop_ap(False) # Restart services
    return valid_psk

@app.route('/static/<path:path>')
def send_static(path):
    """retrieves static files"""
    return send_from_directory('static', path)

@app.route('/signin', methods=['POST'])
def signin():
    email = request.form['email']
    if request.form['ssid'] == "join hotspot without choosing a network":
        password = ""
        
    ssid = request.form['ssid']
    password = request.form['password']

    pwd = 'psk="' + password + '"'
    if password == "": pwd = "key_mgmt=NONE" # If open AP

    print(email, ssid, password)
    valid_psk = check_cred(ssid, password)
    if not valid_psk:
        return render_template('ap.html', message="Incorrect password please try again") # User will not see this because they will be disconnected but we need to break here anyway

    with open('wpa.conf', 'w') as f: f.write(wpa_conf % (ssid, pwd))
    with open('status.json', 'w') as f: f.write(json.dumps({'status':'disconnected'}))
    subprocess.Popen(["./disable_ap.sh"])
    piid = open('pi.id', 'r').read().strip()
    return render_template('index.html', message="Please wait a few seconds to connect. Then your IP address will show up at <a href='https://snaptext.live/{}'>snaptext.live/{}</a>.".format(piid,piid))

def wificonnected():
    result = subprocess.check_output(['iwconfig', 'wlan0'])
    matches = re.findall(r'\"(.+?)\"', result.split(b'\n')[0].decode('utf-8'))
    if len(matches) > 0:
        print("got connected to " + matches[0])
        return True
    return False

if __name__ == "__main__":
    # things to run the first time it boots
    if not os.path.isfile('pi.id'):
        with open('pi.id', 'w') as f: f.write(id_generator())
        subprocess.Popen("./expand_filesystem.sh")
        time.sleep(300)
    piid = open('pi.id', 'r').read().strip()
    print(piid)
    time.sleep(15)
    
    status = {'status':'disconnected'} # get status
    if not os.path.isfile('status.json'): 
        with open('status.json', 'w') as f: f.write(json.dumps(status))
    else: 
        status = json.load(open('status.json'))
    # check connection
    if wificonnected():
        status['status'] = 'connected'
    if not wificonnected():
        if status['status'] == 'connected': # Don't change if status in status.json is hostapd
            status['status'] = 'disconnected'

    with open('status.json', 'w') as f: f.write(json.dumps(status))
    if status['status'] == 'disconnected':
        status['status'] = 'hostapd'
        with open('status.json', 'w') as f: f.write(json.dumps(status))
        with open('wpa.conf', 'w') as f: f.write(wpa_conf_default)
        subprocess.Popen("./enable_ap.sh")
    elif status['status'] == 'connected':
        piid = open('pi.id', 'r').read().strip()

        # get ip address
        status = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        status.connect(("8.8.8.8", 80))
        ipaddress = s.getsockname()[0]
        status.close()

        # alert user on snaptext
        r = requests.post("https://snaptext.live",data=json.dumps({"message":"Your router is online at {}".format(ipaddress),"to":piid,"from":"liOS Cloud Computing Services"}))
        print(r.json())
        subprocess.Popen("./startup.sh")
        while True:
            time.sleep(60000)
    else:
        app.run(host="0.0.0.0", port=80, threaded=True)
