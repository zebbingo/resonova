#!/bin/bash
echo "=== WSL processes ==="
ps aux | grep -E "(python.*server|python.*bot)" | grep -v grep || echo "(no matching processes)"
echo ""
echo "=== MQTT broker test ==="
python3 -c "
import paho.mqtt.client as mqtt
import time
c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
def on_connect(cl, ud, fl, rc, prop=None):
    print(f'on_connect rc={rc}')
    cl.disconnect()
c.on_connect = on_connect
c.connect('localhost', 1883, 10)
c.loop_start()
time.sleep(5)
c.loop_stop()
" 2>&1 || echo "MQTT test failed"
echo ""
echo "=== Server HTTP test ==="
curl -s http://localhost:8765/api/device/list 2>&1 | head -50 || echo "Server not responding"
