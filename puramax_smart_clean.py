import asyncio  # Imports the core Python library for running asynchronous tasks (waiting without freezing).
import time  # Imports the time module to handle delays, current time, and calculations.
import aiohttp  # Imports the library required to make asynchronous web requests to the PetKit cloud.
import os  # Imports the OS module to securely fetch your email and password from the system.
import sys  # Imports system functions to allow the script to safely exit if credentials are missing.
import traceback  # Imports the traceback module to print detailed error maps if the code crashes.
from datetime import datetime  # Imports datetime to format raw timestamps into human-readable UK time.
from pypetkitapi.client import PetKitClient  # Imports the main PetKit client to manage the cloud connection.

# Safely import the command libraries. If they are missing or named differently, catch the error.
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

# --- CONFIGURATION ---  # A marker indicating the start of user-editable variables.
USERNAME = os.environ.get("PETKIT_USERNAME")  # Securely retrieves the PetKit account email from the Pi.
PASSWORD = os.environ.get("PETKIT_PASSWORD")  # Securely retrieves the PetKit account password from the Pi.
TIMEZONE = "Europe/London"  # Sets the timezone to ensure the PetKit cloud syncs timestamps to UK time.
REGION = "United Kingdom"  # Specifies the European/UK region for the API to connect to the correct database.
DELAY_HOURS = 8  # Requirement: the delay between the cat leaving and the main cleaning cycle in hours.
POLL_INTERVAL = 300  # Requirement: Polling time of exactly 5 minutes (300 seconds).
DEBUGGING = False  # Requirement: Set to True for verbose data dumps, False for flow updates only.


# --- DYNAMIC COMMAND HELPERS ---
def get_control_endpoint():  # Function to find the correct API endpoint string for commands.
    if hasattr(LitterCommand, 'CONTROL_DEVICE'): return LitterCommand.CONTROL_DEVICE  # Tries the standard endpoint.
    if hasattr(LitterCommand, 'CONTROL'): return LitterCommand.CONTROL  # Tries the fallback endpoint.
    if DeviceCommand and hasattr(DeviceCommand,
                                 'CONTROL_DEVICE'): return DeviceCommand.CONTROL_DEVICE  # Tries alternative class.
    return "litter/control"  # Ultimate fallback to a raw string path if all else fails.


def get_start_action():  # Function to find the correct API start action code.
    if hasattr(DeviceAction, 'START'): return DeviceAction.START  # Returns the standard start code.
    return "start"  # Fallback string.


def get_action_cmd(action_type):  # Matches your desired action to the library's specific codes.
    if action_type == 'clean':  # If we want to clean...
        if hasattr(LBCommand,
                   'START_CLEAN'): return LBCommand.START_CLEAN  # Prioritise START_CLEAN to avoid the tilt bug.
        if hasattr(LBCommand, 'AUTO_CLEAN'): return LBCommand.AUTO_CLEAN  # Alternative safe clean command.
        if hasattr(LBCommand,'CLEANING'): return LBCommand.CLEANING  # Standard fallback.
        return "cleaning"  # Raw string fallback.
    elif action_type == 'flatten':  # If we want to level...
        if hasattr(LBCommand, 'LEVELING'): return LBCommand.LEVELING
        if hasattr(LBCommand, 'LEVEL'): return LBCommand.LEVEL
        if hasattr(LBCommand, 'FLATTEN'): return LBCommand.FLATTEN
        return "leveling"  # Raw string fallback.
    return None  # Returns None if the action type is unknown.


async def send_device_command(client, device_id,
                              action_type):  # Assembles and sends the physical command to the litter box.
    endpoint = get_control_endpoint()  # Gets the endpoint path.
    start_act = get_start_action()  # Gets the start action code.
    target_cmd = get_action_cmd(action_type)  # Gets the specific command (clean/flatten).

    if DEBUGGING:  # If debugging is on, print the exact command payload.
        print(f"[DEBUG] Sending Command -> Endpoint: {endpoint} | Action: {start_act} | Target: {target_cmd}")

    try:  # Begins a safe block to send the command over the internet.
        await client.send_api_request(device_id, endpoint, {start_act: target_cmd})  # Transmits the command to PetKit.
        print(f"[SUCCESS] {action_type.upper()} command sent successfully.")  # Confirms success to the logs.
        return True  # Returns True so the main loop can update its memory and not repeat the command.
    except Exception as e:  # Catches internet drops or API rejections.
        print(f"[ERROR] Failed to send {action_type} command: {e}")  # Logs the specific error reason.
        if DEBUGGING: traceback.print_exc()  # Prints the full stack trace only if debugging is enabled.
        return False  # Returns False so the script knows it failed and can try again next poll.


async def safety_check(client, target_id):  # Strictly checks if the cat is inside immediately before moving motors.
    print("[SAFETY CHECK] Verifying litter tray is empty right now...")  # Logs the start of the check.
    try:  # Safe block for the network request.
        await client.get_devices_data()  # Forces the client to download the absolute newest data from PetKit.
        for d in client.petkit_entities.values():  # Loops through your downloaded devices.
            if str(getattr(d, 'id', '')) == str(target_id):  # Matches your specific PuraMax ID.
                if hasattr(d, 'state'):  # Checks if the device data contains the 'state' object.
                    if getattr(d.state, 'pet_in_time', 0) > 0:  # If 'pet_in_time' > 0, the cat is actively inside.
                        print(
                            "[SAFETY CHECK] FAILED: Cat is currently inside! Aborting command.")  # Logs the safety abort.
                        return False  # Returns False to permanently block the command.
                if getattr(d, 'is_cat_detected', False):  # Secondary backup check using the standard flag.
                    print("[SAFETY CHECK] FAILED: is_cat_detected is True! Aborting command.")  # Logs the safety abort.
                    return False  # Returns False to permanently block the command.

        print("[SAFETY CHECK] PASSED: Litter box is clear.")  # Logs that no cat was detected.
        return True  # Returns True, authorising the motors to spin.
    except Exception as e:  # Catches any network errors during the check.
        print(f"[SAFETY CHECK] ERROR: Could not verify safety ({e}). Aborting to be safe.")  # Always aborts if blind.
        return False  # Defaults to False (do not send command) if we cannot 100% guarantee it is empty.


async def main():  # Defines the main continuous loop of the programme.
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Script starting. Initialising parameters...")  # Logs the startup time.
    if not USERNAME or not PASSWORD:  # Verifies that credentials exist in the OS.
        print("CRITICAL ERROR: PETKIT_USERNAME or PETKIT_PASSWORD not found.")  # Warns the user of missing details.
        sys.exit(1)  # Shuts down the script immediately to prevent empty login spam.

    delay_seconds = DELAY_HOURS * 3600  # Converts the hours into seconds for timer math.

    async with aiohttp.ClientSession() as session:  # Opens an ongoing, efficient web session.
        client = PetKitClient(USERNAME, PASSWORD, REGION, TIMEZONE, session=session)  # Logs into PetKit.
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Logged in successfully. {DELAY_HOURS}-Hour Delay active.")  # Confirms startup.

        # --- PERSISTENT MEMORY VARIABLES ---
        # These variables exist OUTSIDE the polling loop, meaning they survive the API's midnight data wipe.
        global_latest_exit = 0  # Stores the absolute highest exit timestamp ever seen by the script.
        global_latest_clean = 0  # Stores the absolute highest clean timestamp ever seen by the script.
        last_handled_level = 0  # Tracks the timestamp of the last visit we successfully flattened.
        last_handled_clean = 0  # Tracks the timestamp of the last visit we successfully cleaned.
        first_run = True  # A flag to trigger the startup calculations exactly once.

        while True:  # Starts the infinite 24/7 monitoring loop.
            try:  # Wraps the core logic to catch and log any sudden network drops without crashing.
                if DEBUGGING: print(
                    f"\n[{datetime.now().strftime('%H:%M:%S')}] Polling PetKit servers for fresh data...")  # Verbose poll log.
                await client.get_devices_data()  # Downloads the latest telemetry from the PetKit cloud.

                puramax = None  # Creates an empty variable to store your specific litter box data.
                for d in client.petkit_entities.values():  # Iterates through all devices on your account.
                    if str(getattr(d, 'id', '')) == "100034266" or 't4' in str(
                            getattr(d, 'type', '')).lower():  # Identifies the PuraMax.
                        puramax = d  # Assigns the device object to our variable.
                        break  # Stops searching.

                if not puramax:  # Failsafe if the API server temporarily drops the device list.
                    if DEBUGGING: print(
                        f"[DEBUG] Warning: PuraMax not found in this poll. Retrying later.")  # Verbose warning.
                    await asyncio.sleep(POLL_INTERVAL)  # Sleeps for 5 minutes before trying again.
                    continue  # Skips the rest of the loop.

                # --- 1. LIVE OCCUPANCY ---
                is_cat_in = False  # Defaults the occupancy flag to False.
                if hasattr(puramax, 'state') and getattr(puramax.state, 'pet_in_time',
                                                         0) > 0:  # Checks the live sensor data.
                    is_cat_in = True  # Sets to True if the cat is actively inside.

                # --- 2. HISTORICAL RECORD EXTRACTION (MIDNIGHT SAFE) ---
                records = getattr(puramax, 'device_records', [])  # Pulls the daily historical logs.
                if DEBUGGING and records:  # If debugging, print how many records were found today.
                    print(f"[DEBUG] Found {len(records)} history records for the current day. Analysing...")

                for record in records:  # Iterates through every recorded event in the daily list.
                    evt_type = getattr(record, 'enum_event_type',
                                       '').lower()  # Gets the type of event (pet_out, clean_over, etc).
                    rec_time = getattr(record, 'timestamp', 0)  # Gets the exact Unix timestamp of the event.

                    if DEBUGGING: print(
                        f"[DEBUG] Record -> Type: '{evt_type}' | Time: {rec_time}")  # Verbose event dump.

                    if 'pet_out' in evt_type:  # If the event is the cat leaving...
                        if rec_time > global_latest_exit:  # And the event is NEWER than our persistent memory...
                            global_latest_exit = rec_time  # Update persistent memory. (This ignores the midnight wipe!).
                    elif 'clean' in evt_type or 'reset' in evt_type or 'manual' in evt_type or 'auto' in evt_type:  # If the event is a clean...
                        if rec_time > global_latest_clean:  # And the clean is NEWER than our persistent memory...
                            global_latest_clean = rec_time  # Update persistent clean memory.

                current_time = time.time()  # Grabs the exact current Unix timestamp on the Raspberry Pi.

                if DEBUGGING:  # Prints the memory states if debugging is enabled.
                    print(f"[DATA] Live Occupancy: {is_cat_in}")
                    if global_latest_exit > 0: print(
                        f"[DATA] Memory Last Exit: {datetime.fromtimestamp(global_latest_exit).strftime('%Y-%m-%d %H:%M:%S')}")
                    if global_latest_clean > 0: print(
                        f"[DATA] Memory Last Clean: {datetime.fromtimestamp(global_latest_clean).strftime('%Y-%m-%d %H:%M:%S')}")

                # --- 3. STARTUP REQUIREMENT ---
                if first_run:  # Checks if this is the very first loop after starting the service.
                    if global_latest_exit > 0:  # Ensures there is a past visit in memory to calculate from.
                        if global_latest_clean > global_latest_exit:  # Requirement: Check if a clean happened AFTER the last visit.
                            print(
                                "[STARTUP] The tray has already been cleaned since the last visit. Standby mode active.")  # Logs the state.
                            last_handled_clean = global_latest_exit  # Tricks the memory into thinking it handled this visit already.
                            last_handled_level = global_latest_exit  # Prevents unnecessary levelling.
                        else:  # If the tray is dirty and waiting to cure...
                            time_since = current_time - global_latest_exit  # Calculates how long it has been since the cat left.

                            if time_since >= delay_seconds:  # Requirement: If more than the delay has elapsed...
                                elapsed_hours = int(time_since // 3600)
                                elapsed_minutes = int((time_since % 3600) // 60)
                                print(
                                    f"[STARTUP] Visit was {elapsed_hours}:{elapsed_minutes:02d} ago. Clean required immediately.")  # Log immediate action.
                            else:  # If less than the delay hours...
                                time_to_go = delay_seconds - time_since
                                hours_to_go = int(time_to_go // 3600)
                                minutes_to_go = int((time_to_go % 3600) // 60)
                                print(
                                    f"[STARTUP] Resuming countdown. ~{hours_to_go}:{minutes_to_go:02d} left until clean.")  # Logs resumption.
                    first_run = False  # Disables startup logic permanently for this session.

                # --- 4. ACTION LOGIC ---
                if is_cat_in:  # If the cat is currently inside.
                    if DEBUGGING: print("[ACTION] Cat is currently inside. Standing by.")  # Log standby.

                elif global_latest_exit > 0:  # If the cat is NOT inside, and we have a valid memory of them leaving.
                    # REQUIREMENT: Latest clean detection.
                    if global_latest_clean > global_latest_exit:  # If the last recorded action was a clean...
                        if last_handled_clean < global_latest_exit:  # And we haven't officially marked this bypass yet...
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] A server clean is logged AFTER the last visit. Bypassing commands.")  # Log bypass.
                            last_handled_clean = global_latest_exit  # Mark as handled to prevent timers.
                            last_handled_level = global_latest_exit  # Mark as handled to prevent flattening.

                        # THE HEARTBEAT: Prints exactly once an hour when in standby so you know it's alive.
                        elif int(current_time) % 3600 < POLL_INTERVAL:
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] Standby mode active. Tray is clean, waiting for cat visit.")

                    else:  # If the tray is dirty and needs attention...
                        time_since_exit = current_time - global_latest_exit  # Calculate exact seconds since exit.

                        # REQUIREMENT: Send Clean 8 hours after the last visit.
                        if global_latest_exit > last_handled_clean and time_since_exit >= delay_seconds:  # If timer is up...
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] {DELAY_HOURS}-hour curing time complete. Preparing CLEAN...")  # Log intent.
                            if await safety_check(client, puramax.id):  # REQUIREMENT: Strict live safety check.
                                success = await send_device_command(client, puramax.id, 'clean')  # Sends the command.
                                if success:  # If it didn't crash or get rejected...
                                    last_handled_clean = global_latest_exit  # Update memory so it doesn't clean again.
                                    last_handled_level = global_latest_exit  # Update level memory (it's already flat now).

                        # REQUIREMENT: Send Flatten on the next poll if a visit is detected.
                        elif global_latest_exit > last_handled_level:  # If we have a new visit that hasn't been levelled...
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] New un-levelled visit detected. Preparing FLATTEN...")  # Log intent.
                            if await safety_check(client, puramax.id):  # REQUIREMENT: Strict live safety check.
                                success = await send_device_command(client, puramax.id, 'flatten')  # Sends the command.
                                if success:  # If it didn't crash...
                                    last_handled_level = global_latest_exit  # Update memory so it doesn't flatten again.

                        # FLOW LOGGING: Constantly prints the countdown on every 5 min poll when curing.
                        elif global_latest_exit <= last_handled_level:  # If it is flat, and we are just waiting...
                            time_to_go = delay_seconds - time_since_exit
                            hours_to_go = int(time_to_go // 3600)
                            minutes_to_go = int((time_to_go % 3600) // 60)
                            print(
                                f"[{datetime.now().strftime('%H:%M:%S')}] Litter is currently curing. ~{hours_to_go}:{minutes_to_go:02d} remaining until clean.")  # Print flow update.

            except Exception as e:  # Global catch-all for any unexpected errors anywhere in the loop.
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Unexpected Loop Error: {e}")  # Prints the error summary.
                if DEBUGGING: traceback.print_exc()  # Prints the full technical map if debugging is on.

            await asyncio.sleep(
                POLL_INTERVAL)  # REQUIREMENT: Sleeps exactly 5 minutes (300s) before repeating the loop.


if __name__ == "__main__":  # Ensures the script only triggers if run directly.
    asyncio.run(main())  # Triggers the async loop to start the programme.