from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
from PIL import Image
import io
import os
from main import (
    # Import configuration constants
    NUM_BARS,
    NUM_PALETTE_COLORS,
    BAR_SIZE_PERCENT,
    MIN_BAR_WIDTH,
    BAR_HEIGHT_MULTIPLIER,
    COLOR_TOLERANCE,
    REQUIRED_MATCH_PERCENT,
    JPG_QUALITY,
    # Import functions
    generate_color_palette,
    generate_color_uuid_from_hash,
    create_color_bar,
    phash_dhash_combo,
    decode_url_to_colors,
    init_db,
    store_image_hashes,
    verify_image_uuids,
    encode_uuid_for_url,
    verify_image_colors  # Import the new function
)
from pathlib import Path
import sqlite3

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'temp_uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Initialize database when app starts
init_db()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
        # Create a PIL Image from the uploaded file
        img = Image.open(file.stream).convert('RGB')
        
        # Generate color UUID using same process as main.py
        perceptual_hash = phash_dhash_combo(img)
        uuid_colors, color_hash = generate_color_uuid_from_hash(img, None, perceptual_hash)
        
        # Store in database
        store_image_hashes(perceptual_hash, color_hash)
        
        # Create and add color bar
        bar_img = create_color_bar(uuid_colors, img.width, img.height)
        bar_x = img.width - bar_img.width
        bar_y = img.height - bar_img.height
        
        new_img = img.copy()
        new_img.paste(bar_img, (bar_x, bar_y))
        
        # Save the image
        output_path = Path('images/output') / f"{color_hash}.jpg"
        new_img.save(output_path, format="JPEG", quality=JPG_QUALITY)
        
        # Verify using the same verification function
        detected = verify_image_colors(new_img)
        expected = decode_url_to_colors(color_hash)
        
        # Compare with expected colors
        matches = []
        for exp, det in zip(expected, detected):
            diffs = [abs(e - d) for e, d in zip(exp, det)]
            matches.append(all(df <= COLOR_TOLERANCE for df in diffs))

        match_count = sum(matches)
        required_matches = int(len(matches) * REQUIRED_MATCH_PERCENT / 100)
        verification_success = match_count >= required_matches

        return jsonify({
            'perceptual_hash': perceptual_hash,
            'color_hash': color_hash,
            'image_url': f'/images/output/{color_hash}.jpg',
            'verification': {
                'success': verification_success,
                'matches': match_count,
                'total': len(matches),
                'required': required_matches
            }
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Add route to serve static files from images/output
@app.route('/images/output/<filename>')
def serve_image(filename):
    return send_file(f'images/output/{filename}')

@app.route('/verify', methods=['POST'])
def verify_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Read the image
        img = Image.open(file.stream).convert('RGB')
        
        # Calculate perceptual hash
        perceptual_hash = phash_dhash_combo(img)
        print(f"Perceptual Hash: {perceptual_hash}")
        
        # Generate colors using the same method as encode
        uuid_colors, color_hash = generate_color_uuid_from_hash(img, None, perceptual_hash)
        print(f"Generated Color Hash: {color_hash}")
        
        # Detect colors from the image for verification
        detected = verify_image_colors(img)
        print(f"Detected Colors: {detected}")
        
        # Look up in database
        conn = sqlite3.connect('images.db')
        c = conn.cursor()
        c.execute('''
            SELECT user_id, created_at 
            FROM image_hashes 
            WHERE perceptual_hash = ? AND color_hash = ?
        ''', (perceptual_hash, color_hash))
        exact_match = c.fetchone()
        
        # Then check for any matches with same color hash
        c.execute('''
            SELECT perceptual_hash, user_id, created_at 
            FROM image_hashes 
            WHERE color_hash = ?
        ''', (color_hash,))
        color_matches = c.fetchall()
        conn.close()

        # Compare expected vs detected colors
        matches = []
        for exp, det in zip(uuid_colors, detected):
            diffs = [abs(e - d) for e, d in zip(exp, det)]
            matches.append(all(df <= COLOR_TOLERANCE for df in diffs))
        
        match_count = sum(matches)
        required_matches = int(len(matches) * REQUIRED_MATCH_PERCENT / 100)
        
        response_data = {
            'color_verification': match_count >= required_matches,
            'database_verification': exact_match is not None,
            'verified': exact_match is not None and match_count >= required_matches,
            'perceptual_hash': perceptual_hash,
            'color_hash': color_hash,
            'user_id': exact_match[0] if exact_match else None,
            'created_at': exact_match[1] if exact_match else None,
            'similar_images': [
                {
                    'perceptual_hash': ph,
                    'user_id': uid,
                    'created_at': ca
                } for ph, uid, ca in color_matches
            ] if color_matches else [],
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
        }
        print(f"Response: {response_data}")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error verifying image: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 