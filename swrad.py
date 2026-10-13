# swrad.py — 천리안 2A 지면 하향단파복사(SWRAD, 한반도 KO)를 10분마다 받아 수도권 격자만 작은 JSON 으로.
# 출처: 기상청 천리안위성 2A호 (기상청 API허브). 노출계 위젯이 이 JSON 을 읽는다.
import datetime as dt, json, os, sys, urllib.error, urllib.request
import numpy as np, netCDF4

KEY = os.environ.get("KMA_KEY", "")
if not KEY:
    sys.exit("KMA_KEY 비밀값이 없음 — 저장소 Settings → Secrets → Actions 에 추가")
API = "https://apihub.kma.go.kr/api/typ05/api/GK2A/LE2/SWRAD/KO/data?date={}&authKey=" + KEY
LATLON = "https://apihub.kma.go.kr/api/typ01/url/gk2a_latlon_file_down.php?area=KO&grid={}&authKey=" + KEY
BOX = (36.9, 38.1, 126.3, 127.9)   # 위도·경도 범위 (수도권 + 여유)

def get(url):
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return r.read(), r.headers.get_content_type()
    except urllib.error.HTTPError as e:
        return None, str(e.code)

def latest():
    now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    t = now - dt.timedelta(minutes=now.minute % 10)
    for k in range(18):                        # 3시간 안에서 가장 최근 파일 (10분 간격, 보통 ~15분 지연)
        ts = t - dt.timedelta(minutes=10 * k)
        data, ct = get(API.format(ts.strftime("%Y%m%d%H%M")))
        if data and ct != "application/json":
            return ts, data
    sys.exit("최근 3시간 파일 없음")

def describe(ds):
    for n, v in ds.variables.items():
        print(f"  var {n} {v.dimensions} {v.shape} " + " ".join(f"{a}={getattr(v, a)!r}"[:80] for a in v.ncattrs()))

def pick(ds):
    for n, v in ds.variables.items():   # 하향단파 = DSR (Downward Shortwave Radiation)
        if n.upper() in ("DSR", "SWDN", "DSWR"): return n
    for n, v in ds.variables.items():
        ln = str(getattr(v, "long_name", "")).lower()
        if "downward" in ln and "short" in ln: return n
    return None

ts, data = latest()
ds = netCDF4.Dataset("swrad", memory=data)
print("file", ts.isoformat(), len(data), "bytes"); describe(ds)
name = pick(ds)
if not name: sys.exit("하향단파 변수를 못 찾음 — 위 변수 목록 확인")
ghi = np.ma.filled(ds.variables[name][:].astype("f4"), np.nan).squeeze()
print("use", name, ghi.shape, "min/max", np.nanmin(ghi), np.nanmax(ghi))

# 격자 위경도 (크기가 맞는 해상도를 찾아 캐시)
os.makedirs("latlon", exist_ok=True)
lat = lon = None
for grid in ("2", "1", "0.5"):
    path = f"latlon/ko_{grid}.nc"
    if not os.path.exists(path):
        raw, ct = get(LATLON.format(grid))
        if not raw or ct == "application/json": continue
        open(path, "wb").write(raw)
    ll = netCDF4.Dataset(path)
    vs = {k.lower(): k for k in ll.variables}
    la, lo = ll.variables[vs.get("lat", vs.get("latitude"))][:], ll.variables[vs.get("lon", vs.get("longitude"))][:]
    print("latlon grid", grid, la.shape)
    if la.shape == ghi.shape:
        lat, lon = np.ma.filled(la, np.nan), np.ma.filled(lo, np.nan); break
if lat is None: sys.exit("위경도 격자 크기가 자료와 안 맞음")

m = (lat >= BOX[0]) & (lat <= BOX[1]) & (lon >= BOX[2]) & (lon <= BOX[3])
ii, jj = np.where(m)
step = 2 if len(ii) > 2500 else 1                 # 너무 많으면 한 칸 걸러 (≈4km)
sel = (ii % step == 0) & (jj % step == 0)
pts = [[round(float(lat[i, j]), 3), round(float(lon[i, j]), 3), None if np.isnan(ghi[i, j]) else round(float(ghi[i, j]), 1)]
       for i, j in zip(ii[sel], jj[sel])]
out = {"source": "GK2A SWRAD KO " + name, "attribution": "기상청 천리안위성 2A호",
       "time": ts.strftime("%Y-%m-%dT%H:%MZ"),
       "fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
       "points": pts}
os.makedirs("site", exist_ok=True)
json.dump(out, open("site/swrad.json", "w"), ensure_ascii=False, separators=(",", ":"))
print("points", len(pts), "bytes", os.path.getsize("site/swrad.json"))
