import numpy as np
import uuid
from datetime import datetime, timedelta

def generate_synthetic_patient():
    """Generate a single synthetic patient with realistic values"""
    # Age: normal distribution centered around 65
    age = max(18, min(100, int(np.random.normal(65, 12))))
    
    # Gender
    gender = np.random.choice(['Male', 'Female'], p=[0.48, 0.52])
    
    # BMI: log-normal distribution
    bmi = max(16, min(45, np.random.lognormal(mean=3.25, sigma=0.2)))
    
    # Blood pressure: correlated with age and BMI
    base_systolic = 110 + (age - 50) * 0.5 + (bmi - 25) * 1.2
    base_diastolic = 70 + (age - 50) * 0.25 + (bmi - 25) * 0.8
    
    # Add some noise
    systolic = max(90, min(220, int(base_systolic + np.random.normal(0, 10))))
    diastolic = max(50, min(130, int(base_diastolic + np.random.normal(0, 7))))
    
    # Determine hypertension based on blood pressure
    has_hypertension = 1 if systolic >= 140 or diastolic >= 90 else 0
    
    # Glucose: higher for older patients and those with higher BMI
    base_glucose = 85 + (age - 50) * 0.3 + (bmi - 25) * 1.5
    glucose = max(70, min(300, int(base_glucose + np.random.normal(0, 15))))
    
    # Determine diabetes based on glucose
    has_diabetes = 1 if glucose >= 126 else 0
    
    # Cholesterol: correlated with age and BMI
    base_cholesterol = 170 + (age - 50) * 0.7 + (bmi - 25) * 2.0
    cholesterol = max(120, min(300, int(base_cholesterol + np.random.normal(0, 25))))
    
    # Smoking status: probability increases with age up to 65, then decreases
    smoking_prob = min(0.3, max(0.05, 0.1 + (age - 30) * 0.005)) if age < 65 else min(0.3, max(0.05, 0.3 - (age - 65) * 0.01))
    smoking_status = np.random.choice(
        ['Current Smoker', 'Former Smoker', 'Never Smoked'],
        p=[smoking_prob, smoking_prob * 1.5, 1 - smoking_prob * 2.5]
    )
    
    # Heart disease: probability increases with age and other risk factors
    heart_disease_prob = 0.05 + (age - 50) * 0.003 + has_hypertension * 0.1 + (glucose > 110) * 0.05 + (cholesterol > 240) * 0.1
    heart_disease_prob = min(0.7, max(0.01, heart_disease_prob))
    has_heart_disease = 1 if np.random.random() < heart_disease_prob else 0
    
    # Generate a name
    first_names = ["James", "John", "Robert", "Michael", "William", "David", "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara"]
    last_names = ["Smith", "Johnson", "Williams", "Jones", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Thomas"]
    
    name = f"{np.random.choice(first_names)} {np.random.choice(last_names)}"
    
    # Generate a birthdate
    birth_year = datetime.now().year - age
    birth_month = np.random.randint(1, 13)
    birth_day = np.random.randint(1, 29)  # Simplified to avoid month length issues
    dob = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"
    
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "dob": dob,
        "gender": gender,
        "age": age,
        "bmi": round(bmi, 1),
        "systolic": systolic,
        "diastolic": diastolic,
        "glucose": glucose,
        "cholesterol": cholesterol,
        "smoking": smoking_status,
        "has_hypertension": has_hypertension,
        "has_diabetes": has_diabetes,
        "has_heart_disease": has_heart_disease,
        "created_at": datetime.now().isoformat()
    }

def generate_synthetic_dataset(n=100):
    """Generate a dataset of n synthetic patients"""
    return [generate_synthetic_patient() for _ in range(n)]

def generate_historical_data(patient, num_records=18, months_back=18):
    """
    Generate realistic historical measurements for a patient over time
    
    Parameters:
    -----------
    patient : dict
        Current patient data
    num_records : int
        Number of historical records to generate (default: 18 for monthly records over 18 months)
    months_back : int
        How many months back to go for the earliest record (default: 18 months)
        
    Returns:
    --------
    list of dicts: Historical patient records with realistic progression patterns
    """
    # Start from current values
    current = {
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
    
    # Calculate trend directions (positive means worsening over time, negative means improvement)
    # For realistic data, most patients trend slightly worse over time, but some improve
    bmi_trend = np.random.normal(0.08, 0.05)  # Slight average increase in BMI over time
    systolic_trend = np.random.normal(0.3, 0.15)  # Slight increase in systolic BP
    diastolic_trend = np.random.normal(0.2, 0.1)  # Slight increase in diastolic BP
    glucose_trend = np.random.normal(0.25, 0.2)  # Slight increase in glucose
    cholesterol_trend = np.random.normal(0.3, 0.25)  # Slight increase in cholesterol
    
    # Risk factors can affect trends
    if current["smoking"] == "Current Smoker":
        systolic_trend *= 1.5
        cholesterol_trend *= 1.7
    elif current["smoking"] == "Former Smoker":
        systolic_trend *= 1.2
        cholesterol_trend *= 1.3
        
    if current["has_diabetes"] == 1:
        glucose_trend *= 2  # Diabetic patients have more volatile glucose
        
    if current["has_hypertension"] == 1:
        systolic_trend *= 1.5
        diastolic_trend *= 1.5
        
    # Account for interventions (some patients might have improvement periods)
    intervention_chance = 0.3
    if np.random.random() < intervention_chance:
        # Simulate an intervention at some point in the past
        intervention_point = np.random.randint(1, num_records-1)
        intervention_strength = np.random.uniform(0.5, 1.5)  # How effective the intervention was
    else:
        intervention_point = None
        intervention_strength = 0.0  # No intervention effect
    
    # Ensure consistent patient_id with the current measurement
    patient_id = current.get("patient_id")
    
    # Handle condition development over time
    condition_months = {
        "hypertension": np.random.randint(1, months_back) if current["has_hypertension"] == 1 else None,
        "diabetes": np.random.randint(1, months_back) if current["has_diabetes"] == 1 else None,
        "heart_disease": np.random.randint(1, months_back) if current["has_heart_disease"] == 1 else None
    }
    
    # Generate records going back in time
    history = []
    for i in range(num_records):
        # Calculate date for this record
        months = int(months_back * (i + 1) / num_records)
        record_date = (datetime.now() - timedelta(days=30*months)).isoformat()
        
        # Calculate monthly changes based on trends
        bmi_change = bmi_trend * months / 18
        systolic_change = systolic_trend * months / 18
        diastolic_change = diastolic_trend * months / 18
        glucose_change = glucose_trend * months / 18
        cholesterol_change = cholesterol_trend * months / 18
        
        # If after intervention point, apply improvement effects
        if intervention_point is not None and i >= intervention_point:
            months_since_intervention = months - (intervention_point * months_back / num_records)
            if months_since_intervention > 0:
                improvement_factor = min(1.0, months_since_intervention / 3) * intervention_strength
                bmi_change -= improvement_factor * 0.1
                systolic_change -= improvement_factor * 0.4
                diastolic_change -= improvement_factor * 0.3
                glucose_change -= improvement_factor * 0.3
                cholesterol_change -= improvement_factor * 0.4
        
        # Add seasonal variations (winter effects on blood pressure, holiday effects on glucose)
        month_num = (datetime.now().month - months) % 12 + 1
        
        # Winter effect (peaks in January)
        winter_factor = max(0, 4 - abs(month_num - 1)) / 4
        
        # Holiday effect (peaks in December)
        holiday_factor = max(0, 4 - abs(((month_num + 1) % 12) - 11)) / 4
        
        # Apply seasonal effects
        systolic_seasonal = winter_factor * np.random.uniform(2, 5)  # Higher BP in winter
        diastolic_seasonal = winter_factor * np.random.uniform(1, 3)  # Higher BP in winter
        glucose_seasonal = holiday_factor * np.random.uniform(3, 7)   # Higher glucose during holidays
        
        # Create the record with all calculated effects
        record = {
            "id": str(uuid.uuid4()),
            "patient_id": patient_id,  # Use the consistent patient_id
            "date": record_date,
            "age": max(18, current["age"] - months // 12),
            "bmi": round(max(16, min(45, current["bmi"] - bmi_change + np.random.normal(0, 0.2))), 1),
            "systolic": max(90, min(220, int(current["systolic"] - systolic_change - systolic_seasonal + np.random.normal(0, 3)))),
            "diastolic": max(50, min(130, int(current["diastolic"] - diastolic_change - diastolic_seasonal + np.random.normal(0, 2)))),
            "glucose": max(70, min(300, int(current["glucose"] - glucose_change - glucose_seasonal + np.random.normal(0, 4)))),
            "cholesterol": max(120, min(300, int(current["cholesterol"] - cholesterol_change + np.random.normal(0, 5)))),
            "smoking": current["smoking"],
            "has_hypertension": current["has_hypertension"],
            "has_diabetes": current["has_diabetes"],
            "has_heart_disease": current["has_heart_disease"]
        }
        
        # Apply condition changes if before onset
        if condition_months["hypertension"] is not None and months > condition_months["hypertension"]:
            record["has_hypertension"] = 0
            
        if condition_months["diabetes"] is not None and months > condition_months["diabetes"]:
            record["has_diabetes"] = 0
            
        if condition_months["heart_disease"] is not None and months > condition_months["heart_disease"]:
            record["has_heart_disease"] = 0
        
        # Handle smoking status changes
        if current["smoking"] == "Former Smoker":
            # Calculate when they might have quit
            quit_months = np.random.randint(1, min(60, months_back))
            if months > quit_months:
                record["smoking"] = "Current Smoker"
        
        history.append(record)
    
    # Sort by date (ascending from oldest to newest)
    history.sort(key=lambda x: x["date"])
    
    return history
