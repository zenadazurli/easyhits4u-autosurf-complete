#!/usr/bin/env python3
# autosurf_complete.py - Autosurf con supporto figure + captcha matematici
# Versione: si ferma su captcha non riconosciuti e salva per analisi

import os
import sys
import time
import requests
import numpy as np
import cv2
import json
import re
import ddddocr
import easyocr
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

EASYHITS_EMAIL = os.environ.get("EASYHITS_EMAIL", "sandrominori50+uujkrczveemscvo@gmail.com")
EASYHITS_PASSWORD = os.environ.get("EASYHITS_PASSWORD", "DDnmVV45!!")
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

# OCR per captcha matematici
dddd_ocr = None
easy_ocr = None

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
    """Ottiene le chiavi Browserless da Supabase usando la colonna 'api_key'"""
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
    """Ottiene il token Cloudflare usando Browserless"""
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
    """Genera un nuovo cookie usando Browserless"""
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
            # GET homepage
            session.get("https://www.easyhits4u.com/", headers=headers, verify=False, timeout=15)
            time.sleep(1)
            
            # Token Cloudflare
            token = get_cf_token(api_key)
            if not token:
                continue
            
            # POST login
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
            
            # GET /member/
            session.get("https://www.easyhits4u.com/member/", headers=headers, verify=False, timeout=15)
            time.sleep(1)
            
            # GET /surf/
            session.get("https://www.easyhits4u.com/surf/", headers=headers, verify=False, timeout=15)
            time.sleep(1)
            
            # GET referer
            session.get(REFERER_URL, headers=headers, verify=False, timeout=15)
            
            cookies = session.cookies.get_dict()
            
            if 'user_id' in cookies and 'sesids' in cookies:
                cookie_string = '; '.join([f"{k}={v}" for k, v in cookies.items()])
                log(f"✅ Cookie generato! user_id={cookies['user_id']}, sesids={cookies['sesids']}")
                
                # Salva su Supabase
                try:
                    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                    
                    # Disattiva vecchi cookie
                    supabase.table('account_cookies')\
                        .update({'status': 'expired'})\
                        .eq('account_name', ACCOUNT_NAME)\
                        .eq('status', 'active')\
                        .execute()
                    
                    # Salva nuovo cookie
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

# ================ LEGGI COOKIE DA SUPABASE ====================
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

# ================ INIZIALIZZAZIONE OCR MATEMATICI ====================
def init_math_ocr():
    global dddd_ocr, easy_ocr
    
    log("📥 Inizializzazione OCR per captcha matematici...")
    try:
        dddd_ocr = ddddocr.DdddOcr()
        dddd_ocr.set_ranges("0123456789+-")
        log("✅ DdddOcr pronto")
    except Exception as e:
        log(f"⚠️ DdddOcr non disponibile: {e}")
    
    try:
        easy_ocr = easyocr.Reader(['en'], gpu=False)
        log("✅ EasyOCR pronto")
    except Exception as e:
        log(f"⚠️ EasyOCR non disponibile: {e}")

# ================ RICONOSCIMENTO CAPTCHA MATEMATICO ====================
def preprocess_math(image_path):
    """Preprocessing per captcha matematici"""
    img = cv2.imread(image_path)
    if img is None:
        return None
    
    denoised = cv2.fastNlMeansDenoisingColored(img, None, 15, 15, 7, 21)
    gray = cv2.cvtColor(denoised, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    if np.mean(binary) > 127:
        binary = cv2.bitwise_not(binary)
    
    return binary

def converti_parole_in_numeri(testo):
    """Converte parole numeriche in cifre"""
    parole = {
        'zero':'0', 'one':'1', 'two':'2', 'three':'3', 'four':'4',
        'five':'5', 'six':'6', 'seven':'7', 'eight':'8', 'nine':'9',
        'ten':'10', 'eleven':'11', 'twelve':'12', 'thirteen':'13',
        'fourteen':'14', 'fifteen':'15', 'sixteen':'16', 'seventeen':'17',
        'eighteen':'18', 'nineteen':'19', 'twenty':'20'
    }
    testo = testo.lower()
    for p, n in parole.items():
        testo = testo.replace(p, n)
    return testo

def safe_remove(file_path):
    """Rimuove un file solo se esiste"""
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except:
            pass

def riconosci_captcha_matematico(image_path):
    """Pipeline riconoscimento captcha matematici"""
    if not os.path.exists(image_path):
        log(f"⚠️ File {image_path} non trovato")
        return None
    
    processed = preprocess_math(image_path)
    if processed is None:
        return None
    
    temp_path = "temp_math_processed.jpg"
    cv2.imwrite(temp_path, processed)
    
    # Livello 1: DdddOcr
    if dddd_ocr:
        try:
            with open(temp_path, "rb") as f:
                testo = dddd_ocr.classification(f.read())
            numeri = re.findall(r'\d+', testo)
            if len(numeri) >= 2:
                safe_remove(temp_path)
                safe_remove(image_path)
                return int(numeri[0]), int(numeri[1])
        except:
            pass
    
    # Livello 2: EasyOCR
    if easy_ocr:
        try:
            results = easy_ocr.readtext(processed)
            testo = ' '.join([t[1] for t in results if t[2] > 0.5])
            testo = converti_parole_in_numeri(testo)
            numeri = re.findall(r'\d+', testo)
            if len(numeri) >= 2:
                safe_remove(temp_path)
                safe_remove(image_path)
                return int(numeri[0]), int(numeri[1])
        except:
            pass
    
    # Livello 3: Tesseract
    try:
        config = '--psm 8 -c tessedit_char_whitelist=0123456789+-'
        testo = pytesseract.image_to_string(processed, config=config)
        numeri = re.findall(r'\d+', testo)
        if len(numeri) >= 2:
            safe_remove(temp_path)
            safe_remove(image_path)
            return int(numeri[0]), int(numeri[1])
    except:
        pass
    
    # Non riconosciuto - salva errore
    safe_remove(temp_path)
    return None

def salva_errore_matematico(image_path):
    """Salva captcha matematico non riconosciuto"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")[:-3]
    folder = os.path.join(ERRORI_DIR, f"math_{timestamp}")
    os.makedirs(folder, exist_ok=True)
    
    import shutil
    if os.path.exists(image_path):
        shutil.copy(image_path, os.path.join(folder, "captcha.jpg"))
        
        # Salva anche metadata con info account
        metadata = {
            "timestamp": timestamp,
            "account_email": EASYHITS_EMAIL,
            "account_name": ACCOUNT_NAME,
            "tipo": "matematico_non_riconosciuto"
        }
        with open(os.path.join(folder, "metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)
        
        log(f"📁 Captcha matematico salvato in {folder}")

# ================ FUNZIONI DI RICONOSCIMENTO FIGURE ====================
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
    
    # Carica dataset figure
    if not load_dataset_from_hf():
        log("❌ Impossibile proseguire senza dataset figure")
        return
    
    # Inizializza OCR per captcha matematici
    init_math_ocr()
    
    while True:
        # Ottieni cookie da Supabase
        current_cookie_string = get_cookie_from_supabase()
        
        # Se non c'è cookie, generane uno nuovo
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
                picmap = data.get("picmap", [])
                
                if not urlid or not qpic:
                    log("⚠️ Cookie scaduto, rigenerazione...")
                    break
                
                # ===== CAPTCHA MATEMATICO =====
                if picmap is None or len(picmap) == 0:
                    log("🧮 Captcha matematico rilevato")
                    
                    try:
                        # Scarica immagine captcha
                        img_url = f"https://www.easyhits4u.com/simg/{qpic}.jpg"
                        img_response = session.get(img_url, verify=False, timeout=30)
                        
                        if img_response.status_code != 200:
                            log(f"   ❌ Download fallito: HTTP {img_response.status_code}")
                            time.sleep(seconds)
                            continue
                        
                        temp_path = "temp_math.jpg"
                        with open(temp_path, "wb") as f:
                            f.write(img_response.content)
                        
                        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
                            log("   ❌ File non creato o vuoto")
                            time.sleep(seconds)
                            continue
                        
                        risultato = riconosci_captcha_matematico(temp_path)
                        
                        if risultato:
                            a, b = risultato
                            log(f"📊 Numeri rilevati: {a}, {b}")
                            
                            # Prova somma e moltiplicazione
                            risolto = False
                            for op, answer in [('+', a + b), ('×', a * b)]:
                                log(f"   🎯 Tentativo: {a} {op} {b} = {answer}")
                                resp = session.get(
                                    f"https://www.easyhits4u.com/surf/?f=surf&urlid={urlid}&surftype=2"
                                    f"&ajax=1&answer={answer}&screen_width=1024&screen_height=768",
                                    verify=False
                                )
                                
                                try:
                                    resp_data = resp.json()
                                    if resp_data.get("warning") != "wrong_choice":
                                        risolto = True
                                        break
                                except:
                                    risolto = True
                                    break
                            
                            if risolto:
                                captcha_counter += 1
                                log(f"✅ OK #{captcha_counter}")
                            else:
                                log("❌ Nessuna operazione valida")
                                salva_errore_matematico(temp_path)
                                log("🛑 FERMO PER ANALISI - Account da cambiare")
                                return
                        else:
                            # Non riconosciuto -> ferma tutto
                            log("❌ Captcha matematico NON RICONOSCIUTO")
                            salva_errore_matematico(temp_path)
                            log("🛑 FERMO PER ANALISI - Account da cambiare")
                            return
                        
                        safe_remove(temp_path)
                        
                    except Exception as e:
                        log(f"   ❌ Errore: {e}")
                        salva_errore_matematico(temp_path if 'temp_path' in locals() else None)
                        return
                    
                    time.sleep(seconds)
                    continue
                
                # ===== CAPTCHA A FIGURE =====
                else:
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
                                break
                            seen[label] = i
                    
                    if chosen_idx is None:
                        log("❌ Nessun duplicato - Errore riconoscimento")
                        salva_errore_figure(qpic, img, picmap, labels, None, "nessun_duplicato", urlid)
                        log("🛑 FERMO PER ANALISI - Account da cambiare")
                        return
                    
                    time.sleep(seconds)
                    word = picmap[chosen_idx]["value"]
                    resp = session.get(
                        f"https://www.easyhits4u.com/surf/?f=surf&urlid={urlid}&surftype=2"
                        f"&ajax=1&word={word}&screen_width=1024&screen_height=768",
                        verify=False
                    )
                    
                    if resp.json().get("warning") == "wrong_choice":
                        log("❌ Wrong choice")
                        salva_errore_figure(qpic, img, picmap, labels, chosen_idx, "wrong_choice", urlid)
                        log("🛑 FERMO PER ANALISI - Account da cambiare")
                        return
                    
                    captcha_counter += 1
                    log(f"✅ OK #{captcha_counter}")
                    time.sleep(2)
                
            except Exception as e:
                log(f"❌ Errore: {e}")
                time.sleep(5)
                break

if __name__ == "__main__":
    main()
