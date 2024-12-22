import os
import random
import time
import colorsys
import base64
import sqlite3
from datetime import datetime
from pathlib import Path
from PIL import Image
import numpy as np
from scipy.fftpack import dct

# ─────────────────────────────────────────────────────────
# Configuration / Constants
# ─────────────────────────────────────────────────────────
MAX_IMAGES_TO_PROCESS = 4   # Max number of images for batch processing
BAR_SIZE_PERCENT = 0.5      # Color bar size as percent of smallest dimension (can be a float)
COLOR_TOLERANCE = 40        # Tolerance for color-matching
JPG_QUALITY = 85            # JPEG compression quality
REQUIRED_MATCH_PERCENT = 75 # % of bars that must match
MIN_BAR_WIDTH = 5           # Minimum width (in px) for each color bar
BAR_HEIGHT_MULTIPLIER = 2   # Height is this times the bar width
NUM_BARS = 12               # Number of vertical bars in the color "barcode"
NUM_PALETTE_COLORS = 24     # If using color palettes, how many distinct colors

# Seed random for any globally used random calls.
random.seed(int(time.time()))

# ─────────────────────────────────────────────────────────
# Utility and Core Functions
# ─────────────────────────────────────────────────────────

def init_db():
    """
    Initialize SQLite database (images.db) and create tables if not exist.
    """
    conn = sqlite3.connect('images.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS image_hashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            perceptual_hash TEXT NOT NULL,
            color_hash TEXT NOT NULL,
            query_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(perceptual_hash, color_hash)
        )
    ''')
    conn.commit()
    conn.close()

def store_image_hashes(perceptual_hash, color_hash, user_id='anonymous'):
    """
    Insert the combination of perceptual_hash and color_hash into DB.
    Now accepts the Auth0 user ID directly.
    """
    conn = sqlite3.connect('images.db')
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO image_hashes (user_id, perceptual_hash, color_hash)
            VALUES (?, ?, ?)
        ''', (user_id, perceptual_hash, color_hash))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # This combination already exists
    finally:
        conn.close()

def phash_dhash_combo(image, hash_size=4):
    """
    Compute a combined 64-bit hash from:
    - Perceptual hash (pHash) using DCT.
    - Difference hash (dHash).
    Merges both bit strings into one 64-bit hex string.
    """
    # pHash
    gray_phash = image.convert('L').resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    phash_pixels = np.array(gray_phash.getdata(), dtype=float).reshape((hash_size, hash_size))
    dct_result = dct(dct(phash_pixels, axis=0), axis=1)
    dct_low = dct_result[:hash_size, :hash_size]
    # Exclude the first DC term from average
    avg = (dct_low[0, 1:].sum() + dct_low[1:, :].sum()) / (hash_size * hash_size - 1)
    phash_bits = ''.join(['1' if val >= avg else '0' for val in dct_low.flatten()[1:]])

    # dHash
    gray_dhash = image.convert('L').resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    dhash_pixels = np.array(gray_dhash.getdata(), dtype=float).reshape((hash_size, hash_size + 1))
    dhash_bits = ''.join([
        '1' if dhash_pixels[i, j] > dhash_pixels[i, j + 1] else '0'
        for i in range(hash_size)
        for j in range(hash_size)
    ])

    # Combine to 64 bits
    combined_bits = phash_bits + dhash_bits
    hashcode = hex(int(combined_bits, 2))[2:].rjust(16, '0')  # 16 hex chars = 64 bits
    return hashcode

def generate_color_uuid_from_hash(img, colors, hash_value):
    """
    Given an image, optional color array, and a hash (string),
    produce a deterministic list of RGB colors (NUM_BARS of them).
    Then encode them into a color_hash using base64.
    'colors' is not used here, but kept for API compatibility.
    """
    # Use hash as the seed for deterministic random
    seed_value = int(hash_value, 16)
    rng = random.Random(seed_value)

    # Generate color list
    uuid_colors = []
    for _ in range(NUM_BARS):
        r = rng.randint(0, 255)
        g = rng.randint(0, 255)
        b = rng.randint(0, 255)
        uuid_colors.append((r, g, b))

    # Base64-encode them
    color_hash = encode_uuid_for_url(uuid_colors)
    return uuid_colors, color_hash

def encode_uuid_for_url(uuid_colors):
    """
    Pack each RGB tuple into bytes and Base64 URL-safe encode them.
    Removes padding chars for shorter strings.
    """
    bytes_list = []
    for r, g, b in uuid_colors:
        bytes_list.extend([r, g, b])
    binary_data = bytes(bytes_list)
    url_safe = base64.urlsafe_b64encode(binary_data).decode('ascii').rstrip('=')
    return url_safe

def create_color_bar(uuid_colors, img_width, img_height):
    """
    Create a vertical color bar image from a list of colors (uuid_colors).
    Each bar is a set width and (width * BAR_HEIGHT_MULTIPLIER) in height.
    """
    num_bars = len(uuid_colors)
    bar_width = max(MIN_BAR_WIDTH, int((min(img_width, img_height) * BAR_SIZE_PERCENT) / 100))
    bar_height = bar_width * BAR_HEIGHT_MULTIPLIER
    total_width = bar_width * num_bars

    bar_img = Image.new("RGB", (total_width, bar_height), color=(255, 255, 255))
    for i, (r, g, b) in enumerate(uuid_colors):
        for x in range(bar_width):
            for y in range(bar_height):
                bar_img.putpixel((i * bar_width + x, y), (r, g, b))

    return bar_img

def verify_image_colors(img):
    """
    Given an image with color bars appended, read the bar region and
    extract the average color of each bar. Returns a list of (R,G,B).
    """
    w, h = img.size
    bar_width = max(MIN_BAR_WIDTH, int((min(w, h) * BAR_SIZE_PERCENT) / 100))
    bar_height = bar_width * BAR_HEIGHT_MULTIPLIER
    total_width = bar_width * NUM_BARS
    bar_x = w - total_width
    bar_y = h - bar_height

    detected = []
    for i in range(NUM_BARS):
        x_center = bar_x + i * bar_width + bar_width // 2
        y_center = bar_y + bar_height // 2

        # Sample center pixel and neighbors for a small smoothing
        left_color = img.getpixel((x_center - 1, y_center))
        center_color = img.getpixel((x_center, y_center))
        right_color = img.getpixel((x_center + 1, y_center))
        avg_r = (left_color[0] + center_color[0] + right_color[0]) // 3
        avg_g = (left_color[1] + center_color[1] + right_color[1]) // 3
        avg_b = (left_color[2] + center_color[2] + right_color[2]) // 3
        detected.append((avg_r, avg_g, avg_b))
    return detected

def decode_url_to_colors(url_uuid, palette=None):
    """
    Decode a base64 URL-safe string back into a list of RGB tuples.
    The palette parameter is not used but kept for API compatibility.
    """
    # Add back padding if needed
    padding_needed = len(url_uuid) % 4
    if padding_needed:
        url_uuid += '=' * (4 - padding_needed)

    # Decode base64 to bytes
    try:
        binary_data = base64.urlsafe_b64decode(url_uuid)
        
        # Convert bytes back to RGB tuples
        colors = []
        for i in range(0, len(binary_data), 3):
            r = binary_data[i]
            g = binary_data[i + 1]
            b = binary_data[i + 2]
            colors.append((r, g, b))
        
        return colors
    except Exception as e:
        print(f"Error decoding colors: {e}")
        return []
