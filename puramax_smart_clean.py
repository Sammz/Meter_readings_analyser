import asyncio
import time
import aiohttp
import os
import sys
import traceback
from pypetkitapi.client import PetKitClient
from pypetkitapi.command import DeviceAction, LBCommand, LitterCommand

# --- CONFIGURATION ---
# Extracts credentials from system environment variables
USERNAME = os.environ.get("PETKIT_USERNAME")
PASSWORD = os.environ.get("PETKIT_PASSWORD")
TIMEZONE = "Europe/London"
REGION = "United Kingdom"
DELAY_HOURS = 7
POLL_INTERVAL = 300  # Check status every 5 minutes


async def main():
    print("Start of programme")
    # Safety check to ensure variables are loaded
    if not USERNAME or not PASSWORD:
        print("ERROR: Environment variables PETKIT_USERNAME and PETKIT_PASSWORD are not set.")
        sys.exit(1)

    delay_seconds = DELAY_HOURS * 3600

    async with aiohttp.ClientSession() as session:
        client = PetKitClient(USERNAME, PASSWORD, REGION, TIMEZONE, session=session)
        print(f"--- Petkit Smart Delay Active: {DELAY_HOURS} Hour Window ---")

        last_exit_time = None
        needs_cleaning = False
        has_levelled = False

        while True:
            try:
                # 1. Fetch current status
                await client.get_devices_data()

                # Safely identify the PuraMax (T4) device without causing an integer error
                puramax = None
                for d in client.petkit_entities.values():
                    device_type = getattr(d, 'type', '').lower()
                    device_id_str = str(getattr(d, 'id', ''))
                    # Checks the device type, class name, or string version of the ID
                    if device_type == 't4' or 't4' in device_id_str or 't4' in d.__class__.__name__.lower():
                        puramax = d
                        break

                if not puramax:
                    await asyncio.sleep(10)
                    continue

                # Detect if cat is currently inside
                is_cat_present = getattr(puramax, 'is_cat_detected', False)
                if not is_cat_present and hasattr(puramax, 'state'):
                    is_cat_present = puramax.state.get('is_cat_detected', False)

                if is_cat_present:
                    # Logic: Cat is inside. Reset states.
                    if not needs_cleaning:
                        print("Visit detected. Litter will be levelled when cat leaves.")
                    else:
                        print("Cat returned before cleaning! Resetting timers and queueing new level command.")

                    needs_cleaning = True
                    has_levelled = False
                    last_exit_time = time.time()

                elif needs_cleaning:
                    # Logic: Cat has left. First, level the litter.
                    if not has_levelled:
                        print("Cat has left. Sending levelling command...")
                        try:
                            # Safely fetch the flatten command
                            flatten_cmd = getattr(LBCommand, "FLATTEN", getattr(LBCommand, "MAINTENANCE", None))
                            if flatten_cmd:
                                await client.send_api_request(
                                    puramax.id,
                                    LitterCommand.CONTROL_DEVICE,
                                    {DeviceAction.START: flatten_cmd}
                                )
                                print("Levelling command sent successfully.")
                            else:
                                print("Warning: Flatten command not found in the current pypetkitapi version.")
                        except Exception as e:
                            print(f"Error whilst sending level command: {e}")

                        has_levelled = True
                        # Reset the clock so it waits a full 7 hours AFTER levelling
                        last_exit_time = time.time()

                    elapsed = time.time() - last_exit_time

                    # Logic: Countdown to main clean
                    if elapsed >= delay_seconds:
                        print("Time target reached. Performing Final Safety Check...")

                        # --- THE FINAL SAFETY CHECK ---
                        await client.get_devices_data()

                        # Re-fetch the puramax object safely for the final check
                        puramax_refresh = None
                        for d in client.petkit_entities.values():
                            if getattr(d, 'id', None) == puramax.id:
                                puramax_refresh = d
                                break

                        final_check = False
                        if puramax_refresh:
                            final_check = getattr(puramax_refresh, 'is_cat_detected', False)
                            if not final_check and hasattr(puramax_refresh, 'state'):
                                final_check = puramax_refresh.state.get('is_cat_detected', False)

                        if final_check:
                            print("Safety Check FAILED: Cat walked in at the last second! Resetting timer.")
                            last_exit_time = time.time()
                            has_levelled = False  # Needs re-levelling when they leave again
                        else:
                            print("Safety Check PASSED: No cat detected. Sending clean command.")
                            await client.send_api_request(
                                puramax.id,
                                LitterCommand.CONTROL_DEVICE,
                                {DeviceAction.START: LBCommand.CLEANING}
                            )
                            needs_cleaning = False
                            print("Cleaning initiated. Standing by.")
                    else:
                        # Log status roughly every 60 mins
                        if int(elapsed) % 3600 < POLL_INTERVAL:
                            mins_left = int((delay_seconds - elapsed) / 60)
                            print(f"Litter curing... {mins_left} minutes until clean.")

            except Exception as e:
                # Cleanly prints the error stack trace without crashing the script
                traceback.print_exc()
                print(f"Connection error: {e}. Retrying in {POLL_INTERVAL}s...")

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())