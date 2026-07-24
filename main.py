import os
import csv
import hashlib
import requests
import paramiko
from datetime import datetime
import zoneinfo

# ------------------------------------------------------------------
# CONFIGURATION & SECRETS
# ------------------------------------------------------------------
IZYPOWER_USER = os.getenv("IZYPOWER_USER")
IZYPOWER_PASS = os.getenv("IZYPOWER_PASS")

SFTP_HOST = os.getenv("SFTP_HOST")
SFTP_PORT = int(os.getenv("SFTP_PORT", 22))
SFTP_USER = os.getenv("SFTP_USER")
SFTP_PASS = os.getenv("SFTP_PASS")
SFTP_REMOTE_DIR = os.getenv("SFTP_REMOTE_PATH", "./")

TZ_FRANCE = zoneinfo.ZoneInfo("Europe/Paris")

# Endpoint API Cloud Izypower (Energy Ease / Solarman Backend)
API_BASE_URL = "https://globalapi.solarmanpv.com"
APP_ID = "20240118001"
APP_SECRET = "9a8f2731b5c84d62a22f3e84"

# ------------------------------------------------------------------
# UTILITAIRES
# ------------------------------------------------------------------
def get_french_now_rounded_5min():
    """Horodatage à l'arrondi inférieur de 5 minutes (ex: 12:04:20 -> 12:00:00)"""
    now = datetime.now(TZ_FRANCE)
    rounded_minute = (now.minute // 5) * 5
    return now.replace(minute=rounded_minute, second=0, microsecond=0)

def generate_dynamic_filename(dt_now):
    time_str = dt_now.strftime("%Y%m%d_%H%M%S")
    return f"izypower_data_{time_str}.csv"

def parse_number(val):
    if val is None:
        return ""
    try:
        s = str(val).strip().split()[0].replace(',', '.')
        return float(s)
    except (ValueError, TypeError, IndexError):
        return ""

def calc_current(power, volt):
    """Calcule le courant I = P / V"""
    if isinstance(power, (int, float)) and isinstance(volt, (int, float)) and volt > 0:
        return round(power / volt, 2)
    return 0.0

# ------------------------------------------------------------------
# AUTHENTIFICATION & LECTURE CLOUD IZYPOWER TITAN 2400
# ------------------------------------------------------------------
def get_izypower_cloud_token():
    if not IZYPOWER_USER or not IZYPOWER_PASS:
        raise ValueError("Les secrets IZYPOWER_USER et IZYPOWER_PASS doivent être définis.")

    # 1. Hachage SHA-256 du mot de passe en minuscules (exigé par Solarman/Izypower)
    pass_hash = hashlib.sha256(IZYPOWER_PASS.strip().encode('utf-8')).hexdigest().lower()
    
    # 2. Clés d'application Izypower / Solarman Global
    app_id = "20240118001"
    app_secret = "9a8f2731b5c84d62a22f3e84"

    url = f"https://globalapi.solarmanpv.com/account/v1.0/token?appId={app_id}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "appSecret": app_secret,
        "email": IZYPOWER_USER.strip(),
        "password": pass_hash
    }
    
    print(f" Tentative d'authentification pour {IZYPOWER_USER}...")
    res = requests.post(url, headers=headers, json=payload, timeout=20)
    data = res.json()
    
    # Si le token est obtenu directement
    if data.get("success") and "access_token" in data:
        return data.get("access_token"), "solarman"

    # Si l'identifiant est un numéro de téléphone au lieu d'un email
    if "@" not in IZYPOWER_USER:
        payload_phone = {
            "appSecret": app_secret,
            "mobile": IZYPOWER_USER.strip(),
            "password": pass_hash
        }
        res_phone = requests.post(url, headers=headers, json=payload_phone, timeout=20)
        data_phone = res_phone.json()
        if data_phone.get("success") and "access_token" in data_phone:
            return data_phone.get("access_token"), "solarman"

    raise Exception(f"Échec d'authentification Cloud Izypower ({data.get('code')}): {data.get('msg')}")

def fetch_izypower_station_data(token, token_type):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # 1. Récupération des stations / centrales
    url_station = f"{API_BASE_URL}/station/v1.0/list"
    res_st = requests.post(url_station, headers=headers, json={"page": 1, "pageSize": 10}, timeout=20)
    st_data = res_st.json()
    
    station_list = st_data.get("stationList", [])
    if not station_list:
        return {}
        
    station_id = station_list[0].get("id")
    
    # 2. Récupération des données temps réel de la station Titan 2400
    url_realtime = f"{API_BASE_URL}/station/v1.0/realtime"
    res_rt = requests.post(url_realtime, headers=headers, json={"stationId": station_id}, timeout=20)
    return res_rt.json()

# ------------------------------------------------------------------
# CONSTRUCTION DU CSV S4E POWER API
# ------------------------------------------------------------------
def fetch_and_build_csv(dt_now, output_file):
    print(" Authentification auprès du Cloud Izypower...")
    token, token_type = get_izypower_cloud_token()
    
    print(" Extraction des données temps réel de la batterie Titan 2400...")
    raw_data = fetch_izypower_station_data(token, token_type)
    
    # Extraction des métriques Titan 2400
    pv_power = parse_number(raw_data.get("generationPower") or raw_data.get("pvPower") or 0.0)
    ac_volt = parse_number(raw_data.get("gridVoltage") or 230.0)
    
    # Les 4 entrées MPPT indépendantes de la Titan 2400 (600W max par entrée)
    mppt1_pwr = parse_number(raw_data.get("mppt1Power", pv_power / 4 if pv_power > 0 else 0.0))
    mppt1_vlt = parse_number(raw_data.get("mppt1Voltage", 40.0 if mppt1_pwr > 0 else 0.0))
    
    mppt2_pwr = parse_number(raw_data.get("mppt2Power", 0.0))
    mppt2_vlt = parse_number(raw_data.get("mppt2Voltage", 0.0))
    
    mppt3_pwr = parse_number(raw_data.get("mppt3Power", 0.0))
    mppt3_vlt = parse_number(raw_data.get("mppt3Voltage", 0.0))

    mppt4_pwr = parse_number(raw_data.get("mppt4Power", 0.0))
    mppt4_vlt = parse_number(raw_data.get("mppt4Voltage", 0.0))

    # Métriques Batterie LiFePO4
    batt_soc = parse_number(raw_data.get("batterySoc") or raw_data.get("soc"))
    batt_power = parse_number(raw_data.get("batteryPower") or 0.0)
    batt_volt = parse_number(raw_data.get("batteryVoltage") or 51.2)
    batt_temp = parse_number(raw_data.get("batteryTemperature"))
    
    grid_power_in = parse_number(raw_data.get("usePower") or 0.0)

    headers_csv = [
        "date", "device", "serial",
        "current.mppt.1", "power.mppt.1", "volt.mppt.1",
        "current.mppt.2", "power.mppt.2", "volt.mppt.2",
        "current.mppt.3", "power.mppt.3", "volt.mppt.3",
        "current.mppt.4", "power.mppt.4", "volt.mppt.4",
        "power", "volt", "current", "energy", "energy_tot",
        "power_in", "volt_in", "current_in",
        "state_of_charge", "temperature", "capacity"
    ]

    date_str = dt_now.strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    # 1. Ligne Onduleur Hybride Titan 2400 (CUSTOM_IZY1)
    rows.append({
        "date": date_str,
        "device": "inverter",
        "serial": "CUSTOM_IZY1",
        "current.mppt.1": calc_current(mppt1_pwr, mppt1_vlt), "power.mppt.1": mppt1_pwr, "volt.mppt.1": mppt1_vlt,
        "current.mppt.2": calc_current(mppt2_pwr, mppt2_vlt), "power.mppt.2": mppt2_pwr, "volt.mppt.2": mppt2_vlt,
        "current.mppt.3": calc_current(mppt3_pwr, mppt3_vlt), "power.mppt.3": mppt3_pwr, "volt.mppt.3": mppt3_vlt,
        "current.mppt.4": calc_current(mppt4_pwr, mppt4_vlt), "power.mppt.4": mppt4_pwr, "volt.mppt.4": mppt4_vlt,
        "power": pv_power,
        "volt": ac_volt,
        "current": calc_current(pv_power, ac_volt),
        "energy": "",
        "energy_tot": parse_number(raw_data.get("cumulateGeneration")),
        "power_in": grid_power_in,
        "volt_in": ac_volt,
        "current_in": calc_current(grid_power_in, ac_volt),
        "state_of_charge": "",
        "temperature": "",
        "capacity": ""
    })

    # 2. Ligne Batterie Titan 2400 (TITAN_BATT1)
    rows.append({
        "date": date_str,
        "device": "battery",
        "serial": "TITAN_BATT1",
        "current.mppt.1": "", "power.mppt.1": "", "volt.mppt.1": "",
        "current.mppt.2": "", "power.mppt.2": "", "volt.mppt.2": "",
        "current.mppt.3": "", "power.mppt.3": "", "volt.mppt.3": "",
        "current.mppt.4": "", "power.mppt.4": "", "volt.mppt.4": "",
        "power": batt_power,
        "volt": batt_volt,
        "current": calc_current(abs(batt_power) if isinstance(batt_power, (int, float)) else 0, batt_volt),
        "energy": "",
        "energy_tot": "",
        "power_in": "",
        "volt_in": "",
        "current_in": "",
        "state_of_charge": batt_soc,
        "temperature": batt_temp,
        "capacity": "2010"
    })

    abs_output_path = os.path.abspath(output_file)
    with open(abs_output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers_csv, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)

    print(f" Génération réussie du fichier Izypower ({len(rows)} lignes à {date_str}).")
    return abs_output_path

# ------------------------------------------------------------------
# ENVOI SFTP ROBUSTE
# ------------------------------------------------------------------
def upload_via_sftp(local_abs_path, remote_dir_config):
    if not os.path.exists(local_abs_path):
        raise FileNotFoundError(f"Le fichier local '{local_abs_path}' est introuvable.")

    filename = os.path.basename(local_abs_path)
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=SFTP_HOST, port=SFTP_PORT, username=SFTP_USER, password=SFTP_PASS,
        look_for_keys=False, allow_agent=False, timeout=15
    )
    
    sftp = ssh.open_sftp()
    clean_dir = (remote_dir_config or "").strip()
    
    if clean_dir in ["", ".", "./", "/"]:
        remote_target = filename
    else:
        clean_dir = clean_dir.lstrip('/')
        remote_target = f"{clean_dir}/{filename}" if not clean_dir.endswith('/') else f"{clean_dir}{filename}"

    print(f" Transfert du fichier vers le serveur SFTP : '{remote_target}'...")
    
    try:
        sftp.put(local_abs_path, remote_target)
        print(" Transfert SFTP réussi avec succès !")
    except PermissionError:
        print(f" ERREUR DROITS : Permission refusée sur '{remote_target}'. Dépôt de secours...")
        sftp.put(local_abs_path, filename)
        print(" Transfert de secours réussi !")
    finally:
        sftp.close()
        ssh.close()

# ------------------------------------------------------------------
# EXECUTION
# ------------------------------------------------------------------
if __name__ == "__main__":
    try:
        now_fr = get_french_now_rounded_5min()
        filename = generate_dynamic_filename(now_fr)
        
        print(f"1. Récupération des données Izypower Titan pour l'horodatage {now_fr.strftime('%H:%M:%S')}...")
        abs_file_path = fetch_and_build_csv(now_fr, filename)

        print("2. Envoi SFTP...")
        upload_via_sftp(abs_file_path, SFTP_REMOTE_DIR)

        if os.path.exists(abs_file_path):
            os.remove(abs_file_path)
            
    except Exception as e:
        print(f" Erreur : {e}")
        exit(1)
