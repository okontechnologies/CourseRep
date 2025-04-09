from flask import Flask, render_template, request, session, send_from_directory
from flask_socketio import SocketIO, emit
import os
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'super-secret-key'  # Change this for production security
socketio = SocketIO(app)

# Setup uploads folder for Render's persistent disk
UPLOAD_FOLDER = '/data/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)  # Create folder if it doesn’t exist

# Initialize SQLite database with tables for users, messages, courses, and files
def init_db():
    conn = sqlite3.connect('/data/database.db')  # Render persistent path
    c = conn.cursor()
    # Users table with points for gamification
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, points INTEGER DEFAULT 0)')
    # Messages table for chat history
    c.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, timestamp TEXT)')
    # Courses table for tagging uploads
    c.execute('CREATE TABLE IF NOT EXISTS courses (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    # Files table linking uploads to courses
    c.execute('CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, course_id INTEGER, filename TEXT)')
    conn.commit()
    conn.close()

# Home route: Render the main page with chat, uploads, and leaderboard
@app.route('/')
def index():
    if 'username' not in session:
        return render_template('index.html', username=None)
    conn = sqlite3.connect('/data/database.db')
    c = conn.cursor()
    c.execute('SELECT name FROM courses')
    courses = [row[0] for row in c.fetchall()]  # List of course names for dropdown
    c.execute('SELECT f.filename, c.name FROM files f JOIN courses c ON f.course_id = c.id')
    files = c.fetchall()  # List of files with course names
    c.execute('SELECT username, points FROM users ORDER BY points DESC LIMIT 5')
    leaderboard = c.fetchall()  # Top 5 users by points
    conn.close()
    return render_template('index.html', username=session['username'], courses=courses, files=files, leaderboard=leaderboard)

# Set username for session and store in DB
@app.route('/set_username', methods=['POST'])
def set_username():
    username = request.form['username']
    conn = sqlite3.connect('/data/database.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username) VALUES (?)', (username,))
        session['username'] = username
    except sqlite3.IntegrityError:
        return "Username taken", 400
    conn.commit()
    conn.close()
    return "Username set", 200

# Handle file uploads with course tagging
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'username' not in session:
        return "Login required", 403
    file = request.files['file']
    course_name = request.form['course']
    if file.filename == '' or not course_name:
        return "Missing file or course", 400
    if not file.filename.endswith(('.pdf', '.docx')) or file.content_length > 10 * 1024 * 1024:
        return "Invalid file type or size (>10MB)", 400
    filename = file.filename
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    conn = sqlite3.connect('/data/database.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO courses (name) VALUES (?)', (course_name,))
    c.execute('SELECT id FROM courses WHERE name = ?', (course_name,))
    course_id = c.fetchone()[0]
    c.execute('INSERT INTO files (course_id, filename) VALUES (?, ?)', (course_id, filename))
    conn.commit()
    conn.close()
    # Broadcast upload event for real-time notification
    socketio.emit('new_upload', {'course': course_name, 'filename': filename}, broadcast=True)
    return "File uploaded", 200

# Serve uploaded files for download
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Handle chat messages with points and real-time updates
@socketio.on('message')
def handle_message(data):
    if 'username' not in session:
        return
    conn = sqlite3.connect('/data/database.db')
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username = ?', (session['username'],))
    user_id = c.fetchone()[0]
    timestamp = datetime.now().isoformat()
    c.execute('INSERT INTO messages (user_id, text, timestamp) VALUES (?, ?, ?)', (user_id, data, timestamp))
    c.execute('UPDATE users SET points = points + 1 WHERE id = ?', (user_id,))  # Award point per message
    conn.commit()
    conn.close()
    # Broadcast message for real-time chat and notifications
    emit('message', {'username': session['username'], 'text': data, 'timestamp': timestamp}, broadcast=True)

if __name__ == '__main__':
    init_db()  # Initialize DB on startup
    socketio.run(app, debug=True, host='0.0.0.0')  # Run on all interfaces