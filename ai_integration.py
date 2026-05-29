import os
import json
import uuid
from datetime import datetime
from openai import OpenAI
import utils

def get_openai_client():
    """Get OpenAI client with API key from environment variables"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    
    return OpenAI(api_key=api_key)

def get_llm_analysis(patient_data, risk_data, measurement_data):
    """
    Get AI-enhanced analysis and recommendations using LLM
    Falls back to standard recommendations if OpenAI API is unavailable
    """
    client = get_openai_client()
    if not client:
        return generate_standard_recommendations(patient_data, risk_data, measurement_data)
    
    try:
        # Prepare patient context
        # Convert any numpy types to native Python types
        def convert_to_native(value):
            if hasattr(value, 'item'):
                return value.item()
            return value
            
        patient_context = {
            "patient": {
                "age": convert_to_native(measurement_data.get("age", 0)),
                "gender": patient_data.get("gender", "Unknown"),
                "bmi": convert_to_native(measurement_data.get("bmi", 0)),
                "systolic": convert_to_native(measurement_data.get("systolic", 0)),
                "diastolic": convert_to_native(measurement_data.get("diastolic", 0)),
                "glucose": convert_to_native(measurement_data.get("glucose", 0)),
                "cholesterol": convert_to_native(measurement_data.get("cholesterol", 0)),
                "smoking_status": measurement_data.get("smoking", "Unknown"),
                "has_hypertension": convert_to_native(measurement_data.get("has_hypertension", 0)),
                "has_diabetes": convert_to_native(measurement_data.get("has_diabetes", 0)),
                "has_heart_disease": convert_to_native(measurement_data.get("has_heart_disease", 0))
            },
            "risk_score": convert_to_native(risk_data.get("ensemble", {}).get("score", 0)),
            "risk_confidence": convert_to_native(risk_data.get("ensemble", {}).get("confidence", 0))
        }
        
        # Create patient data string avoiding any format strings
        patient_age = str(patient_context['patient']['age'])
        patient_gender = str(patient_context['patient']['gender'])
        patient_bmi = str(patient_context['patient']['bmi'])
        patient_systolic = str(patient_context['patient']['systolic'])
        patient_diastolic = str(patient_context['patient']['diastolic'])
        patient_glucose = str(patient_context['patient']['glucose'])
        patient_cholesterol = str(patient_context['patient']['cholesterol'])
        patient_smoking = str(patient_context['patient']['smoking_status'])
        patient_hypertension = 'Yes' if patient_context['patient']['has_hypertension'] == 1 else 'No'
        patient_diabetes = 'Yes' if patient_context['patient']['has_diabetes'] == 1 else 'No'
        patient_heart_disease = 'Yes' if patient_context['patient']['has_heart_disease'] == 1 else 'No'
        patient_risk_score = str(patient_context['risk_score'])
        patient_risk_confidence = str(patient_context['risk_confidence']*100)
        
        # Create prompt
        prompt = "You are a medical AI assistant helping healthcare providers analyze patient data and provide recommendations.\n"
        prompt += "Here is a patient's health data:\n\n"
        prompt += "Patient Information:\n"
        prompt += f"- Age: {patient_age}\n"
        prompt += f"- Gender: {patient_gender}\n"
        prompt += f"- BMI: {patient_bmi}\n"
        prompt += f"- Blood Pressure: {patient_systolic}/{patient_diastolic} mmHg\n"
        prompt += f"- Glucose: {patient_glucose} mg/dL\n"
        prompt += f"- Cholesterol: {patient_cholesterol} mg/dL\n"
        prompt += f"- Smoking Status: {patient_smoking}\n"
        prompt += f"- Hypertension: {patient_hypertension}\n"
        prompt += f"- Diabetes: {patient_diabetes}\n"
        prompt += f"- Heart Disease: {patient_heart_disease}\n\n"
        prompt += f"Stroke Risk Assessment:\n"
        prompt += f"- Risk Score: {patient_risk_score}% (confidence: {patient_risk_confidence}%)\n\n"
        prompt += "Based on this information, please provide:\n"
        prompt += "1. A concise health analysis summary\n"
        prompt += "2. A list of 3-5 specific recommendations for improving health and reducing stroke risk\n"
        prompt += "3. Key risk factors that need attention\n\n"
        prompt += "Format your response as JSON with the following structure:\n"
        prompt += '{"summary": "health analysis summary", "recommendations": [{"title": "recommendation title", "description": "detailed description"}], "risk_factors": [{"factor": "risk factor name", "severity": "severity level"}]}'
        
        try:
            # Call OpenAI API
            # the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
            # do not change this unless explicitly requested by the user
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a medical AI assistant specialized in cardiovascular health."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7
            )
            
            # Parse response
            analysis = json.loads(response.choices[0].message.content)
            
            # Add source information
            analysis["source"] = "OpenAI GPT-4o"
            analysis["timestamp"] = datetime.now().isoformat()
            
            return analysis
            
        except json.JSONDecodeError:
            # Fall back to standard recommendations if JSON parsing fails
            return {
                "error": "Failed to parse AI response as JSON - using standard recommendations instead",
                **generate_standard_recommendations(patient_data, risk_data, measurement_data)
            }
            
    except Exception as e:
        # Check if this is a quota or API key error
        error_str = str(e)
        if "quota" in error_str.lower() or "api key" in error_str.lower() or "insufficient_quota" in error_str:
            # Fall back to standard recommendations
            standard_recs = generate_standard_recommendations(patient_data, risk_data, measurement_data)
            standard_recs["error"] = f"OpenAI API quota exceeded. Using standard recommendations instead."
            return standard_recs
        else:
            # Some other error occurred
            standard_recs = generate_standard_recommendations(patient_data, risk_data, measurement_data)
            standard_recs["error"] = f"Error calling OpenAI API: {error_str}. Using standard recommendations instead."
            return standard_recs


def generate_standard_recommendations(patient_data, risk_data, measurement_data):
    """
    Generate standard health recommendations based on patient data
    Used as fallback when OpenAI API is unavailable
    """
    # Get patient metrics
    bmi = measurement_data.get("bmi", 0)
    systolic = measurement_data.get("systolic", 0)
    diastolic = measurement_data.get("diastolic", 0)
    glucose = measurement_data.get("glucose", 0)
    cholesterol = measurement_data.get("cholesterol", 0)
    smoking = measurement_data.get("smoking", "Unknown")
    has_hypertension = measurement_data.get("has_hypertension", 0)
    has_diabetes = measurement_data.get("has_diabetes", 0)
    has_heart_disease = measurement_data.get("has_heart_disease", 0)
    
    # Risk score
    risk_score = risk_data.get("ensemble", {}).get("score", 0)
    
    # Generate health summary
    if risk_score < 20:
        risk_level = "low"
    elif risk_score < 50:
        risk_level = "moderate"
    else:
        risk_level = "high"
    
    summary = f"Patient has a {risk_level} risk of stroke based on current health metrics."
    
    # Build recommendations list
    recommendations = []
    risk_factors = []
    
    # BMI recommendations
    if bmi > 25:
        recommendations.append({
            "title": "Weight Management",
            "description": "Maintain a healthy weight through balanced diet and regular exercise. Aim for a BMI between 18.5-24.9."
        })
        risk_factors.append({
            "factor": "Elevated BMI",
            "severity": "Moderate" if bmi < 30 else "High"
        })
    
    # Blood pressure recommendations
    if systolic > 120 or diastolic > 80:
        recommendations.append({
            "title": "Blood Pressure Control",
            "description": "Monitor blood pressure regularly and follow prescribed medications. Aim for readings below 120/80 mmHg."
        })
        severity = "Moderate" if (systolic < 140 and diastolic < 90) else "High"
        risk_factors.append({
            "factor": "Elevated Blood Pressure",
            "severity": severity
        })
    
    # Cholesterol management
    if cholesterol > 200:
        recommendations.append({
            "title": "Cholesterol Management",
            "description": "Maintain cholesterol below 200 mg/dL through diet, exercise, and medication if prescribed."
        })
        risk_factors.append({
            "factor": "Elevated Cholesterol",
            "severity": "Moderate" if cholesterol < 240 else "High"
        })
    
    # Glucose management
    if glucose > 100:
        recommendations.append({
            "title": "Blood Glucose Control",
            "description": "Monitor blood glucose levels and maintain within normal range (70-100 mg/dL) through diet and medication if needed."
        })
        risk_factors.append({
            "factor": "Elevated Blood Glucose",
            "severity": "Moderate" if glucose < 126 else "High"
        })
    
    # Smoking cessation
    if smoking in ["Current Smoker", "Former Smoker"]:
        recommendations.append({
            "title": "Smoking Cessation",
            "description": "Quit smoking completely and avoid second-hand smoke exposure to reduce cardiovascular risk."
        })
        if smoking == "Current Smoker":
            risk_factors.append({
                "factor": "Active Smoking",
                "severity": "High"
            })
    
    # General recommendations if list is empty or has fewer than 3 items
    if len(recommendations) < 3:
        recommendations.append({
            "title": "Regular Physical Activity",
            "description": "Engage in at least 150 minutes of moderate-intensity aerobic activity per week."
        })
        
        recommendations.append({
            "title": "Heart-Healthy Diet",
            "description": "Follow a diet rich in fruits, vegetables, whole grains, and lean proteins. Limit sodium, saturated fats, and added sugars."
        })
        
        recommendations.append({
            "title": "Regular Health Check-ups",
            "description": "Schedule regular check-ups with healthcare providers to monitor cardiovascular health metrics."
        })
    
    # Create the final response
    response = {
        "summary": summary,
        "recommendations": recommendations,
        "risk_factors": risk_factors,
        "source": "Standard Health Guidelines",
        "timestamp": datetime.now().isoformat()
    }
    
    return response

def ask_custom_question(patient_data, measurement_data, risk_data, question):
    """
    Ask a custom question about a patient's health data using AI
    """
    client = get_openai_client()
    if not client:
        return {
            "error": "OpenAI API key not configured. Please add your API key to use the AI assistant."
        }
    
    try:
        # Convert numpy types to native Python types
        def convert_to_native(value):
            if hasattr(value, 'item'):
                return value.item()
            return value
        
        # Prepare patient context
        patient_age = utils.calculate_age(patient_data.get("dob", "1970-01-01"))
        patient_gender = patient_data.get("gender", "Unknown")
        patient_bmi = convert_to_native(measurement_data.get("bmi", 0))
        patient_systolic = convert_to_native(measurement_data.get("systolic", 0))
        patient_diastolic = convert_to_native(measurement_data.get("diastolic", 0))
        patient_glucose = convert_to_native(measurement_data.get("glucose", 0))
        patient_cholesterol = convert_to_native(measurement_data.get("cholesterol", 0))
        patient_smoking = measurement_data.get("smoking", "Unknown")
        patient_hypertension = 'Yes' if measurement_data.get('has_hypertension', 0) == 1 else 'No'
        patient_diabetes = 'Yes' if measurement_data.get('has_diabetes', 0) == 1 else 'No'
        patient_heart_disease = 'Yes' if measurement_data.get('has_heart_disease', 0) == 1 else 'No'
        
        # Get risk score if available
        risk_score = "Not calculated"
        risk_confidence = 0
        if risk_data and "ensemble" in risk_data:
            risk_score = f"{convert_to_native(risk_data['ensemble'].get('score', 0)):.1f}%"
            risk_confidence = f"{convert_to_native(risk_data['ensemble'].get('confidence', 0)) * 100:.1f}%"
        
        # Create comprehensive prompt
        prompt = "You are a medical AI assistant helping healthcare providers analyze patient data.\n\n"
        prompt += "Patient Health Information:\n"
        prompt += f"- Age: {patient_age} years\n"
        prompt += f"- Gender: {patient_gender}\n"
        prompt += f"- BMI: {patient_bmi}\n"
        prompt += f"- Blood Pressure: {patient_systolic}/{patient_diastolic} mmHg\n"
        prompt += f"- Glucose: {patient_glucose} mg/dL\n"
        prompt += f"- Cholesterol: {patient_cholesterol} mg/dL\n"
        prompt += f"- Smoking Status: {patient_smoking}\n"
        prompt += f"- Hypertension: {patient_hypertension}\n"
        prompt += f"- Diabetes: {patient_diabetes}\n"
        prompt += f"- Heart Disease: {patient_heart_disease}\n"
        prompt += f"- Stroke Risk Score: {risk_score}"
        if risk_confidence:
            prompt += f" (confidence: {risk_confidence})"
        prompt += "\n\n"
        prompt += f"Healthcare Provider's Question: {question}\n\n"
        prompt += "Please provide a clear, evidence-based response that helps the healthcare provider understand the patient's health situation and make informed decisions."
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a medical AI assistant specialized in cardiovascular health and stroke risk assessment. Provide clear, evidence-based responses to help healthcare providers."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        return {
            "answer": response.choices[0].message.content,
            "source": "OpenAI GPT-4o"
        }
        
    except Exception as e:
        error_str = str(e)
        if "quota" in error_str.lower() or "insufficient_quota" in error_str:
            return {
                "error": "OpenAI API quota exceeded. Please check your API usage or upgrade your plan."
            }
        else:
            return {
                "error": f"Error communicating with AI: {error_str}"
            }

def save_ai_recommendations(patient_id, measurement_id, analysis, database_module):
    """Save AI recommendations to database"""
    if "error" in analysis:
        # Save error as recommendation for debugging
        recommendation = {
            "id": str(uuid.uuid4()),
            "patient_id": patient_id,
            "measurement_id": measurement_id,
            "date": datetime.now().isoformat(),
            "recommendation": f"Error generating recommendations: {analysis['error']}",
            "source": "AI Error"
        }
        database_module.save_recommendation(recommendation)
        return
    
    # Save summary as a recommendation
    if "summary" in analysis:
        recommendation = {
            "id": str(uuid.uuid4()),
            "patient_id": patient_id,
            "measurement_id": measurement_id,
            "date": datetime.now().isoformat(),
            "recommendation": f"Health Analysis: {analysis['summary']}",
            "source": analysis.get("source", "AI Analysis")
        }
        database_module.save_recommendation(recommendation)
    
    # Save each recommendation
    if "recommendations" in analysis:
        for rec in analysis["recommendations"]:
            recommendation = {
                "id": str(uuid.uuid4()),
                "patient_id": patient_id,
                "measurement_id": measurement_id,
                "date": datetime.now().isoformat(),
                "recommendation": f"{rec.get('title', 'Recommendation')}: {rec.get('description', '')}",
                "source": analysis.get("source", "AI Recommendation")
            }
            database_module.save_recommendation(recommendation)
    
    # Save risk factors as recommendations
    if "risk_factors" in analysis:
        for factor in analysis["risk_factors"]:
            recommendation = {
                "id": str(uuid.uuid4()),
                "patient_id": patient_id,
                "measurement_id": measurement_id,
                "date": datetime.now().isoformat(),
                "recommendation": f"Risk Factor - {factor.get('factor', 'Unknown')}: {factor.get('severity', 'Unknown')} severity",
                "source": analysis.get("source", "AI Risk Assessment")
            }
            database_module.save_recommendation(recommendation)
