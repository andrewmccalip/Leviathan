from flask import Flask, render_template, request, send_file, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image
import io
import os
from pathlib import Path
from main import (
    # Core functions
    generate_color_uuid_from_hash,
    verify_image_colors,
    create_color_bar,
    phash_dhash_combo,
    # Database functions
    init_db,
    store_image_hashes,
    # Constants
    COLOR_TOLERANCE,
    REQUIRED_MATCH_PERCENT,
    JPG_QUALITY
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'temp_uploads'
app.config['OUTPUT_FOLDER'] = 'images/output'

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Add this route to serve images
@app.route('/images/output/<filename>')
def serve_image(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

# Initialize database
init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        img = Image.open(file.stream).convert('RGB')
        perceptual_hash = phash_dhash_combo(img)
        uuid_colors, color_hash = generate_color_uuid_from_hash(img, None, perceptual_hash)
        
        # Store in database
        store_image_hashes(perceptual_hash, color_hash)
        
        # Create and save image with color bar
        bar_img = create_color_bar(uuid_colors, img.width, img.height)
        new_img = img.copy()
        new_img.paste(bar_img, (img.width - bar_img.width, img.height - bar_img.height))
        
        # Verify the image after adding the color bar
        detected = verify_image_colors(new_img)
        
        # Compare colors
        matches = []
        for exp, det in zip(uuid_colors, detected):
            diffs = [abs(e - d) for e, d in zip(exp, det)]
            matches.append(all(df <= COLOR_TOLERANCE for df in diffs))
        
        match_count = sum(matches)
        required_matches = int(len(matches) * REQUIRED_MATCH_PERCENT / 100)
        
        # Save the image
        output_path = Path('images/output') / f"{color_hash}.jpg"
        new_img.save(output_path, format="JPEG", quality=JPG_QUALITY)
        
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
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        img = Image.open(file.stream).convert('RGB')
        perceptual_hash = phash_dhash_combo(img)
        uuid_colors, color_hash = generate_color_uuid_from_hash(img, None, perceptual_hash)
        detected = verify_image_colors(img)
        
        # Compare colors
        matches = []
        for exp, det in zip(uuid_colors, detected):
            diffs = [abs(e - d) for e, d in zip(exp, det)]
            matches.append(all(df <= COLOR_TOLERANCE for df in diffs))
        
        match_count = sum(matches)
        required_matches = int(len(matches) * REQUIRED_MATCH_PERCENT / 100)
        
        # Check database
        import sqlite3
        conn = sqlite3.connect('images.db')
        c = conn.cursor()
        c.execute(
            'SELECT user_id, created_at FROM image_hashes WHERE perceptual_hash = ? AND color_hash = ?',
            (perceptual_hash, color_hash)
        )
        exact_match = c.fetchone()
        
        c.execute(
            'SELECT perceptual_hash, user_id, created_at FROM image_hashes WHERE color_hash = ?',
            (color_hash,)
        )
        color_matches = c.fetchall()
        conn.close()
        
        return jsonify({
            'color_verification': match_count >= required_matches,
            'database_verification': exact_match is not None,
            'verified': exact_match is not None and match_count >= required_matches,
            'perceptual_hash': perceptual_hash,
            'color_hash': color_hash,
            'matches': {
                'count': match_count,
                'required': required_matches,
                'total': len(matches),
                'details': [
                    {
                        'bar': i,
                        'expected': exp,
                        'detected': det,
                        'matched': match,
                        'diffs': [abs(e - d) for e, d in zip(exp, det)]
                    }
                    for i, (exp, det, match) in enumerate(zip(uuid_colors, detected, matches))
                ]
            }
        })
        
    except Exception as e:
        print(f"Error verifying image: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 