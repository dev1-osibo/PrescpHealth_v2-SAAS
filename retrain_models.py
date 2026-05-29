"""
Retrain ML models with regression approach
"""
import pandas as pd
import data_generation
import models

print("Generating synthetic training data...")
synthetic_data = data_generation.generate_synthetic_dataset(500)

# Create DataFrame for training
df = pd.DataFrame(synthetic_data)

# Prepare features for model training
feature_columns = ['age', 'bmi', 'systolic', 'diastolic', 'glucose', 'cholesterol',
                 'smoking_encoded', 'has_hypertension', 'has_diabetes', 'has_heart_disease', 'gender_encoded']

# Encode categorical variables
df['smoking_encoded'] = df['smoking'].map({'Never Smoked': 0, 'Former Smoker': 1, 'Current Smoker': 2})
df['gender_encoded'] = df['gender'].map({'Male': 1, 'Female': 0})

# Create target variable (simplified stroke risk calculation)
df['stroke_risk'] = (
    (df['age'] > 55).astype(int) * 20 +
    (df['bmi'] > 30).astype(int) * 15 +
    (df['systolic'] > 140).astype(int) * 20 +
    (df['glucose'] > 126).astype(int) * 15 +
    df['smoking_encoded'] * 10 +
    df['has_hypertension'] * 15 +
    df['has_diabetes'] * 10 +
    df['has_heart_disease'] * 25
)

# Ensure risk is between 0-100
df['stroke_risk'] = df['stroke_risk'].clip(0, 100)

X = df[feature_columns]
y = df['stroke_risk']

print(f"Training data: {len(df)} samples")
print(f"Features: {feature_columns}")
print(f"Risk score range: {y.min():.1f} - {y.max():.1f}")

# Train and save models
print("\nTraining regression models...")
trained_models, scaler = models.train_and_save_models(X, y)

print("\n✓ Models trained successfully!")
print(f"  - Trained models: {list(trained_models.keys())}")
print(f"  - Scaler saved")
print("\nModel files saved to models/")
