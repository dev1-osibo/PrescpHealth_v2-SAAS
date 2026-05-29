"""
Optimized bulk database population script for 120 demo patients.
Uses batch inserts to avoid database connection overhead.
"""

import os
import sys
from datetime import datetime
import uuid
import numpy as np

# Import existing modules
from database import get_db_connection, get_placeholder, init_db
from data_generation import generate_synthetic_patient, generate_historical_data
from models import load_trained_models, predict_stroke_risk

# Extended name lists for more variety
FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles",
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen",
    "Christopher", "Daniel", "Matthew", "Anthony", "Mark", "Donald", "Steven", "Paul", "Andrew", "Joshua",
    "Nancy", "Lisa", "Margaret", "Betty", "Sandra", "Ashley", "Dorothy", "Kimberly", "Emily", "Donna",
    "George", "Kenneth", "Kevin", "Brian", "Edward", "Ronald", "Timothy", "Jason", "Jeffrey", "Ryan",
    "Carol", "Michelle", "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca", "Laura", "Sharon", "Cynthia",
    "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon",
    "Kathleen", "Amy", "Shirley", "Angela", "Helen", "Anna", "Brenda", "Pamela", "Nicole", "Samantha",
    "Alexander", "Benjamin", "Samuel", "Frank", "Raymond", "Gregory", "Patrick", "Jack", "Dennis", "Jerry",
    "Emma", "Olivia", "Ava", "Isabella", "Sophia", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
    "Tyler", "Aaron", "Jose", "Adam", "Henry", "Nathan", "Douglas", "Zachary", "Peter", "Kyle",
    "Abigail", "Emily", "Madison", "Elizabeth", "Sofia", "Avery", "Ella", "Scarlett", "Grace", "Chloe",
    "Walter", "Harold", "Jeremy", "Keith", "Christian", "Roger", "Noah", "Gerald", "Carl", "Terry"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor",
    "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Garcia", "Martinez", "Robinson",
    "Clark", "Rodriguez", "Lewis", "Lee", "Walker", "Hall", "Allen", "Young", "Hernandez", "King",
    "Wright", "Lopez", "Hill", "Scott", "Green", "Adams", "Baker", "Gonzalez", "Nelson", "Carter",
    "Mitchell", "Perez", "Roberts", "Turner", "Phillips", "Campbell", "Parker", "Evans", "Edwards", "Collins",
    "Stewart", "Sanchez", "Morris", "Rogers", "Reed", "Cook", "Morgan", "Bell", "Murphy", "Bailey",
    "Rivera", "Cooper", "Richardson", "Cox", "Howard", "Ward", "Torres", "Peterson", "Gray", "Ramirez",
    "James", "Watson", "Brooks", "Kelly", "Sanders", "Price", "Bennett", "Wood", "Barnes", "Ross",
    "Henderson", "Coleman", "Jenkins", "Perry", "Powell", "Long", "Patterson", "Hughes", "Flores", "Washington",
    "Butler", "Simmons", "Foster", "Gonzales", "Bryant", "Alexander", "Russell", "Griffin", "Diaz", "Hayes",
    "Myers", "Ford", "Hamilton", "Graham", "Sullivan", "Wallace", "Woods", "Cole", "West", "Jordan",
    "Owens", "Reynolds", "Fisher", "Ellis", "Harrison", "Gibson", "McDonald", "Cruz", "Marshall", "Ortiz"
]

def generate_unique_patient():
    """Generate a patient with a unique name"""
    patient = generate_synthetic_patient()
    
    # Create unique name from expanded lists
    first_name = np.random.choice(FIRST_NAMES)
    last_name = np.random.choice(LAST_NAMES)
    
    # Add middle initial for more variety
    middle_initials = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'R', 'S', 'T', 'W']
    middle_initial = np.random.choice(middle_initials) if np.random.random() > 0.3 else ""
    
    if middle_initial:
        patient["name"] = f"{first_name} {middle_initial}. {last_name}"
    else:
        patient["name"] = f"{first_name} {last_name}"
    
    return patient

def bulk_insert_patients(conn, patients_data):
    """Bulk insert patients using single transaction"""
    c = conn.cursor()
    placeholder = get_placeholder()
    
    if os.environ.get('DATABASE_URL'):
        # PostgreSQL - use execute_values for best performance
        from psycopg2.extras import execute_values
        values = [(p['id'], p['name'], p['dob'], p['gender'], p['created_at']) for p in patients_data]
        execute_values(c, f"""
            INSERT INTO patients (id, name, dob, gender, created_at)
            VALUES %s
        """, values)
    else:
        # SQLite - use executemany
        c.executemany(f"""
            INSERT INTO patients (id, name, dob, gender, created_at)
            VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
        """, [(p['id'], p['name'], p['dob'], p['gender'], p['created_at']) for p in patients_data])

def bulk_insert_measurements(conn, measurements_data):
    """Bulk insert measurements using single transaction"""
    c = conn.cursor()
    placeholder = get_placeholder()
    
    if os.environ.get('DATABASE_URL'):
        # PostgreSQL - use execute_values
        from psycopg2.extras import execute_values
        values = [(m['id'], m['patient_id'], m['date'], m['age'], m['bmi'], m['systolic'],
                  m['diastolic'], m['glucose'], m['cholesterol'], m['smoking'],
                  m['has_hypertension'], m['has_diabetes'], m['has_heart_disease']) 
                 for m in measurements_data]
        execute_values(c, """
            INSERT INTO measurements (
                id, patient_id, date, age, bmi, systolic, 
                diastolic, glucose, cholesterol, smoking,
                has_hypertension, has_diabetes, has_heart_disease
            ) VALUES %s
        """, values)
    else:
        # SQLite - use executemany
        placeholders = ", ".join([placeholder] * 13)
        c.executemany(f"""
            INSERT INTO measurements (
                id, patient_id, date, age, bmi, systolic, 
                diastolic, glucose, cholesterol, smoking,
                has_hypertension, has_diabetes, has_heart_disease
            ) VALUES ({placeholders})
        """, [(m['id'], m['patient_id'], m['date'], m['age'], m['bmi'], m['systolic'],
              m['diastolic'], m['glucose'], m['cholesterol'], m['smoking'],
              m['has_hypertension'], m['has_diabetes'], m['has_heart_disease']) 
             for m in measurements_data])

def bulk_insert_risk_scores(conn, risk_scores_data):
    """Bulk insert risk scores using single transaction"""
    c = conn.cursor()
    placeholder = get_placeholder()
    
    if os.environ.get('DATABASE_URL'):
        # PostgreSQL - use execute_values
        from psycopg2.extras import execute_values
        values = [(r['id'], r['patient_id'], r['measurement_id'], r['date'],
                  r['model_name'], r['model_version'], r['score'], r['confidence'])
                 for r in risk_scores_data]
        execute_values(c, """
            INSERT INTO risk_scores (
                id, patient_id, measurement_id, date, 
                model_name, model_version, score, confidence
            ) VALUES %s
        """, values)
    else:
        # SQLite - use executemany
        placeholders = ", ".join([placeholder] * 8)
        c.executemany(f"""
            INSERT INTO risk_scores (
                id, patient_id, measurement_id, date, 
                model_name, model_version, score, confidence
            ) VALUES ({placeholders})
        """, [(r['id'], r['patient_id'], r['measurement_id'], r['date'],
              r['model_name'], r['model_version'], r['score'], r['confidence'])
             for r in risk_scores_data])

def categorize_patient_risk(risk_score):
    """Categorize patient based on risk score"""
    if risk_score < 20:
        return "Low Risk"
    elif risk_score < 50:
        return "Moderate Risk"
    elif risk_score < 80:
        return "High Risk"
    else:
        return "Critical Risk"

def populate_demo_database_bulk(num_patients=120, batch_size=30):
    """
    Populate database with demo patients using bulk inserts
    """
    
    print(f"🏥 PrescpHealth Demo Database Population (Bulk Mode)")
    print(f"=" * 60)
    print(f"Generating {num_patients} diverse patients for client demo...")
    print(f"Using batch size: {batch_size}\n")
    
    # Initialize database
    print("📊 Initializing database...")
    if not init_db():
        print("❌ Failed to initialize database")
        return False
    
    # Load ML models
    print("🤖 Loading stroke risk prediction models...")
    try:
        models = load_trained_models()
        if not models:
            print("⚠️  Warning: Could not load models. Risk scores will not be calculated.")
            models = None
    except Exception as e:
        print(f"⚠️  Warning: Error loading models: {e}")
        models = None
    
    # Track statistics
    risk_distribution = {"Low Risk": 0, "Moderate Risk": 0, "High Risk": 0, "Critical Risk": 0}
    gender_distribution = {"Male": 0, "Female": 0}
    age_groups = {"18-40": 0, "41-60": 0, "61-80": 0, "80+": 0}
    
    # Generate all data in memory first
    print(f"\n👥 Generating patient data in memory...")
    used_names = set()
    all_patients_data = []
    all_measurements_data = []
    all_risk_scores_data = []
    
    for i in range(num_patients):
        # Generate unique patient
        patient = None
        max_attempts = 10
        for attempt in range(max_attempts):
            patient = generate_unique_patient()
            if patient["name"] not in used_names:
                used_names.add(patient["name"])
                break
            if attempt == max_attempts - 1:
                patient["name"] = f"{patient['name']} ({i+1})"
        
        if patient is None:
            patient = generate_unique_patient()
            patient["name"] = f"{patient['name']} ({i+1})"
        
        # Track statistics
        gender_distribution[patient["gender"]] += 1
        age = patient["age"]
        if age <= 40:
            age_groups["18-40"] += 1
        elif age <= 60:
            age_groups["41-60"] += 1
        elif age <= 80:
            age_groups["61-80"] += 1
        else:
            age_groups["80+"] += 1
        
        # Prepare patient data
        patient_id = str(uuid.uuid4())
        patient_data = {
            "id": patient_id,
            "name": patient["name"],
            "dob": patient["dob"],
            "gender": patient["gender"],
            "created_at": datetime.now().isoformat()
        }
        all_patients_data.append(patient_data)
        
        # Generate historical measurements (3-6 months)
        num_historical = np.random.randint(3, 7)
        current_measurement = {
            "patient_id": patient_id,
            "age": patient["age"],
            "bmi": patient["bmi"],
            "systolic": patient["systolic"],
            "diastolic": patient["diastolic"],
            "glucose": patient["glucose"],
            "cholesterol": patient["cholesterol"],
            "smoking": patient["smoking"],
            "has_hypertension": patient["has_hypertension"],
            "has_diabetes": patient["has_diabetes"],
            "has_heart_disease": patient["has_heart_disease"]
        }
        
        historical_records = generate_historical_data(current_measurement, num_records=num_historical)
        
        # Add historical measurements
        for record in historical_records:
            measurement_data = {
                "id": str(uuid.uuid4()),
                "patient_id": patient_id,
                "date": record["date"],
                "age": record["age"],
                "bmi": record["bmi"],
                "systolic": record["systolic"],
                "diastolic": record["diastolic"],
                "glucose": record["glucose"],
                "cholesterol": record["cholesterol"],
                "smoking": record["smoking"],
                "has_hypertension": record["has_hypertension"],
                "has_diabetes": record["has_diabetes"],
                "has_heart_disease": record["has_heart_disease"]
            }
            all_measurements_data.append(measurement_data)
        
        # Add current measurement
        measurement_id = str(uuid.uuid4())
        current_date = datetime.now().isoformat()
        current_measurement_data = {
            "id": measurement_id,
            "patient_id": patient_id,
            "date": current_date,
            "age": patient["age"],
            "bmi": patient["bmi"],
            "systolic": patient["systolic"],
            "diastolic": patient["diastolic"],
            "glucose": patient["glucose"],
            "cholesterol": patient["cholesterol"],
            "smoking": patient["smoking"],
            "has_hypertension": patient["has_hypertension"],
            "has_diabetes": patient["has_diabetes"],
            "has_heart_disease": patient["has_heart_disease"]
        }
        all_measurements_data.append(current_measurement_data)
        
        # Calculate risk score if models are available
        if models:
            try:
                patient_data_for_prediction = {
                    "age": patient["age"],
                    "gender": patient["gender"],
                    "bmi": patient["bmi"],
                    "systolic": patient["systolic"],
                    "diastolic": patient["diastolic"],
                    "glucose": patient["glucose"],
                    "cholesterol": patient["cholesterol"],
                    "smoking": patient["smoking"],
                    "hypertension": patient["has_hypertension"],
                    "diabetes": patient["has_diabetes"],
                    "heart_disease": patient["has_heart_disease"]
                }
                
                risk_result = predict_stroke_risk(patient_data_for_prediction, models)
                risk_score = float(risk_result['ensemble']['score'])
                confidence = float(risk_result['ensemble']['confidence'])
                
                risk_score_data = {
                    "id": str(uuid.uuid4()),
                    "patient_id": patient_id,
                    "measurement_id": measurement_id,
                    "date": current_date,
                    "model_name": "Ensemble Model",
                    "model_version": "1.0",
                    "score": risk_score,
                    "confidence": confidence
                }
                all_risk_scores_data.append(risk_score_data)
                
                risk_category = categorize_patient_risk(risk_score)
                risk_distribution[risk_category] += 1
                
            except Exception as e:
                print(f"⚠️  Warning: Could not calculate risk for patient {i+1}: {e}")
        
        if (i + 1) % 20 == 0:
            print(f"   ✓ Generated {i + 1}/{num_patients} patients in memory...")
    
    # Now bulk insert in batches
    print(f"\n💾 Inserting data into database in batches of {batch_size}...")
    
    try:
        # Get a single connection for all batches
        conn = get_db_connection()
        
        # For SQLite, disable autocommit for bulk operations
        if not os.environ.get('DATABASE_URL'):
            conn.isolation_level = None
            c = conn.cursor()
            c.execute('BEGIN')
        
        # Insert patients in batches
        for i in range(0, len(all_patients_data), batch_size):
            batch = all_patients_data[i:i+batch_size]
            bulk_insert_patients(conn, batch)
            print(f"   ✓ Inserted patients batch {i//batch_size + 1}/{(len(all_patients_data)-1)//batch_size + 1}")
        
        # Insert measurements in batches
        for i in range(0, len(all_measurements_data), batch_size * 5):
            batch = all_measurements_data[i:i+batch_size * 5]
            bulk_insert_measurements(conn, batch)
            print(f"   ✓ Inserted measurements batch {i//(batch_size*5) + 1}/{(len(all_measurements_data)-1)//(batch_size*5) + 1}")
        
        # Insert risk scores in batches
        if all_risk_scores_data:
            for i in range(0, len(all_risk_scores_data), batch_size):
                batch = all_risk_scores_data[i:i+batch_size]
                bulk_insert_risk_scores(conn, batch)
                print(f"   ✓ Inserted risk scores batch {i//batch_size + 1}/{(len(all_risk_scores_data)-1)//batch_size + 1}")
        
        # Commit for SQLite
        if not os.environ.get('DATABASE_URL'):
            c.execute('COMMIT')
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error during bulk insert: {e}")
        if conn:
            conn.close()
        return False
    
    # Print summary
    print(f"\n✅ Successfully generated {num_patients} demo patients!")
    print(f"\n📊 Patient Demographics:")
    print(f"   Gender Distribution:")
    for gender, count in gender_distribution.items():
        percentage = (count / num_patients) * 100
        print(f"      {gender}: {count} ({percentage:.1f}%)")
    
    print(f"\n   Age Distribution:")
    for age_range, count in age_groups.items():
        percentage = (count / num_patients) * 100
        print(f"      {age_range}: {count} ({percentage:.1f}%)")
    
    if models:
        print(f"\n   Risk Distribution:")
        for risk_level, count in risk_distribution.items():
            percentage = (count / num_patients) * 100
            print(f"      {risk_level}: {count} ({percentage:.1f}%)")
    
    print(f"\n🎉 Demo database is ready for client presentations!")
    print(f"=" * 60)
    
    return True

if __name__ == "__main__":
    num_patients = 120
    if len(sys.argv) > 1:
        try:
            num_patients = int(sys.argv[1])
        except ValueError:
            print(f"Invalid number of patients: {sys.argv[1]}")
            print("Usage: python populate_demo_database_bulk.py [number_of_patients]")
            sys.exit(1)
    
    success = populate_demo_database_bulk(num_patients)
    
    if not success:
        sys.exit(1)
