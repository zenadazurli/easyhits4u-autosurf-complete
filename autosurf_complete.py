#!/usr/bin/env python3
# cookie_generator.py - Genera cookie per EasyHits4U usando Browserless

import os
import time
import json
import requests
from datetime import datetime
from supabase import create_client
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================ CONFIGURAZIONE ====================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

BROWSERLESS_SUPABASE_URL = os.environ.get("BROWSERLESS_SUPABASE_URL")
BROWSERLESS_SUPABASE_KEY = os.environ.get("BROWSERLESS_SUPABASE_KEY")

EASYHITS_EMAIL = os.environ.get("EASYHITS_EMAIL")
EASYHITS_PASSWORD = os.environ.get("EASYHITS_PASSWORD")
ACCOUNT_NAME = os.environ.get("ACCOUNT_NAME", "main")

# ================ FUNZIONI ====================
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_browserless_keys():
    """Ottiene le chiavi Browserless da Supabase"""
    try:
        supabase = create_client(BROWSERLESS_SUPABASE_URL, BROWSERLESS_SUPABASE_KEY)
        resp = supabase.table('browserless_keys')\
            .select('key')\
            .eq('status', 'working')\
            .execute()
        
        keys = [item['key'] for item in resp.data] if resp.data else []
        log(f"📋 Trovate {len(keys)} chiavi Browserless 'working'")
        return keys
    except Exception as e:
        log(f"❌ Errore recupero chiavi: {e}")
        return []

def update_key_status(key, status, error_msg=None):
    """Aggiorna lo stato di una chiave Browserless"""
    try:
        supabase = create_client(BROWSERLESS_SUPABASE_URL, BROWSERLESS_SUPABASE_KEY)
        data = {'status': status}
        if error_msg:
            data['last_error'] = error_msg
            data['error_count'] = supabase.table('browserless_keys')\
                .select('error_count')\
                .eq('key', key)\
                .execute()
            current = data['error_count'].data[0]['error_count'] if data['error_count'].data else 0
            data['error_count'] = current + 1
        
        supabase.table('browserless_keys')\
            .update(data)\
            .eq('key', key)\
            .execute()
    except:
        pass

def generate_cookie_with_browserless(browserless_key):
    """Genera cookie usando Browserless.io"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache"
    }
    
    browserless_url = f"https://{browserless_key}@production-sfo.browserless.io/chrome/bql"
    
    bql_script = """
    // Login su EasyHits4U e cattura cookie
    
    // Vai alla pagina di login
    await page.goto('https://www.easyhits4u.com/login.php', { waitUntil: 'networkidle0' });
    await page.waitForTimeout(2000);
    
    // Inserisci email
    await page.type('input[name="email"]', '""" + EASYHITS_EMAIL + """');
    
    // Inserisci password
    await page.type('input[name="password"]', '""" + EASYHITS_PASSWORD + """');
    
    // Click sul pulsante login
    await page.click('input[type="submit"]');
    await page.waitForTimeout(5000);
    
    // Ottieni i cookie
    const cookies = await page.cookies();
    
    // Estrai il sesid
    let sesids = null;
    for (const cookie of cookies) {
        if (cookie.name === 'sesids') {
            sesids = cookie.value;
            break;
        }
    }
    
    return {
        sesids: sesids,
        all_cookies: cookies.map(c => `${c.name}=${c.value}`).join('; ')
    };
    """
    
    payload = {
        "code": bql_script,
        "context": {
            "viewport": {"width": 1024, "height": 768}
        }
    }
    
    start_time = time.time()
    
    try:
        response = requests.post(
            browserless_url,
            json=payload,
            headers=headers,
            timeout=60,
            verify=False
        )
        
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            sesids = result.get('sesids')
            all_cookies = result.get('all_cookies')
            
            if sesids:
                log(f"   ✅ Token ({elapsed:.1f}s)")
                return {
                    'success': True,
                    'sesids': sesids,
                    'cookies_string': all_cookies
                }
            else:
                log(f"   ❌ Nessun sesids trovato")
                return {'success': False, 'error': 'No sesids found'}
        else:
            log(f"   ❌ HTTP {response.status_code}")
            return {'success': False, 'error': f'HTTP {response.status_code}'}
            
    except requests.exceptions.Timeout:
        log(f"   ❌ Timeout")
        return {'success': False, 'error': 'Timeout'}
    except Exception as e:
        log(f"   ❌ Errore: {str(e)[:50]}")
        return {'success': False, 'error': str(e)}

def save_cookie_to_db(sesids, cookies_string):
    """Salva il cookie nel database"""
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Controlla se esiste già un cookie attivo per questo account
        existing = supabase.table('account_cookies')\
            .select('id')\
            .eq('account_name', ACCOUNT_NAME)\
            .eq('status', 'active')\
            .execute()
        
        # Disattiva i vecchi cookie
        if existing.data:
            supabase.table('account_cookies')\
                .update({'status': 'expired'})\
                .eq('account_name', ACCOUNT_NAME)\
                .eq('status', 'active')\
                .execute()
            log(f"   📝 Disattivati {len(existing.data)} vecchi cookie")
        
        # Inserisci il nuovo cookie
        data = {
            'account_name': ACCOUNT_NAME,
            'cookies_string': cookies_string,  # ← CORRETTO: usa cookies_string
            'status': 'active',
            'created_at': datetime.now().isoformat()
        }
        
        result = supabase.table('account_cookies').insert(data).execute()
        
        if result.data:
            log(f"   ✅ Cookie salvato nel database (ID: {result.data[0]['id']})")
            return True
        else:
            log(f"   ❌ Errore salvataggio cookie")
            return False
            
    except Exception as e:
        log(f"   ❌ Errore DB: {e}")
        return False

def main():
    log("=" * 50)
    log("🚀 GENERATORE COOKIE EASYHITS4U")
    log("=" * 50)
    
    # Verifica configurazione
    if not EASYHITS_EMAIL or not EASYHITS_PASSWORD:
        log("❌ EASYHITS_EMAIL o EASYHITS_PASSWORD non impostati")
        return
    
    # Ottieni chiavi Browserless
    keys = get_browserless_keys()
    if not keys:
        log("❌ Nessuna chiave Browserless disponibile")
        return
    
    # Prova ogni chiave
    for i, key in enumerate(keys):
        log(f"🔑 Tentativo {i+1}/{len(keys)}: {key[:15]}...")
        
        result = generate_cookie_with_browserless(key)
        
        if result['success']:
            log(f"✅ Cookie generato! user_id=?, sesids={result['sesids']}")
            
            # Salva nel database
            if save_cookie_to_db(result['sesids'], result['cookies_string']):
                log("🎉 Cookie salvato e pronto per l'uso!")
                update_key_status(key, 'working')
                return True
            else:
                log("❌ Impossibile salvare il cookie")
                update_key_status(key, 'error', 'DB save failed')
        else:
            update_key_status(key, 'error', result.get('error', 'Unknown error'))
        
        time.sleep(1)
    
    log("❌ Nessuna chiave Browserless ha funzionato")
    return False

if __name__ == "__main__":
    main()
