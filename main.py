"""
Refactored main.py with a reliable approach for generating, annotating, and verifying images with color-based UUIDs.

Updates in this version:
  • We now use 'secrets' instead of 'random' for more secure/unpredictable randomization.
  • The verification criteria is stricter: at least 14 out of 16 squares must match.
  • The palette remains 24 colors, equally spaced around the HSV color wheel.
  • Bar size is 1% of the image’s smallest dimension, min 4px.

Usage:
  1) Place images to be processed in the "images" folder.
  2) Run this script; it will generate output in "images/output".
  3) It will then verify each processed image by reading the color bar at the bottom-right corner.
"""

import secrets
import colorsys
from pathlib import Path
from PIL import Image

def generate_color_palette(num_colors=24):
    """
    Generate a palette of 'num_colors' distinct colors evenly spaced around the HSV color wheel.
    Each color is (R, G, B) in [0, 255].
    """
    colors = []
    for i in range(num_colors):
        hue = i / num_colors
        saturation = 1.0
        value = 1.0
        rgb = colorsys.hsv_to_rgb(hue, saturation, value)
        color = tuple(round(c * 255) for c in rgb)
        colors.append(color)
    return colors

def generate_color_uuid(img, colors, num_squares=16):
    """
    Generate a color-based UUID of length 96 chars (16 squares × 6 hex digits each).
    Returns (uuid_colors, uuid_hex).
    """
    width, height = img.size
    uuid_colors = []
    prev_color = None

    for _ in range(num_squares):
        # Use secrets.randbelow to get a uniform random coordinate
        x = secrets.randbelow(width)
        y = secrets.randbelow(height)
        pix = img.getpixel((x, y))
        # Nearest color from palette, excluding the previous color to avoid duplicates
        available = [c for c in colors if c != prev_color]
        chosen = min(
            available,
            key=lambda c: (c[0] - pix[0])**2 + (c[1] - pix[1])**2 + (c[2] - pix[2])**2
        )
        uuid_colors.append(chosen)
        prev_color = chosen

    # Final pass to avoid identical adjacent squares
    for i in range(1, len(uuid_colors)):
        if uuid_colors[i] == uuid_colors[i - 1]:
            alt = [
                c for c in colors
                if c != uuid_colors[i - 1]
                and (i == len(uuid_colors) - 1 or c != uuid_colors[i + 1])
            ]
            if alt:
                # Replace with a secrets-based choice to reduce predictability
                uuid_colors[i] = secrets.choice(alt)
    
    # Encode to 96-char string
    hex_uuid = ""
    for (r, g, b) in uuid_colors:
        hex_uuid += f"{r:02x}{g:02x}{b:02x}"
    if len(hex_uuid) != num_squares * 6:
        raise ValueError("Resulting UUID must be 96 characters long.")
    return uuid_colors, hex_uuid

def create_color_bar(uuid_colors, img_width, img_height):
    """
    Creates a color bar (16 squares) in RGB mode.
    The bar is sized to 1% of the smallest dimension, min 4px high.
    """
    num_squares = len(uuid_colors)
    size_percent = 1
    pixel_size = max(4, (min(img_width, img_height) * size_percent) // 100)
    bar_width = pixel_size * num_squares
    bar_height = pixel_size

    # Use RGB to avoid any alpha channel issues
    bar_img = Image.new("RGB", (bar_width, bar_height), color=(255, 255, 255))

    # Draw each color square
    for i, (r, g, b) in enumerate(uuid_colors):
        for x in range(pixel_size):
            for y in range(pixel_size):
                bar_img.putpixel((i * pixel_size + x, y), (r, g, b))
    return bar_img

def process_images(folder_path="images"):
    """
    1) Clears/creates the 'output' folder.
    2) For each valid image in folder_path:
       - Generate a 16-color UUID (96 chars).
       - Draw the color bar on the bottom-right corner.
       - Save as a PNG with the UUID in the filename.
    """
    src_folder = Path(folder_path)
    out_folder = src_folder / "output"
    if out_folder.exists():
        for f in out_folder.glob("*"):
            f.unlink()
    else:
        out_folder.mkdir()

    # Now we use 24 colors in the palette
    palette = generate_color_palette(num_colors=24)

    for img_path in src_folder.glob("*"):
        if img_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".bmp"]:
            continue

        try:
            with Image.open(img_path) as pil_img:
                img_rgb = pil_img.convert("RGB")
                uuid_colors, uuid_str = generate_color_uuid(img_rgb, palette, 16)

                # Create the bar & place it at the bottom-right
                bar_img = create_color_bar(uuid_colors, img_rgb.width, img_rgb.height)
                bar_x = img_rgb.width - bar_img.width
                bar_y = img_rgb.height - bar_img.height

                new_img = img_rgb.copy()
                print(f"Placing bar at: (x={bar_x}, y={bar_y}), size=({bar_img.width}x{bar_img.height})")
                # Paste without a mask to avoid "bad transparency mask" errors:
                new_img.paste(bar_img, (bar_x, bar_y))

                out_name = f"{img_path.stem}_uuid_{uuid_str}.png"
                out_path = out_folder / out_name
                new_img.save(out_path, format="PNG")

                print(f"Processed: {img_path.name}")
                print(f"UUID: {uuid_str}\n")

        except Exception as exc:
            print(f"Error processing {img_path.name}: {exc}")

def verify_image_uuids(folder_path="images/output"):
    """
    Verifies each processed image by reading the color bar from the bottom-right corner
    and comparing with the UUID in the filename. Uses ±15 color tolerance.
    A match requires at least 14 out of 16 squares to meet that color tolerance.
    """
    src_folder = Path(folder_path)
    if not src_folder.exists():
        print(f"Folder not found: {folder_path}")
        return

    total_count = 0
    success_count = 0
    COLOR_TOLERANCE = 15

    for img_path in src_folder.glob("*"):
        if img_path.suffix.lower() not in [".png", ".jpg", ".jpeg", ".bmp"]:
            continue

        total_count += 1
        try:
            fn_parts = img_path.stem.split("_uuid_")
            if len(fn_parts) < 2:
                raise ValueError("Could not extract UUID from filename.")
            file_uuid = fn_parts[-1]
            if len(file_uuid) != 96:
                raise ValueError("Incorrect UUID length; must be 96 chars.")

            # Decode the expected colors
            expected = []
            for i in range(0, 96, 6):
                chunk = file_uuid[i:i + 6]
                r = int(chunk[0:2], 16)
                g = int(chunk[2:4], 16)
                b = int(chunk[4:6], 16)
                expected.append((r, g, b))
            if len(expected) != 16:
                raise ValueError("UUID must decode to 16 colors.")

            pil_img = Image.open(img_path).convert("RGB")
            w, h = pil_img.size
            size_percent = 1
            pixel_size = max(4, (min(w, h) * size_percent) // 100)
            bar_w = pixel_size * 16
            bar_h = pixel_size
            bar_x = w - bar_w
            bar_y = h - bar_h

            print(f"Reading bar from: (x={bar_x}, y={bar_y}), size=({bar_w}x{bar_h})")

            # Read each square
            detected = []
            for i in range(16):
                x0 = bar_x + i * pixel_size
                y0 = bar_y
                sq_pixels = []
                for xx in range(x0, x0 + pixel_size):
                    for yy in range(y0, y0 + pixel_size):
                        if 0 <= xx < w and 0 <= yy < h:
                            sq_pixels.append(pil_img.getpixel((xx, yy)))
                if not sq_pixels:
                    raise ValueError("No pixels found in bar region.")

                avg_r = sum(px[0] for px in sq_pixels) // len(sq_pixels)
                avg_g = sum(px[1] for px in sq_pixels) // len(sq_pixels)
                avg_b = sum(px[2] for px in sq_pixels) // len(sq_pixels)
                detected.append((avg_r, avg_g, avg_b))

            # Compare
            matches = []
            for i in range(16):
                exp = expected[i]
                det = detected[i]
                diffs = [abs(e - d) for e, d in zip(exp, det)]
                close_enough = all(df <= COLOR_TOLERANCE for df in diffs)
                matches.append(close_enough)

            match_count = sum(matches)
            # Now require at least 14 matches to pass
            if match_count >= 14:
                print(f"✅ Verified {img_path.name} - ({match_count}/16 matched)\n")
                success_count += 1
            else:
                print(f"❌ Mismatch {img_path.name} - ({match_count}/16 matched)")
                print("Color-by-color comparison:")
                for idx, (exp, det, ok) in enumerate(zip(expected, detected, matches)):
                    dr, dg, db = [abs(a - b) for a, b in zip(exp, det)]
                    print(
                        f"  Square {idx} -> Expected: {exp}, Detected: {det}, "
                        f"Diff: R:{dr} G:{dg} B:{db}, {'OK' if ok else 'FAIL'}"
                    )
                print()

        except Exception as exc:
            print(f"Error verifying {img_path.name}: {exc}")

    print("\nSummary:")
    print(f"Total Images: {total_count}")
    print(f"Successes: {success_count}")
    print(f"Failures: {total_count - success_count}")
    if total_count:
        print(f"Success Rate: {success_count/total_count*100:.2f}%")

if __name__ == "__main__":
    # 1) Generate & save images
    process_images("images")

    # 2) Verify them
    print("\nVerifying processed images...")
    verify_image_uuids("images/output")
