"""
Script to populate the database with 120 diverse demo patients for client demonstrations.
Each patient will have:
- Realistic health metrics
- Historical measurements (6-18 months of data)
- Calculated stroke risk scores
- Varied health profiles (low risk to critical risk)
"""

import os
import sys
from datetime import datetime
import uuid
import numpy as np

# Import existing modules
from database import init_db, get_db_connection, save_patient, save_measurement, save_risk_score
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
    # Generate base patient
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

def populate_demo_database(num_patients=120):
    """
    Populate database with demo patients
    
    Parameters:
    -----------
    num_patients : int
        Number of patients to generate (default: 120)
    """
    
    print(f"🏥 PrescpHealth Demo Database Population")
    print(f"=" * 60)
    print(f"Generating {num_patients} diverse patients for client demo...\n")
    
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
    
    # Generate and add patients
    print(f"\n👥 Generating {num_patients} patients with health histories...")
    used_names = set()
    
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
                # Add timestamp to ensure uniqueness
                patient["name"] = f"{patient['name']} ({i+1})"
        
        # Safety check
        if patient is None:
            patient = generate_unique_patient()
            patient["name"] = f"{patient['name']} ({i+1})"
        
        # Track gender distribution
        gender_distribution[patient["gender"]] += 1
        
        # Track age distribution
        age = patient["age"]
        if age <= 40:
            age_groups["18-40"] += 1
        elif age <= 60:
            age_groups["41-60"] += 1
        elif age <= 80:
            age_groups["61-80"] += 1
        else:
            age_groups["80+"] += 1
        
        # Add patient to database
        patient_id = str(uuid.uuid4())
        patient_data = {
            "id": patient_id,
            "name": patient["name"],
            "dob": patient["dob"],
            "gender": patient["gender"],
            "created_at": datetime.now().isoformat()
        }
        save_patient(patient_data)
        
        # Generate historical measurements (3-6 months of data for faster generation)
        num_historical = np.random.randint(3, 7)
        
        # Prepare current measurement for historical generation
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
        
        # Generate historical data
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
            save_measurement(measurement_data)
        
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
        save_measurement(current_measurement_data)
        
        # Calculate and store risk score if models are available
        if models:
            try:
                # Prepare patient data for prediction
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
                
                # Convert numpy types to native Python types for database
                risk_score = float(risk_result['ensemble']['score'])
                confidence = float(risk_result['ensemble']['confidence'])
                
                # Store risk score
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
                save_risk_score(risk_score_data)
                
                # Track risk distribution
                risk_category = categorize_patient_risk(risk_score)
                risk_distribution[risk_category] += 1
                
            except Exception as e:
                print(f"⚠️  Warning: Could not calculate risk for patient {i+1}: {e}")
        
        # Progress indicator
        if (i + 1) % 20 == 0:
            print(f"   ✓ Generated {i + 1}/{num_patients} patients...")
    
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
    # Check for number of patients argument
    num_patients = 120
    if len(sys.argv) > 1:
        try:
            num_patients = int(sys.argv[1])
        except ValueError:
            print(f"Invalid number of patients: {sys.argv[1]}")
            print("Usage: python populate_demo_database.py [number_of_patients]")
            sys.exit(1)
    
    # Run the population script
    success = populate_demo_database(num_patients)
    
    if not success:
        sys.exit(1)
