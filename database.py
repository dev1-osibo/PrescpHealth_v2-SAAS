import psycopg2
from psycopg2 import sql
from datetime import datetime
import uuid
import os
import sqlite3

def init_db():
    """Initialize the database and create tables if they don't exist."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            
            # The schema is the same for both SQLite and PostgreSQL
            # Create tables if they don't exist
            c.execute('''
            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY,
                name TEXT,
                dob TEXT,
                gender TEXT,
                created_at TEXT
            )
            ''')
            
            c.execute('''
            CREATE TABLE IF NOT EXISTS measurements (
                id TEXT PRIMARY KEY,
                patient_id TEXT,
                date TEXT,
                age INTEGER,
                bmi REAL,
                systolic INTEGER,
                diastolic INTEGER,
                glucose REAL,
                cholesterol REAL,
                smoking TEXT,
                has_hypertension INTEGER,
                has_diabetes INTEGER,
                has_heart_disease INTEGER,
                FOREIGN KEY (patient_id) REFERENCES patients (id)
            )
            ''')
            
            c.execute('''
            CREATE TABLE IF NOT EXISTS risk_scores (
                id TEXT PRIMARY KEY,
                patient_id TEXT,
                measurement_id TEXT,
                date TEXT,
                model_name TEXT,
                model_version TEXT,
                score REAL,
                confidence REAL,
                FOREIGN KEY (patient_id) REFERENCES patients (id),
                FOREIGN KEY (measurement_id) REFERENCES measurements (id)
            )
            ''')
            
            c.execute('''
            CREATE TABLE IF NOT EXISTS recommendations (
                id TEXT PRIMARY KEY,
                patient_id TEXT,
                measurement_id TEXT,
                date TEXT,
                recommendation TEXT,
                source TEXT,
                FOREIGN KEY (patient_id) REFERENCES patients (id),
                FOREIGN KEY (measurement_id) REFERENCES measurements (id)
            )
            ''')
            
            conn.commit()
            conn.close()
            print("Database initialization successful")
            return True
        
        except Exception as e:
            print(f"Database initialization attempt {retry_count + 1} failed: {str(e)}")
            retry_count += 1
            
            if retry_count < max_retries:
                import time
                time.sleep(2)  # Wait 2 seconds before retry
    
    print(f"All database initialization attempts failed after {max_retries} retries")
    return False

def get_db_connection():
    """
    Get a connection to the database.
    Works both in Replit environment (PostgreSQL) and locally (SQLite).
    Implements retry logic for PostgreSQL connections.
    """
    # First, try to use PostgreSQL if available (Replit environment)
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        # Try to connect to PostgreSQL with retry logic
        max_retries = 3
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                # Connect to PostgreSQL with keepalives to prevent connection timeouts
                connection = psycopg2.connect(
                    database_url,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5
                )
                # Set autocommit to True to avoid transaction issues
                connection.autocommit = True
                return connection
            except psycopg2.OperationalError as e:
                last_error = e
                retry_count += 1
                print(f"PostgreSQL connection attempt {retry_count} failed: {e}")
                if retry_count < max_retries:
                    import time
                    time.sleep(1)  # Wait 1 second before retry
            except Exception as e:
                print(f"Unexpected PostgreSQL error: {e}")
                break
        
        # If we reach here, all retries failed
        print(f"All PostgreSQL connection attempts failed: {last_error}")
        print("Falling back to SQLite...")
    
    # Fall back to SQLite for local development
    print("Using SQLite database for local development")
    return sqlite3.connect('prescphealth.db')

# Use this to get the appropriate placeholder for SQL queries
# PostgreSQL uses %s, SQLite uses ?
def get_placeholder():
    """Return the appropriate placeholder for the current database type"""
    if os.environ.get('DATABASE_URL'):
        return "%s"  # PostgreSQL
    else:
        return "?"   # SQLite

def save_patient(patient_data):
    """Save a patient to the database."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the appropriate placeholder
    placeholder = get_placeholder()
    
    # Generate ID if not provided (for new patients)
    patient_id = patient_data.get("id", str(uuid.uuid4()))
    
    # Check if patient already exists
    c.execute(f"SELECT id FROM patients WHERE id = {placeholder}", (patient_id,))
    result = c.fetchone()
    
    if result:
        # Update existing patient
        c.execute(f'''
        UPDATE patients 
        SET name = {placeholder}, dob = {placeholder}, gender = {placeholder}, created_at = {placeholder}
        WHERE id = {placeholder}
        ''', (
            patient_data["name"], 
            patient_data["dob"], 
            patient_data["gender"], 
            patient_data.get("created_at", datetime.now().isoformat()),
            patient_id
        ))
    else:
        # Insert new patient
        c.execute(f'''
        INSERT INTO patients (id, name, dob, gender, created_at)
        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
        ''', (
            patient_id, 
            patient_data["name"], 
            patient_data["dob"], 
            patient_data["gender"],
            patient_data.get("created_at", datetime.now().isoformat())
        ))
    
    conn.commit()
    conn.close()
    return patient_id

def save_measurement(measurement_data):
    """Save a measurement to the database."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the appropriate placeholder
    placeholder = get_placeholder()
    
    measurement_id = measurement_data.get("id", str(uuid.uuid4()))
    
    # Check if measurement already exists
    c.execute(f"SELECT id FROM measurements WHERE id = {placeholder}", (measurement_id,))
    result = c.fetchone()
    
    if result:
        # Update existing measurement
        c.execute(f'''
        UPDATE measurements 
        SET patient_id = {placeholder}, date = {placeholder}, age = {placeholder}, bmi = {placeholder}, systolic = {placeholder}, 
            diastolic = {placeholder}, glucose = {placeholder}, cholesterol = {placeholder}, smoking = {placeholder},
            has_hypertension = {placeholder}, has_diabetes = {placeholder}, has_heart_disease = {placeholder}
        WHERE id = {placeholder}
        ''', (
            measurement_data["patient_id"], 
            measurement_data.get("date", datetime.now().isoformat()), 
            measurement_data["age"], 
            measurement_data["bmi"],
            measurement_data["systolic"],
            measurement_data["diastolic"],
            measurement_data["glucose"],
            measurement_data["cholesterol"],
            measurement_data["smoking"],
            measurement_data["has_hypertension"],
            measurement_data["has_diabetes"],
            measurement_data["has_heart_disease"],
            measurement_id
        ))
    else:
        # Insert new measurement
        placeholders = ", ".join([placeholder] * 13)
        c.execute(f'''
        INSERT INTO measurements (
            id, patient_id, date, age, bmi, systolic, 
            diastolic, glucose, cholesterol, smoking,
            has_hypertension, has_diabetes, has_heart_disease
        )
        VALUES ({placeholders})
        ''', (
            measurement_id,
            measurement_data["patient_id"], 
            measurement_data.get("date", datetime.now().isoformat()), 
            measurement_data["age"], 
            measurement_data["bmi"],
            measurement_data["systolic"],
            measurement_data["diastolic"],
            measurement_data["glucose"],
            measurement_data["cholesterol"],
            measurement_data["smoking"],
            measurement_data["has_hypertension"],
            measurement_data["has_diabetes"],
            measurement_data["has_heart_disease"]
        ))
    
    conn.commit()
    conn.close()
    return measurement_id

def save_risk_score(risk_data):
    """Save a risk score to the database."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the appropriate placeholder
    placeholder = get_placeholder()
    
    risk_id = risk_data.get("id", str(uuid.uuid4()))
    
    # Check if risk score already exists
    c.execute(f"SELECT id FROM risk_scores WHERE id = {placeholder}", (risk_id,))
    result = c.fetchone()
    
    if result:
        # Update existing risk score
        c.execute(f'''
        UPDATE risk_scores 
        SET patient_id = {placeholder}, measurement_id = {placeholder}, date = {placeholder}, 
            model_name = {placeholder}, model_version = {placeholder}, score = {placeholder}, confidence = {placeholder}
        WHERE id = {placeholder}
        ''', (
            risk_data["patient_id"], 
            risk_data["measurement_id"], 
            risk_data.get("date", datetime.now().isoformat()), 
            risk_data["model_name"],
            risk_data["model_version"],
            risk_data["score"],
            risk_data["confidence"],
            risk_id
        ))
    else:
        # Insert new risk score
        placeholders = ", ".join([placeholder] * 8)
        c.execute(f'''
        INSERT INTO risk_scores (
            id, patient_id, measurement_id, date, 
            model_name, model_version, score, confidence
        )
        VALUES ({placeholders})
        ''', (
            risk_id,
            risk_data["patient_id"], 
            risk_data["measurement_id"], 
            risk_data.get("date", datetime.now().isoformat()), 
            risk_data["model_name"],
            risk_data["model_version"],
            risk_data["score"],
            risk_data["confidence"]
        ))
    
    conn.commit()
    conn.close()
    return risk_id

def save_recommendation(recommendation_data):
    """Save a recommendation to the database."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the appropriate placeholder
    placeholder = get_placeholder()
    
    recommendation_id = recommendation_data.get("id", str(uuid.uuid4()))
    
    # Check if recommendation already exists
    c.execute(f"SELECT id FROM recommendations WHERE id = {placeholder}", (recommendation_id,))
    result = c.fetchone()
    
    if result:
        # Update existing recommendation
        c.execute(f'''
        UPDATE recommendations 
        SET patient_id = {placeholder}, measurement_id = {placeholder}, date = {placeholder}, 
            recommendation = {placeholder}, source = {placeholder}
        WHERE id = {placeholder}
        ''', (
            recommendation_data["patient_id"], 
            recommendation_data["measurement_id"], 
            recommendation_data.get("date", datetime.now().isoformat()), 
            recommendation_data["recommendation"],
            recommendation_data["source"],
            recommendation_id
        ))
    else:
        # Insert new recommendation
        placeholders = ", ".join([placeholder] * 6)
        c.execute(f'''
        INSERT INTO recommendations (
            id, patient_id, measurement_id, date, 
            recommendation, source
        )
        VALUES ({placeholders})
        ''', (
            recommendation_id,
            recommendation_data["patient_id"], 
            recommendation_data["measurement_id"], 
            recommendation_data.get("date", datetime.now().isoformat()), 
            recommendation_data["recommendation"],
            recommendation_data["source"]
        ))
    
    conn.commit()
    conn.close()
    return recommendation_id

def get_patients():
    """Get all patients from the database."""
    max_retries = 3
    retry_count = 0
    last_error = None
    
    while retry_count < max_retries:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            
            c.execute("SELECT * FROM patients ORDER BY name")
            patients = c.fetchall()
            
            patient_list = []
            for p in patients:
                patient_list.append({
                    "id": p[0],
                    "name": p[1],
                    "dob": p[2],
                    "gender": p[3],
                    "created_at": p[4]
                })
            
            conn.close()
            return patient_list
            
        except Exception as e:
            last_error = str(e)
            print(f"Database query attempt {retry_count + 1} failed: {last_error}")
            retry_count += 1
            
            if retry_count < max_retries:
                import time
                time.sleep(2)  # Wait 2 seconds before retry
    
    print(f"All attempts to get patients failed after {max_retries} retries")
    # Return empty list if all attempts fail
    return []

def get_patient_by_id(patient_id):
    """Get a patient by ID."""
    max_retries = 3
    retry_count = 0
    last_error = None
    
    while retry_count < max_retries:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            
            # Get the appropriate placeholder
            placeholder = get_placeholder()
            
            c.execute(f"SELECT * FROM patients WHERE id = {placeholder}", (patient_id,))
            p = c.fetchone()
            
            if not p:
                conn.close()
                return None
            
            patient = {
                "id": p[0],
                "name": p[1],
                "dob": p[2],
                "gender": p[3],
                "created_at": p[4]
            }
            
            conn.close()
            return patient
            
        except Exception as e:
            last_error = str(e)
            print(f"Database query attempt {retry_count + 1} failed: {last_error}")
            retry_count += 1
            
            if retry_count < max_retries:
                import time
                time.sleep(2)  # Wait 2 seconds before retry
    
    print(f"All attempts to get patient by ID failed after {max_retries} retries")
    return None

def get_measurements_for_patient(patient_id):
    """Get all measurements for a patient."""
    max_retries = 3
    retry_count = 0
    last_error = None
    
    while retry_count < max_retries:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            
            # Get the appropriate placeholder
            placeholder = get_placeholder()
            
            c.execute(f"SELECT * FROM measurements WHERE patient_id = {placeholder} ORDER BY date DESC", (patient_id,))
            measurements = c.fetchall()
            
            measurement_list = []
            for m in measurements:
                measurement_list.append({
                    "id": m[0],
                    "patient_id": m[1],
                    "date": m[2],
                    "age": m[3],
                    "bmi": m[4],
                    "systolic": m[5],
                    "diastolic": m[6],
                    "glucose": m[7],
                    "cholesterol": m[8],
                    "smoking": m[9],
                    "has_hypertension": m[10],
                    "has_diabetes": m[11],
                    "has_heart_disease": m[12]
                })
            
            conn.close()
            return measurement_list
            
        except Exception as e:
            last_error = str(e)
            print(f"Database query attempt {retry_count + 1} failed: {last_error}")
            retry_count += 1
            
            if retry_count < max_retries:
                import time
                time.sleep(2)  # Wait 2 seconds before retry
    
    print(f"All attempts to get measurements failed after {max_retries} retries")
    return []

def get_latest_measurement_for_patient(patient_id):
    """Get the latest measurement for a patient."""
    measurements = get_measurements_for_patient(patient_id)
    if measurements:
        return measurements[0]
    return None

def get_risk_scores_for_measurement(measurement_id):
    """Get risk scores for a measurement."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the appropriate placeholder
    placeholder = get_placeholder()
    
    c.execute(f"SELECT * FROM risk_scores WHERE measurement_id = {placeholder}", (measurement_id,))
    scores = c.fetchall()
    
    score_list = []
    for s in scores:
        score_list.append({
            "id": s[0],
            "patient_id": s[1],
            "measurement_id": s[2],
            "date": s[3],
            "model_name": s[4],
            "model_version": s[5],
            "score": s[6],
            "confidence": s[7]
        })
    
    conn.close()
    return score_list

def get_recommendations_for_measurement(measurement_id):
    """Get recommendations for a measurement."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the appropriate placeholder
    placeholder = get_placeholder()
    
    c.execute(f"SELECT * FROM recommendations WHERE measurement_id = {placeholder}", (measurement_id,))
    recommendations = c.fetchall()
    
    recommendation_list = []
    for r in recommendations:
        recommendation_list.append({
            "id": r[0],
            "patient_id": r[1],
            "measurement_id": r[2],
            "date": r[3],
            "recommendation": r[4],
            "source": r[5]
        })
    
    conn.close()
    return recommendation_list

def delete_patient(patient_id):
    """Delete a patient and all associated data."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get the appropriate placeholder
    placeholder = get_placeholder()
    
    # Get all measurements for this patient
    c.execute(f"SELECT id FROM measurements WHERE patient_id = {placeholder}", (patient_id,))
    measurement_ids = [m[0] for m in c.fetchall()]
    
    # Delete recommendations for these measurements
    for measurement_id in measurement_ids:
        c.execute(f"DELETE FROM recommendations WHERE measurement_id = {placeholder}", (measurement_id,))
    
    # Delete risk scores for these measurements
    for measurement_id in measurement_ids:
        c.execute(f"DELETE FROM risk_scores WHERE measurement_id = {placeholder}", (measurement_id,))
    
    # Delete measurements
    c.execute(f"DELETE FROM measurements WHERE patient_id = {placeholder}", (patient_id,))
    
    # Delete the patient
    c.execute(f"DELETE FROM patients WHERE id = {placeholder}", (patient_id,))
    
    conn.commit()
    conn.close()
