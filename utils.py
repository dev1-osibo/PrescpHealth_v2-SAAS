from datetime import datetime, timedelta
import pandas as pd
import numpy as np

def format_date(date_str):
    """Format date string for display"""
    try:
        date_obj = datetime.fromisoformat(date_str)
        return date_obj.strftime('%b %d, %Y')
    except:
        return date_str

def calculate_age(dob):
    """Calculate age from date of birth"""
    try:
        birth_date = datetime.fromisoformat(dob.replace('Z', '+00:00'))
        today = datetime.now()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        return age
    except:
        # Default to 50 if there's an error
        return 50

def get_risk_level(score):
    """Get risk level from score"""
    if score < 20:
        return "Low", "green"
    elif score < 50:
        return "Moderate", "orange"
    else:
        return "High", "red"

def get_heart_health_metrics(measurement):
    """Calculate heart health metrics"""
    metrics = {}
    
    # Blood pressure classification
    if measurement["systolic"] < 120 and measurement["diastolic"] < 80:
        metrics["bp_status"] = "Normal"
        metrics["bp_color"] = "green"
    elif (measurement["systolic"] >= 120 and measurement["systolic"] < 130) and measurement["diastolic"] < 80:
        metrics["bp_status"] = "Elevated"
        metrics["bp_color"] = "yellow"
    elif (measurement["systolic"] >= 130 and measurement["systolic"] < 140) or (measurement["diastolic"] >= 80 and measurement["diastolic"] < 90):
        metrics["bp_status"] = "Stage 1 Hypertension"
        metrics["bp_color"] = "orange"
    else:
        metrics["bp_status"] = "Stage 2 Hypertension"
        metrics["bp_color"] = "red"
    
    # BMI classification
    if measurement["bmi"] < 18.5:
        metrics["bmi_status"] = "Underweight"
        metrics["bmi_color"] = "yellow"
    elif measurement["bmi"] >= 18.5 and measurement["bmi"] < 25:
        metrics["bmi_status"] = "Normal"
        metrics["bmi_color"] = "green"
    elif measurement["bmi"] >= 25 and measurement["bmi"] < 30:
        metrics["bmi_status"] = "Overweight"
        metrics["bmi_color"] = "yellow"
    else:
        metrics["bmi_status"] = "Obese"
        metrics["bmi_color"] = "red"
    
    # Glucose classification
    if measurement["glucose"] < 100:
        metrics["glucose_status"] = "Normal"
        metrics["glucose_color"] = "green"
    elif measurement["glucose"] >= 100 and measurement["glucose"] < 126:
        metrics["glucose_status"] = "Prediabetes"
        metrics["glucose_color"] = "yellow"
    else:
        metrics["glucose_status"] = "Diabetes"
        metrics["glucose_color"] = "red"
    
    # Cholesterol classification
    if measurement["cholesterol"] < 200:
        metrics["cholesterol_status"] = "Desirable"
        metrics["cholesterol_color"] = "green"
    elif measurement["cholesterol"] >= 200 and measurement["cholesterol"] < 240:
        metrics["cholesterol_status"] = "Borderline High"
        metrics["cholesterol_color"] = "yellow"
    else:
        metrics["cholesterol_status"] = "High"
        metrics["cholesterol_color"] = "red"
    
    return metrics

def measurements_to_dataframe(measurements):
    """Convert measurements list to pandas DataFrame"""
    if not measurements:
        return pd.DataFrame()
    
    df = pd.DataFrame(measurements)
    
    # Convert dates to datetime
    df['date'] = pd.to_datetime(df['date'])
    
    # Sort by date
    df = df.sort_values('date')
    
    return df

def calculate_trend(current, previous, metric):
    """Calculate trend for a specific metric"""
    if not previous:
        return "stable", "gray"
    
    current_value = current.get(metric, 0)
    previous_value = previous.get(metric, 0)
    
    # Define thresholds for different metrics
    thresholds = {
        "bmi": 0.5,
        "systolic": 5,
        "diastolic": 5,
        "glucose": 5,
        "cholesterol": 10
    }
    
    threshold = thresholds.get(metric, 0.1)
    
    # Calculate percent change
    if previous_value == 0:
        percent_change = 0
    else:
        percent_change = (current_value - previous_value) / previous_value * 100
    
    # Determine trend
    if abs(percent_change) < threshold:
        return "stable", "gray"
    elif metric in ["bmi", "systolic", "diastolic", "glucose", "cholesterol"]:
        # For these metrics, lower is better
        if percent_change > 0:
            return "increasing", "red"
        else:
            return "decreasing", "green"
    else:
        # For other metrics, higher might be better
        if percent_change > 0:
            return "increasing", "green"
        else:
            return "decreasing", "red"
