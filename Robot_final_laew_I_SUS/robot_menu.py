import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "queue_number.txt"

WELCOME_MESSAGE = (
    "Ee rah shy mah seh! "
    "Welcome to our sushi restaurant!"
)

QUEUE_MESSAGE = "Queue number {n}, your queue is ready."


def speak(message):
    """Speak English through the robot's USB speaker."""
    audio_file = "/tmp/robot_menu_voice.mp3"

    print("\nSPEAKING:", message, flush=True)

    try:
        subprocess.run(
            [
                "edge-tts",
                "--voice", "en-US-AriaNeural",
                "--rate=-10%",
                "--text", message,
                "--write-media", audio_file,
            ],
            check=True,
            timeout=45,
        )

        subprocess.run(
            [
                "mpg123",
                "-q",
                "-a", "plughw:2,0",
                audio_file,
            ],
            check=True,
            timeout=45,
        )

        print("VOICE FINISHED\n")
        return True

    except Exception as e:
        print("VOICE ERROR:", e)
        return False


def get_last_queue():
    try:
        number = int(STATE_FILE.read_text().strip())
        return number if 1 <= number <= 999 else 0
    except (OSError, ValueError):
        return 0


def save_queue(number):
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(str(number) + "\n")
    temporary.replace(STATE_FILE)


def call_queue():
    while True:
        last = get_last_queue()

        print("\n===== QUEUE CALL =====")
        print("Last queue:", last if last else "None")
        print("[1] Call next queue")
        print("[2] Repeat current queue")
        print("[3] Set next queue number")
        print("[4] Reset queue to 1")
        print("[0] Back to main menu")

        choice = input("Select: ").strip()

        if choice == "1":
            number = 1 if last >= 999 else last + 1
            message = QUEUE_MESSAGE.format(n=number)
            if speak(message):
                save_queue(number)

        elif choice == "2":
            if last:
                speak(QUEUE_MESSAGE.format(n=last))
            else:
                print("No queue called yet.")

        elif choice == "3":
            value = input("Enter next queue (1-999): ")
            try:
                number = int(value)
                if 1 <= number <= 999:
                    save_queue(number - 1)
                    print("Next queue:", number)
                else:
                    print("Number must be 1-999.")
            except ValueError:
                print("Invalid number.")

        elif choice == "4":
            save_queue(0)
            print("Queue reset. Next queue is 1.")

        elif choice == "0":
            return

        else:
            print("Invalid choice.")


def checkout():
    print("\nStarting plate detection and billing...\n")

    # Run the original working checkout program.
    try:
        subprocess.run(
            [sys.executable, str(BASE / "plate_checkout.py")],
            cwd=BASE,
            check=False,
        )
    except OSError as e:
        print("CHECKOUT ERROR:", e)


def scan_for_plate():
    """Use ROS2 in the existing Docker; billing is never triggered here."""
    print("\nScanning 360 degrees and approaching a plate...\n")
    script = BASE / "scan_plate_360.py"
    if not script.is_file():
        print("SCAN ERROR: scan_plate_360.py must be beside robot_menu.py")
        return
    try:
        # This menu normally runs on Raspberry Pi Host, while ROS2 runs in Docker.

        subprocess.run(
            ["docker", "exec", "-i", "confident_keller", "bash", "-lc",
             "source /opt/ros/humble/setup.bash; "
             "export ROS_DOMAIN_ID=61 ROS_LOCALHOST_ONLY=0 "
             "FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_udp.xml; "
             "python3 /root/share/scan_plate_360.py "
             "--model /root/plate_trial/model/best.pt "
             "--classes Pink,Blue,Green,Yellow --stop-gap 0.30"],
            check=False,
        )
    except (OSError, subprocess.CalledProcessError) as e:
        print("SCAN ERROR:", e)



def welcome_with_drift():
    """Run figure-eight and repeat Welcome until drift finishes."""
    import time

    command = [
        "docker", "exec", "-i", "confident_keller",
        "bash", "-lc",
        "source /opt/ros/humble/setup.bash && "
        "export ROS_DOMAIN_ID=61 && "
        "export ROS_LOCALHOST_ONLY=0 && "
        "export FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_udp.xml && "
        "python3 /root/share/rosmaster_m1_drift_8.py"
    ]

    print("STARTING WELCOME + DRIFT 8", flush=True)

    try:
        drift = subprocess.Popen(command)
    except OSError as e:
        print("DRIFT ERROR:", e)
        return

    time.sleep(0.5)

    try:
        while drift.poll() is None:
            if not speak(WELCOME_MESSAGE):
                print("VOICE ERROR: waiting for drift to finish")
                break

        code = drift.wait()
        print("DRIFT FINISHED (exit %s)" % code, flush=True)

    except KeyboardInterrupt:
        print("STOP REQUESTED", flush=True)
        raise


def main():
    while True:
        print("\n================================")
        print("   ROSMASTER M1 SUSHI ROBOT")
        print("================================")
        print("[1] Welcome Customer")
        print("[2] Detect Plates & Calculate Bill")
        print("[3] Call Queue Number")
        print("[4] Scan 360 & Approach Plate (No Billing)")
        print("[0] Exit")

        choice = input("\nSelect mode: ").strip()

        if choice == "1":
            welcome_with_drift()

        elif choice == "2":
            checkout()

        elif choice == "3":
            import subprocess
            import sys

            print("\n=== VOICE QUEUE COMMAND ===")
            print("Say: Hey Robot")
            print("Then: Call the next customer")
            print("Press Ctrl+C to return to menu\n")

            subprocess.run([
                sys.executable,
                str(BASE / "robot_voice_command.py")
            ])

        elif choice == "4":
            scan_for_plate()

        elif choice == "0":
            print("Goodbye!")
            break

        else:
            print("Invalid choice.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram stopped.")
