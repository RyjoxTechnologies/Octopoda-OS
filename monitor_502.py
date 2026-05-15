#!/usr/bin/env python3
'''Octopoda 502 watcher - greps nginx access log for recent 502 Bad Gateway
responses. If threshold exceeded in the window, emails joe@octopodas.com via Resend.
Cooldown prevents flood during sustained outage.'''
import os, re, json, time, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

THRESHOLD = 3
WINDOW_MIN = 5
COOLDOWN_MIN = 10
TO = 'joe@octopodas.com'
FROM = 'Octopoda Alerts <noreply@octopodas.com>'
LOG = '/var/log/nginx/access.log'
STATE = '/var/tmp/octopoda_502_monitor.json'
MONTHS = {'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12}

def load_state():
    if Path(STATE).exists():
        try: return json.loads(Path(STATE).read_text())
        except: pass
    return {'last_alert_ts': 0}

def save_state(s):
    Path(STATE).write_text(json.dumps(s))

def count_recent():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=WINDOW_MIN)
    count, samples = 0, []
    r = subprocess.run(['tail','-5000',LOG], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        m = re.search(r'\[(\d{2})/(\w{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2})', line)
        if not m: continue
        d,mo,y,h,mn,s = m.groups()
        try:
            dt = datetime(int(y), MONTHS[mo], int(d), int(h), int(mn), int(s), tzinfo=timezone.utc)
        except KeyError: continue
        if dt < cutoff: continue
        parts = line.split()
        if len(parts) < 9: continue
        if parts[8] == '502':
            count += 1
            if len(samples) < 5: samples.append(line[:200])
    return count, samples

def send_alert(count, samples):
    key = os.environ.get('RESEND_API_KEY','')
    if not key:
        print('NO RESEND_API_KEY')
        return False
    html = '<h3>Octopoda 502 alert</h3>' +            f'<p><strong>{count}</strong> x 502 Bad Gateway in last {WINDOW_MIN} min.</p>' +            '<p>API may be restarting or failing. systemd auto-restart should recover.</p>' +            '<h4>Samples:</h4><pre>' + '\n'.join(samples) + '</pre>'
    payload = json.dumps({'from': FROM, 'to':[TO], 'subject': f'Octopoda: {count}x 502s in last {WINDOW_MIN}min', 'html': html})
    r = subprocess.run(['curl','-s','-X','POST','https://api.resend.com/emails',
        '-H',f'Authorization: Bearer {key}','-H','Content-Type: application/json','-d',payload],
        capture_output=True, text=True, timeout=15)
    return r.returncode == 0 and 'id' in r.stdout

def main():
    count, samples = count_recent()
    print(f'[{datetime.now(timezone.utc).isoformat()}] 502 count in last {WINDOW_MIN}min: {count}')
    if count < THRESHOLD: return
    state = load_state()
    now_ts = int(time.time())
    if now_ts - state['last_alert_ts'] < COOLDOWN_MIN * 60:
        print(f'within cooldown ({COOLDOWN_MIN}min), suppressing')
        return
    if send_alert(count, samples):
        state['last_alert_ts'] = now_ts
        save_state(state)
        print(f'ALERTED ({count}x 502s)')
    else:
        print('send_alert failed')

if __name__ == '__main__':
    main()
