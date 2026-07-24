import os
import csv
import requests
import paramiko
from datetime import datetime
import zoneinfo

# ------------------------------------------------------------------
# CONFIGURATION ET SECRETS IZYPOWER & SFTP
# ------------------------------------------------------------------
IZYPOWER_USER = os.getenv("IZYPOWER_USER")
IZYPOWER_PASS = os.getenv("IZYPOWER_PASS")

SFTP_HOST = os.getenv("SFTP_HOST")
SFTP_PORT = int(os.getenv("SFTP_PORT", 22))
SFTP_USER = os.getenv("SFTP_USER")
SFTP_PASS = os.getenv("SFTP_PASS")
SFTP_REMOTE_DIR = os.getenv("SFTP_REMOTE_PATH", "./")

TZ_FRANCE = zoneinfo.ZoneInfo("Europe/Paris")
BASE_URL = "https://api.izypower.fr/v1"  # Endpoint API Izypower Cloud

# ------------------------------------------------------------------
# UTILITAIRES
# ------------------------------------------------------------------
def get_french_now_rounded_5min():
    """Renvoie l'heure actuelle en France arrondie aux 5 minutes inférieures"""
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
# AUTHENTIFICATION ET RECUPERATION DES DONNEES IZYPOWER CLOUD
# ------------------------------------------------------------------
def get_izypower_data():
    session = requests.Session()
    
    # 1. Connexion au Cloud Izypower
    login_payload = {
        "username": IZYPOWER_USER,
        "password": IZYPOWER_PASS
    }
    
    print(" Authentification auprès d'Izypower Cloud...")
    res_login = session.post(f"{BASE_URL}/auth/login", json=login_payload, timeout=20)
    
    if res_login.status_code != 200:
        raise Exception(f"Échec d'authentification Izypower ({res_login.status_code}) : {res_login.text}")
    
    token = res_login.json().get("token") or res_login.json().get("access_token")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 2. Récupération des centrales et équipements
    print(" Récupération des données en temps réel de la centrale Izypower...")
    res_plants = session.get(f"{BASE_URL}/plants", headers=headers, timeout=20)
    plants_data = res_plants.json()
    
    # Extraction des données de la première centrale associée au compte
    plant = plants_data[0] if isinstance(plants_data, list) and len(plants_data) > 0 else plants_data
    plant_id = plant.get("id") or plant.get("plant_id")

    res_details = session.get(f"{BASE_URL}/plants/{plant_id}/realtime", headers=headers, timeout=20)
    return res_details.json()

# ------------------------------------------------------------------
# FORMATAGE AU FORMAT S4E POWER API
# ------------------------------------------------------------------
def fetch_and_build_csv(dt_now, output_file):
    data = get_izypower_data()
    
    # Extraction des métriques de production et consommation
    pv_power = parse_number(data.get("pv_power") or data.get("power") or 0.0)
    ac_volt = parse_number(data.get("grid_voltage") or data.get("volt") or 230.0)
    
    grid_power_in = parse_number(data.get("grid_power_import") or 0.0)
    grid_power_out = parse_number(data.get("grid_power_export") or 0.0)
    
    # Métriques Batterie (si présente dans l'écosystème Izypower)
    batt_soc = parse_number(data.get("battery_soc") or data.get("soc"))
    batt_power = parse_number(data.get("battery_power") or 0.0)
    batt_volt = parse_number(data.get("battery_voltage") or 51.2)
    batt_temp = parse_number(data.get("battery_temperature"))

    # Pistes MPPT virtuelles (Izypower répartit sa puissance sur les micro-onduleurs)
    c1 = calc_current(pv_power, ac_volt)

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

    # 1. Ligne Onduleur / Micro-onduleurs Izypower
    rows.append({
        "date": date_str,
        "device": "inverter",
        "serial": "IZYPOWER_INV1",
        "current.mppt.1": c1, "power.mppt.1": pv_power, "volt.mppt.1": ac_volt,
        "current.mppt.2": "", "power.mppt.2": "", "volt.mppt.2": "",
        "current.mppt.3": "", "power.mppt.3": "", "volt.mppt.3": "",
        "current.mppt.4": "", "power.mppt.4": "", "volt.mppt.4": "",
        "power": pv_power,
        "volt": ac_volt,
        "current": c1,
        "energy": "",
        "energy_tot": parse_number(data.get("total_energy")),
        "power_in": grid_power_in,
        "volt_in": ac_volt,
        "current_in": calc_current(grid_power_in, ac_volt),
        "state_of_charge": "",
        "temperature": "",
        "capacity": ""
    })

    # 2. Ligne Batterie (si présente)
    if batt_soc != "":
        rows.append({
            "date": date_str,
            "device": "battery",
            "serial": "IZYPOWER_BATT1",
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
            "capacity": ""
        })

    abs_output_path = os.path.abspath(output_file)
    with open(abs_output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers_csv, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)

    print(f" Génération du CSV Izypower réussie à {date_str} ({len(rows)} lignes).")
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

    print(f" Transfert SFTP vers : '{remote_target}'...")
    
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
        
        print(f"1. Récupération des données Izypower pour l'horodatage {now_fr.strftime('%H:%M:%S')}...")
        abs_file_path = fetch_and_build_csv(now_fr, filename)

        print("2. Envoi SFTP...")
        upload_via_sftp(abs_file_path, SFTP_REMOTE_DIR)

        if os.path.exists(abs_file_path):
            os.remove(abs_file_path)
            
    except Exception as e:
        print(f" Erreur : {e}")
        exit(1)
