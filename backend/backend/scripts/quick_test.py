"""Diagnosis: wait for intro audio to end before sending audio."""
import sys, json, time, secrets, threading, numpy as np
sys.path.insert(0, '/mnt/d/zebbingo/projects/stt-test-tool/backend/scripts')
from device_firmware import DeviceFirmware
import scipy.io.wavfile as wavfile
from pathlib import Path

fw = DeviceFirmware("diag-device")
fw.on_log = lambda msg: None
fw.power_on()

wavs = list(Path("/mnt/d/zebbingo/projects/stt-test-tool/backend/audio_cache").glob("*sim.wav"))
sr, data = wavfile.read(str(wavs[0]))
if sr != 16000:
    from scipy.signal import resample
    data = resample(data, int(len(data) * 16000 / sr)).astype(np.int16)

fw.start_session(figurine_id="unicorn", nfc_id="diag")
print(f"Session: {fw.session_id}")

# Wait for intro signal
fw.wait_for_intro_eos(timeout=25)
print(f"Intro signal: done")

# WAIT for intro audio to finish playing (this takes ~25s of TTS playback)
got = fw.wait_for_intro_audio_end(timeout=90)
print(f"Intro audio end: {got}")

# Now send user audio
fw.start_turn(data)
print(f"Turn {fw.current_turn_id} sent, waiting...")

got_resp = fw.wait_for_turn_response(timeout=90)
print(f"\nResponse: {got_resp}")
print(f"Chunks: {fw.response_chunks}")
print(f"STT: '{fw.stt_text}'")

fw.stop_session()
fw.power_off()
