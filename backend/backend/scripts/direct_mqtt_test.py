"""Direct MQTT test - publishes session/start and subscribes simultaneously."""
import sys, json, time, threading
sys.path.insert(0, '/mnt/d/zebbingo/projects/stt-test-tool/backend')

import paho.mqtt.client as mqtt

received = []

def on_message(client, userdata, msg):
    received.append((msg.topic, msg.payload[:50]))
    print(f"  RECEIVED: {msg.topic}")

def on_connect(client, userdata, flags, rc):
    print(f"Connected: rc={rc}")
    client.subscribe("prod/direct-test-001/response/#", qos=0)

pub_client = mqtt.Client(client_id="direct_pub_test")
pub_client.connect("localhost", 1883, 60)
pub_client.loop_start()
time.sleep(1)

payload = json.dumps({
    "turn_proto": 1,
    "audio": {"codec": "opus", "sr": 16000, "channels": 1},
    "character": "unicorn",
    "nfc_id": "sim-nfc-direct",
    "mode": "dialogue",
    "fw": "1.0.0"
})

topic = "prod/direct-test-001/request/session/direct001/start"
pub_client.publish(topic, payload, qos=1)
print(f"Published: {topic}")

sub_client = mqtt.Client(client_id="direct_sub_test")
sub_client.on_connect = on_connect
sub_client.on_message = on_message
sub_client.connect("localhost", 1883, 60)
sub_client.loop_start()

print("\nWaiting 10s for response...")
for i in range(10):
    time.sleep(1)
    if received:
        print(f"\nGot {len(received)} messages!")
        break
    print(f"  [{i+1}s] waiting...")

print(f"\nTotal received: {len(received)} messages")
pub_client.loop_stop()
pub_client.disconnect()
sub_client.loop_stop()
sub_client.disconnect()
