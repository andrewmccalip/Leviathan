# Image Color Barcode System

A web application that embeds unique, survivable color barcodes into images for tracking and verification purposes. The system adds a small color barcode to images that survives screenshots and modifications while enabling origin verification.

## 🎯 Key Features

- **Color Barcode Generation**: Creates a unique 12-color barcode for each image that serves as a visual fingerprint
- **Image Verification**: Verifies image authenticity by checking both the color pattern and database records
- **User Galleries**: Personal galleries for users to track their uploaded images
- **Usage Statistics**: Track how many times each image has been viewed/verified
- **Auth0 Integration**: Secure user authentication and management

## 🖼️ How It Works

1. When an image is uploaded, the system:
   - Generates a perceptual hash of the image
   - Creates a unique 12-color barcode based on the hash
   - Embeds the color barcode into the image
   - Stores the hash and color pattern in the database

2. When verifying an image:
   - Extracts and analyzes the embedded color barcode
   - Compares against expected color patterns
   - Checks database for matching hash combinations
   - Returns detailed verification results

3. The color barcode is designed to:
   - Survive screenshots and basic image modifications
   - Be visually unobtrusive
   - Provide reliable verification
   - Enable origin tracking

## 🚀 Getting Started

1. Clone the repository
2. Install dependencies: 