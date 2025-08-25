import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'discord'))
from modules.economy import Economy, CASINO_USER_ID

def main():
    econ = Economy()
    # Purge the old casino entry (user_id = 0)
    econ.remove_entry(0)
    # Add $1000 to the casino
    econ.add_money(CASINO_USER_ID, 1000)
    casino_entry = econ.get_entry(CASINO_USER_ID)
    print(f"Casino balance is now: ${casino_entry[1]}")

if __name__ == "__main__":
    main()
