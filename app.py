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
    decode_url_to_colors
)
from pathlib import Path

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'temp_uploads'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

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
        
        # Generate color UUID
        palette = generate_color_palette(NUM_PALETTE_COLORS)
        perceptual_hash = phash_dhash_combo(img)
        uuid_colors, color_hash = generate_color_uuid_from_hash(img, palette, perceptual_hash)
        
        # Create and add color bar
        bar_img = create_color_bar(uuid_colors, img.width, img.height)
        bar_x = img.width - bar_img.width
        bar_y = img.height - bar_img.height
        
        new_img = img.copy()
        new_img.paste(bar_img, (bar_x, bar_y))
        
        # Save the image
        output_path = Path('images/output') / f"{color_hash}.jpg"
        new_img.save(output_path, format="JPEG", quality=JPG_QUALITY)
        
        # Verify immediately after saving
        w, h = new_img.size
        pixel_size = max(MIN_BAR_WIDTH, (min(w, h) * BAR_SIZE_PERCENT) // 100)
        bar_w = pixel_size * NUM_BARS
        bar_h = pixel_size * BAR_HEIGHT_MULTIPLIER
        bar_x = w - bar_w
        bar_y = h - bar_h

        # Detect colors
        detected = []
        for i in range(NUM_BARS):
            x_center = bar_x + (i * pixel_size) + (pixel_size // 2)
            y_center = bar_y + (bar_h // 2)
            
            # Sample multiple pixels for accuracy
            left_color = new_img.getpixel((x_center - 1, y_center))
            center_color = new_img.getpixel((x_center, y_center))
            right_color = new_img.getpixel((x_center + 1, y_center))
            
            avg_r = (left_color[0] + center_color[0] + right_color[0]) // 3
            avg_g = (left_color[1] + center_color[1] + right_color[1]) // 3
            avg_b = (left_color[2] + center_color[2] + right_color[2]) // 3
            
            detected.append((avg_r, avg_g, avg_b))

        # Compare with expected colors
        matches = []
        for exp, det in zip(uuid_colors, detected):
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

@app.route('/verify/<color_hash>')
def verify_hash(color_hash):
    try:
        # Find the image
        image_path = Path('images/output') / f"{color_hash}.jpg"
        if not image_path.exists():
            return jsonify({'error': 'Image not found'}), 404

        # Generate color palette
        palette = generate_color_palette(num_colors=NUM_PALETTE_COLORS)
        
        # Get expected colors from hash
        expected = decode_url_to_colors(color_hash, palette)
        
        # Read and verify image
        with Image.open(image_path) as pil_img:
            pil_img = pil_img.convert("RGB")
            w, h = pil_img.size
            pixel_size = max(MIN_BAR_WIDTH, (min(w, h) * BAR_SIZE_PERCENT) // 100)
            bar_w = pixel_size * NUM_BARS
            bar_h = pixel_size * BAR_HEIGHT_MULTIPLIER
            bar_x = w - bar_w
            bar_y = h - bar_h

            # Detect colors
            detected = []
            for i in range(NUM_BARS):
                x_center = bar_x + (i * pixel_size) + (pixel_size // 2)
                y_center = bar_y + (bar_h // 2)
                
                # Sample multiple pixels for better accuracy
                left_color = pil_img.getpixel((x_center - 1, y_center))
                center_color = pil_img.getpixel((x_center, y_center))
                right_color = pil_img.getpixel((x_center + 1, y_center))
                
                avg_r = (left_color[0] + center_color[0] + right_color[0]) // 3
                avg_g = (left_color[1] + center_color[1] + right_color[1]) // 3
                avg_b = (left_color[2] + center_color[2] + right_color[2]) // 3
                
                detected.append((avg_r, avg_g, avg_b))

            # Compare colors
            matches = []
            for exp, det in zip(expected, detected):
                diffs = [abs(e - d) for e, d in zip(exp, det)]
                matches.append(all(df <= COLOR_TOLERANCE for df in diffs))

            match_count = sum(matches)
            required_matches = int(len(matches) * REQUIRED_MATCH_PERCENT / 100)
            
            return jsonify({
                'success': match_count >= required_matches,
                'matches': match_count,
                'total': len(matches)
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True) 