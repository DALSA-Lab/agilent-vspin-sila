import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vspin_driver.centrifuge_api import VSpinCentrifuge

# --- Configuration ---
CENTRIFUGE_COM_PORT = "COM15" 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_calibration():
    centrifuge = VSpinCentrifuge(port=CENTRIFUGE_COM_PORT, calibration_offset=0)
    
    try:
        centrifuge.initialize()
        
        logging.info("Getting post-initialization 'home' position...")
        home_position = centrifuge._get_position()
        if home_position is None:
            logging.error("Could not get the initial home position. Aborting.")
            return

        print("\n--- Centrifuge Calibration ---")
        print(f"Initial 'Home' position recorded: {home_position}")

        logging.info("Unlocking bucket and opening door...")
        centrifuge.open_door()
        centrifuge.unlock_bucket()
        
        print("\nACTION REQUIRED:")
        print("1. The centrifuge door is now open and the bucket is unlocked.")
        print("2. Please MANUALLY and GENTLY rotate the centrifuge rotor in CLOCKWISE-DIRECTION until")
        print("   BUCKET 1 is perfectly aligned with the loader opening.")
        input("3. Press Enter here when you have aligned Bucket 1 and are ready to continue...")

        logging.info("Getting 'Bucket 1' position...")
        bucket_1_position = centrifuge._get_position()
        if bucket_1_position is None:
            logging.error("Could not get the Bucket 1 position. Aborting.")
            return

        print(f"\n'Bucket 1' position recorded: {bucket_1_position}")
        calibration_offset = bucket_1_position - home_position
        
        print("\n--- CALIBRATION COMPLETE ---")
        print(f"The calculated calibration offset is: {calibration_offset}")
        print("\nUse this value as the '--calibration-offset' parameter when starting the SiLA server.")
        print("-------------------------------\n")

    except Exception as e:
        logging.error(f"An error occurred during calibration: {e}")
    finally:
        logging.info("Closing connection to centrifuge.")
        if centrifuge.ser.is_open:
            centrifuge.ser.close()

if __name__ == "__main__":
    run_calibration()