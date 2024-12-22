# Configuration Constants
MAX_IMAGES_TO_PROCESS = 4   # Maximum number of images to process
BAR_SIZE_PERCENT = 1          # Size of color bar as percentage of smallest image dimension
COLOR_TOLERANCE = 30          # Tolerance for color matching during verification
JPG_QUALITY = 85             # JPEG compression quality (0-100)
REQUIRED_MATCH_PERCENT = 87.5 # Percentage of bars that must match
MIN_BAR_WIDTH = 5            # Minimum width in pixels for each color bar
BAR_HEIGHT_MULTIPLIER = 2     # Height will be this times the width
NUM_BARS = 12                # Number of vertical bars in the color barcode
NUM_PALETTE_COLORS = 24      # Number of possible colors to choose from

import random
import time
import colorsys
from pathlib import Path
from PIL import Image
import cv2
import numpy as np
import base64

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

def generate_color_uuid(img, colors, num_bars=NUM_BARS):
    """
    Generate a 24-color UUID by randomly picking 24 colors from the palette.
    Adjacency duplicates are avoided. We encode them as a 144-character hex string
    (24 bars × 6 hex digits per color).
    """
    uuid_colors = []
    prev_color = None

    for _ in range(num_bars):
        # Choose a random color from the palette
        chosen = random.choice(colors)

        # Avoid identical repeats (adjacent bars)
        if chosen == prev_color:
            alt = [c for c in colors if c != chosen]
            if alt:
                chosen = random.choice(alt)

        uuid_colors.append(chosen)
        prev_color = chosen

    # Encode to 144-char hex string
    hex_uuid = ""
    for (r, g, b) in uuid_colors:
        hex_uuid += f"{r:02x}{g:02x}{b:02x}"
    if len(hex_uuid) != num_bars * 6:
        raise ValueError("Resulting UUID must be 144 characters long.")
    return uuid_colors, hex_uuid

def create_color_bar(uuid_colors, img_width, img_height):
    """
    Creates a vertical color barcode in RGB mode.
    Each bar's width is based on BAR_SIZE_PERCENT of the smallest image dimension,
    with a minimum of MIN_BAR_WIDTH pixels. Height is BAR_HEIGHT_MULTIPLIER times the width.
    """
    num_bars = len(uuid_colors)
    # Calculate bar width based on percentage of smallest image dimension
    bar_width = max(MIN_BAR_WIDTH, (min(img_width, img_height) * BAR_SIZE_PERCENT) // 100)
    bar_height = bar_width * BAR_HEIGHT_MULTIPLIER
    total_width = bar_width * num_bars

    # Use RGB to avoid alpha-channel issues
    bar_img = Image.new("RGB", (total_width, bar_height), color=(255, 255, 255))

    # Draw each color bar
    for i, (r, g, b) in enumerate(uuid_colors):
        for x in range(bar_width):
            for y in range(bar_height):
                bar_img.putpixel((i * bar_width + x, y), (r, g, b))
    return bar_img

def process_images(folder_path="images"):
    """
    Process images and save them with just the encoded ID as the filename.
    """
    src_folder = Path(folder_path)
    out_folder = src_folder / "output"
    if out_folder.exists():
        for f in out_folder.glob("*"):
            f.unlink()
    else:
        out_folder.mkdir()

    palette = generate_color_palette(num_colors=NUM_PALETTE_COLORS)
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
                uuid_colors, _ = generate_color_uuid(img_rgb, palette, NUM_BARS)
                
                # Generate compact URL-safe UUID
                url_uuid = encode_uuid_for_url(uuid_colors, palette)
                
                bar_img = create_color_bar(uuid_colors, img_rgb.width, img_rgb.height)
                bar_x = img_rgb.width - bar_img.width
                bar_y = img_rgb.height - bar_img.height

                new_img = img_rgb.copy()
                new_img.paste(bar_img, (bar_x, bar_y))

                # Use just the encoded ID as filename
                out_path = out_folder / f"{url_uuid}.jpg"
                new_img.save(out_path, format="JPEG", quality=JPG_QUALITY)

                print(f"Processed: {img_path.name}")
                print(f"Saved as: {url_uuid}.jpg")
                print(f"URL: yourdomain.com/{url_uuid}\n")
                processed_count += 1

        except Exception as exc:
            print(f"Error processing {img_path.name}: {exc}")

def verify_image_uuids(folder_path="images/output"):
    """
    Verifies each processed image using the filename as the ID.
    """
    src_folder = Path(folder_path)
    if not src_folder.exists():
        print(f"Folder not found: {folder_path}")
        return

    palette = generate_color_palette(num_colors=NUM_PALETTE_COLORS)
    total_count = 0
    success_count = 0

    for img_path in src_folder.glob("*.jpg"):
        total_count += 1
        try:
            # Extract the UUID from the filename (remove .jpg extension)
            file_uuid = img_path.stem
            
            # Decode the expected colors from the URL-safe UUID
            expected = decode_url_to_colors(file_uuid, palette)
            if len(expected) != NUM_BARS:
                raise ValueError(f"UUID must decode to {NUM_BARS} colors.")

            pil_img = Image.open(img_path).convert("RGB")
            w, h = pil_img.size
            # Calculate the same pixel size as used in creation
            pixel_size = max(MIN_BAR_WIDTH, (min(w, h) * BAR_SIZE_PERCENT) // 100)
            bar_w = pixel_size * NUM_BARS
            bar_h = pixel_size * BAR_HEIGHT_MULTIPLIER
            bar_x = w - bar_w
            bar_y = h - bar_h

            # Read each color bar from that region
            detected = []
            for i in range(NUM_BARS):
                x0 = bar_x + i * pixel_size
                y0 = bar_y
                # Sample from center strip of each bar
                margin_x = int(pixel_size * 0.3)  # 30% margin from sides
                margin_y = int(bar_h * 0.1)  # 10% margin from top/bottom
                sq_pixels = []
                for xx in range(x0 + margin_x, x0 + pixel_size - margin_x):
                    for yy in range(y0 + margin_y, y0 + bar_h - margin_y):
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
            for i in range(NUM_BARS):
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
                        f"  Bar {idx} -> Expected: {exp}, Detected: {det}, "
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

def create_montage_video(folder_path="images/output", fps=5, output_name="montage.mp4"):
    """
    Creates a video montage of all processed images.
    
    Args:
        folder_path (str): Path to folder containing processed images
        fps (int): Frames per second (images shown per second)
        output_name (str): Name of output video file
    """
    src_folder = Path(folder_path)
    if not src_folder.exists():
        print(f"Folder not found: {folder_path}")
        return

    # Get all image files
    image_files = [f for f in src_folder.glob("*") 
                   if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".bmp"]]
    
    if not image_files:
        print("No images found to process")
        return

    # Read first image to get dimensions
    first_img = cv2.imread(str(image_files[0]))
    height, width = first_img.shape[:2]
    
    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_name, fourcc, fps, (width, height))

    print(f"Creating video montage at {fps} FPS...")
    for img_path in image_files:
        try:
            # Read and ensure image is in BGR format for OpenCV
            img = cv2.imread(str(img_path))
            if img is None:
                continue
                
            # Resize if necessary
            if img.shape[:2] != (height, width):
                img = cv2.resize(img, (width, height))
                
            # Write frame
            out.write(img)
            
        except Exception as exc:
            print(f"Error processing {img_path.name}: {exc}")
            continue

    out.release()
    print(f"Video montage saved as {output_name}")

def encode_uuid_for_url(uuid_colors, color_palette):
    """
    Encode the UUID colors into a compact base64 URL-safe string.
    With 24 colors (5 bits needed), we can pack 24 colors into 15 bytes (120 bits).
    """
    # Convert colors to their palette indices (0-23)
    indices = [color_palette.index(color) for color in uuid_colors]
    
    # Pack indices into bytes (each index needs 5 bits)
    packed = 0
    for idx in indices:
        packed = (packed << 5) | idx
    
    # Convert to bytes
    bytes_needed = (NUM_BARS * 5 + 7) // 8  # Round up to nearest byte
    bytes_list = []
    for i in range(bytes_needed - 1, -1, -1):
        bytes_list.append((packed >> (i * 8)) & 0xFF)
    
    # Convert to URL-safe base64
    binary_data = bytes(bytes_list)
    url_safe = base64.urlsafe_b64encode(binary_data).decode('ascii').rstrip('=')
    return url_safe

def decode_url_to_colors(url_string, color_palette):
    """
    Decode a URL-safe string back into RGB colors.
    """
    # Add back padding if needed
    padding = 4 - (len(url_string) % 4)
    if padding != 4:
        url_string += '=' * padding
    
    # Decode base64 to bytes
    binary_data = base64.urlsafe_b64decode(url_string)
    
    # Convert bytes back to packed value
    packed = 0
    for byte in binary_data:
        packed = (packed << 8) | byte
    
    # Extract indices
    indices = []
    mask = (1 << 5) - 1  # 5-bit mask
    for _ in range(NUM_BARS):
        indices.insert(0, packed & mask)
        packed >>= 5
    
    # Convert indices back to RGB colors
    return [color_palette[i] for i in indices]

if __name__ == "__main__":
    # 1) Generate & save images
    process_images("images")

    # 2) Verify them
    print("\nVerifying processed images...")
    verify_image_uuids("images/output")
    
    # # 3) Create video montage
    # print("\nCreating video montage...")
    # create_montage_video(fps=3)
