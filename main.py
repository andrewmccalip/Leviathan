# Configuration Constants
MAX_IMAGES_TO_PROCESS = 100  # Maximum number of images to process
BAR_SIZE_PERCENT = 1         # Size of color bar as percentage of smallest image dimension
COLOR_TOLERANCE = 50         # Tolerance for color matching during verification
JPG_QUALITY = 50            # JPEG compression quality (0-100)
REQUIRED_MATCH_PERCENT = 87.5  # Percentage of squares that must match (14/16 = 87.5%)

"""
Refactored main.py to generate a purely color-based barcode (UUID) that does not depend on the image's pixels.
The barcode now comprises 16 random color squares, chosen from a 24-color HSV palette.

Key Points:
• The palette remains 24 colors, equally spaced around the HSV color wheel.
• Each of the 16 squares is chosen at random from the palette, avoiding adjacent duplicates.
• Verification still checks the bottom-right color bar's averages and compares to the UUID in the filename.
• A match requires at least 14 out of 16 squares to meet ±15 color tolerance.
• We continue to seed the "random" module with the current time for variability.
"""

import random
import time
import colorsys
from pathlib import Path
from PIL import Image

# Seed the random generator with current time
random.seed(int(time.time()))

def generate_color_palette(num_colors=24):
    """
    Generate a palette of 'num_colors' distinct colors
    evenly spaced around the HSV color wheel.
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
    Generate a 16-color UUID by randomly picking 16 colors from the palette.
    Adjacency duplicates are avoided. We encode them as a 96-character hex string
    (16 squares × 6 hex digits per color). Returns (uuid_colors, uuid_hex).
    """
    uuid_colors = []
    prev_color = None

    for _ in range(num_squares):
        # Choose a random color from the palette
        chosen = random.choice(colors)

        # Avoid identical repeats (adjacent squares)
        if chosen == prev_color:
            alt = [c for c in colors if c != chosen]
            if alt:
                chosen = random.choice(alt)

        uuid_colors.append(chosen)
        prev_color = chosen

    # Encode to 96-char hex string
    hex_uuid = ""
    for (r, g, b) in uuid_colors:
        hex_uuid += f"{r:02x}{g:02x}{b:02x}"
    if len(hex_uuid) != num_squares * 6:
        raise ValueError("Resulting UUID must be 96 characters long.")
    return uuid_colors, hex_uuid

def create_color_bar(uuid_colors, img_width, img_height):
    """
    Creates a color bar (16 squares) in RGB mode.
    The bar is sized according to BAR_SIZE_PERCENT of the smallest image dimension,
    with a minimum of 5px per square.
    """
    num_squares = len(uuid_colors)
    # Calculate pixel size based on percentage of smallest image dimension
    pixel_size = max(5, (min(img_width, img_height) * BAR_SIZE_PERCENT) // 100)
    bar_width = pixel_size * num_squares
    bar_height = pixel_size

    # Use RGB to avoid alpha-channel issues
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
       - Generate a 16-color UUID (96 chars) from random palette picks.
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

    palette = generate_color_palette(num_colors=24)
    processed_count = 0

    for img_path in src_folder.glob("*"):
        if processed_count >= MAX_IMAGES_TO_PROCESS:
            break
            
        # Skip non-image files
        if img_path.suffix.lower() not in [".jpg", ".jpeg", ".png", ".bmp"]:
            continue

        try:
            with Image.open(img_path) as pil_img:
                img_rgb = pil_img.convert("RGB")
                uuid_colors, uuid_str = generate_color_uuid(img_rgb, palette, 16)

                bar_img = create_color_bar(uuid_colors, img_rgb.width, img_rgb.height)
                bar_x = img_rgb.width - bar_img.width
                bar_y = img_rgb.height - bar_img.height

                new_img = img_rgb.copy()
                new_img.paste(bar_img, (bar_x, bar_y))

                # Preserve original file extension
                out_name = f"{img_path.stem}_uuid_{uuid_str}{img_path.suffix}"
                out_path = out_folder / out_name
                if out_path.suffix.lower() in ['.jpg', '.jpeg']:
                    new_img.save(out_path, format="JPEG", quality=JPG_QUALITY)
                else:
                    new_img.save(out_path, format="PNG")

                print(f"Processed: {img_path.name}")
                print(f"UUID: {uuid_str}\n")
                processed_count += 1

        except Exception as exc:
            print(f"Error processing {img_path.name}: {exc}")

def verify_image_uuids(folder_path="images/output"):
    """
    Verifies each processed image by reading the color bar from the bottom-right corner
    and comparing with the UUID in the filename. Uses ±15 color tolerance.
    A match requires at least 14 out of 16 squares to meet that tolerance.
    """
    src_folder = Path(folder_path)
    if not src_folder.exists():
        print(f"Folder not found: {folder_path}")
        return

    total_count = 0
    success_count = 0

    for img_path in src_folder.glob("*"):
        # Check only common image extensions
        if img_path.suffix.lower() not in [".png", ".jpg", ".jpeg", ".bmp"]:
            continue

        total_count += 1
        try:
            # Extract the 96-char UUID from the filename
            fn_parts = img_path.stem.split("_uuid_")
            if len(fn_parts) < 2:
                raise ValueError("Could not extract UUID from filename.")
            file_uuid = fn_parts[-1]
            if len(file_uuid) != 96:
                raise ValueError("Incorrect UUID length; must be 96 chars.")

            # Decode the expected colors from the UUID
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
            # Calculate the same pixel size as used in creation
            pixel_size = max(5, (min(w, h) * BAR_SIZE_PERCENT) // 100)
            bar_w = pixel_size * 16
            bar_h = pixel_size
            bar_x = w - bar_w
            bar_y = h - bar_h

            # Read each color square from that region
            detected = []
            for i in range(16):
                x0 = bar_x + i * pixel_size
                y0 = bar_y
                # Sample from center 60% of each square
                margin = int(pixel_size * 0.2)  # 20% margin from edges
                sq_pixels = []
                for xx in range(x0 + margin, x0 + pixel_size - margin):
                    for yy in range(y0 + margin, y0 + pixel_size - margin):
                        if 0 <= xx < w and 0 <= yy < h:
                            sq_pixels.append(pil_img.getpixel((xx, yy)))
                if not sq_pixels:
                    raise ValueError("No pixels found in bar region.")
                avg_r = sum(px[0] for px in sq_pixels) // len(sq_pixels)
                avg_g = sum(px[1] for px in sq_pixels) // len(sq_pixels)
                avg_b = sum(px[2] for px in sq_pixels) // len(sq_pixels)
                detected.append((avg_r, avg_g, avg_b))

            # Compare detected vs. expected
            matches = []
            for i in range(16):
                exp = expected[i]
                det = detected[i]
                diffs = [abs(e - d) for e, d in zip(exp, det)]
                close_enough = all(df <= COLOR_TOLERANCE for df in diffs)
                matches.append(close_enough)

            match_count = sum(matches)
            required_matches = int((len(matches) * REQUIRED_MATCH_PERCENT) / 100)
            if match_count >= required_matches:
                print(f"✅ Verified {img_path.name} - ({match_count}/{len(matches)} matched)\n")
                success_count += 1
            else:
                print(f"❌ Mismatch {img_path.name} - ({match_count}/{len(matches)} matched)")
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

    # Print summary
    print("\nSummary:")
    print(f"Total Images: {total_count}")
    print(f"Successes: {success_count}")
    print(f"Failures: {total_count - success_count}")
    if total_count:
        print(f"Success Rate: {success_count / total_count * 100:.2f}%")

if __name__ == "__main__":
    # 1) Generate & save images
    process_images("images")

    # 2) Verify them
    print("\nVerifying processed images...")
    verify_image_uuids("images/output")
