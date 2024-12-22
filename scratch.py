# Constants from main.py
NUM_BARS = 12                # Number of vertical bars in the color barcode
NUM_PALETTE_COLORS = 24      # Number of possible colors to choose from

def calculate_possibilities():
    """
    Calculate the total number of possible unique color combinations.
    
    With our current scheme:
    - Each bar can be one of 24 colors
    - We have 24 bars
    - Adjacent bars can be the same color
    """
    
    # Total possibilities = NUM_PALETTE_COLORS ^ NUM_BARS
    total = NUM_PALETTE_COLORS ** NUM_BARS
    
    # Format the number for readability
    formatted = format(total, ',')
    
    # Calculate the number of bits needed to represent this
    bits_needed = total.bit_length()
    
    print(f"Total possible unique combinations: {formatted}")
    print(f"In scientific notation: {total:.2e}")
    print(f"Bits needed to represent: {bits_needed}")
    print(f"\nFor comparison:")
    print(f"IPv4 addresses (2^32): {format(2**32, ',')}")
    print(f"IPv6 addresses (2^128): {format(2**128, ',')}")
    print(f"UUID v4 (2^122): {format(2**122, ',')}")

if __name__ == "__main__":
    calculate_possibilities()
