import sys, math, statistics
sys.path.insert(0, '.')
from utils.gpx_utils import parse_gpx_points, compute_distances
pts = parse_gpx_points('imported_gpx/IpBike_152.gpx')
pts = compute_distances(pts)
t0 = pts[0]['time']
for p in pts:
    p['t_s'] = (p['time'] - t0).total_seconds() if p['time'] else None
pts = [p for p in pts if p['t_s'] is not None]
prev = None
print('=== PROFILO ALTIMETRICO min 88-100 (ogni 30s) ===')
for p in pts:
    t_s = p['t_s']
    if t_s < 5280 or t_s > 6000: continue
    if int(t_s) % 30 != 0: continue
    m, s2 = int(t_s)//60, int(t_s)%60
    v_str, de_str = '', ''
    if prev:
        dt = t_s - prev[0]
        dd = p['dist_from_start_m'] - prev[1]
        if dt > 0 and dd > 0: v_str = str(round(dd/dt*3.6, 1))
        de_str = str(round(p['ele'] - prev[2]))
    print(f'  {m}m{s2:02d}s  ele={p["ele"]:4.0f}m  v={v_str:>5}  de={de_str}')
    prev = (t_s, p['dist_from_start_m'], p['ele'])
t_ws = 92*60+42
t_we = 97*60+42
ps2 = min(pts, key=lambda p: abs(p['t_s']-t_ws))
pe = min(pts, key=lambda p: abs(p['t_s']-t_we))
dw = pe['dist_from_start_m'] - ps2['dist_from_start_m']
print()
print('=== FINESTRA 92m42s - 97m42s ===')
print(f'  Ele inizio: {ps2["ele"]:.0f}m  fine: {pe["ele"]:.0f}m  delta: {pe["ele"]-ps2["ele"]:+.0f}m')
if dw > 0: print(f'  Distanza: {dw:.0f}m  Pendenza media: {(pe["ele"]-ps2["ele"])/dw*100:+.1f}pct')
all_v = []
for i in range(1, len(pts)):
    dt = pts[i]['t_s'] - pts[i-1]['t_s']
    dd = pts[i]['dist_from_start_m'] - pts[i-1]['dist_from_start_m']
    if dt >= 1 and dd > 0: all_v.append(dd/dt)
med = statistics.median(all_v)
mad = statistics.median([abs(v-med) for v in all_v])
thr = med + 6 * max(mad, 0.5)
print()
print('=== OUTLIER DETECTION ===')
print(f'  Mediana v: {med:.2f} m/s ({med*3.6:.0f} kmh)')
print(f'  MAD: {mad:.3f} m/s')
print(f'  Soglia (med+6*MAD): {thr:.2f} m/s ({thr*3.6:.0f} kmh)')
print(f'  Outlier: {sum(1 for v in all_v if v>thr)}/{len(all_v)}')
M=85; g=9.81; rho=1.225; cda=0.32; crr=0.005
total_s = int(pts[-1]['t_s']) + 1
pw_arr = [0.0] * total_s
skip = 0
for i in range(1, len(pts)):
    p0, p1 = pts[i-1], pts[i]
    dt = p1['t_s'] - p0['t_s']
    dd = p1['dist_from_start_m'] - p0['dist_from_start_m']
    if dt < 1 or dd <= 0: continue
    v = dd / dt
    if v > thr:
        skip += 1
        continue
    de = p1['ele'] - p0['ele']
    sl = max(-0.35, min(0.35, de/dd))
    fg = M*g*math.sin(math.atan(sl))
    fr = M*g*math.cos(math.atan(sl))*crr
    fa = 0.5*rho*cda*v*v
    pw = max(0.0, (fg+fr+fa)*v)
    for sec in range(int(p0['t_s']), min(total_s, int(p1['t_s']))):
        pw_arr[sec] = pw
print()
print('=== POTENZA CON OUTLIER SCARTATI ===')
print(f'  Segmenti scartati: {skip}')
pfx = [0.0]
for v2 in pw_arr: pfx.append(pfx[-1] + v2)
best_w, best_s2 = 0, 0
for st in range(len(pw_arr)-300+1):
    a = (pfx[st+300]-pfx[st])/300
    if a > best_w: best_w, best_s2 = a, st
print(f'  BEST 5min PULITO: {best_w:.1f} W  ({best_s2//60}m{best_s2%60:02d}s - {(best_s2+300)//60}m{(best_s2+300)%60:02d}s)')
avg_all = statistics.mean([v3 for v3 in pw_arr if v3 > 0]) if any(v3 > 0 for v3 in pw_arr) else 0
print(f'  Media totale ride: {avg_all:.1f} W')
print(f'  Max istantaneo: {max(pw_arr):.1f} W')
