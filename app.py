from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image
import os
from pathlib import Path
import sqlite3

from main import (
    init_db,
    store_image_hashes,
    verify_image_colors,
    generate_color_uuid_from_hash,
    phash_dhash_combo,
    create_color_bar,
    COLOR_TOLERANCE,
    REQUIRED_MATCH_PERCENT,
    JPG_QUALITY,
    decode_url_to_colors
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'temp_uploads'
app.config['OUTPUT_FOLDER'] = 'images/output'

# Ensure necessary directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Initialize the database on startup
init_db()

def upgrade_db():
    conn = sqlite3.connect('images.db')
    c = conn.cursor()
    try:
        c.execute('ALTER TABLE image_hashes ADD COLUMN query_count INTEGER DEFAULT 0')
        conn.commit()
    except sqlite3.OperationalError:
        # Column might already exist
        pass
    finally:
        conn.close()

@app.route('/')
def index():
    """Render the main HTML page."""
    return render_template('index.html')

@app.route('/images/output/<filename>')
def serve_image(filename):
    """Route to serve images from the output folder."""
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

@app.route('/process', methods=['POST'])
def process_image():
    """
    Handles encoding images. Accepts a single file, processes it by:
    1. Converting to RGB.
    2. Generating a combined hash (perceptual + difference).
    3. Generating deterministic color bars from hash.
    4. Storing the image + color bars + hash data.
    5. Returning JSON with success status and the new image URL.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file or file.filename.strip() == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        img = Image.open(file.stream).convert('RGB')
        perceptual_hash = phash_dhash_combo(img)
        uuid_colors, color_hash = generate_color_uuid_from_hash(img, None, perceptual_hash)

        # Store in DB
        store_image_hashes(perceptual_hash, color_hash)

        # Create color bar and paste onto the image
        bar_img = create_color_bar(uuid_colors, img.width, img.height)
        processed_img = img.copy()
        processed_img.paste(bar_img, (img.width - bar_img.width, img.height - bar_img.height))

        # Verify color bars (optional, but we do it to show success/fail in one step)
        detected_colors = verify_image_colors(processed_img)
        matches = []
        for expected, detected in zip(uuid_colors, detected_colors):
            diffs = [abs(e - d) for e, d in zip(expected, detected)]
            matches.append(all(df <= COLOR_TOLERANCE for df in diffs))

        match_count = sum(matches)
        required_matches = int(len(matches) * REQUIRED_MATCH_PERCENT / 100)

        # Save final result
        output_path = Path(app.config['OUTPUT_FOLDER']) / f"{color_hash}.jpg"
        processed_img.save(output_path, format="JPEG", quality=JPG_QUALITY)

        return jsonify({
            'success': True,
            'perceptual_hash': perceptual_hash,
            'color_hash': color_hash,
            'image_url': f'/images/output/{color_hash}.jpg',
            'verification': {
                'success': match_count >= required_matches,
                'matches': match_count,
                'total': len(matches),
                'required': required_matches
            }
        })
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/verify', methods=['POST'])
def verify_image():
    """
    Verifies an image that presumably has embedded color bars:
    1. Reads image and extracts color bars.
    2. Checks color similarity vs. expected from recomputed hash-based bars.
    3. Checks if there's a match in the database for (perceptual_hash, color_hash).
    4. Returns JSON with verification details.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file or file.filename.strip() == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        img = Image.open(file.stream).convert('RGB')

        # Recompute the same hash and color bars
        perceptual_hash = phash_dhash_combo(img)
        uuid_colors, color_hash = generate_color_uuid_from_hash(img, None, perceptual_hash)
        detected_colors = verify_image_colors(img)

        # Compare the bars
        matches = []
        for expected, detected in zip(uuid_colors, detected_colors):
            diffs = [abs(e - d) for e, d in zip(expected, detected)]
            matches.append(all(df <= COLOR_TOLERANCE for df in diffs))
        match_count = sum(matches)
        required_matches = int(len(matches) * REQUIRED_MATCH_PERCENT / 100)
        color_verification = (match_count >= required_matches)

        # Check DB for exact combination
        conn = sqlite3.connect('images.db')
        c = conn.cursor()
        c.execute(
            'SELECT user_id, created_at FROM image_hashes WHERE perceptual_hash = ? AND color_hash = ?',
            (perceptual_hash, color_hash)
        )
        exact_match = c.fetchone()
        conn.close()

        return jsonify({
            'color_verification': color_verification,
            'database_verification': (exact_match is not None),
            'verified': (exact_match is not None and color_verification),
            'perceptual_hash': perceptual_hash,
            'color_hash': color_hash,
            'matches': {
                'count': match_count,
                'required': required_matches,
                'total': len(matches),
                'details': [
                    {
                        'bar': i,
                        'expected': expected,
                        'detected': detected,
                        'matched': is_matched,
                        'diffs': [abs(e - d) for e, d in zip(expected, detected)]
                    }
                    for i, (expected, detected, is_matched) in 
                    enumerate(zip(uuid_colors, detected_colors, matches))
                ]
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/<color_hash>')
def show_image(color_hash):
    """Display details for a specific image by its color hash."""
    try:
        # Query the database for image details and increment counter
        conn = sqlite3.connect('images.db')
        c = conn.cursor()
        
        # First, increment the query counter
        c.execute('''
            UPDATE image_hashes 
            SET query_count = query_count + 1 
            WHERE color_hash = ?
        ''', (color_hash,))
        
        # Then fetch all details including the updated counter
        c.execute('''
            SELECT user_id, perceptual_hash, created_at, query_count 
            FROM image_hashes 
            WHERE color_hash = ?
        ''', (color_hash,))
        
        result = c.fetchone()
        conn.commit()
        conn.close()

        if not result:
            return "Image not found", 404

        user_id, perceptual_hash, created_at, query_count = result
        
        # Decode the color hash back to RGB values
        colors = decode_url_to_colors(color_hash)

        return render_template('photo.html',
            color_hash=color_hash,
            perceptual_hash=perceptual_hash,
            user_id=user_id,
            created_at=created_at,
            query_count=query_count,
            colors=colors
        )

    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/user/<int:user_id>')  # Sample URL: /user/1
def show_user_gallery(user_id):
    """Display all images created by a specific user."""
    try:
        conn = sqlite3.connect('images.db')
        c = conn.cursor()
        
        # Get all images for this user
        c.execute('''
            SELECT color_hash, perceptual_hash, created_at, query_count 
            FROM image_hashes 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        ''', (user_id,))
        
        results = c.fetchall()
        
        # Calculate user stats
        c.execute('''
            SELECT 
                COUNT(*) as total_images,
                SUM(query_count) as total_queries,
                MIN(created_at) as first_upload
            FROM image_hashes 
            WHERE user_id = ?
        ''', (user_id,))
        
        stats = c.fetchone()
        conn.close()

        # Process the results
        images = []
        for color_hash, perceptual_hash, created_at, query_count in results:
            colors = decode_url_to_colors(color_hash)
            images.append({
                'color_hash': color_hash,
                'perceptual_hash': perceptual_hash,
                'created_at': created_at,
                'query_count': query_count,
                'colors': colors
            })

        total_queries = stats[1] or 0
        first_upload = stats[2] or 'No uploads yet'

        return render_template('user.html',
            user_id=user_id,
            images=images,
            total_queries=total_queries,
            first_upload=first_upload
        )

    except Exception as e:
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    init_db()
    upgrade_db()
    app.run(debug=True) 