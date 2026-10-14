# swrad.py — 천리안 2A 지면 하향단파복사(DSR, 한반도 KO 2km)를 10분마다 받아 수도권 격자만 작은 JSON 으로.
# 출처: 기상청 천리안위성 2A호 (기상청 API허브). 노출계 위젯이 이 JSON 을 읽는다.
import datetime as dt, json, os, sys, urllib.error, urllib.request
import numpy as np, netCDF4
from pyproj import Transformer

KEY = os.environ.get("KMA_KEY", "")
if not KEY:
    sys.exit("KMA_KEY 비밀값이 없음 — 저장소 Settings → Secrets → Actions 에 추가")
API = "https://apihub.kma.go.kr/api/typ05/api/GK2A/LE2/SWRAD/KO/data?date={}&authKey=" + KEY
BOX = (36.9, 38.1, 126.3, 127.9)   # 위도·경도 범위 (수도권 + 여유)

def get(url):
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return r.read(), r.headers.get_content_type()
    except urllib.error.HTTPError as e:
        return None, str(e.code)

LAST = os.environ.get("LAST", "")             # 직전에 올린 시각 (YYYYMMDDHHMM) — 같으면 받지 않고 끝

def latest():
    now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    t = now - dt.timedelta(minutes=now.minute % 10)
    for k in range(18):                        # 3시간 안에서 가장 최근 파일 (10분 간격, 보통 ~15분 지연)
        ts = t - dt.timedelta(minutes=10 * k)
        if LAST and ts.strftime("%Y%m%d%H%M") <= LAST:
            print("새 파일 없음", LAST); sys.exit(3)
        data, ct = get(API.format(ts.strftime("%Y%m%d%H%M")))
        if data and ct != "application/json":
            return ts, data
    sys.exit("최근 3시간 파일 없음")

ts, data = latest()
ds = netCDF4.Dataset("swrad", memory=data)
print("file", ts.isoformat(), len(data), "bytes", flush=True)

# 격자: 람베르트 정각원추 (파일의 gk2a_imager_projection 속성에서 읽음), 픽셀 중심 좌표
p = ds.variables["gk2a_imager_projection"]
crs = (f"+proj=lcc +lat_1={float(p.standard_parallel1)} +lat_2={float(p.standard_parallel2)} "
       f"+lat_0={float(p.origin_latitude)} +lon_0={float(p.central_meridian)} +x_0=0 +y_0=0 +ellps=WGS84 +units=m")
px, x0, y0 = float(p.pixel_size), float(p.upper_left_easting), float(p.upper_left_northing)

dsr = np.ma.filled(ds.variables["DSR"][:].astype("f4"), np.nan)          # W/m², scale_factor 자동 적용
good = np.ma.filled(ds.variables["DSR_DQF1"][:], 0) == 1
angle = np.ma.filled(ds.variables["SW_DQF"][:], 0) == 1                  # 0 이면 SZA>70 등 (저고도 태양)
print("DSR", dsr.shape, "valid", int(np.isfinite(dsr).sum()), flush=True)

# 상자 → 행·열 범위
to_xy = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
xs, ys = to_xy.transform([BOX[2], BOX[3], BOX[2], BOX[3]], [BOX[0], BOX[0], BOX[1], BOX[1]])
c0, c1 = int((min(xs) - x0) // px), int((max(xs) - x0) // px) + 1
r0, r1 = int((y0 - max(ys)) // px), int((y0 - min(ys)) // px) + 1
rows, cols = np.arange(r0, r1 + 1, 2), np.arange(c0, c1 + 1, 2)         # 한 칸 걸러 (≈4km)
R, C = np.meshgrid(rows, cols, indexing="ij")
lon, lat = to_ll.transform(x0 + C * px, y0 - R * px)

pts = []
for i, j, la, lo in zip(R.ravel(), C.ravel(), lat.ravel(), lon.ravel()):
    if not (BOX[0] <= la <= BOX[1] and BOX[2] <= lo <= BOX[3]):
        continue
    v = dsr[i, j]
    pts.append([round(float(la), 3), round(float(lo), 3),
                None if np.isnan(v) else round(float(v), 1),
                int(good[i, j] and angle[i, j])])
vals = [q[2] for q in pts if q[2] is not None]
print("points", len(pts), "with value", len(vals),
      "min/max", (min(vals), max(vals)) if vals else None, flush=True)

out = {"source": "GK2A LE2 SWRAD KO DSR", "attribution": "기상청 천리안위성 2A호", "unit": "W/m2",
       "time": ts.strftime("%Y-%m-%dT%H:%MZ"),
       "fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
       "night": not vals,
       "points": pts}                                                    # [위도, 경도, 일사량|null, 품질 1/0]
os.makedirs("site", exist_ok=True)
json.dump(out, open("site/swrad.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("json bytes", os.path.getsize("site/swrad.json"))
open("last.txt", "w").write(ts.strftime("%Y%m%d%H%M"))
