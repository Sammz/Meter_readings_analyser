import asyncio  # Imports the core Python library for running asynchronous tasks.
import time  # Imports the time module to handle delays and calculations.
import aiohttp  # Imports the library required to make asynchronous web requests.
import os  # Imports the OS module to securely fetch your email and password.
import sys  # Imports system functions to allow the script to safely exit on fatal errors.
import traceback  # Imports the traceback module to print detailed error maps.
from datetime import datetime  # Imports datetime to format raw timestamps into UK time.
from pypetkitapi.client import PetKitClient  # Imports the main PetKit cloud client.

# Safely import the command libraries. If they are missing or named differently, catch the error.
try:
    from pypetkitapi.command import DeviceAction, LBCommand, LitterCommand
except ImportError as e:
    print(f"CRITICAL ERROR: Failed to import commands from pypetkitapi: {e}")
    sys.exit(1)

# DeviceCommand sometimes exists in different versions of the library, so we import it optionally.
try:
    from pypetkitapi.command import DeviceCommand
except ImportError:
    DeviceCommand = None

# --- CONFIGURATION ---
USERNAME = os.environ.get("PETKIT_USERNAME")
PASSWORD = os.environ.get("PETKIT_PASSWORD")
TIMEZONE = "Europe/London"
REGION = "United Kingdom"
DELAY_HOURS = 8.5  # Requirement: 8.5 hours before the main cleaning cycle.
POLL_INTERVAL = 800  # Requirement: Polling time of 800 seconds.
DEBUGGING = False  # Requirement: Toggle for verbose data dumps vs flow updates.


# --- DYNAMIC COMMAND HELPERS ---
def get_control_endpoint():
    if hasattr(LitterCommand, 'CONTROL_DEVICE'): return LitterCommand.CONTROL_DEVICE
    if hasattr(LitterCommand, 'CONTROL'): return LitterCommand.CONTROL
    if DeviceCommand and hasattr(DeviceCommand, 'CONTROL_DEVICE'): return DeviceCommand.CONTROL_DEVICE
    return "litter/control"


def get_start_action():
    if hasattr(DeviceAction, 'START'): return DeviceAction.START
    return "start"


def get_action_cmd(action_type):
    if action_type == 'clean':
        if hasattr(LBCommand, 'START_CLEAN'): return LBCommand.START_CLEAN
        if hasattr(LBCommand, 'AUTO_CLEAN'): return LBCommand.AUTO_CLEAN
        if hasattr(LBCommand, 'CLEANING'): return LBCommand.CLEANING
        return "cleaning"
    elif action_type == 'flatten':
        # Requirement: Uses the more effective "Waste Covering / Deep Levelling" oscillation.
        # if hasattr(LBCommand, 'SAND_LEVELING'): return LBCommand.SAND_LEVELING
        # if hasattr(LBCommand, 'PRE_CLEAN_LEVELING'): return LBCommand.PRE_CLEAN_LEVELING
        if hasattr(LBCommand, 'LEVELING'): return LBCommand.LEVELING
        if hasattr(LBCommand, 'LEVEL'): return LBCommand.LEVEL
        if hasattr(LBCommand, 'FLATTEN'): return LBCommand.FLATTEN
        return 5  # The raw PuraMax integer code for Waste Covering.
    return None


async def send_device_command(client, device_id, action_type):
    endpoint = get_control_endpoint()
    start_act = get_start_action()
    target_cmd = get_action_cmd(action_type)

    if DEBUGGING:
        print(f"[DEBUG] Sending Command -> Endpoint: {endpoint} | Action: {start_act} | Target: {target_cmd}")

    try:
        await client.send_api_request(device_id, endpoint, {start_act: target_cmd})
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [SUCCESS] {action_type.upper()} command sent successfully.")
        return True
    except Exception as e:
        # Check if it's an expired session first to suppress log flooding
        if "Session expired" in str(e) or "SessionExpired" in type(e).__name__:
            raise e

        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] Failed to send {action_type} command: {e}")
        if DEBUGGING: traceback.print_exc()
        return False


async def safety_check(client, target_id):
    if DEBUGGING: print("[SAFETY CHECK] Verifying litter tray is empty right now...")
    try:
        await client.get_devices_data()
        for d in client.petkit_entities.values():
            if str(getattr(d, 'id', '')) == str(target_id):
                if hasattr(d, 'state') and getattr(d.state, 'pet_in_time', 0) > 0:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] [SAFETY CHECK] FAILED: Cat is currently inside! Aborting command.")
                    return False
                if getattr(d, 'is_cat_detected', False):
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] [SAFETY CHECK] FAILED: Motion detected! Aborting command.")
                    return False
        if DEBUGGING: print("[SAFETY CHECK] PASSED: Litter box is clear.")
        return True
    except Exception as e:
        if "Session expired" in str(e) or "SessionExpired" in type(e).__name__:
            raise e

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] [SAFETY CHECK] ERROR: Could not verify safety ({e}). Aborting to be safe.")
        return False


async def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Script starting. Initialising parameters...")
    if not USERNAME or not PASSWORD:
        print("CRITICAL ERROR: PETKIT_USERNAME or PETKIT_PASSWORD not found.")
        sys.exit(1)

    delay_seconds = DELAY_HOURS * 3600

    # --- PERSISTENT MEMORY VARIABLES ---
    # Placed completely outside the reconnection loop so timers survive a forced re-login.
    global_latest_exit = 0
    global_latest_clean = 0
    last_handled_level = 0
    last_handled_clean = 0
    first_run = True

    while True:  # OUTER LOOP: Handles complete session re-authentication.
        try:
            async with aiohttp.ClientSession() as session:
                client = PetKitClient(USERNAME, PASSWORD, REGION, TIMEZONE, session=session)
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Logged in successfully. {DELAY_HOURS}-Hour Delay active.")

                while True:  # INNER LOOP: Handles the continuous polling.
                    try:
                        if DEBUGGING: print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Polling PetKit servers...")
                        await client.get_devices_data()

                        puramax = None
                        for d in client.petkit_entities.values():
                            if str(getattr(d, 'id', '')) == "100034266" or 't4' in str(getattr(d, 'type', '')).lower():
                                puramax = d
                                break

                        if not puramax:
                            if DEBUGGING: print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] [DEBUG] Warning: PuraMax not found in this poll. Retrying later.")
                            await asyncio.sleep(POLL_INTERVAL)
                            continue

                        # --- 1. LIVE OCCUPANCY ---
                        is_cat_in = False
                        if hasattr(puramax, 'state') and getattr(puramax.state, 'pet_in_time', 0) > 0:
                            is_cat_in = True

                        # --- 2. HISTORICAL RECORD EXTRACTION ---
                        records = getattr(puramax, 'device_records', [])
                        for record in records:
                            evt_type = getattr(record, 'enum_event_type', '').lower()
                            rec_time = getattr(record, 'timestamp', 0)

                            if 'pet_out' in evt_type and rec_time > global_latest_exit:
                                global_latest_exit = rec_time
                            elif any(k in evt_type for k in
                                     ['clean', 'reset', 'manual', 'auto']) and rec_time > global_latest_clean:
                                global_latest_clean = rec_time

                        current_time = time.time()

                        # --- 3. STARTUP REQUIREMENT ---
                        if first_run:
                            if global_latest_exit > 0:
                                if global_latest_clean > global_latest_exit:
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] [STARTUP] The tray has already been cleaned since the last visit. Standby mode active.")
                                    last_handled_clean = global_latest_exit
                                    last_handled_level = global_latest_exit
                                else:
                                    time_since = current_time - global_latest_exit
                                    if time_since >= delay_seconds:
                                        elapsed_h = int(time_since // 3600)
                                        elapsed_m = int((time_since % 3600) // 60)
                                        print(
                                            f"[{datetime.now().strftime('%H:%M:%S')}] [STARTUP] Visit was {elapsed_h}:{elapsed_m:02d} ago. Clean required immediately.")
                                    else:
                                        ttg = delay_seconds - time_since
                                        hours_to_go = int(ttg // 3600)
                                        minutes_to_go = int((ttg % 3600) // 60)
                                        print(
                                            f"[{datetime.now().strftime('%H:%M:%S')}] [STARTUP] Resuming countdown. ~{hours_to_go}:{minutes_to_go:02d} left until clean.")
                            first_run = False

                        # --- 4. ACTION LOGIC ---
                        if is_cat_in:
                            if DEBUGGING: print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] [ACTION] Cat is currently inside. Standing by.")

                        elif global_latest_exit > 0:
                            if global_latest_clean > global_latest_exit:
                                if last_handled_clean < global_latest_exit:
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] A server clean is logged AFTER the last visit. Bypassing commands.")
                                last_handled_clean = global_latest_exit
                                last_handled_level = global_latest_exit

                                # Hourly heartbeat when inactive to assure you it isn't stuck
                                if int(current_time) % 3600 < POLL_INTERVAL and not DEBUGGING:
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] Standby mode active. Tray is clean, waiting for cat.")

                            else:
                                time_since_exit = current_time - global_latest_exit

                                # TRIGGER CLEAN
                                if global_latest_exit > last_handled_clean and time_since_exit >= delay_seconds:
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] {DELAY_HOURS}-hour curing time complete. Preparing CLEAN...")
                                    if await safety_check(client, puramax.id):
                                        if await send_device_command(client, puramax.id, 'clean'):
                                            last_handled_clean = global_latest_exit
                                            last_handled_level = global_latest_exit

                                # TRIGGER FLATTEN / WASTE COVERING
                                elif global_latest_exit > last_handled_level:
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] New visit detected. Preparing DEEP LEVEL...")
                                    if await safety_check(client, puramax.id):
                                        if await send_device_command(client, puramax.id, 'flatten'):
                                            last_handled_level = global_latest_exit

                                # COUNTDOWN LOGGING
                                elif global_latest_exit <= last_handled_level:
                                    ttg = delay_seconds - time_since_exit
                                    hours_to_go = int(ttg // 3600)
                                    minutes_to_go = int((ttg % 3600) // 60)
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] Litter is curing. ~{hours_to_go}:{minutes_to_go:02d} remaining until clean.")

                        await asyncio.sleep(POLL_INTERVAL)

                    except Exception as e:
                        error_msg = str(e)

                        # ANTI-FLOOD REQUIREMENT: Cleanly catch session timeouts and skip the massive traceback.
                        if "Session expired" in error_msg or "SessionExpired" in type(e).__name__:
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] Session expired due to idle timeout. Automatically re-authenticating...")
                            break  # Breaks inner loop to immediately fetch a fresh token.

                        # If it is a different, unexpected error:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected Loop Error: {e}")
                        if DEBUGGING: traceback.print_exc()

                        # REQUIREMENT: Enforce a strict minimum 5-minute (300s) delay on general errors to prevent log floods.
                        print(
                            f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] General error encountered. Pausing for 5 minutes before retrying...")
                        await asyncio.sleep(300)

        except Exception as e:
            # Catches absolute failures (like full internet drops) preventing the login step.
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Critical Reconnection Error: {e}")
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] Pausing for 5 minutes before attempting to connect again...")
            await asyncio.sleep(300)


if __name__ == "__main__":
    asyncio.run(main())