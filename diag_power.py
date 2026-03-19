"""Diagnostic script: analyze IpBike_152.gpx around minutes 92-97 to find root cause of absurd power estimates."""
import math, sys, statistics
sys.path.insert(0, ".")
from utils.gpx_utils import parse_gpx_points, compute_distances

GPX = "imported_gpx/IpBike_152.gpx"
T_START, T_END = 90*60, 100*60  # analyze 90m-100m range (wider window)

# Physics params (same as server.py defaults)
M_TOT = 75 + 10  # rider + bike
G = 9.81
RHO = 1.225
CRR = 0.005
CDA = 0.32
MAX_SPEED = 35.0
MAX_SLOPE = 0.35
MAX_POWER = 2500

points = parse_gpx_points(GPX)
points = compute_distances(points)
t0 = points[0]["time"]
for p in points:
    p["t_s"] = (p["time"] - t0).total_seconds() if p["time"] else None
points = [p for p in points if p["t_s"] is not None]

print(f"Total points: {len(points)}, duration: {points[-1]['t_s']:.0f}s ({points[-1]['t_s']/60:.1f}min)")
print(f"\n{'='*100}")
print(f"DETAILED ANALYSIS: {T_START//60}m - {T_END//60}m")
print(f"{'='*100}\n")

# Find segments in the time range
segs_in_range = []
power_vals = []
for i in range(1, len(points)):
    p0, p1 = points[i-1], points[i]
    if p0["t_s"] < T_START or p1["t_s"] > T_END:
        continue
    dt = p1["t_s"] - p0["t_s"]
    dd = p1["dist_from_start_m"] - p0["dist_from_start_m"]
    de = p1["ele"] - p0["ele"]
    if dt < 0.01 or dd <= 0:
        continue
    v_raw = dd / dt
    slope_raw = de / dd
    v = min(v_raw, MAX_SPEED)
    slope = max(-MAX_SLOPE, min(MAX_SLOPE, slope_raw))
    f_grav = M_TOT * G * math.sin(math.atan(slope))
    f_roll = M_TOT * G * math.cos(math.atan(slope)) * CRR
    f_aero = 0.5 * RHO * CDA * v * v
    p_raw = (f_grav + f_roll + f_aero) * v
    p_clamped = max(0, min(p_raw, MAX_POWER))

    is_anomaly = v_raw > 25 or abs(slope_raw) > 0.3 or p_raw > 500 or dt < 1.0
    segs_in_range.append({
        "t": p0["t_s"], "dt": dt, "dd": dd, "de": de,
        "v_raw": v_raw, "slope_raw": slope_raw,
        "p_raw": p_raw, "p_clamped": p_clamped,
        "ele0": p0["ele"], "ele1": p1["ele"],
        "lat0": p0["lat"], "lng0": p0["lng"],
        "lat1": p1["lat"], "lng1": p1["lng"],
        "anomaly": is_anomaly,
    })
    power_vals.append(p_clamped)

print(f"Segments in range: {len(segs_in_range)}")
if power_vals:
    print(f"Power stats: avg={statistics.mean(power_vals):.1f}W, "
          f"median={statistics.median(power_vals):.1f}W, "
          f"max={max(power_vals):.1f}W, "
          f"p95={sorted(power_vals)[int(len(power_vals)*0.95)]:.1f}W")
    at_cap = sum(1 for v in power_vals if v >= MAX_POWER - 1)
    print(f"Segments at {MAX_POWER}W cap: {at_cap} ({100*at_cap/len(power_vals):.1f}%)")

print(f"\n--- ANOMALOUS SEGMENTS (v>25m/s OR |slope|>30% OR P>500W OR dt<1s) ---")
print(f"{'t_s':>7} {'dt':>5} {'dd':>7} {'de':>7} {'v_raw':>8} {'slope%':>8} {'P_raw':>9} {'P_clamp':>8} {'ele0':>6}→{'ele1':>6}")
for s in segs_in_range:
    if s["anomaly"]:
        print(f"{s['t']:7.1f} {s['dt']:5.1f} {s['dd']:7.1f} {s['de']:7.2f} "
              f"{s['v_raw']:8.2f} {s['slope_raw']*100:8.2f}% {s['p_raw']:9.1f} {s['p_clamped']:8.1f} "
              f"{s['ele0']:6.1f}→{s['ele1']:6.1f}")

# Count how many seconds in range hit the cap
print(f"\n--- POWER DISTRIBUTION (1-second bins, {T_START//60}m-{T_END//60}m) ---")
total_secs = T_END - T_START
power_1s = [0.0] * total_secs
for s in segs_in_range:
    w = s["p_clamped"]
    s0 = int(s["t"] - T_START)
    s1 = int(s["t"] + s["dt"] - T_START)
    for sec in range(max(0, s0), min(total_secs, s1)):
        power_1s[sec] = w

# Show distribution
bins = [0, 50, 100, 200, 300, 500, 1000, 2000, 2500]
for i in range(len(bins)-1):
    lo, hi = bins[i], bins[i+1]
    cnt = sum(1 for v in power_1s if lo <= v < hi)
    print(f"  {lo:5d}-{hi:5d}W: {cnt:4d}s ({100*cnt/total_secs:.1f}%)")
cnt_cap = sum(1 for v in power_1s if v >= 2500)
print(f"  >=2500W: {cnt_cap:4d}s ({100*cnt_cap/total_secs:.1f}%)")

avg_5min = sum(power_1s) / len(power_1s)
print(f"\nAvg power over this 10-min window: {avg_5min:.1f}W")

# Find the worst 5-min window
prefix = [0.0]
for v in power_1s:
    prefix.append(prefix[-1] + v)
best_avg = 0
best_start = 0
for start in range(len(power_1s) - 300 + 1):
    avg = (prefix[start + 300] - prefix[start]) / 300
    if avg > best_avg:
        best_avg = avg
        best_start = start
print(f"Best 5-min avg in this window: {best_avg:.1f}W at offset {best_start}s ({(T_START+best_start)/60:.1f}m-{(T_START+best_start+300)/60:.1f}m)")

# Show the actual power meter data if present
print(f"\n--- GPX POWER METER DATA (extensions) around {T_START//60}m-{T_END//60}m ---")
import gpxpy
with open(GPX) as f:
    gpx = gpxpy.parse(f)
pwr_data = []
for track in gpx.tracks:
    for seg in track.segments:
        for pt in seg.points:
            if pt.time:
                t_s = (pt.time - gpx.tracks[0].segments[0].points[0].time).total_seconds()
                if T_START <= t_s <= T_END:
                    for ext in (pt.extensions or []):
                        for child in list(ext):
                            tag = child.tag.split("}")[-1].lower()
                            if tag in ("power", "watts"):
                                try:
                                    pwr_data.append((t_s, float(child.text)))
                                except:
                                    pass
if pwr_data:
    vals = [v for _, v in pwr_data]
    print(f"  Power meter points: {len(pwr_data)}")
    print(f"  Avg: {statistics.mean(vals):.1f}W, Max: {max(vals):.1f}W, Median: {statistics.median(vals):.1f}W")
else:
    print("  No power meter data in extensions")

gpx_path = "imported_gpx/IpBike_152.gpx"
points = parse_gpx_points(gpx_path)
points = compute_distances(points)

t0 = points[0]["time"]
for p in points:
    p["t_s"] = (p["time"] - t0).total_seconds() if p["time"] else None
points = [p for p in points if p["t_s"] is not None]

print(f"Total points: {len(points)}")
print(f"Duration: {points[-1]['t_s']:.0f}s ({points[-1]['t_s']/60:.1f}min)")
print(f"Total distance: {points[-1]['dist_from_start_m']:.0f}m")
print()

# Check if GPX has power extensions
import gpxpy
with open(gpx_path) as f:
    gpx = gpxpy.parse(f)

sample_exts = []
for track in gpx.tracks:
    for seg in track.segments:
        for i, pt in enumerate(seg.points):
            if pt.extensions:
                for ext in pt.extensions:
                    # Collect extension tag names from first few points
                    sample_exts.append((i, ext.tag, ext.text, {c.tag: c.text for c in ext}))
                if len(sample_exts) >= 5:
                    break
        if sample_exts:
            break
    if sample_exts:
        break

print("=== GPX EXTENSIONS (first 5 points with extensions) ===")
for idx, tag, text, children in sample_exts:
    print(f"  Point {idx}: tag={tag}, text={text}")
    for ctag, ctext in children.items():
        print(f"    child: {ctag} = {ctext}")
print()

# Physics model parameters (same as server.py)
m_tot = 85.0  # 75 + 10
g = 9.81
rho = 1.225
crr = 0.005
cda = 0.32
MAX_SPEED_MS = 35.0
MAX_SLOPE = 0.35
MAX_INST_POWER = 2500

# Analyze the problematic window: minutes 90-100 (broader than 92-97 for context)
T_START = 90 * 60  # 5400s
T_END = 100 * 60   # 6000s

print(f"=== RAW DATA: minutes {T_START//60}-{T_END//60} (seconds {T_START}-{T_END}) ===")
print(f"{'t_s':>7} {'dt':>5} {'dd_m':>8} {'de_m':>7} {'v_ms':>6} {'v_kmh':>7} {'slope%':>7} {'P_raw':>8} {'P_cap':>7} {'lat':>12} {'lng':>12} {'ele':>8}")

count_above_500 = 0
count_above_1000 = 0
count_capped = 0
power_in_window = []

for i in range(1, len(points)):
    p0, p1 = points[i-1], points[i]
    if p0["t_s"] < T_START or p0["t_s"] > T_END:
        continue
    
    dt = p1["t_s"] - p0["t_s"]
    if dt < 0.01:
        print(f"{p0['t_s']:7.1f} {dt:5.1f}  ** dt~0, SKIPPED **")
        continue
    
    dd = p1["dist_from_start_m"] - p0["dist_from_start_m"]
    de = p1["ele"] - p0["ele"]
    
    v_raw = dd / dt if dt > 0 else 0
    v = min(v_raw, MAX_SPEED_MS)
    
    slope_raw = de / dd if dd > 0 else 0
    slope = max(-MAX_SLOPE, min(MAX_SLOPE, slope_raw))
    
    f_grav = m_tot * g * math.sin(math.atan(slope))
    f_roll = m_tot * g * math.cos(math.atan(slope)) * crr
    f_aero = 0.5 * rho * cda * v * v
    p_raw = (f_grav + f_roll + f_aero) * v
    p_cap = max(0.0, min(p_raw, MAX_INST_POWER))
    
    if p_cap > 500:
        count_above_500 += 1
    if p_cap > 1000:
        count_above_1000 += 1
    if p_raw > MAX_INST_POWER:
        count_capped += 1
    
    power_in_window.append(p_cap)
    
    flag = ""
    if p_raw > 500:
        flag = " <<<" 
    if p_raw > MAX_INST_POWER:
        flag = " *** CAPPED ***"
    
    print(f"{p0['t_s']:7.1f} {dt:5.1f} {dd:8.2f} {de:7.2f} {v_raw:6.2f} {v_raw*3.6:7.1f} {slope_raw*100:7.2f} {p_raw:8.1f} {p_cap:7.1f} {p0['lat']:12.6f} {p0['lng']:12.6f} {p0['ele']:8.2f}{flag}")

print()
print(f"=== SUMMARY for minutes {T_START//60}-{T_END//60} ===")
print(f"Points in window: {len(power_in_window)}")
if power_in_window:
    print(f"Avg estimated power: {sum(power_in_window)/len(power_in_window):.1f} W")
    print(f"Max estimated power: {max(power_in_window):.1f} W")
    print(f"Points > 500W: {count_above_500}")
    print(f"Points > 1000W: {count_above_1000}")
    print(f"Points capped at {MAX_INST_POWER}W: {count_capped}")

# Also show the overall power distribution
print()
print("=== FULL RIDE POWER DISTRIBUTION ===")
all_powers = []
for i in range(1, len(points)):
    p0, p1 = points[i-1], points[i]
    dt = p1["t_s"] - p0["t_s"]
    if dt < 1.0:
        continue
    dd = p1["dist_from_start_m"] - p0["dist_from_start_m"]
    if dd <= 0:
        continue
    de = p1["ele"] - p0["ele"]
    v = min(dd / dt, MAX_SPEED_MS)
    slope = max(-MAX_SLOPE, min(MAX_SLOPE, de / dd))
    f_grav = m_tot * g * math.sin(math.atan(slope))
    f_roll = m_tot * g * math.cos(math.atan(slope)) * crr
    f_aero = 0.5 * rho * cda * v * v
    p_inst = max(0.0, min((f_grav + f_roll + f_aero) * v, MAX_INST_POWER))
    all_powers.append(p_inst)

if all_powers:
    import statistics
    all_powers.sort()
    print(f"Total segments: {len(all_powers)}")
    print(f"Mean: {statistics.mean(all_powers):.1f} W")
    print(f"Median: {statistics.median(all_powers):.1f} W")
    print(f"P90: {all_powers[int(len(all_powers)*0.90)]:.1f} W")
    print(f"P95: {all_powers[int(len(all_powers)*0.95)]:.1f} W")
    print(f"P99: {all_powers[int(len(all_powers)*0.99)]:.1f} W")
    print(f"Max: {all_powers[-1]:.1f} W")
    
    # Count by bucket
    buckets = [0, 50, 100, 200, 300, 500, 1000, 2000, 2500]
    for j in range(len(buckets)-1):
        cnt = sum(1 for p in all_powers if buckets[j] <= p < buckets[j+1])
        print(f"  [{buckets[j]:4d}-{buckets[j+1]:4d}W): {cnt} ({cnt/len(all_powers)*100:.1f}%)")
    cnt = sum(1 for p in all_powers if p >= 2500)
    print(f"  [2500W+    ): {cnt} ({cnt/len(all_powers)*100:.1f}%)")
