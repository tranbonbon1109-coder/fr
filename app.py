import requests
import json
import threading
import time
import base64
import os
import concurrent.futures
from datetime import datetime

from flask import Flask, request, jsonify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from flask_cors import CORS

# ============================================================
#  IMPORT ENCRYPT HELPERS
# ============================================================
try:
    from byte import Encrypt_ID, encrypt_api
except ImportError:
    def Encrypt_ID(uid: str) -> str:
        return uid.encode().hex()
    def encrypt_api(payload: str) -> str:
        return payload.encode().hex()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.json.sort_keys = False
CORS(app)

# ============================================================
#  CẤU HÌNH — đọc từ ENV để linh hoạt
# ============================================================
DEBUG = os.environ.get("DEBUG", "0") == "1"

# Vercel /tmp chỉ ghi được tạm thời, không persist giữa các invocation
# -> dùng in-memory cache là chính
TOKEN_CACHE_FILE = "/tmp/jwt_cache.json"

JWT_FETCH_WORKERS = int(os.environ.get("JWT_FETCH_WORKERS", "16"))
SPAM_THREAD_DELAY = float(os.environ.get("SPAM_THREAD_DELAY", "0.05"))
JWT_MIN_VALID_SECONDS = 300

# Giới hạn để không vượt timeout Vercel (Hobby ~10s, Pro ~60s)
MAX_UIDS_PER_REQUEST = int(os.environ.get("MAX_UIDS_PER_REQUEST", "210"))
REQUEST_BUDGET_SEC = float(os.environ.get("REQUEST_BUDGET_SEC", "8"))

# ============================================================
#  DEBUG HELPER
# ============================================================
def dbg(tag, msg, data=None):
    if not DEBUG:
        return
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}][{tag}] {msg}", flush=True)
    if data is not None:
        try:
            pretty = json.dumps(data, ensure_ascii=False, default=str)
            if len(pretty) > 1500:
                pretty = pretty[:1500] + "\n... (truncated)"
            print(pretty, flush=True)
        except Exception:
            print(f"    {data}", flush=True)

def dbg_sep(title=""):
    if DEBUG:
        print(f"\n{'='*70}\n  {title}\n{'='*70}", flush=True)

# ============================================================
#  REGION MAP
# ============================================================
REGION_MAP = {
    "ind": "https://client.ind.freefiremobile.com",
    "me":  "https://clientbp.ggblueshark.com",
    "vn":  "https://clientbp.ggpolarbear.com",
    "bd":  "https://clientbp.ggwhitehawk.com",
    "pk":  "https://clientbp.ggblueshark.com",
    "sg":  "https://clientbp.ggpolarbear.com",
    "br":  "https://client.us.freefiremobile.com",
    "na":  "https://client.us.freefiremobile.com",
    "id":  "https://clientbp.ggpolarbear.com",
    "ru":  "https://clientbp.ggpolarbear.com",
    "th":  "https://clientbp.ggpolarbear.com",
}
ALL_REGIONS = list(REGION_MAP.items())

PROTO_KEY = b'Yg&tc%DEuh6%Zc^8'
PROTO_IV  = b'6oyZDr22E3ychjM%'

# ============================================================
#  GLOBAL STATE
# ============================================================
JWT_TOKEN = {}
_token_lock = threading.Lock()

BASE_HEADERS = {
    'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 11; ASUS_Z01QD Build/PI)",
    'Connection': "Keep-Alive",
    'Accept-Encoding': "gzip",
    'Content-Type': "application/x-www-form-urlencoded",
    'Expect': "100-continue",
    'X-Unity-Version': "2018.4.11f1",
    'X-GA': "v1 1",
    'ReleaseVersion': "OB55"
}

# ============================================================
#  HTTP SESSION (module-level, dùng lại trong cùng 1 lambda container)
# ============================================================
def make_session(pool_size=32):
    s = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=Retry(
            total=1,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; JWT-Fetcher/1.0)",
        "Accept": "application/json, text/plain, */*",
    })
    return s

_HTTP = make_session(pool_size=32)

# ============================================================
#  TOKEN PERSISTENCE — dùng /tmp (chỉ để log, không cần thiết)
# ============================================================
def save_tokens():
    try:
        with _token_lock:
            snapshot = dict(JWT_TOKEN)
        data = {
            "saved_at": datetime.now().isoformat(),
            "count": len(snapshot),
            "tokens": snapshot
        }
        tmp = TOKEN_CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, TOKEN_CACHE_FILE)
    except Exception as e:
        dbg("CACHE", f"⚠️  Không lưu được cache: {e}")


def load_tokens():
    """Load token từ /tmp nếu có (chỉ dùng trong cùng 1 container ấm)."""
    global JWT_TOKEN
    if not os.path.exists(TOKEN_CACHE_FILE):
        return
    try:
        with open(TOKEN_CACHE_FILE, "r") as f:
            data = json.load(f)
        tokens = data.get("tokens", {})
        valid = {uid: tok for uid, tok in tokens.items() if jwt_is_valid(tok)}
        JWT_TOKEN = valid
        dbg("CACHE", f"📂 Load {len(valid)} token từ /tmp cache")
    except Exception as e:
        dbg("CACHE", f"⚠️  Lỗi load cache: {e}")


def jwt_is_valid(token, min_seconds=JWT_MIN_VALID_SECONDS):
    if not token or not isinstance(token, str):
        return False
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if not exp:
            return True
        return exp > (time.time() + min_seconds)
    except Exception:
        return True

# ============================================================
#  ACCOUNTS LOADING — đọc từ repo (Vercel bundle)
# ============================================================
def _base_dir():
    """Trả về thư mục chứa file app.py (Vercel bundle tại /var/task)."""
    return os.path.dirname(os.path.abspath(__file__))


def load_accounts(region=None):
    """Load accounts từ file theo region, fallback accounts.txt."""
    dbg_sep(f"LOAD ACCOUNTS | region={region}")
    base = _base_dir()

    filenames = []
    if region:
        reg = region.lower().strip()
        filenames += [f"Account_{reg}.txt", f"accounts_{reg}.txt", f"Account{reg}.txt"]
    filenames.append("accounts.txt")

    target = None
    for fname in filenames:
        p = os.path.join(base, fname)
        if os.path.exists(p):
            target = p
            break
    if not target:
        dbg("LOAD", "❌ Không tìm thấy file account nào")
        return []

    dbg("LOAD", f"✅ Dùng file: {target}")
    accounts = []
    try:
        with open(target) as f:
            for line in f:
                line = line.strip()
                if not line or ':' not in line:
                    continue
                uid, pwd = line.split(':', 1)
                accounts.append({"uid": uid.strip(), "password": pwd.strip()})
        dbg("LOAD", f"✅ Load {len(accounts)} tài khoản")
    except Exception as e:
        dbg("LOAD", f"❌ Lỗi: {e}")
    return accounts


def collect_all_uid_pwd():
    base = _base_dir()
    files = ["accounts.txt"] + \
            [f"Account_{r}.txt" for r in REGION_MAP] + \
            [f"accounts_{r}.txt" for r in REGION_MAP]
    uid_pwd = {}
    for fname in files:
        p = os.path.join(base, fname)
        if not os.path.exists(p):
            continue
        try:
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line or ':' not in line:
                        continue
                    uid, pwd = line.split(':', 1)
                    uid, pwd = uid.strip(), pwd.strip()
                    if uid and uid not in uid_pwd:
                        uid_pwd[uid] = pwd
        except Exception:
            pass
    return uid_pwd

# ============================================================
#  JWT FETCH
# ============================================================
def fetch_jwt_from_api(uid, password, retries=1):
    api_url = f"https://jwtt-gf.vercel.app/token?uid={uid}&password={password}"
    for attempt in range(retries + 1):
        try:
            r = _HTTP.get(api_url, timeout=8)
            if r.status_code == 200:
                try:
                    data = r.json()
                    token = data.get("jwt_token") or data.get("token")
                    if token:
                        return token, None
                    return None, "Token key missing"
                except json.JSONDecodeError:
                    tok = r.text.strip()
                    return (tok, None) if tok else (None, "Empty response")
            elif r.status_code in (429, 503):
                time.sleep(0.3 * (attempt + 1))
                continue
            else:
                return None, f"HTTP {r.status_code}"
        except requests.exceptions.Timeout:
            if attempt < retries:
                continue
            return None, "Timeout"
        except Exception as e:
            return None, str(e)
    return None, "Max retries exceeded"


def fetch_tokens_parallel(uid_pwd_pairs, max_workers=JWT_FETCH_WORKERS,
                          budget_sec=None):
    """Fetch song song, có budget thời gian để tránh vượt timeout Vercel."""
    if not uid_pwd_pairs:
        return {}, []

    dbg_sep(f"PARALLEL FETCH | {len(uid_pwd_pairs)} UID | workers={max_workers}")
    t_start = time.time()
    deadline = t_start + budget_sec if budget_sec else None

    success = {}
    failed = []
    counter = {"done": 0, "total": len(uid_pwd_pairs)}
    lock = threading.Lock()

    def worker(pair):
        uid, pwd = pair
        if deadline and time.time() > deadline:
            with lock:
                failed.append((uid, "Skipped: request budget exceeded"))
            return
        token, err = fetch_jwt_from_api(uid, pwd)
        with lock:
            counter["done"] += 1
            if token:
                success[uid] = token
                with _token_lock:
                    JWT_TOKEN[uid] = token
            else:
                failed.append((uid, err))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(worker, uid_pwd_pairs))

    elapsed = time.time() - t_start
    dbg("PARALLEL", f"⏱️  {len(uid_pwd_pairs)} UID trong {elapsed:.2f}s "
                     f"| OK={len(success)} FAIL={len(failed)}")

    if success:
        save_tokens()
    return success, failed

# ============================================================
#  PLAYER INFO
# ============================================================
def get_player_info(target_uid):
    api_url = f"https://tranbonbonba-nhat-cai-ff.vercel.app/api/get?uid={target_uid}"
    dbg_sep(f"PLAYER INFO | uid={target_uid}")
    try:
        r = _HTTP.get(api_url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            acc = data.get("AccountInfo")
            if acc:
                info = {
                    "nickname":    acc.get("AccountName", "N/A"),
                    "uid":         str(acc.get("AccountUID", target_uid)),
                    "region":      acc.get("AccountRegion", "N/A"),
                    "likes":       "N/A",
                    "prime_level": 0,
                    "level":       acc.get("AccountLevel", "N/A"),
                    "last_login":  acc.get("AccountLastLogin", "0"),
                    "created_at":  acc.get("AccountCreateTime", "N/A"),
                }
                return info
    except Exception as e:
        dbg("PLAYER", f"❌ Lỗi: {e}")
    return None

# ============================================================
#  SEND FRIEND REQUEST
# ============================================================
def send_friend_request(target_uid, token, region_server_url):
    try:
        encrypted_id = Encrypt_ID(target_uid)
        payload = f"08a7c4839f1e10{encrypted_id}1801"
        encrypted_payload = encrypt_api(payload)
        url = f"{region_server_url}/RequestAddingFriend"

        headers = {
            "Expect": "100-continue",
            "Authorization": f"Bearer {token}",
            "X-Unity-Version": "2018.4.f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55",
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(encrypted_payload) // 2),
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; SM-N975F Build/PI)",
            "Connection": "close",
            "Accept-Encoding": "gzip, deflate, br"
        }
        r = _HTTP.post(url, headers=headers,
                       data=bytes.fromhex(encrypted_payload), timeout=10)
        resp_text = r.text[:200]

        if r.status_code == 200:
            if "Invalid request body" in resp_text:
                return False, f"200 but body: {resp_text}", url
            return True, resp_text, url
        return False, f"HTTP {r.status_code}: {resp_text}", url
    except Exception as e:
        return False, str(e), region_server_url

# ============================================================
#  PROCESS 1 ACCOUNT
# ============================================================
def process_account(account, target_uid, results, regions_to_try, delay=0):
    if delay > 0:
        time.sleep(delay)
    uid = account['uid']
    token = JWT_TOKEN.get(uid)
    if not token:
        results['failed_count'] += 1
        return

    for region_name, server_url in regions_to_try:
        ok, resp_msg, used_url = send_friend_request(target_uid, token, server_url)
        if ok:
            results['successful_count'] += 1
            results['region_urls_used'].add(used_url)
            return
    results['failed_count'] += 1

# ============================================================
#  MAIN SPAM LOGIC (có budget)
# ============================================================
def spam_friend_requests(target_uid, count=None, region=None,
                         budget_sec=REQUEST_BUDGET_SEC):
    t_start = time.time()
    dbg_sep("SPAM FRIEND REQUESTS")
    dbg("SPAM", f"target={target_uid} | count={count} | region={region}")

    accounts = load_accounts(region)
    if not accounts:
        return {"error": f"No accounts found for region '{region}'"}, 404

    # Giới hạn số UID cho 1 request để không vượt timeout
    hard_cap = MAX_UIDS_PER_REQUEST
    if count is not None:
        if count <= 0:
            return {"error": "Count must be positive"}, 400
        hard_cap = min(hard_cap, count)
    accounts = accounts[:hard_cap]
    dbg("SPAM", f"Dùng {len(accounts)} account (cap={hard_cap})")

    if region:
        rl = region.lower()
        if rl not in REGION_MAP:
            return {"error": f"Invalid region: {region}"}, 400
        regions_to_try = [(rl, REGION_MAP[rl])]
    else:
        regions_to_try = ALL_REGIONS

    # ===== PREFETCH TOKEN SONG SONG (có budget) =====
    elapsed = time.time() - t_start
    remaining = max(0.5, budget_sec - elapsed)
    to_fetch = [
        (a["uid"], a["password"]) for a in accounts
        if not JWT_TOKEN.get(a["uid"]) or not jwt_is_valid(JWT_TOKEN[a["uid"]])
    ]
    if to_fetch:
        dbg("SPAM", f"Prefetch {len(to_fetch)} token (budget={remaining:.1f}s)")
        fetch_tokens_parallel(to_fetch,
                              max_workers=JWT_FETCH_WORKERS,
                              budget_sec=remaining)

    # ===== SPAM (song song, có kiểm soát) =====
    elapsed = time.time() - t_start
    remaining = max(0.5, budget_sec - elapsed)

    results = {
        "successful_count": 0,
        "failed_count": 0,
        "region_urls_used": set()
    }

    # Chạy song song thay vì tạo hàng trăm thread
    spam_workers = min(len(accounts), JWT_FETCH_WORKERS * 2, 32)

    def _task(idx_acc):
        idx, acc = idx_acc
        if time.time() - t_start > budget_sec:
            results['failed_count'] += 1
            return
        # delay nhỏ để giãn request
        if idx > 0 and SPAM_THREAD_DELAY > 0:
            time.sleep(min(SPAM_THREAD_DELAY, 0.05))
        process_account(acc, target_uid, results, regions_to_try, delay=0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=spam_workers) as ex:
        list(ex.map(_task, list(enumerate(accounts))))

    dbg("SPAM", f"Kết quả: OK={results['successful_count']} "
                 f"FAIL={results['failed_count']}")

    # ===== PLAYER INFO =====
    player_info = get_player_info(target_uid)
    out = {"Status": "success"}
    if player_info:
        out["Nickname"]    = player_info["nickname"]
        out["Uid"]         = player_info["uid"]
        out["Region"]      = player_info["region"]
        out["Likes"]       = player_info["likes"]
        out["Prime level"] = player_info["prime_level"]
    else:
        out["Nickname"]    = "N/A"
        out["Uid"]         = str(target_uid)
        out["Region"]      = "N/A"
        out["Likes"]       = "N/A"
        out["Prime level"] = 0

    out["Successful count"] = results["successful_count"]
    out["Failed count"]     = results["failed_count"]
    out["Ob_version"]       = "OB55"
    out["Client_Version"]   = "1.132.1"
    out["Status_Code"]      = 200
    out["Elapsed_sec"]      = round(time.time() - t_start, 2)
    return out

# ============================================================
#  ROUTES
# ============================================================
@app.route('/')
def index():
    return jsonify({
        "status": "ok",
        "service": "Free Fire Spam Server",
        "endpoints": [
            "GET  /spam?uid=X&count=N&region=ind",
            "GET  /health",
            "POST /refresh",
        ]
    })


@app.route('/spam', methods=['GET'])
def rizer():
    dbg_sep("HTTP /spam")
    target_uid = request.args.get('uid')
    if not target_uid:
        return jsonify({"error": "Missing 'uid' parameter"}), 400

    count_param = request.args.get('count')
    try:
        count = int(count_param) if count_param else None
    except ValueError:
        return jsonify({"error": "Invalid 'count'"}), 400

    region = request.args.get('region')

    result = spam_friend_requests(target_uid, count, region)
    if isinstance(result, tuple) and result[1] in (400, 404):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@app.route('/health', methods=['GET'])
def health():
    total = 0
    regions = {}
    base = _base_dir()
    for reg in REGION_MAP.keys():
        for fname in [f"Account_{reg}.txt", f"accounts_{reg}.txt", f"Account{reg}.txt"]:
            p = os.path.join(base, fname)
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        uids = [l.split(':', 1)[0].strip()
                                for l in f if l.strip() and ':' in l]
                    cached = sum(1 for u in uids if u in JWT_TOKEN)
                    total += len(uids)
                    regions[reg.upper()] = {
                        "file_used": fname,
                        "total_accounts": len(uids),
                        "cached_tokens": cached
                    }
                except Exception:
                    pass
                break

    return jsonify({
        "status": "ok",
        "total_uid_password_count": total,
        "total_cached_tokens": len(JWT_TOKEN),
        "regional_tokens": regions,
        "config": {
            "jwt_fetch_workers": JWT_FETCH_WORKERS,
            "max_uids_per_request": MAX_UIDS_PER_REQUEST,
            "request_budget_sec": REQUEST_BUDGET_SEC,
            "token_cache_file": TOKEN_CACHE_FILE,
            "runtime": "vercel-serverless"
        }
    })


@app.route('/refresh', methods=['GET', 'POST'])
def manual_refresh():
    """Ép refresh token ngay. Chỉ refresh trong giới hạn để không timeout."""
    dbg_sep("HTTP /refresh")
    t0 = time.time()
    uid_pwd = collect_all_uid_pwd()

    to_fetch_all = [
        (uid, pwd) for uid, pwd in uid_pwd.items()
        if not JWT_TOKEN.get(uid) or not jwt_is_valid(JWT_TOKEN[uid])
    ]

    if not to_fetch_all:
        return jsonify({"status": "ok", "message": "Tất cả token đã hợp lệ",
                        "total": len(uid_pwd)})

    # Chỉ fetch batch nhỏ để không vượt timeout
    batch = to_fetch_all[:MAX_UIDS_PER_REQUEST]

    ok, fail = fetch_tokens_parallel(
        batch,
        max_workers=JWT_FETCH_WORKERS,
        budget_sec=REQUEST_BUDGET_SEC
    )
    elapsed = time.time() - t0

    return jsonify({
        "status": "ok",
        "total_pending": len(to_fetch_all),
        "fetched": len(ok),
        "failed": len(fail),
        "remaining": max(0, len(to_fetch_all) - len(ok)),
        "elapsed_sec": round(elapsed, 2),
        "failed_details": [{"uid": u, "error": e} for u, e in fail[:20]]
    })


# ============================================================
#  KHỞI TẠO (chạy 1 lần khi cold start container)
# ============================================================
load_tokens()

# Handler cho Vercel: export `app` (đã có ở trên)
# Khi chạy local: python app.py
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  🚀 FREE FIRE SPAM SERVER - LOCAL DEV MODE")
    print("=" * 70 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=DEBUG, threaded=True)
