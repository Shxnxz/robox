import cv2
import json
import time
import queue
import threading
import sys
import uuid
from pathlib import Path
from collections import Counter
from datetime import datetime
import numpy as np
import onnxruntime as ort

from billing import Bill, Detection, SceneScanner, load_config, COLORS

BASE = Path("/home/pi/plate_billing_trial")
CONFIG = load_config(BASE / "billing_config.json")

MODEL = BASE / "best.onnx"
OUTPUT = BASE / "checkout_output"
OUTPUT.mkdir(exist_ok=True)

CAMERA = "/dev/video0"
SIZE = 640

# Load ONNX model
session = ort.InferenceSession(
    str(MODEL),
    providers=["CPUExecutionProvider"]
)
input_name = session.get_inputs()[0].name

# Open camera
cap = cv2.VideoCapture(CAMERA, cv2.CAP_V4L2)

if not cap.isOpened():
    raise RuntimeError("Cannot open USB camera")

cap.set(
    cv2.CAP_PROP_FOURCC,
    cv2.VideoWriter_fourcc(*"MJPG")
)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

scanner = SceneScanner(CONFIG)
bill = Bill(CONFIG)
commands = queue.Queue()
last_image = None

def read_commands():
    for line in sys.stdin:
        commands.put(line.strip().lower())

threading.Thread(target=read_commands, daemon=True).start()


def detect(frame):
    h, w = frame.shape[:2]

    # Letterbox resize without changing aspect ratio
    scale = min(SIZE / w, SIZE / h)
    nw, nh = round(w * scale), round(h * scale)

    resized = cv2.resize(frame, (nw, nh))
    pad_x = (SIZE - nw) // 2
    pad_y = (SIZE - nh) // 2

    canvas = np.full((SIZE, SIZE, 3), 114, dtype=np.uint8)
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    tensor = np.transpose(rgb, (2, 0, 1))
    tensor = np.ascontiguousarray(
        tensor[None].astype(np.float32) / 255.0
    )

    output = session.run(None, {input_name: tensor})[0]

    # YOLO11 output: [1, 8, 8400]
    predictions = output[0].T

    boxes = []
    scores = []
    classes = []

    for row in predictions:
        cls = int(np.argmax(row[4:8]))
        conf = float(row[4 + cls])

        if conf < CONFIG["presence_confidence"]:
            continue

        cx, cy, bw, bh = row[:4]

        x1 = int((cx - bw / 2 - pad_x) / scale)
        y1 = int((cy - bh / 2 - pad_y) / scale)
        x2 = int((cx + bw / 2 - pad_x) / scale)
        y2 = int((cy + bh / 2 - pad_y) / scale)

        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))
        x2 = max(0, min(w, x2))
        y2 = max(0, min(h, y2))

        if x2 <= x1 or y2 <= y1:
            continue

        boxes.append([x1, y1, x2 - x1, y2 - y1])
        scores.append(conf)
        classes.append(cls)

    detections = []
    annotated = frame.copy()

    # Non-max suppression, separately for each color
    for cls in range(len(COLORS)):
        ids = [i for i, c in enumerate(classes) if c == cls]
        if not ids:
            continue

        picked = cv2.dnn.NMSBoxes(
            [boxes[i] for i in ids],
            [scores[i] for i in ids],
            CONFIG["presence_confidence"],
            0.45
        )

        for local_index in np.array(picked).reshape(-1):
            i = ids[int(local_index)]
            x, y, bw, bh = boxes[i]

            color = COLORS[cls]
            confidence = scores[i]

            detections.append(Detection(color, confidence))

            cv2.rectangle(
                annotated, (x, y),
                (x + bw, y + bh), (0, 255, 0), 2
            )
            cv2.putText(
                annotated,
                f"{color} {confidence:.2f}",
                (x, max(18, y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (0, 255, 0), 2
            )

    return detections, annotated


def show_bill():
    receipt = bill.receipt()
    print("\n========== BILL ==========")

    for line in receipt["lines"]:
        print(
            f"{line['color']:7} x{line['quantity']} "
            f"= {line['amount']} THB"
        )

    print("Subtotal:", receipt["subtotal"])
    print("Service:", receipt["service_charge"])
    print("VAT:", receipt["vat"])
    print("TOTAL:", receipt["total"], "THB")
    print("==========================\n")
    return receipt


print("PLATE CHECKOUT STARTED")
print("Show all plates to the camera.")

def speak_total(total, counts):
    """Announce the bill in English."""
    import subprocess
    from decimal import Decimal, ROUND_HALF_UP

    amount = Decimal(str(total)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    cents = int(amount * 100)
    baht, satang = divmod(cents, 100)

    # Announce plate counts and the final total.
    color_order = ["Pink", "Blue", "Green", "Yellow"]

    plate_count = sum(int(n) for n in counts.values())

    details = []
    for color in color_order:
        number = int(counts.get(color, 0))

        # Skip colors that were not detected.
        if number <= 0:
            continue

        unit = "plate" if number == 1 else "plates"
        details.append(f"{number} {color.lower()} {unit}")

    message = f"You have {plate_count} plates in total. "
    message += "That is " + ", ".join(details[:-1])
    message += ", and " + details[-1] + ". "
    message += f"Your total comes to {baht}.{satang:02d} baht."

    print("SPEAKING:", message, flush=True)

    audio_file = "/tmp/checkout_voice.mp3"

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
                "mpg123", "-q",
                "-a", "plughw:2,0",
                audio_file,
            ],
            check=True,
            timeout=45,
        )

        print("VOICE FINISHED", flush=True)

    except Exception as e:
        print("VOICE ERROR:", e, flush=True)


print("Commands: c=capture, t=total, f=finish, q=quit")
print("Waiting for stable detection...")

last_status = None
last_counts = None
frame_count = 0
auto_billed = False

try:
    while True:
        ok, frame = cap.read()
        if not ok:
            print("ERROR: Camera frame unavailable")
            break

        detections, annotated = detect(frame)

        # Print detected plates and provisional price
        if frame_count % 10 == 0:
            detected_counts = Counter(d.color for d in detections)

            print("\n--- LIVE DETECTION ---")
            for d in detections:
                print(f"Detected: {d.color}")

            print("VISIBLE COUNTS:", dict(detected_counts))

            if detected_counts:
                preview_bill = Bill(CONFIG)
                preview_bill.replace_counts(dict(detected_counts))
                print(
                    "ESTIMATED TOTAL:",
                    preview_bill.receipt()["total"],
                    "THB (not confirmed)"
                )
            else:
                print("No plates detected")

        counts = scanner.update(detections)
        frame_count += 1

        if scanner.status != last_status:
            print("STATUS:", scanner.status, flush=True)
            last_status = scanner.status

        if counts is not None:
            if counts != last_counts:
                print("\nREADY COUNTS:", counts, flush=True)
                preview = Bill(CONFIG)
                preview.replace_counts(counts)
                print(
                    "PREVIEW TOTAL:",
                    preview.receipt()["total"],
                    "THB",
                    flush=True
                )
                print("Type c + Enter to capture.")
                last_counts = counts

            # Automatically capture one stable scene
            if not auto_billed:
                bill.replace_counts(counts)

                cv2.imwrite(
                    str(OUTPUT / "captured.jpg"),
                    annotated
                )

                print("\n===== AUTO CHECKOUT =====", flush=True)
                print("Stable plates detected!", flush=True)
                print("COUNTS:", counts, flush=True)

                receipt = show_bill()
                speak_total(receipt["total"], counts)

                print("Bill displayed automatically.", flush=True)
                print("SCAN FINISHED - Camera will close.", flush=True)
                raise SystemExit(0)
                print("=========================\n", flush=True)

                auto_billed = True
        else:
            last_counts = None

        last_image = annotated

        # Save a preview occasionally
        if frame_count % 15 == 0:
            cv2.imwrite(
                str(OUTPUT / "latest.jpg"),
                annotated
            )

        while not commands.empty():
            cmd = commands.get_nowait()

            if cmd in ("c", "capture"):
                if bill.finalized:
                    print("Bill finalized. Restart for next customer.")
                elif scanner.ready_counts is None:
                    print("NOT READY: Hold all plates still.")
                else:
                    bill.replace_counts(scanner.ready_counts)
                    cv2.imwrite(
                        str(OUTPUT / "captured.jpg"),
                        last_image
                    )
                    print("CAPTURED!")
                    show_bill()

            elif cmd in ("t", "total"):
                show_bill()

            elif cmd in ("f", "finish"):
                if not bill.plates:
                    print("Capture plates first.")
                elif bill.finalized:
                    print("Already finalized.")
                else:
                    receipt = show_bill()
                    receipt["status"] = "final"
                    receipt["id"] = uuid.uuid4().hex
                    receipt["created_at"] = datetime.now().isoformat()

                    file = OUTPUT / f"receipt_{receipt['id']}.json"
                    file.write_text(
                        json.dumps(receipt, indent=2),
                        encoding="utf-8"
                    )
                    bill.finalized = True
                    print("RECEIPT SAVED:", file)

            elif cmd in ("q", "quit"):
                print("Stopping checkout.")
                sys.exit(0)

except KeyboardInterrupt:
    print("Stopped by user.")

finally:
    cap.release()
    print("Camera released.")
