import asyncio
import time
import aiohttp
from pypetkitapi.client import PetKitClient
from pypetkitapi.command import DeviceAction, LBCommand, LitterCommand

# --- CONFIGURATION ---
USERNAME = "your_second_email@example.com"
PASSWORD = "your_password"
REGION = "EU"  # Changed to EU for the UK
DELAY_HOURS = 7
POLL_INTERVAL = 60  # Check status every 60 seconds


async def main():
    delay_seconds = DELAY_HOURS * 3600

    async with aiohttp.ClientSession() as session:
        client = PetKitClient(USERNAME, PASSWORD, REGION, session=session)
        print(f"--- Petkit Smart Delay Active: {DELAY_HOURS} Hour Window with Final Safety Check ---")

        last_exit_time = None
        needs_cleaning = False

        while True:
            try:
                # 1. Fetch current status
                await client.get_devices_data()
                puramax = next((d for d in client.petkit_entities.values() if "T4" in d.id), None)

                if not puramax:
                    await asyncio.sleep(10)
                    continue

                # Detect if cat is currently inside
                is_cat_present = getattr(puramax, 'is_cat_detected', False)
                if not is_cat_present and hasattr(puramax, 'state'):
                    is_cat_present = puramax.state.get('is_cat_detected', False)

                if is_cat_present:
                    # Logic: If cat is in, reset timer
                    if not needs_cleaning:
                        print("Visit detected. Countdown will begin when cat leaves.")
                    else:
                        print("Cat returned before cleaning. Resetting timer.")

                    needs_cleaning = True
                    last_exit_time = time.time()

                elif needs_cleaning:
                    elapsed = time.time() - last_exit_time

                    if elapsed >= delay_seconds:
                        print("Time target reached. Performing Final Safety Check...")

                        # --- THE FINAL SAFETY CHECK ---
                        # Fetch fresh data one last time and refresh the puramax object
                        await client.get_devices_data()
                        puramax_refresh = next((d for d in client.petkit_entities.values() if "T4" in d.id), None)

                        # Check the refreshed object
                        final_check = False
                        if puramax_refresh:
                            final_check = getattr(puramax_refresh, 'is_cat_detected', False)
                            if not final_check and hasattr(puramax_refresh, 'state'):
                                final_check = puramax_refresh.state.get('is_cat_detected', False)

                        if final_check:
                            print("Safety Check FAILED: Cat walked in at the last second! Resetting timer.")
                            last_exit_time = time.time()
                        else:
                            print("Safety Check PASSED: No cat detected. Sending Clean Command.")
                            await client.send_api_request(
                                puramax.id,
                                LitterCommand.CONTROL_DEVICE,
                                {DeviceAction.START: LBCommand.CLEANING}
                            )
                            needs_cleaning = False
                            print("Cleaning initiated. Standing by.")
                    else:
                        # Log status roughly every hour
                        if int(elapsed) % 3600 < POLL_INTERVAL:
                            mins_left = int((delay_seconds - elapsed) / 60)
                            print(f"Litter curing... {mins_left} minutes until clean.")

            except Exception as e:
                print(f"Connection error: {e}. Retrying in 60s...")

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())