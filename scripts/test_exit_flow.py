#!/usr/bin/env python3
"""Test the full exit flow: list trucks, send exit, verify results."""

import json
import time
import urllib.request

BASE = "http://localhost:8080"

# 1. List trucks from S3
print("=" * 60)
print("1. Trucks currently in S3:")
print("=" * 60)
r = urllib.request.urlopen(f"{BASE}/api/trucks")
trucks = json.loads(r.read())
for t in trucks:
    print(f"   {t['truck_id'][:8]}  {t['license_plate']}  event={t['event']}")

if not trucks:
    print("   No trucks found — creating one first.")
    req = urllib.request.Request(
        f"{BASE}/api/trucks/enter?plate=EXIT-TEST-001",
        method="POST",
    )
    r = urllib.request.urlopen(req)
    result = json.loads(r.read())
    exit_truck_id = result["truck_id"]
    print(f"   Created truck: {exit_truck_id}")
    time.sleep(2)  # wait for background S3 upload
else:
    exit_truck_id = trucks[0]["truck_id"]

# 2. Send exit
print()
print("=" * 60)
print(f"2. Sending exit for truck {exit_truck_id[:8]}...")
print("=" * 60)
req = urllib.request.Request(
    f"{BASE}/api/trucks/exit?truck_id={exit_truck_id}",
    method="POST",
)
try:
    r = urllib.request.urlopen(req)
    result = json.loads(r.read())
    print(f"   Response: {result}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"   Error {e.code}: {body}")

# 3. Wait for background task and check S3
print()
print("Waiting 3s for S3 background upload...")
time.sleep(3)

print()
print("=" * 60)
print("3. Trucks in S3 after exit:")
print("=" * 60)
r = urllib.request.urlopen(f"{BASE}/api/trucks")
trucks = json.loads(r.read())
for t in trucks:
    event = t["event"]
    plate = t["license_plate"]
    tid = t["truck_id"][:8]
    extra = ""
    if event == "truck_exit":
        extra = f"  exit_time={t.get('exit_time','?')}"
    print(f"   {tid}  {plate}  event={event}{extra}")

# 4. Dashboard check
print()
print("=" * 60)
print("4. Dashboard HTML check (searching for EXIT-TEST):")
print("=" * 60)
r = urllib.request.urlopen(f"{BASE}/")
html = r.read().decode()
if "EXIT-TEST" in html:
    print("   ✅ Dashboard shows EXIT-TEST truck data")
else:
    print("   ⚠️  EXIT-TEST not found in dashboard HTML")
if "Exited" in html or "exit" in html.lower():
    print("   ✅ Dashboard contains exit status references")
