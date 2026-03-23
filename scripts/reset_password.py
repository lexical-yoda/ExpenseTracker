"""
Reset the login password for Expense Manager.

Usage:
    python scripts/reset_password.py                    # Interactive prompt
    python scripts/reset_password.py -p newpassword     # Non-interactive

For Docker:
    docker exec -it expense-manager python scripts/reset_password.py
"""

import os
import sys
import json
import getpass
import argparse

try:
    import bcrypt
except ImportError:
    print("Error: bcrypt not installed. Run: pip install bcrypt")
    sys.exit(1)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
AUTH_FILE = os.path.join(DATA_DIR, 'auth.json')


def reset_password(new_password):
    if not os.path.exists(AUTH_FILE):
        print(f"Error: {AUTH_FILE} not found. Run the app first to complete setup.")
        sys.exit(1)

    with open(AUTH_FILE, 'r') as f:
        auth = json.load(f)

    password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    auth['password_hash'] = password_hash

    with open(AUTH_FILE, 'w') as f:
        json.dump(auth, f, indent=2)

    print(f"Password reset for user '{auth['username']}'.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Reset Expense Manager password")
    parser.add_argument('-p', '--password', help="New password (omit for interactive prompt)")
    args = parser.parse_args()

    if args.password:
        reset_password(args.password)
    else:
        pw = getpass.getpass("New password: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2:
            print("Passwords don't match.")
            sys.exit(1)
        if len(pw) < 6:
            print("Password must be at least 6 characters.")
            sys.exit(1)
        reset_password(pw)
