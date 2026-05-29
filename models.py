import os
import pickle
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import uuid
from datetime import datetime

# Function to check if models directory exists and create it if not
def ensure_models_directory():
    """Ensure the models directory exists"""
    if not os.path.exists('models'):
        os.makedirs('models')

def train_and_save_models(X_train, y_train):
    """Train models and save them to disk with feature scaling"""
    ensure_models_directory()
    
    # Initialize and fit scaler
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    
    # Save scaler
    with open('models/scaler.pkl', 'wb') as f:
        pickle.dump(scaler, f)
    
    models = {
        'xgboost': xgb.XGBRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42
        ),
        'random_forest': RandomForestRegressor(
            n_estimators=100,
            max_depth=5,
            random_state=42
        ),
        'ridge': Ridge(
            alpha=1.0,
            random_state=42
        )
    }
    
    for name, model in models.items():
        model.fit(X_train_scaled, y_train)
        with open(f'models/{name}_model.pkl', 'wb') as f:
            pickle.dump(model, f)
    
    return models, scaler

def load_trained_models():
    """Load trained models and scaler from disk"""
    ensure_models_directory()
    
    try:
        # Load scaler first
        scaler_path = 'models/scaler.pkl'
        if not os.path.exists(scaler_path):
            return None
        
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        
        models = {}
        for name in ['xgboost', 'random_forest', 'ridge']:
            model_path = f'models/{name}_model.pkl'
            
            # If model doesn't exist, return None
            if not os.path.exists(model_path):
                return None
                
            with open(model_path, 'rb') as f:
                models[name] = pickle.load(f)
        
        # Return both models and scaler as a dictionary
        return {'models': models, 'scaler': scaler}
    except Exception as e:
        print(f"Error loading models: {e}")
        return None

def extract_features(patient_data):
    """Extract features from patient data for prediction"""
    # Map categorical variables to numerical
    smoking_map = {
        'Current Smoker': 2, 
        'Former Smoker': 1, 
        'Never Smoked': 0
    }
    
    gender_map = {
        'Male': 1,
        'Female': 0
    }
    
    # Get smoking value or default to 0
    smoking_value = smoking_map.get(patient_data.get('smoking'), 0)
    
    # Get gender value or default to 0
    gender_value = gender_map.get(patient_data.get('gender'), 0)
    
    # Create feature dictionary with all 11 features in correct order
    features = {
        'age': patient_data.get('age', 50),
        'bmi': patient_data.get('bmi', 25.0),
        'systolic': patient_data.get('systolic', 120),
        'diastolic': patient_data.get('diastolic', 80),
        'glucose': patient_data.get('glucose', 100),
        'cholesterol': patient_data.get('cholesterol', 180),
        'smoking_encoded': smoking_value,
        'has_hypertension': patient_data.get('has_hypertension', 0),
        'has_diabetes': patient_data.get('has_diabetes', 0),
        'has_heart_disease': patient_data.get('has_heart_disease', 0),
        'gender_encoded': gender_value
    }
    
    return features

def predict_stroke_risk(patient_data, model_data):
    """Calculate stroke risk using ensemble of regression models"""
    if not model_data:
        return {
            'error': 'Models not loaded',
            'ensemble': {
                'score': 0.0,
                'confidence': 0.0
            }
        }
    
    # Extract models and scaler
    models = model_data['models']
    scaler = model_data['scaler']
    
    # Extract features
    features = extract_features(patient_data)
    X = pd.DataFrame([features])
    
    # Scale features
    X_scaled = scaler.transform(X)
    
    # Get predictions from each model
    predictions = {}
    raw_predictions = {}
    
    for name, model in models.items():
        try:
            # Get risk score prediction (already 0-100 from training)
            risk_score = model.predict(X_scaled)[0]
            
            # Clip to valid range
            risk_score = np.clip(risk_score, 0, 100)
            
            raw_predictions[name] = risk_score
            predictions[name] = {
                'score': float(risk_score),
                'confidence': calculate_confidence_regression(model, X_scaled, risk_score)
            }
        except Exception as e:
            print(f"Error predicting with {name} model: {e}")
            import traceback
            traceback.print_exc()
            predictions[name] = {
                'score': 0.0,
                'confidence': 0.0,
                'error': str(e)
            }
    
    # Calculate ensemble score with weights
    weights = {
        'xgboost': 0.5,
        'random_forest': 0.3,
        'ridge': 0.2
    }
    
    # Filter out models with errors
    valid_models = {k: v for k, v in predictions.items() if 'error' not in v}
    
    if not valid_models:
        ensemble_score = 0.0
        ensemble_confidence = 0.0
    else:
        # Normalize weights for available models
        total_weight = sum(weights[model] for model in valid_models.keys())
        normalized_weights = {model: weights[model]/total_weight for model in valid_models.keys()}
        
        ensemble_score = sum(
            valid_models[model]['score'] * normalized_weights[model] 
            for model in valid_models.keys()
        )
        
        # Calculate ensemble confidence based on agreement
        ensemble_confidence = calculate_ensemble_confidence_regression(raw_predictions, normalized_weights)
    
    return {
        'models': predictions,
        'ensemble': {
            'score': round(ensemble_score, 1),
            'confidence': round(ensemble_confidence, 2)
        }
    }

def calculate_confidence_regression(model, X_scaled, prediction):
    """Calculate model confidence for regression models"""
    # For regression, we use prediction magnitude as confidence proxy
    # Higher predictions (closer to extremes) generally mean higher confidence
    
    # Base confidence from prediction distance from middle (50)
    distance_from_middle = abs(prediction - 50) / 50
    base_confidence = 0.6 + (distance_from_middle * 0.3)
    
    # Scale confidence based on model type
    if isinstance(model, xgb.XGBRegressor):
        confidence = base_confidence * 1.1  # Boost XGBoost confidence
    elif isinstance(model, RandomForestRegressor):
        confidence = base_confidence * 1.0  # Keep RF as is
    else:  # Ridge
        confidence = base_confidence * 0.9  # Reduce Ridge confidence slightly
    
    return min(confidence, 1.0)

def calculate_ensemble_confidence_regression(raw_predictions, weights):
    """Calculate ensemble confidence based on model agreement"""
    if not raw_predictions or len(raw_predictions) < 2:
        return 0.7  # Default confidence
    
    # Calculate standard deviation of predictions (low = high agreement)
    predictions_list = list(raw_predictions.values())
    std_dev = float(np.std(predictions_list))
    
    # Convert std_dev to confidence (lower std = higher confidence)
    # Max std would be ~50 (predictions ranging 0-100)
    agreement_confidence = 1.0 - min(std_dev / 50.0, 0.4)
    
    # Boost ensemble confidence due to model diversity
    ensemble_boost = 1.1
    return min(agreement_confidence * ensemble_boost, 1.0)

def save_risk_prediction(patient_id, measurement_id, risk_data, database_module):
    """Save risk prediction to database"""
    # Save individual model predictions
    for model_name, prediction in risk_data['models'].items():
        # Skip models with errors
        if 'error' in prediction:
            continue
            
        # Convert any numpy types to native Python types
        score = float(prediction['score']) if hasattr(prediction['score'], 'item') else prediction['score']
        confidence = float(prediction['confidence']) if hasattr(prediction['confidence'], 'item') else prediction['confidence']
        
        risk_score = {
            'id': str(uuid.uuid4()),
            'patient_id': patient_id,
            'measurement_id': measurement_id,
            'date': datetime.now().isoformat(),
            'model_name': model_name,
            'model_version': '1.0',  # Could track model versions
            'score': score,
            'confidence': confidence
        }
        database_module.save_risk_score(risk_score)
    
    # Save ensemble prediction
    # Convert any numpy types to native Python types
    ensemble_score_value = float(risk_data['ensemble']['score']) if hasattr(risk_data['ensemble']['score'], 'item') else risk_data['ensemble']['score']
    ensemble_confidence = float(risk_data['ensemble']['confidence']) if hasattr(risk_data['ensemble']['confidence'], 'item') else risk_data['ensemble']['confidence']
    
    ensemble_score = {
        'id': str(uuid.uuid4()),
        'patient_id': patient_id,
        'measurement_id': measurement_id,
        'date': datetime.now().isoformat(),
        'model_name': 'ensemble',
        'model_version': '1.0',
        'score': ensemble_score_value,
        'confidence': ensemble_confidence
    }
    database_module.save_risk_score(ensemble_score)
