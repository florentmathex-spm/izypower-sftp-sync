import time
import requests
import pandas as pd
from datetime import datetime

# --- CONFIGURATION ---
IZYPOWER_EMAIL = "yohann.rey26@gmail.com"
IZYPOWER_PASSWORD = "Oce30101997%"

BASE_URL = "https://cloud.izypower.fr/api"
LOGIN_URL = f"{BASE_URL}/v1/auth/login"
PLANTS_URL = f"{BASE_URL}/v1/plants"

CSV_FILE_PATH = "dernier_point_izypower.csv"
CHECK_INTERVAL_SECONDS = 300  # 5 minutes (300 secondes)


def get_auth_token(email, password):
    """S'authentifie auprès du Cloud IZYPOWER et récupère le Token Bearer."""
    payload = {"email": email, "password": password}
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "IzypowerDataFetcher/1.0"
    }

    try:
        response = requests.post(LOGIN_URL, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        token = data.get("token") or data.get("access_token")
        if not token and "data" in data:
            token = data["data"].get("token")
        return token
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Erreur d'authentification : {e}")
        return None


def get_latest_telemetry(token):
    """Récupère les données brutes de la centrale depuis l'API Cloud IZYPOWER."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "IzypowerDataFetcher/1.0"
    }

    try:
        response = requests.get(PLANTS_URL, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Erreur de récupération des données : {e}")
        return None


def format_to_powerapi(raw_data):
    """
    Mappe les données brutes JSON reçues du Cloud IZYPOWER vers la structure
    PowerAPI pour votre installation triphasée (3 batteries / 3 MPPTs).
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Extraction du premier objet centrale de la liste
    p_data = raw_data[0] if isinstance(raw_data, list) and len(raw_data) > 0 else raw_data

    record = {
        "timestamp": now_str,
        # --- Compteur Triphasé ---
        "meter_u_l1_v": p_data.get("u_l1", 230.0),
        "meter_u_l2_v": p_data.get("u_l2", 230.0),
        "meter_u_l3_v": p_data.get("u_l3", 230.0),
        "meter_i_l1_a": p_data.get("i_l1", 0.0),
        "meter_i_l2_a": p_data.get("i_l2", 0.0),
        "meter_i_l3_a": p_data.get("i_l3", 0.0),
        "meter_p_total_w": p_data.get("grid_power", 0.0),
        "meter_frequency_hz": p_data.get("frequency", 50.0),
        "meter_power_factor": p_data.get("power_factor", 0.98),
        # --- Panneaux Solaires (3 Chaînes / MPPTs) ---
        "pv1_power_w": p_data.get("pv1_power", 0.0),
        "pv1_voltage_v": p_data.get("pv1_voltage", 0.0),
        "pv1_current_a": p_data.get("pv1_current", 0.0),
        "pv2_power_w": p_data.get("pv2_power", 0.0),
        "pv2_voltage_v": p_data.get("pv2_voltage", 0.0),
        "pv2_current_a": p_data.get("pv2_current", 0.0),
        "pv3_power_w": p_data.get("pv3_power", 0.0),
        "pv3_voltage_v": p_data.get("pv3_voltage", 0.0),
        "pv3_current_a": p_data.get("pv3_current", 0.0),
        "pv_total_power_w": p_data.get("pv_total_power", 0.0),
        # --- Batteries Titan (3 unités) ---
        "bat1_soc_pct": p_data.get("bat1_soc", 0.0),
        "bat1_power_w": p_data.get("bat1_power", 0.0),
        "bat1_voltage_v": p_data.get("bat1_voltage", 0.0),
        "bat2_soc_pct": p_data.get("bat2_soc", 0.0),
        "bat2_power_w": p_data.get("bat2_power", 0.0),
        "bat2_voltage_v": p_data.get("bat2_voltage", 0.0),
        "bat3_soc_pct": p_data.get("bat3_soc", 0.0),
        "bat3_power_w": p_data.get("bat3_power", 0.0),
        "bat3_voltage_v": p_data.get("bat3_voltage", 0.0),
        # --- Consommation globale ---
        "load_total_power_w": p_data.get("load_power", 0.0)
    }

    return record


def save_to_csv(record_dict, filepath=CSV_FILE_PATH):
    """Écrit / Remplace le fichier CSV avec le dernier point de mesure."""
    df = pd.DataFrame([record_dict])
    df.to_csv(filepath, index=False, sep=";")
    print(f"[{datetime.now()}] 💾 Fichier CSV réécrit : '{filepath}'")


def main():
    print("🚀 Démarrage du service d'extraction automatique IZYPOWER Cloud...")
    
    token = get_auth_token(IZYPOWER_EMAIL, IZYPOWER_PASSWORD)
    
    while True:
        try:
            if not token:
                print("🔑 Authentification en cours...")
                token = get_auth_token(IZYPOWER_EMAIL, IZYPOWER_PASSWORD)

            if token:
                print(f"[{datetime.now()}] 📡 Récupération de la télémétrie...")
                raw_data = get_latest_telemetry(token)

                if raw_data:
                    record = format_to_powerapi(raw_data)
                    save_to_csv(record)
                else:
                    print("⚠️ Réponse vide. Le token sera renouvelé au prochain cycle.")
                    token = None

        except Exception as e:
            print(f"❌ Erreur lors de l'exécution : {e}")

        # Pause de 5 minutes avant d'exécuter la boucle suivante
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
