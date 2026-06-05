# app.py - API de Licenciamento (com horas)
import secrets
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATABASE = 'licenses.db'
ADMIN_KEY = "admin123"

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            license_key TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            last_used TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_machine_id ON licenses(machine_id)")
    conn.commit()
    conn.close()
    print("✅ Banco de dados inicializado!")

init_db()

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'message': 'License API is running!'})

@app.route('/api/generate-license', methods=['POST'])
def generate_license():
    data = request.json
    if data.get('admin_key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    days_valid = data.get('days_valid', 30)
    license_key = secrets.token_hex(16).upper()
    expires_at = (datetime.now() + timedelta(days=days_valid)).isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO licenses (license_key, machine_id, expires_at) VALUES (?, ?, ?)",
                   (license_key, '', expires_at))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'license_key': license_key, 'expires_at': expires_at})

@app.route('/api/validate', methods=['POST'])
def validate_license():
    data = request.json
    license_key = data.get('license_key')
    machine_id = data.get('machine_id')
    
    if not license_key or not machine_id:
        return jsonify({'valid': False, 'message': 'Missing parameters'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT license_key, machine_id, expires_at, is_active, created_at FROM licenses WHERE license_key = ?", (license_key,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return jsonify({'valid': False, 'message': 'License key not found'})
    
    stored_machine = result['machine_id']
    expires_at_str = result['expires_at']
    is_active = bool(result['is_active'])
    created_at = result['created_at']
    
    # Se a licença não tem Machine ID (não ativada ainda)
    if stored_machine == '':
        created_date = datetime.fromisoformat(created_at)
        original_expires = datetime.fromisoformat(expires_at_str)
        days_valid = (original_expires - created_date).days
        
        new_expires_at = datetime.now() + timedelta(days=days_valid)
        new_expires_at_str = new_expires_at.isoformat()
        
        cursor.execute("""
            UPDATE licenses 
            SET machine_id = ?, expires_at = ? 
            WHERE license_key = ?
        """, (machine_id, new_expires_at_str, license_key))
        conn.commit()
        conn.close()
        
        # Calcular dias e horas restantes
        delta = new_expires_at - datetime.now()
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        
        if days == 0:
            if hours == 0:
                message = f'License activated! {minutes}m left'
            else:
                message = f'License activated! {hours}h left'
        else:
            message = f'License activated! {days}d {hours}h left'
        
        return jsonify({
            'valid': True,
            'message': message,
            'days_left': days,
            'hours_left': hours,
            'expires_at': new_expires_at_str
        })
    
    # Verificações para licenças já vinculadas
    if stored_machine != machine_id:
        conn.close()
        return jsonify({'valid': False, 'message': 'License not for this computer'})
    
    if not is_active:
        conn.close()
        return jsonify({'valid': False, 'message': 'License revoked'})
    
    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at < datetime.now():
        conn.close()
        return jsonify({'valid': False, 'message': 'License expired'})
    
    cursor.execute("UPDATE licenses SET last_used = ? WHERE license_key = ?", (datetime.now().isoformat(), license_key))
    conn.commit()
    conn.close()
    
    # Calcular dias e horas restantes
    delta = expires_at - datetime.now()
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    
    if days == 0:
        if hours == 0:
            message = f'Valid license. {minutes}m left'
        else:
            message = f'Valid license. {hours}h left'
    else:
        message = f'Valid license. {days}d {hours}h left'
    
    return jsonify({
        'valid': True,
        'message': message,
        'days_left': days,
        'hours_left': hours,
        'expires_at': expires_at_str
    })

@app.route('/api/revoke', methods=['POST'])
def revoke_license():
    data = request.json
    if data.get('admin_key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    license_key = data.get('license_key')
    if not license_key:
        return jsonify({'error': 'license_key required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE licenses SET is_active = 0 WHERE license_key = ?", (license_key,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'License revoked'})

@app.route('/api/reactivate', methods=['POST'])
def reactivate_license():
    data = request.json
    if data.get('admin_key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    license_key = data.get('license_key')
    days_valid = data.get('days_valid', 30)
    
    if not license_key:
        return jsonify({'error': 'license_key required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT license_key FROM licenses WHERE license_key = ?", (license_key,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({'error': 'License not found'}), 404
    
    new_expires_at = (datetime.now() + timedelta(days=days_valid)).isoformat()
    
    cursor.execute("""
        UPDATE licenses 
        SET expires_at = ?, is_active = 1, last_used = ? 
        WHERE license_key = ?
    """, (new_expires_at, datetime.now().isoformat(), license_key))
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': f'License reactivated for {days_valid} days',
        'expires_at': new_expires_at,
        'days_valid': days_valid
    })

@app.route('/api/delete-license', methods=['POST'])
def delete_license():
    data = request.json
    if data.get('admin_key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    license_key = data.get('license_key')
    if not license_key:
        return jsonify({'error': 'license_key required'}), 400
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM licenses WHERE license_key = ?", (license_key,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'License deleted'})

@app.route('/api/list-licenses', methods=['POST'])
def list_licenses():
    data = request.json
    if data.get('admin_key') != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT license_key, machine_id, created_at, expires_at, is_active, last_used FROM licenses ORDER BY created_at DESC")
    results = cursor.fetchall()
    conn.close()
    
    licenses = []
    for row in results:
        licenses.append({
            'license_key': row[0],
            'machine_id': row[1] if row[1] else 'Not assigned',
            'created_at': row[2],
            'expires_at': row[3],
            'is_active': bool(row[4]),
            'last_used': row[5] if row[5] else 'Never'
        })
    
    return jsonify({'licenses': licenses})

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 License API iniciando...")
    print("📍 http://localhost:5000/api/health")
    print("🔑 Admin Key: admin123")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)