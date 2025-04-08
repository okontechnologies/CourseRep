from flask import Flask, render_template, request, session, send_from_directory
from flask_socketio import SocketIO, emit
import os
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'super-secret-key'  # Change this for production
socketio = SocketIO(app)

# Setup uploads folder
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Initialize database
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, points INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT, timestamp TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS courses (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, course_id INTEGER, filename TEXT)')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    if 'username' not in session:
        return render_template('index.html', username=None)
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT name FROM courses')
    courses = [row[0] for row in c.fetchall()]
    c.execute('SELECT f.filename, c.name FROM files f JOIN courses c ON f.course_id = c.id')
    files = c.fetchall()
    c.execute('SELECT username, points FROM users ORDER BY points DESC LIMIT 5')
    leaderboard = c.fetchall()
    conn.close()
    return render_template('index.html', username=session['username'], courses=courses, files=files, leaderboard=leaderboard)

@app.route('/set_username', methods=['POST'])
def set_username():
    username = request.form['username']
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username) VALUES (?)', (username,))
        session['username'] = username
    except sqlite3.IntegrityError:
        return "Username taken", 400
    conn.commit()
    conn.close()
    return "Username set", 200

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
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO courses (name) VALUES (?)', (course_name,))
    c.execute('SELECT id FROM courses WHERE name = ?', (course_name,))
    course_id = c.fetchone()[0]
    c.execute('INSERT INTO files (course_id, filename) VALUES (?, ?)', (course_id, filename))
    conn.commit()
    conn.close()
    socketio.emit('new_upload', {'course': course_name, 'filename': filename}, broadcast=True)
    return "File uploaded", 200

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('message')
def handle_message(data):
    if 'username' not in session:
        return
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT id FROM users WHERE username = ?', (session['username'],))
    user_id = c.fetchone()[0]
    timestamp = datetime.now().isoformat()
    c.execute('INSERT INTO messages (user_id, text, timestamp) VALUES (?, ?, ?)', (user_id, data, timestamp))
    c.execute('UPDATE users SET points = points + 1 WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    emit('message', {'username': session['username'], 'text': data, 'timestamp': timestamp}, broadcast=True)

if __name__ == '__main__':
    init_db()
    socketio.run(app, debug=True, host='0.0.0.0')