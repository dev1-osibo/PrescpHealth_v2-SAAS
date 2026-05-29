"""
Test blood pressure correlation with stroke risk
This verifies that high BP increases risk and low BP decreases risk
"""
import models

# Load the trained models
model_data = models.load_trained_models()

if not model_data:
    print("ERROR: Models not loaded!")
    exit(1)

print("✓ Models loaded successfully\n")

# Test Case 1: High blood pressure (should show HIGH risk)
print("=" * 60)
print("TEST 1: High Blood Pressure (200/110 mmHg)")
print("=" * 60)
high_bp_patient = {
    'age': 70,
    'gender': 'Male',
    'bmi': 28.0,
    'systolic': 200,
    'diastolic': 110,
    'glucose': 110,
    'cholesterol': 200,
    'smoking': 'Former Smoker',
    'has_hypertension': 1,
    'has_diabetes': 0,
    'has_heart_disease': 0
}

result_high = models.predict_stroke_risk(high_bp_patient, model_data)
print(f"\nRisk Score: {result_high['ensemble']['score']}%")
print(f"Confidence: {result_high['ensemble']['confidence']}")
print(f"\nIndividual Models:")
for model_name, prediction in result_high['models'].items():
    if 'error' not in prediction:
        print(f"  {model_name}: {prediction['score']:.1f}%")

# Test Case 2: Normal blood pressure (should show MODERATE risk due to age)
print("\n" + "=" * 60)
print("TEST 2: Normal Blood Pressure (120/80 mmHg)")
print("=" * 60)
normal_bp_patient = {
    'age': 70,
    'gender': 'Male',
    'bmi': 28.0,
    'systolic': 120,
    'diastolic': 80,
    'glucose': 110,
    'cholesterol': 200,
    'smoking': 'Former Smoker',
    'has_hypertension': 0,
    'has_diabetes': 0,
    'has_heart_disease': 0
}

result_normal = models.predict_stroke_risk(normal_bp_patient, model_data)
print(f"\nRisk Score: {result_normal['ensemble']['score']}%")
print(f"Confidence: {result_normal['ensemble']['confidence']}")
print(f"\nIndividual Models:")
for model_name, prediction in result_normal['models'].items():
    if 'error' not in prediction:
        print(f"  {model_name}: {prediction['score']:.1f}%")

# Test Case 3: Low blood pressure (should show LOWER risk)
print("\n" + "=" * 60)
print("TEST 3: Low Blood Pressure (95/65 mmHg)")
print("=" * 60)
low_bp_patient = {
    'age': 70,
    'gender': 'Male',
    'bmi': 28.0,
    'systolic': 95,
    'diastolic': 65,
    'glucose': 110,
    'cholesterol': 200,
    'smoking': 'Former Smoker',
    'has_hypertension': 0,
    'has_diabetes': 0,
    'has_heart_disease': 0
}

result_low = models.predict_stroke_risk(low_bp_patient, model_data)
print(f"\nRisk Score: {result_low['ensemble']['score']}%")
print(f"Confidence: {result_low['ensemble']['confidence']}")
print(f"\nIndividual Models:")
for model_name, prediction in result_low['models'].items():
    if 'error' not in prediction:
        print(f"  {model_name}: {prediction['score']:.1f}%")

# Verify correlation
print("\n" + "=" * 60)
print("VERIFICATION")
print("=" * 60)

high_risk = result_high['ensemble']['score']
normal_risk = result_normal['ensemble']['score']
low_risk = result_low['ensemble']['score']

print(f"\nRisk Scores:")
print(f"  High BP (200/110):   {high_risk}%")
print(f"  Normal BP (120/80):  {normal_risk}%")
print(f"  Low BP (95/65):      {low_risk}%")

print(f"\nExpected Relationship: High BP > Normal BP > Low BP")
print(f"Actual Relationship:   {high_risk:.1f}% {'>' if high_risk > normal_risk else '≤'} {normal_risk:.1f}% {'>' if normal_risk > low_risk else '≤'} {low_risk:.1f}%")

if high_risk > normal_risk and normal_risk > low_risk:
    print("\n✅ SUCCESS: Blood pressure correctly correlated with stroke risk!")
    print("   Higher BP → Higher Risk")
else:
    print("\n❌ FAILED: Blood pressure correlation is still incorrect!")
    if high_risk < normal_risk:
        print("   ERROR: High BP shows LOWER risk than normal BP!")
    if normal_risk < low_risk:
        print("   ERROR: Normal BP shows LOWER risk than low BP!")
