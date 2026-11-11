#!/usr/bin/env python3

import json
import subprocess
import time
from pathlib import Path

from vosk import Model, KaldiRecognizer, SetLogLevel

import robot_menu as menu

BASE = Path(__file__).resolve().parent
MODEL_PATH = BASE / "vosk-model-en"
MIC_DEVICE = "plughw:2,0"

SetLogLevel(-1)
model = Model(str(MODEL_PATH))


def listen(timeout=None):
    """Listen to one spoken English phrase."""
    recognizer = KaldiRecognizer(model, 16000)

    cmd = [
        "arecord",
        "-D", MIC_DEVICE,
        "-f", "S16_LE",
        "-r", "16000",
        "-c", "1",
        "-t", "raw",
        "-q"
    ]

    mic = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    start = time.monotonic()

    try:
        while True:
            if timeout is not None:
                if time.monotonic() - start >= timeout:
                    return ""

            data = mic.stdout.read(4000)

            if not data:
                return ""

            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip().lower()

                if text:
                    print("HEARD:", text, flush=True)
                    return text

    finally:
        mic.terminate()
        mic.stdout.close()
        mic.wait()


def is_wake_word(text):
    return (
        "hey robot" in text
        or "hi robot" in text
        or "hello robot" in text
    )


def is_queue_command(text):
    words = set(text.split())

    action = "call" in words
    target = "queue" in words or "customer" in words

    return action and target


def announce_next_queue():
    last = menu.get_last_queue()
    last = int(last) if last is not None else 0

    number = last + 1

    if number > 999:
        menu.speak("The queue limit has been reached.")
        return

    message = menu.QUEUE_MESSAGE.format(n=number)

    print("ANNOUNCING:", message, flush=True)

    try:
        menu.speak(message)
    except Exception as e:
        print("VOICE ERROR:", e)
        return

    menu.save_queue(number)

    print("QUEUE SAVED:", number, flush=True)


def main():
    print("=" * 40)
    print("ROBOT VOICE COMMAND READY")
    print("Say: Hey Robot")
    print("Press Ctrl+C to stop")
    print("=" * 40)

    try:
        while True:
            heard = listen()

            if not is_wake_word(heard):
                continue

            print("ROBOT ACTIVATED")

            menu.speak("Yes, how can I help you?")

            print("LISTENING FOR COMMAND")

            command = listen(timeout=10)

            if "reset" in command.split() and (
                "queue" in command.split() or "que" in command.split()
            ):
                print("QUEUE RESET REQUESTED")

                menu.speak(
                    "Do you want to reset the queue? "
                    "Say yes to confirm."
                )

                print("WAITING FOR CONFIRMATION")
                answer = listen(timeout=8)

                if answer.strip() in ("yes", "yes please", "confirm", "yes confirm"):
                    menu.save_queue(0)
                    print("QUEUE RESET SUCCESSFUL")
                    menu.speak(
                        "Queue reset successfully. "
                        "The next queue is number one."
                    )
                else:
                    print("QUEUE RESET CANCELLED")
                    menu.speak("Queue reset cancelled.")

            elif is_queue_command(command):
                announce_next_queue()
            elif command:
                menu.speak(
                    "Sorry, I did not understand the command."
                )
            else:
                print("COMMAND TIMEOUT")

            print("WAITING FOR HEY ROBOT")

    except KeyboardInterrupt:
        print("\nVOICE COMMAND STOPPED")


if __name__ == "__main__":
    main()
