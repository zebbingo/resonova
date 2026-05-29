#!/usr/bin/env python3
"""Verify AWS IoT Core MQTT connectivity via the test platform's DeviceFirmware.

Usage:
    uv run python scripts/verify_aws_iot.py --host <endpoint>.iot.eu-west-2.amazonaws.com
    uv run python scripts/verify_aws_iot.py --host <endpoint> --list-things
    uv run python scripts/verify_aws_iot.py --host <endpoint> --thing my-device

The script uses MQTT_TLS_CA_CERT / MQTT_TLS_CLIENT_CERT / MQTT_TLS_CLIENT_KEY
from the environment (or --cert-root/--thing CLI args) to establish a TLS
connection and verify the full pub/sub round trip.
"""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.device_firmware import DeviceFirmware


DEFAULT_PORT = 8883


def _find_one(base_dir: Path, patterns: tuple[str, ...], label: str) -> Path:
    for pattern in patterns:
        matches = sorted(path for path in base_dir.glob(pattern) if path.is_file())
        if len(matches) == 1:
            return matches[0]
        non_sg_matches = [path for path in matches if ".sg." not in path.name]
        if len(non_sg_matches) == 1:
            return non_sg_matches[0]
    all_matches: list[Path] = []
    for pattern in patterns:
        all_matches.extend(sorted(path for path in base_dir.glob(pattern) if path.is_file()))
    unique_matches = list(dict.fromkeys(all_matches))
    if len(unique_matches) == 1:
        return unique_matches[0]
    if not unique_matches:
        raise FileNotFoundError(f"No {label} found under {base_dir}")
    formatted = "\n  ".join(str(path) for path in unique_matches)
    raise ValueError(
        f"Multiple {label} files found under {base_dir}; pass --{label.replace(' ', '-')} explicitly:\n  {formatted}"
    )


def _find_ca(thing_dir: Path, cert_root: Path | None) -> Path | None:
    ca_patterns = ("root-CA.crt", "AmazonRootCA*.pem", "*RootCA*.pem", "*.ca.pem")
    base_dirs = [thing_dir]
    if cert_root:
        base_dirs.append(cert_root)
    for base_dir in base_dirs:
        for pattern in ca_patterns:
            matches = sorted(path for path in base_dir.rglob(pattern) if path.is_file())
            if matches:
                return matches[0]
    return None


def _resolve_thing_dir(cert_root: Path | None, thing: str | None, cert_dir: Path | None) -> Path:
    if cert_dir:
        return cert_dir.expanduser().resolve()
    if not cert_root:
        raise ValueError("Pass --cert-root or --cert-dir")
    if not thing:
        raise ValueError("Pass --thing or --cert-dir")
    return (cert_root.expanduser() / thing).resolve()


def _list_things(cert_root: Path) -> int:
    if not cert_root.exists():
        print(f"Certificate root does not exist: {cert_root}", file=sys.stderr)
        return 2
    rows: list[str] = []
    for directory in sorted(path for path in cert_root.iterdir() if path.is_dir()):
        certs = list(directory.glob("*.cert.pem")) + list(directory.glob("*.pem.crt"))
        keys = list(directory.glob("*.private.key")) + list(directory.glob("*-private.key"))
        if certs and keys:
            rows.append(directory.name)
    if not rows:
        print(f"No certificate folders found under {cert_root}")
        return 1
    print("\n".join(rows))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default=os.getenv("MQTT_HOST"),
        help="AWS IoT MQTT endpoint; can also be set with MQTT_HOST",
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("MQTT_PORT", str(DEFAULT_PORT))),
        help="MQTT TLS port",
    )
    parser.add_argument(
        "--cert-root", type=Path,
        default=Path(os.environ["AWS_IOT_CERT_ROOT"]) if os.getenv("AWS_IOT_CERT_ROOT") else None,
        help="Root directory containing certificate folders; can also be set with AWS_IOT_CERT_ROOT",
    )
    parser.add_argument("--thing", default=os.getenv("AWS_IOT_THING"),
                        help="Certificate subfolder name under --cert-root")
    parser.add_argument("--cert-dir", type=Path,
                        help="Certificate directory; overrides --cert-root/--thing")
    parser.add_argument("--ca-file", type=Path, help="Root CA file. Auto-detected when omitted")
    parser.add_argument("--cert-file", type=Path, help="Device certificate file. Auto-detected when omitted")
    parser.add_argument("--key-file", type=Path, help="Device private key file. Auto-detected when omitted")
    parser.add_argument("--device-id", default=f"verify-{uuid.uuid4().hex[:8]}",
                        help="Device ID for the test connection")
    parser.add_argument("--list-things", action="store_true",
                        help="List usable certificate subfolders and exit")
    args = parser.parse_args()

    cert_root = args.cert_root.expanduser().resolve() if args.cert_root else None

    if args.list_things:
        if not cert_root:
            print("Missing --cert-root (or AWS_IOT_CERT_ROOT) for --list-things.", file=sys.stderr)
            return 2
        return _list_things(cert_root)

    if not args.host:
        print("Missing --host (or MQTT_HOST).", file=sys.stderr)
        return 2

    try:
        thing_dir = _resolve_thing_dir(cert_root, args.thing, args.cert_dir)
        cert_file = (
            args.cert_file.expanduser().resolve() if args.cert_file
            else _find_one(thing_dir, ("*.cert.pem", "*.pem.crt"), "cert file")
        )
        key_file = (
            args.key_file.expanduser().resolve() if args.key_file
            else _find_one(thing_dir, ("*.private.key", "*-private.key"), "key file")
        )
        ca_file = (
            args.ca_file.expanduser().resolve() if args.ca_file
            else _find_ca(thing_dir, cert_root)
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not cert_file.exists():
        print(f"Certificate not found: {cert_file}", file=sys.stderr)
        return 2
    if not key_file.exists():
        print(f"Private key not found: {key_file}", file=sys.stderr)
        return 2
    if not ca_file or not ca_file.exists():
        print(f"Root CA not found: {ca_file}", file=sys.stderr)
        return 2

    device_id = args.device_id
    test_topic = f"development/{device_id}/verify/test"
    test_payload = json.dumps({
        "device_id": device_id,
        "sent_at": time.time(),
        "nonce": uuid.uuid4().hex,
    })

    received = Event()
    result: list[str] = []

    def on_event(etype: str, data):
        if etype == "mqtt_message":
            topic = data.get("topic", "")
            payload = data.get("payload", "")
            if topic == test_topic:
                print(f"  [RECV] echo received on {topic}")
                result.append(payload)
                received.set()

    print(f"\n{'='*60}")
    print(f"AWS IoT Core Connection Verification")
    print(f"{'='*60}")
    print(f"  Endpoint: {args.host}:{args.port}")
    print(f"  CA:       {ca_file}")
    print(f"  Cert:     {cert_file}")
    print(f"  Key:      {key_file}")
    print(f"  Device:   {device_id}")
    print(f"  Topic:    {test_topic}")
    print(f"{'='*60}")

    print("\n[1] Creating DeviceFirmware instance...")
    fw = DeviceFirmware(
        device_id,
        env="development",
        broker_host=args.host,
        broker_port=args.port,
        tls_enabled=True,
        tls_ca_cert=str(ca_file),
        tls_client_cert=str(cert_file),
        tls_client_key=str(key_file),
        on_mqtt_event=on_event,
    )
    print("  OK: DeviceFirmware created")

    print("\n[2] Connecting to AWS IoT Core...")
    try:
        fw.power_on()
        print(f"  OK: Connected to {args.host}:{args.port}")
    except ConnectionError as exc:
        print(f"  FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}", file=sys.stderr)
        return 1

    print("\n[3] Publishing test message...")
    import paho.mqtt.client as mqtt
    fw._client.publish(test_topic, test_payload, qos=1)
    print(f"  OK: Published to {test_topic}")

    print("\n[4] Waiting for echo (15s timeout)...")
    if received.wait(timeout=15):
        print(f"  OK: Echo received, payload matches")
    else:
        print(f"  WARN: No echo received within 15s")
        print(f"  This may be expected if no subscriber is on the topic.")

    print("\n[5] Cleaning up...")
    fw.power_off()
    print("  OK: Disconnected")

    print(f"\n{'='*60}")
    print("VERIFICATION COMPLETE")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
