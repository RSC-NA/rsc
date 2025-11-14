import random
import string


def random_string(length=8):
    """Generate a random alphanumeric string of given length."""

    letters_and_digits = string.ascii_letters
    return "".join(random.choice(letters_and_digits) for i in range(length))


def generate_discord_id():
    """Generate a random Discord ID (17-19 digit integer)."""
    return random.randint(10**16, 9223372036854775807)
