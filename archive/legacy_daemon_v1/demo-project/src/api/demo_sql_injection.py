import sqlite3

def get_user_by_id(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    # VULNERABLE: SEC003 SQL Injection (Inline for demo regex)
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    # cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

    # ALSO VULNERABLE: Direct f-string in execute
    cursor.execute("UPDATE users SET active = 1 WHERE id = ?", (user_id,))
    
    return cursor.fetchall()
