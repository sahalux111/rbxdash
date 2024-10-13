from flask import Flask, render_template, request, redirect, session, url_for
import pymysql
from datetime import datetime, timedelta
from threading import Thread
import time
from config import db_config
import pytz

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Define the IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Function to get the current time in IST
def current_time_ist():
    return datetime.now(IST)

# Database connection
def get_db_connection():
    return pymysql.connect(
        host=db_config['host'],
        user=db_config['user'],
        password=db_config['password'],
        database=db_config['db']
    )

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, role FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['role'] = user[1]
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

# Dashboard route
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch schedules of available users, adjusted for IST
    cursor.execute("""
        SELECT s.id, u.username, u.role, s.start_time, s.end_time, s.is_available 
        FROM schedules s
        JOIN users u ON s.user_id = u.id
        WHERE s.end_time > NOW() AND s.is_available = TRUE
    """)
    available_schedules = cursor.fetchall()

    # Fetch users currently on break, adjusted for IST
    cursor.execute("""
        SELECT b.id, u.username, u.role, b.start_time, b.end_time 
        FROM breaks b
        JOIN users u ON b.user_id = u.id
        WHERE b.end_time > NOW()
    """)
    breaks = cursor.fetchall()

    conn.close()

    return render_template('dashboard.html', available_schedules=available_schedules, breaks=breaks, role=session['role'])

# Set availability route
@app.route('/set_availability', methods=['GET', 'POST'])
def set_availability():
    if 'user_id' not in session or session['role'] not in ['doctor', 'qa']:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        
        # Convert to IST before saving to the database
        start_time = IST.localize(datetime.fromisoformat(start_time))
        end_time = IST.localize(datetime.fromisoformat(end_time))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO schedules (user_id, start_time, end_time) 
            VALUES (%s, %s, %s)
        """, (session['user_id'], start_time, end_time))
        conn.commit()
        conn.close()

        return redirect(url_for('dashboard'))
    return render_template('set_availability.html')

# Set break route
@app.route('/set_break', methods=['GET', 'POST'])
def set_break():
    if 'user_id' not in session or session['role'] not in ['doctor', 'qa']:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        duration = int(request.form['duration'])
        start_time = current_time_ist()
        end_time = start_time + timedelta(minutes=duration)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO breaks (user_id, start_time, end_time) 
            VALUES (%s, %s, %s)
        """, (session['user_id'], start_time, end_time))
        # Update the user's availability status to False during the break
        cursor.execute("""
            UPDATE schedules SET is_available = FALSE 
            WHERE user_id = %s AND end_time > NOW()
        """, (session['user_id'],))
        conn.commit()
        conn.close()

        return redirect(url_for('dashboard'))
    return render_template('set_break.html')

# Admin panel route for managing schedules and breaks
@app.route('/admin_panel', methods=['GET', 'POST'])
def admin_panel():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        record_id = request.form.get('record_id')
        record_type = request.form.get('record_type')

        # Admin can delete or update schedules or breaks
        if action == 'delete':
            if record_type == 'schedule':
                cursor.execute("DELETE FROM schedules WHERE id = %s", (record_id,))
            elif record_type == 'break':
                cursor.execute("DELETE FROM breaks WHERE id = %s", (record_id,))
        elif action == 'update':
            # Handle update logic here if needed.
            pass

        conn.commit()

    # Fetch all schedules and breaks for admin management
    cursor.execute("SELECT s.id, u.username, u.role, s.start_time, s.end_time FROM schedules s JOIN users u ON s.user_id = u.id")
    schedules = cursor.fetchall()
    cursor.execute("SELECT b.id, u.username, u.role, b.start_time, b.end_time FROM breaks b JOIN users u ON b.user_id = u.id")
    breaks = cursor.fetchall()

    conn.close()
    return render_template('admin_panel.html', schedules=schedules, breaks=breaks)

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Function to update user availability based on current time in IST
def update_user_statuses():
    while True:
        try:
            time.sleep(60)
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Set users as unavailable if their availability end time has passed
            cursor.execute("UPDATE schedules SET is_available = FALSE WHERE end_time < NOW()")
            
            # Update users' availability back to TRUE if their break has ended and they are still within their availability time
            cursor.execute("""
                UPDATE schedules s
                JOIN breaks b ON s.user_id = b.user_id
                SET s.is_available = TRUE
                WHERE b.end_time < NOW() AND s.end_time > NOW()
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error in updating user statuses: {e}")

# Start thread for updating user statuses
Thread(target=update_user_statuses).start()

if __name__ == '__main__':
    app.run(debug=True)

