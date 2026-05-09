import asyncio  # Required for asynchronous operations so the script doesn't freeze the system while waiting.
import time  # Provides time tracking and delay calculation functions.
import aiohttp  # Async HTTP client required by the PetKit library to make network requests.
import os  # Allows the script to securely read environment variables for credentials.
import sys  # Allows the script to exit safely if there's a critical configuration error.
import traceback  # Helps print detailed error traces when something crashes.
from datetime import datetime  # Used to convert raw computer timestamps into readable UK time for logs.
from pypetkitapi.client import PetKitClient  # The main API client that connects to your PetKit account.

# Try to safely import the command libraries. If they are missing or named differently, catch the error.
try:
    from pypetkitapi.command import DeviceAction, LBCommand, LitterCommand  # Standard PetKit command classes.
except ImportError as e:
    print(f"CRITICAL ERROR: Failed to import commands from pypetkitapi: {e}")  # Explains the import failure.
    sys.exit(1)  # Kills the script if the library is fundamentally broken.

# DeviceCommand sometimes exists in different versions of the library, so we import it optionally.
try:
    from pypetkitapi.command import DeviceCommand  # Alternative command class.
except ImportError:
    DeviceCommand = None  # If it doesn't exist, set it to None so we can safely ignore it.

# --- CONFIGURATION ---
USERNAME = os.environ.get("PETKIT_USERNAME")  # Fetches your secure email from the Raspberry Pi environment.
PASSWORD = os.environ.get("PETKIT_PASSWORD")  # Fetches your secure password from the environment.
TIMEZONE = "Europe/London"  # Specifies your timezone to sync the PetKit data accurately.
REGION = "United Kingdom"  # Tells the API to connect to the EU/UK data centers.
DELAY_HOURS = 7  # Requirement: 7-hour delay between visit and deep clean.
POLL_INTERVAL = 300  # Requirement: Polling time of 5 minutes (300 seconds).
DEBUGGING = True  # Requirement: Toggle this to False to reduce log output to just flow updates.


# --- DYNAMIC COMMAND HELPERS ---
# These functions dynamically search the library to find the correct API command names,
# preventing the "AttributeError" crash you experienced when the library updates.
def get_control_endpoint():
    # Checks LitterCommand first for the control endpoint
    if hasattr(LitterCommand, 'CONTROL_DEVICE'): return LitterCommand.CONTROL_DEVICE
    if hasattr(LitterCommand, 'CONTROL'): return LitterCommand.CONTROL
    # Checks DeviceCommand as a backup
    if DeviceCommand and hasattr(DeviceCommand, 'CONTROL_DEVICE'): return DeviceCommand.CONTROL_DEVICE
    if DeviceCommand and hasattr(DeviceCommand, 'CONTROL'): return DeviceCommand.CONTROL
    return "litter/control"  # Ultimate fallback to string path


def get_start_action():
    if hasattr(DeviceAction, 'START'): return DeviceAction.START
    return "start"  # Fallback


def get_action_cmd(action_type):
    # Matches your desired action to the library's specific codes.
    if action_type == 'clean':
        if hasattr(LBCommand, 'CLEANING'): return LBCommand.CLEANING
        if hasattr(LBCommand, 'CLEAN'): return LBCommand.CLEAN
        return "cleaning"
    elif action_type == 'flatten':
        if hasattr(LBCommand, 'LEVELING'): return LBCommand.LEVELING
        if hasattr(LBCommand, 'LEVEL'): return LBCommand.LEVEL
        if hasattr(LBCommand, 'FLATTEN'): return LBCommand.FLATTEN
        return "flatten"
    return None


async def send_device_command(client, device_id, action_type):
    # This compiles the safest available endpoints from our helper functions
    endpoint = get_control_endpoint()
    start_act = get_start_action()
    target_cmd = get_action_cmd(action_type)

    if DEBUGGING:  # Prints exactly what command is being assembled
        print(f"[DEBUG] Sending Command -> Endpoint: {endpoint} | Action: {start_act} | Target: {target_cmd}")

    try:
        # Transmits the compiled request to the PetKit cloud
        await client.send_api_request(device_id, endpoint, {start_act: target_cmd})
        print(f"[SUCCESS] {action_type.upper()} command sent successfully.")  # Confirms success
        return True  # Returns True so the main loop can update its memory
    except Exception as e:
        print(f"[ERROR] Failed to send {action_type} command: {e}")  # Logs the failure reason
        print(traceback.format_exc())  # Prints the full stack trace for deep debugging
        if DEBUGGING:  # If it failed, dump all available commands so we can map it if necessary
            print("[DEBUG] Dumping available endpoints to help troubleshoot:")
            print(f"  LitterCommand attributes: {[a for a in dir(LitterCommand) if not a.startswith('_')]}")
            if DeviceCommand: print(
                f"  DeviceCommand attributes: {[a for a in dir(DeviceCommand) if not a.startswith('_')]}")
            print(f"  LBCommand attributes: {[a for a in dir(LBCommand) if not a.startswith('_')]}")
        return False  # Returns False so the script tries again on the next poll


async def safety_check(client, target_id):
    # Requirement: Always check if the cat is in the litter immediately before sending a command.
    if DEBUGGING: print("[SAFETY CHECK] Verifying litter tray is empty right now...")
    try:
        await client.get_devices_data()  # Forces a fresh, instant download of sensor data.
        for d in client.petkit_entities.values():  # Iterates through devices.
            if str(getattr(d, 'id', '')) == str(target_id):
                # 1. We check the state object for the live 'pet_in_time' timer found in your logs.
                if hasattr(d, 'state'):
                    if getattr(d.state, 'pet_in_time', 0) > 0:
                        print("[SAFETY CHECK] FAILED: Cat is currently inside (pet_in_time > 0).")
                        return False  # Aborts command
                # 2. We check the main object's boolean flag as a backup safety net.
                if getattr(d, 'is_cat_detected', False):
                    print("[SAFETY CHECK] FAILED: Cat is currently inside (is_cat_detected is True).")
                    return False  # Aborts command

        if DEBUGGING: print("[SAFETY CHECK] PASSED: Litter box is clear.")
        return True  # Coast is clear, authorise command.
    except Exception as e:
        print(f"[SAFETY CHECK] ERROR: Could not verify safety ({e}). Aborting to be safe.")
        return False  # Defaults to False (do not send) if network fails during the check.


async def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Script starting. Initialising parameters...")
    if not USERNAME or not PASSWORD:  # Ensures credentials loaded properly
        print("CRITICAL ERROR: PETKIT_USERNAME or PETKIT_PASSWORD not found.")
        sys.exit(1)

    delay_seconds = DELAY_HOURS * 3600  # Converts 7 hours to 25,200 seconds for math.

    async with aiohttp.ClientSession() as session:  # Opens persistent web session.
        client = PetKitClient(USERNAME, PASSWORD, REGION, TIMEZONE, session=session)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Logged in successfully. {DELAY_HOURS}-Hour Delay active.")

        # --- MEMORY VARIABLES ---
        last_handled_level = 0  # Tracks the timestamp of the last visit we levelled.
        last_handled_clean = 0  # Tracks the timestamp of the last visit we cleaned.
        first_run = True  # Flag to identify the very first run for startup calculations.

        while True:  # Starts the infinite 24/7 loop.
            try:
                if DEBUGGING: print(
                    f"\n[{datetime.now().strftime('%H:%M:%S')}] Polling PetKit servers for fresh data...")
                await client.get_devices_data()  # Downloads the latest telemetry.

                puramax = None
                for d in client.petkit_entities.values():  # Finds the specific PuraMax device.
                    if str(getattr(d, 'id', '')) == "100034266" or 't4' in str(getattr(d, 'type', '')).lower():
                        puramax = d
                        break

                if not puramax:  # Failsafe if the API server drops the device list temporarily.
                    if DEBUGGING: print(f"[DEBUG] Warning: PuraMax not found in this poll. Retrying later.")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # --- 1. LIVE OCCUPANCY ---
                is_cat_in = False
                if hasattr(puramax, 'state') and getattr(puramax.state, 'pet_in_time', 0) > 0:
                    is_cat_in = True  # Cat is inside right now.

                # --- 2. HISTORICAL RECORD EXTRACTION ---
                latest_exit_time = 0
                latest_clean_time = 0

                records = getattr(puramax, 'device_records', [])  # Pulls the historical logs
                if DEBUGGING and records:
                    print(f"[DEBUG] Found {len(records)} history records. Analysing...")

                for record in records:  # Iterates through every record log
                    evt_type = getattr(record, 'enum_event_type', '').lower()
                    rec_time = getattr(record, 'timestamp', 0)

                    if DEBUGGING: print(f"[DEBUG] Record -> Type: '{evt_type}' | Time: {rec_time}")

                    if 'pet_out' in evt_type:  # If the record is a cat visit ending
                        if rec_time > latest_exit_time:
                            latest_exit_time = rec_time
                    elif 'clean' in evt_type or 'clear' in evt_type or 'manual' in evt_type or 'auto' in evt_type:
                        # Requirement: Check if the last recorded action in the data has been a clean.
                        if rec_time > latest_clean_time:
                            latest_clean_time = rec_time

                current_time = time.time()  # Grabs current Unix time

                if DEBUGGING:
                    print(f"[DATA] Live Occupancy: {is_cat_in}")
                    if latest_exit_time > 0: print(
                        f"[DATA] Last Exit: {datetime.fromtimestamp(latest_exit_time).strftime('%Y-%m-%d %H:%M:%S')}")
                    if latest_clean_time > 0: print(
                        f"[DATA] Last Clean: {datetime.fromtimestamp(latest_clean_time).strftime('%Y-%m-%d %H:%M:%S')}")

                # --- 3. STARTUP REQUIREMENT ---
                if first_run:
                    if latest_exit_time > 0:
                        if latest_clean_time > latest_exit_time:
                            print("[STARTUP] The tray has already been cleaned since the last visit. Standby.")
                            # Sets memory so it doesn't trigger anything for this old visit
                            last_handled_clean = latest_exit_time
                            last_handled_level = latest_exit_time
                        else:
                            time_since = current_time - latest_exit_time
                            if time_since >= delay_seconds:
                                print(
                                    f"[STARTUP] Visit was {time_since / 3600:.1f} hours ago. Clean required immediately.")
                            else:
                                hours_to_go = (delay_seconds - time_since) / 3600
                                print(f"[STARTUP] Resuming countdown. ~{hours_to_go:.1f} hours left until clean.")
                    first_run = False  # Disables the startup logic

                # --- 4. ACTION LOGIC ---
                if is_cat_in:
                    if DEBUGGING: print("[ACTION] Cat is currently inside. Standing by.")

                elif latest_exit_time > 0:
                    # Requirement: If last recorded action has been a clean, timer does not start and flatten is skipped.
                    if latest_clean_time > latest_exit_time:
                        if DEBUGGING and (last_handled_clean < latest_exit_time):
                            print("[ACTION] A server clean is logged AFTER the last visit. Bypassing commands.")
                        last_handled_clean = latest_exit_time
                        last_handled_level = latest_exit_time

                    else:
                        time_since_exit = current_time - latest_exit_time

                        # REQUIREMENT: Clean Command (7 Hours)
                        if latest_exit_time > last_handled_clean and time_since_exit >= delay_seconds:
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] 7-hour curing time complete. Preparing CLEAN...")
                            if await safety_check(client, puramax.id):
                                success = await send_device_command(client, puramax.id, 'clean')
                                if success:
                                    last_handled_clean = latest_exit_time
                                    last_handled_level = latest_exit_time  # Doesn't need level if it just cleaned

                        # REQUIREMENT: Flatten Command (Next Poll)
                        elif latest_exit_time > last_handled_level:
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] New un-levelled visit detected. Preparing FLATTEN...")
                            if await safety_check(client, puramax.id):
                                success = await send_device_command(client, puramax.id, 'flatten')
                                if success:
                                    last_handled_level = latest_exit_time

                        # COUNTDOWN LOGGING
                        elif latest_exit_time <= last_handled_level:
                            if DEBUGGING:
                                hours_left = (delay_seconds - time_since_exit) / 3600
                                print(
                                    f"[INFO] Litter is currently curing. ~{hours_left:.2f} hours remaining until clean.")

            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected Loop Error: {e}")
                traceback.print_exc()

            # REQUIREMENT: Wait exactly 5 minutes before looping
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())