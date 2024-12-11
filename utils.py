# utils.py

def is_arabic(text):
    """
    Check if the given text contains Arabic characters.
    """
    arabic_range = range(0x0600, 0x06FF + 1)
    return any(ord(char) in arabic_range for char in text)
