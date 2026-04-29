#!/usr/bin/env python3
# autosurf_complete.py - Autosurf completo per EasyHits4U

import os
import sys
import time
import requests
import numpy as np
import cv2
import json
import re
import ddddocr
import pytesseract
from datetime import datetime
from supabase import create_client
from datasets import load_dataset
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================ CONFIGURAZIONE ====================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

BROWSERLESS_SUPABASE_URL = os.environ.get("BROWSERLESS_SUPABASE_URL")
BROWSERLESS_SUPABASE_KEY = os.environ.get("BROWSERLESS_SUPABASE_KEY")

MATH_SUPABASE_URL = os.environ.get("MATH_SUPABASE_URL")
MATH_SUPABASE_KEY = os.environ.get("MATH_SUPABASE_KEY")

EASYHITS_EMAIL = os.environ.get("EASYHITS_EMAIL")
EASYHITS_PASSWORD = os.environ.get("EASYHITS_PASSWORD")
ACCOUNT_NAME = os.environ.get("ACCOUNT_NAME", "main")
REFERER_URL = "https://www.easyhits4u.com/?ref=nicolacaporale"
BROWSERLESS_URL = "https://production-sfo.browserless.io/chrome/bql"

DIM = 64
REQUEST_TIMEOUT = 15
ERRORI_DIR = "errori"
DATASET_REPO = "zenadazurli/easyhits4u-dataset"

os.makedirs(ERRORI_DIR, exist_ok=True)

# ================ GLOBALS ====================
X_fast = None
y_fast = None
classes_fast = None
current_cookie_string = None
dddd_ocr = None
rapid_ocr = None

# ================ MAPPATURA PAROLE -> NUMERI ====================
WORD_TO_NUM = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
    'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17,
    'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'twentyone': 21, 'twentytwo': 22, 'twentythree': 23, 'twentyfour': 24, 'twentyfive': 25,
    'twentysix': 26, 'twentyseven': 27, 'twentyeight': 28, 'twentynine': 29,
    'thirty': 30, 'thirtyone': 31, 'thirtytwo': 32, 'thirtythree': 33, 'thirtyfour': 34,
    'thirtyfive': 35, 'thirtysix': 36, 'thirtyseven': 37, 'thirtyeight': 38, 'thirtynine': 39,
    'forty': 40, 'fortyone': 41, 'fortytwo': 42, 'fortythree': 43, 'fortyfour': 44,
    'fortyfive': 45, 'fortysix': 46, 'fortyseven': 47, 'fortyeight': 48, 'fortynine': 49,
    'fifty': 50
}

NUM_TO_WORD = {v: k for k, v in WORD_TO_NUM.items()}
NUM_TO_WORD.update({
    0: 'zero', 1: 'one', 2: 'two', 3: 'three', 4: 'four',
    5: 'five', 6: 'six', 7: 'seven', 8: 'eight', 9: 'nine',
    10: 'ten', 11: 'eleven', 12: 'twelve', 13: 'thirteen',
    14: 'fourteen', 15: 'fifteen', 16: 'sixteen', 17: 'seventeen',
    18: 'eighteen', 19: 'nineteen', 20: 'twenty'
})

# ================ LOG ====================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ================ CARICAMENTO DATASET FIGURE ====================
def load_dataset_from_hf():
    global X_fast, y_fast, classes_fast
    
    log(f"📥 Caricamento dataset figure da Hugging Face: {DATASET_REPO}")
    
    try:
        dataset = load_dataset(DATASET_REPO, trust_remote_code=True)
        data = dataset["train"] if "train" in dataset else dataset
        
        X = []
        y = []
        class_to_idx = {}
        
        for item in data:
            features = item.get("X")
            label_idx = item.get("y")
            
            if features is None or label_idx is None:
                continue
            
            if hasattr(data.features['y'], 'names'):
                class_name = data.features['y'].names[label_idx]
            else:
                class_name = str(label_idx)
            
            if class_name not in class_to_idx:
                class_to_idx[class_name] = len(class_to_idx)
            
            X.append(np.array(features, dtype=np.float32))
            y.append(class_to_idx[class_name])
        
        if not X:
            log("❌ Nessun dato valido nel dataset")
            return False
        
        X_fast = np.vstack(X).astype(np.float32)
        y_fast = np.array(y, dtype=np.int32)
        classes_fast = {v: k for k, v in class_to_idx.items()}
        
        log(f"✅ Dataset caricato: {X_fast.shape[0]} vettori, {len(classes_fast)} classi")
        return True
        
    except Exception as e:
        log(f"❌ Errore caricamento dataset: {e}")
        return False

# ================ GESTIONE CHIAVI BROWSERLESS ====================
def get_browserless_keys():
    try:
        supabase = create_client(BROWSERLESS_SUPABASE_URL, BROWSERLESS_SUPABASE_KEY)
        resp = supabase.table('browserless_keys')\
            .select('api_key')\
            .eq('status', 'working')\
            .execute()
        
        keys = [item['api_key'] for item in resp.data] if resp.data else []
        log(f"📋 Trovate {len(keys)} chiavi Browserless 'working'")
        return keys
    except Exception as e:
        log(f"❌ Errore recupero chiavi: {e}")
        return []

def get_cf_token(api_key):
    query = """
    mutation {
      goto(url: "https://www.easyhits4u.com/logon/", waitUntil: networkIdle, timeout: 60000) {
        status
      }
      solve(type: cloudflare, timeout: 60000) {
        solved
        token
        time
      }
    }
    """
    url = f"{BROWSERLESS_URL}?token={api_key}"
    try:
        start = time.time()
        response = requests.post(url, json={"query": query}, headers={"Content-Type": "application/json"}, timeout=120)
        if response.status_code != 200:
            return None
        data = response.json()
        if "errors" in data:
            return None
        solve_info = data.get("data", {}).get("solve", {})
        if solve_info.get("solved"):
            token = solve_info.get("token")
            log(f"   ✅ Token ({time.time()-start:.1f}s)")
            return token
        return None
    except Exception as e:
        log(f"   ❌ Errore token: {e}")
        return None

def generate_cookie():
    log("🔄 Generazione nuovo cookie...")
    
    keys = get_browserless_keys()
    if not keys:
        log("❌ Nessuna chiave Browserless disponibile")
        return None
    
    for api_key in keys:
        log(f"🔑 Tentativo con chiave: {api_key[:15]}...")
        
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.easyhits4u.com/',
            'Origin': 'https://www.easyhits4u.com',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        try:
            session.get("https://www.easyhits4u.com/", headers=headers, verify=False, timeout=15)
            time.sleep(1)
            
            token = get_cf_token(api_key)
            if not token:
                continue
            
            login_headers = headers.copy()
            login_headers['Content-Type'] = 'application/x-www-form-urlencoded'
            login_headers['Referer'] = REFERER_URL
            data = {
                'manual': '1',
                'fb_id': '',
                'fb_token': '',
                'google_code': '',
                'username': EASYHITS_EMAIL,
                'password': EASYHITS_PASSWORD,
                'cf-turnstile-response': token,
            }
            
            login_resp = session.post("https://www.easyhits4u.com/logon/", data=data, headers=login_headers, allow_redirects=True, timeout=30)
            if login_resp.status_code != 200:
                continue
            
            time.sleep(2)
            session.get("https://www.easyhits4u.com/member/", headers=headers, verify=False, timeout=15)
            time.sleep(1)
            session.get("https://www.easyhits4u.com/surf/", headers=headers, verify=False, timeout=15)
            time.sleep(1)
            session.get(REFERER_URL, headers=headers, verify=False, timeout=15)
            
            cookies = session.cookies.get_dict()
            
            if 'user_id' in cookies and 'sesids' in cookies:
                cookie_string = '; '.join([f"{k}={v}" for k, v in cookies.items()])
                log(f"✅ Cookie generato! user_id={cookies['user_id']}, sesids={cookies['sesids']}")
                
                try:
                    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                    
                    supabase.table('account_cookies')\
                        .update({'status': 'expired'})\
                        .eq('account_name', ACCOUNT_NAME)\
                        .eq('status', 'active')\
                        .execute()
                    
                    cookie_data = {
                        'account_name': ACCOUNT_NAME,
                        'email': EASYHITS_EMAIL,
                        'password': EASYHITS_PASSWORD,
                        'cookies_string': cookie_string,
                        'user_id': cookies['user_id'],
                        'sesids': cookies['sesids'],
                        'status': 'active',
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    supabase.table('account_cookies').insert(cookie_data).execute()
                    log("💾 Cookie salvato su Supabase")
                except Exception as e:
                    log(f"⚠️ Errore salvataggio Supabase: {e}")
                
                return cookie_string
        except Exception as e:
            log(f"   ❌ Errore: {e}")
            continue
    
    log("❌ Impossibile generare cookie")
    return None

def get_cookie_from_supabase():
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        resp = supabase.table('account_cookies')\
            .select('cookies_string')\
            .eq('account_name', ACCOUNT_NAME)\
            .eq('status', 'active')\
            .execute()
        
        if resp.data:
            log("✅ Cookie trovato su Supabase")
            return resp.data[0]['cookies_string']
        return None
    except Exception as e:
        log(f"❌ Errore lettura cookie: {e}")
        return None

# ================ INIZIALIZZAZIONE OCR ====================
def init_ocr():
    global dddd_ocr, rapid_ocr
    
    log("📥 Inizializzazione OCR...")
    
    try:
        dddd_ocr = ddddocr.DdddOcr()
        dddd_ocr.set_ranges("0123456789+-abcdefghijklmnopqrstuvwxyz")
        log("✅ DdddOcr pronto")
    except Exception as e:
        log(f"⚠️ DdddOcr non disponibile: {e}")
        dddd_ocr = None
    
    try:
        from rapidocr_onnxruntime import RapidOCR
        rapid_ocr = RapidOCR()
        log("✅ RapidOCR pronto")
    except ImportError:
        log("⚠️ RapidOCR non installato")
        rapid_ocr = None
    except Exception as e:
        log(f"⚠️ Errore RapidOCR: {e}")
        rapid_ocr = None

# ================ FUNZIONI PER CAPTCHA MATEMATICI ====================
def preprocess_math_image(image_path):
    """Preprocessing avanzato per OCR captcha matematici"""
    img = cv2.imread(image_path)
    if img is None:
        return None
    
    # Converti in scala di grigi
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Aumenta contrasto (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    enhanced = clahe.apply(gray)
    
    # Riduci rumore
    denoised = cv2.fastNlMeansDenoising(enhanced, None, 15, 7, 21)
    
    # Binarizzazione adattiva
    binary = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 15, 2)
    
    # Ridimensiona per migliorare OCR
    binary = cv2.resize(binary, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    
    return binary

def converti_testo_in_numeri(testo):
    if not testo:
        return []
    
    testo_conv = testo.lower()
    
    for word in sorted(WORD_TO_NUM.keys(), key=len, reverse=True):
        if word in testo_conv:
            testo_conv = testo_conv.replace(word, str(WORD_TO_NUM[word]))
    
    numeri = re.findall(r'\d+', testo_conv)
    return [int(n) for n in numeri]

def converti_numero_in_parole(num):
    if num in NUM_TO_WORD:
        return NUM_TO_WORD[num]
    
    if 21 <= num <= 99:
        tens = num // 10
        ones = num % 10
        tens_words = {2: 'twenty', 3: 'thirty', 4: 'forty', 5: 'fifty'}
        if ones == 0:
            return tens_words.get(tens, str(num))
        else:
            ones_word = NUM_TO_WORD.get(ones, str(ones))
            return f"{tens_words.get(tens, '')}{ones_word}"
    
    return str(num)

def riconosci_testo_da_immagine(image_path):
    """Usa RapidOCR poi DdddOcr con preprocessing avanzato"""
    
    processed = preprocess_math_image(image_path)
    
    if processed is None:
        return None
    
    # Salva per debug
    cv2.imwrite("debug_processed.jpg", processed)
    
    # Prova con RapidOCR
    if rapid_ocr:
        try:
            processed_rgb = cv2.cvtColor(processed, cv2.COLOR_GRAY2RGB)
            result, _ = rapid_ocr(processed_rgb)
            
            if result and len(result) > 0:
                texts = [item[1] for item in result]
                testo = ' '.join(texts)
                if testo and len(testo) > 2:
                    log(f"   📝 RapidOCR: '{testo}'")
                    return testo
        except Exception as e:
            log(f"   ⚠️ RapidOCR errore: {e}")
    
    # Prova con DdddOcr
    if dddd_ocr:
        try:
            _, buffer = cv2.imencode('.jpg', processed)
            testo = dddd_ocr.classification(buffer.tobytes())
            if testo:
                log(f"   📝 DdddOcr: '{testo}'")
                return testo
        except Exception as e:
            log(f"   ⚠️ DdddOcr errore: {e}")
    
    return None

def upload_captcha_to_supabase(image_path, surfses, urlid, qpic):
    try:
        if not MATH_SUPABASE_URL or not MATH_SUPABASE_KEY:
            return False
        
        supabase_math = create_client(MATH_SUPABASE_URL, MATH_SUPABASE_KEY)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
        
        with open(image_path, "rb") as f:
            file_data = f.read()
        
        file_path = f"{timestamp}/captcha.jpg"
        supabase_math.storage.from_("math-captchas").upload(
            file_path,
            file_data,
            {"content-type": "image/jpeg"}
        )
        
        log(f"📤 Captcha caricato su Supabase: {file_path}")
        return True
    except Exception as e:
        log(f"⚠️ Errore upload: {e}")
        return False

def salva_errore_matematico(surfses, urlid, qpic, image_path=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
    folder = os.path.join(ERRORI_DIR, f"math_{timestamp}")
    os.makedirs(folder, exist_ok=True)
    
    if image_path and os.path.exists(image_path):
        import shutil
        dest_path = os.path.join(folder, "captcha.jpg")
        shutil.copy(image_path, dest_path)
        upload_captcha_to_supabase(dest_path, surfses, urlid, qpic)
    
    metadata = {
        "timestamp": timestamp,
        "urlid": urlid,
        "qpic": qpic,
        "surfses": surfses,
        "account_email": EASYHITS_EMAIL,
        "account_name": ACCOUNT_NAME
    }
    
    with open(os.path.join(folder, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
    
    log(f"📁 Captcha salvato in {folder}")

def risolvi_captcha_matematico(surfses, image_path):
    opzioni = [
        surfses.get("aword1_number"),
        surfses.get("aword2_number"),
        surfses.get("aword3_number")
    ]
    opzioni = [x for x in opzioni if x is not None]
    
    if not opzioni:
        log("   ❌ Nessuna opzione dal server")
        return None
    
    log(f"   📊 Opzioni server: {opzioni}")
    
    testo_ocr = riconosci_testo_da_immagine(image_path)
    
    if not testo_ocr:
        log("   ❌ OCR non ha riconosciuto nulla")
        return None
    
    numeri = converti_testo_in_numeri(testo_ocr)
    
    if len(numeri) < 2:
        log(f"   ❌ OCR ha riconosciuto solo {len(numeri)} numeri: {numeri}")
        return None
    
    num1, num2 = numeri[0], numeri[1]
    log(f"   📊 Numeri OCR: {num1}, {num2}")
    
    somma = num1 + num2
    if somma in opzioni:
        log(f"   ✅ Somma: {num1} + {num2} = {somma}")
        return converti_numero_in_parole(somma)
    
    diff = abs(num1 - num2)
    if diff in opzioni:
        log(f"   ✅ Differenza: {max(num1,num2)} - {min(num1,num2)} = {diff}")
        return converti_numero_in_parole(diff)
    
    log(f"   ❌ Nessuna operazione corrisponde")
    log(f"      Somma={somma}, Differenza={diff}")
    return None

# ================ FUNZIONI PER CAPTCHA FIGURE ====================
def centra_figura(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return cv2.resize(image, (DIM, DIM))
    cnt = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(cnt)
    crop = image[y:y+h, x:x+w]
    return cv2.resize(crop, (DIM, DIM))

def estrai_descrittori(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    circularity = 0.0
    aspect_ratio = 0.0
    if contours:
        cnt = max(contours, key=cv2.contourArea)
        peri = cv2.arcLength(cnt, True)
        area = cv2.contourArea(cnt)
        if peri != 0:
            circularity = 4.0 * np.pi * area / (peri * peri)
        x, y, w, h = cv2.boundingRect(cnt)
        aspect_ratio = float(w)/h if h != 0 else 0.0

    moments = cv2.moments(thresh)
    hu = cv2.HuMoments(moments).flatten().tolist()

    h, w = img.shape[:2]
    cx, cy = w//2, h//2
    raggi = [int(min(h,w)*r) for r in (0.2, 0.4, 0.6, 0.8)]
    radiale = []
    for r in raggi:
        mask = np.zeros((h,w), np.uint8)
        cv2.circle(mask, (cx,cy), r, 255, -1)
        mean = cv2.mean(img, mask=mask)[:3]
        radiale.extend([m/255.0 for m in mean])

    spaziale = []
    quadranti = [(0,0,cx,cy), (cx,0,w,cy), (0,cy,cx,h), (cx,cy,w,h)]
    for (x1,y1,x2,y2) in quadranti:
        roi = img[y1:y2, x1:x2]
        if roi.size > 0:
            mean = cv2.mean(roi)[:3]
            spaziale.extend([m/255.0 for m in mean])

    vettore = radiale + spaziale + [circularity, aspect_ratio] + hu
    return np.array(vettore, dtype=float)

def get_features(img):
    img_centrata = centra_figura(img)
    return estrai_descrittori(img_centrata)

def predict_figure(img_crop):
    global X_fast, y_fast, classes_fast
    
    if X_fast is None or img_crop is None or img_crop.size == 0:
        return None
    
    features = get_features(img_crop)
    distances = np.linalg.norm(X_fast - features, axis=1)
    best_idx = np.argmin(distances)
    return classes_fast.get(int(y_fast[best_idx]), "errore")

def crop_safe(img, coords):
    try:
        x1, y1, x2, y2 = map(int, coords.split(","))
    except:
        return None
    h, w = img.shape[:2]
    x1 = max(0, min(w-1, x1))
    x2 = max(0, min(w, x2))
    y1 = max(0, min(h-1, y1))
    y2 = max(0, min(h, y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2]

def fallback_pixel_compare(crops):
    norm = []
    for c in crops:
        if c is None or c.size == 0:
            norm.append(None)
        else:
            centered = centra_figura(c)
            resized = cv2.resize(centered, (DIM, DIM)).astype(np.float32)
            norm.append(resized)

    best = None
    min_diff = float("inf")
    n = len(norm)

    for i in range(n):
        if norm[i] is None:
            continue
        for j in range(i+1, n):
            if norm[j] is None:
                continue
            diff = np.linalg.norm(norm[i].flatten() - norm[j].flatten())
            if diff < min_diff:
                min_diff = diff
                best = (i, j)

    if best and min_diff < 400.0:
        return min(best)
    return None

def salva_errore_figure(qpic, img, picmap, labels, chosen_idx, motivo, urlid=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
    folder = os.path.join(ERRORI_DIR, f"{timestamp}_{qpic}")
    os.makedirs(folder, exist_ok=True)
    
    full_path = os.path.join(folder, "full.jpg")
    cv2.imwrite(full_path, img)
    
    for i, p in enumerate(picmap):
        crop = crop_safe(img, p.get("coords", ""))
        if crop is not None and crop.size > 0:
            crop_path = os.path.join(folder, f"crop_{i+1}.jpg")
            cv2.imwrite(crop_path, crop)
    
    metadata = {
        "timestamp": timestamp,
        "qpic": qpic,
        "urlid": urlid,
        "motivo": motivo,
        "labels_predette": labels,
        "chosen_idx": chosen_idx,
        "account_email": EASYHITS_EMAIL,
        "account_name": ACCOUNT_NAME
    }
    
    with open(os.path.join(folder, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
    
    log(f"📁 Errore salvato in {folder}")

# ================ MAIN LOOP ====================
def main():
    global current_cookie_string
    
    log("=" * 50)
    log("🚀 AUTOSURF COMPLETO - Figure + Captcha Matematici")
    log("=" * 50)
    
    if not load_dataset_from_hf():
        log("❌ Impossibile proseguire senza dataset figure")
        return
    
    init_ocr()
    
    while True:
        current_cookie_string = get_cookie_from_supabase()
        
        if not current_cookie_string:
            log("⚠️ Nessun cookie attivo trovato, generazione...")
            current_cookie_string = generate_cookie()
            
            if not current_cookie_string:
                log("❌ Impossibile generare cookie, riprovo tra 60 secondi")
                time.sleep(60)
                continue
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": current_cookie_string
        }
        session = requests.Session()
        session.headers.update(headers)
        
        captcha_counter = 0
        
        while True:
            try:
                r = session.post(
                    "https://www.easyhits4u.com/surf/?ajax=1&try=1",
                    verify=False, timeout=REQUEST_TIMEOUT
                )
                
                if r.status_code != 200:
                    time.sleep(5)
                    continue
                
                data = r.json()
                urlid = data.get("surfses", {}).get("urlid")
                qpic = data.get("surfses", {}).get("qpic")
                seconds = int(data.get("surfses", {}).get("seconds", 20))
                picmap = data.get("picmap")
                
                if not urlid or not qpic:
                    log("⚠️ Cookie scaduto, rigenerazione...")
                    break
                
                if picmap is not None and len(picmap) > 0:
                    # CAPTCHA A FIGURE
                    log("🎯 Captcha a figure rilevato")
                    
                    img_data = session.get(f"https://www.easyhits4u.com/simg/{qpic}.jpg", verify=False).content
                    img = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
                    
                    crops = [crop_safe(img, p.get("coords", "")) for p in picmap]
                    labels = [predict_figure(c) for c in crops]
                    log(f"📋 Labels figure: {labels}")
                    
                    seen = {}
                    chosen_idx = None
                    for i, label in enumerate(labels):
                        if label and label != "errore":
                            if label in seen:
                                chosen_idx = seen[label]
                                log(f"🎯 Duplicato via label: '{label}'")
                                break
                            seen[label] = i
                    
                    if chosen_idx is None:
                        log("⚠️ Nessun duplicato, provo fallback pixel...")
                        chosen_idx = fallback_pixel_compare(crops)
                        if chosen_idx is not None:
                            log(f"🎯 Duplicato via fallback pixel: posizione {chosen_idx}")
                    
                    if chosen_idx is None:
                        log("❌ Nessun duplicato trovato")
                        salva_errore_figure(qpic, img, picmap, labels, None, "nessun_duplicato", urlid)
                        log("🛑 FERMO PER ANALISI")
                        return
                    
                    time.sleep(seconds)
                    word = picmap[chosen_idx]["value"]
                    log(f"📤 Invio risposta: word={word}")
                    
                    resp = session.get(
                        f"https://www.easyhits4u.com/surf/?f=surf&urlid={urlid}&surftype=2"
                        f"&ajax=1&word={word}&screen_width=1024&screen_height=768",
                        verify=False
                    )
                    
                    resp_data = resp.json()
                    warning = resp_data.get("warning")
                    
                    if warning == "wrong_choice":
                        log("❌ Wrong choice")
                        salva_errore_figure(qpic, img, picmap, labels, chosen_idx, "wrong_choice", urlid)
                        log("🛑 FERMO PER ANALISI")
                        return
                    
                    captcha_counter += 1
                    log(f"✅ OK #{captcha_counter} (punteggio: {warning})")
                    
                else:
                    # CAP
