import streamlit as st
import pandas as pd
import uuid
from datetime import datetime
import database
import models
import utils
import health_dashboard
import risk_gauge
import sklearn_forecasting
import ai_integration
import data_generation
import pdf_reports

# Page configuration
st.set_page_config(
    page_title="PrescpHealth",
    page_icon="static/logo.jpg",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize database
database.init_db()

# Initialize session state
if 'selected_patient' not in st.session_state:
    st.session_state.selected_patient = None
if 'selected_measurement' not in st.session_state:
    st.session_state.selected_measurement = None
if 'ml_models' not in st.session_state:
    st.session_state.ml_models = models.load_trained_models()
    if st.session_state.ml_models:
        print(f"✓ ML models loaded successfully: {list(st.session_state.ml_models['models'].keys())}")
    else:
        print("✗ WARNING: ML models failed to load - risk scores will not be calculated")
if 'page' not in st.session_state:
    st.session_state.page = 'dashboard'
if 'show_new_patient_form' not in st.session_state:
    st.session_state.show_new_patient_form = False
if 'notification' not in st.session_state:
    st.session_state.notification = None

# Create a sidebar for navigation with logo
st.sidebar.image("static/logo.jpg", width=200)
st.sidebar.markdown("**Predict • Prescribe • Protect**")
st.sidebar.markdown("""
<div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
            padding: 8px 12px; 
            border-radius: 6px; 
            text-align: center; 
            margin-top: 10px;">
    <span style="color: white; font-size: 13px; font-weight: 600;">
        ⚡ AI-POWERED PLATFORM
    </span>
</div>
""", unsafe_allow_html=True)

st.sidebar.markdown("---")

# Navigation
page_options = ["Dashboard", "Patient List", "Analytics", "Settings"]
current_index = 0
if hasattr(st.session_state, 'page'):
    page_mapping = {
        'dashboard': 0,
        'patient list': 1,
        'analytics': 2,
        'settings': 3
    }
    current_index = page_mapping.get(st.session_state.page, 0)

page = st.sidebar.radio(
    "Navigation",
    options=page_options,
    index=current_index
)

# Set current page
st.session_state.page = page.lower()

# Handle notification display
if st.session_state.notification:
    st.success(st.session_state.notification)
    st.session_state.notification = None

# Check if models are loaded
if st.session_state.ml_models is None:
    st.sidebar.warning("ML models not found. Generate sample data and train models to enable full functionality.")
    
    if st.sidebar.button("Generate Sample Data & Train Models"):
        with st.spinner("Generating sample data and training models..."):
            # Generate synthetic training data for models
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
            
            # Train and save models
            models.train_and_save_models(X, y)
            st.session_state.ml_models = models.load_trained_models()
            
            st.sidebar.success("Models trained successfully!")

# Patient Management Section
st.sidebar.markdown("---")
st.sidebar.markdown("**Patient Management**")

# Add new patient button
if st.sidebar.button("+ Add New Patient"):
    st.session_state.show_new_patient_form = True

# Show new patient form if needed
if st.session_state.show_new_patient_form:
    with st.sidebar.form("new_patient_form"):
        st.write("Add New Patient")
        name = st.text_input("Full Name")
        gender = st.selectbox("Gender", ["Male", "Female"])
        dob = st.date_input("Date of Birth")
        
        if st.form_submit_button("Add Patient"):
            if name:
                # Create patient record
                patient_data = {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "gender": gender,
                    "dob": dob.isoformat(),
                    "created_at": datetime.now().isoformat()
                }
                
                # Save to database
                database.save_patient(patient_data)
                st.session_state.show_new_patient_form = False
                st.session_state.notification = f"Patient {name} added successfully"
                st.rerun()
            else:
                st.error("Patient name is required")

# Get all patients for selector
patients = database.get_patients()

if patients:
    # Create a selectbox with patient names
    patient_options = ["Select a patient"] + [p["name"] for p in patients]
    selected_index = 0
    
    # If a patient is already selected, set the index
    if st.session_state.selected_patient:
        for i, p in enumerate(patients):
            if p["id"] == st.session_state.selected_patient:
                selected_index = i + 1  # +1 because of the "Select a patient" option
                break
    
    selected_patient_name = st.sidebar.selectbox(
        "Select Patient",
        options=patient_options,
        index=selected_index
    )
    
    # Update selected patient if changed
    if selected_patient_name != "Select a patient":
        selected_patient = next(p for p in patients if p["name"] == selected_patient_name)
        st.session_state.selected_patient = selected_patient["id"]
    elif selected_index != 0:  # If "Select a patient" is chosen explicitly
        st.session_state.selected_patient = None
else:
    st.sidebar.info("No patients in database. Add a new patient to begin.")

# Main content area based on selected page
if st.session_state.page == 'dashboard':
    # Show dashboard for selected patient
    if st.session_state.selected_patient:
        patient = database.get_patient_by_id(st.session_state.selected_patient)
        measurements = database.get_measurements_for_patient(st.session_state.selected_patient)
        
        if patient:
            # Compact patient header
            age = utils.calculate_age(patient['dob'])
            st.markdown(f"""
            <div style="background-color: #f8f9fa; padding: 15px 20px; border-radius: 8px; margin-bottom: 25px; border-left: 4px solid #2E4057;">
                <h3 style="color: #2E4057; margin: 0; display: inline;">Patient: {patient['name']}</h3>
                <span style="color: #666; font-size: 14px; margin-left: 15px;">
                    {age} years • {patient['gender']} • ID: {patient['id']}
                </span>
            </div>
            """, unsafe_allow_html=True)
            
            # Check if patient has measurements
            if measurements:
                latest_measurement = measurements[0]
                
                # Create organized tabs for different sections
                overview_tab, health_tab, analytics_tab = st.tabs(["Overview", "Health Metrics", "Analytics & Forecasting"])
                
                with overview_tab:
                    # MODERN STROKE RISK ASSESSMENT - Completely Redesigned
                    risk_scores = database.get_risk_scores_for_measurement(latest_measurement["id"])
                    if risk_scores:
                        # Get ensemble score specifically (not just first score)
                        ensemble_score = next((s for s in risk_scores if s['model_name'] == 'ensemble'), None)
                        if not ensemble_score:
                            # Fallback to first score if ensemble not found
                            ensemble_score = risk_scores[0]
                        risk_score = ensemble_score['score']
                        confidence = ensemble_score.get('confidence', 0.85)
                        
                        # Determine risk level and styling
                        if risk_score < 20:
                            risk_level = "Low Risk"
                            risk_color = "#10b981"
                            risk_bg = "#ecfdf5"
                            risk_icon = "✓"
                            risk_message = "Patient shows low stroke risk based on current health metrics."
                            action_message = "Continue monitoring and maintain healthy lifestyle."
                        elif risk_score < 50:
                            risk_level = "Moderate Risk"
                            risk_color = "#f59e0b"
                            risk_bg = "#fffbeb"
                            risk_icon = "⚠"
                            risk_message = "Patient has moderate stroke risk. Monitor closely and consider preventive measures."
                            action_message = "Recommend lifestyle modifications and regular follow-ups."
                        elif risk_score < 80:
                            risk_level = "High Risk"
                            risk_color = "#ef4444"
                            risk_bg = "#fef2f2"
                            risk_icon = "!"
                            risk_message = "Patient has high stroke risk. Immediate intervention recommended."
                            action_message = "Urgent: Initiate treatment plan and specialist consultation."
                        else:
                            risk_level = "Critical Risk"
                            risk_color = "#dc2626"
                            risk_bg = "#fef2f2"
                            risk_icon = "!!"
                            risk_message = "Patient has critical stroke risk. Urgent medical attention required."
                            action_message = "EMERGENCY: Immediate medical intervention required."
                        
                        # Build HTML in parts to avoid f-string issues
                        html_card = f"""
                        <div style="background: linear-gradient(135deg, {risk_bg} 0%, white 100%); border-radius: 16px; padding: 30px; margin-bottom: 30px; border-left: 6px solid {risk_color}; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 25px;">
                                <div>
                                    <h2 style="color: #1f2937; margin: 0 0 5px 0; font-size: 24px; font-weight: 700;">🧠 Stroke Risk Assessment</h2>
                                    <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;">⚡ AI-POWERED</span>
                                </div>
                                <div style="text-align: right;">
                                    <div style="color: #6b7280; font-size: 13px; margin-bottom: 4px;">Confidence</div>
                                    <div style="color: #1f2937; font-size: 18px; font-weight: 600;">{int(confidence*100)}%</div>
                                </div>
                            </div>
                            <div style="display: flex; align-items: center; gap: 30px; margin-bottom: 25px;">
                                <div style="background: {risk_color}; color: white; width: 120px; height: 120px; border-radius: 16px; display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);">
                                    <div style="font-size: 36px; font-weight: 800; line-height: 1;">{int(risk_score)}%</div>
                                    <div style="font-size: 12px; margin-top: 5px; opacity: 0.9;">Risk Score</div>
                                </div>
                                <div style="flex: 1;">
                                    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                                        <span style="background: {risk_color}; color: white; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 18px;">{risk_icon}</span>
                                        <h3 style="color: {risk_color}; margin: 0; font-size: 22px; font-weight: 700;">{risk_level}</h3>
                                    </div>
                                    <p style="color: #4b5563; margin: 0 0 10px 0; line-height: 1.6; font-size: 15px;">{risk_message}</p>
                                    <p style="color: {risk_color}; margin: 0; font-weight: 600; font-size: 14px;">→ {action_message}</p>
                                </div>
                            </div>
                            <div style="background: white; border-radius: 12px; padding: 15px; border: 1px solid #e5e7eb;">
                                <div style="flex: 1;">
                                    <div style="background: #f3f4f6; height: 8px; border-radius: 4px; overflow: hidden;">
                                        <div style="background: linear-gradient(90deg, {risk_color} 0%, {risk_color}dd 100%); height: 100%; width: {int(risk_score)}%;"></div>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 11px; color: #9ca3af;">
                                        <span>0% Low</span>
                                        <span>50% Moderate</span>
                                        <span>100% Critical</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                        """
                        
                        st.markdown(html_card, unsafe_allow_html=True)
                    else:
                        st.warning("Stroke risk assessment unavailable. Please ensure patient measurements are complete.")
                    
                    st.markdown("---")
                    
                    # RISK FACTOR ANALYSIS
                    st.markdown("### 🎯 Risk Factor Analysis")
                    st.markdown("""
                    <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                                 color: white; 
                                 padding: 4px 12px; 
                                 border-radius: 20px; 
                                 font-size: 11px; 
                                 font-weight: 600;">
                        ⚡ AI-POWERED
                    </span>
                    """, unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    # Calculate individual factor contributions
                    factor_contributions = []
                    
                    # Get patient age
                    patient_age = utils.calculate_age(patient['dob'])
                    
                    # Age contribution (normalized 0-100)
                    age_contribution = min((patient_age / 90) * 30, 30) if patient_age > 45 else 0
                    factor_contributions.append(('Age', age_contribution, patient_age))
                    
                    # Blood Pressure (Systolic)
                    if latest_measurement['systolic'] >= 180:
                        bp_sys_contribution = 25
                    elif latest_measurement['systolic'] >= 140:
                        bp_sys_contribution = 20
                    elif latest_measurement['systolic'] >= 120:
                        bp_sys_contribution = 10
                    else:
                        bp_sys_contribution = 0
                    factor_contributions.append(('Systolic BP', bp_sys_contribution, latest_measurement['systolic']))
                    
                    # Blood Pressure (Diastolic)
                    if latest_measurement['diastolic'] >= 110:
                        bp_dia_contribution = 20
                    elif latest_measurement['diastolic'] >= 90:
                        bp_dia_contribution = 15
                    elif latest_measurement['diastolic'] >= 80:
                        bp_dia_contribution = 8
                    else:
                        bp_dia_contribution = 0
                    factor_contributions.append(('Diastolic BP', bp_dia_contribution, latest_measurement['diastolic']))
                    
                    # BMI contribution
                    if latest_measurement['bmi'] >= 35:
                        bmi_contribution = 20
                    elif latest_measurement['bmi'] >= 30:
                        bmi_contribution = 15
                    elif latest_measurement['bmi'] >= 25:
                        bmi_contribution = 8
                    else:
                        bmi_contribution = 0
                    factor_contributions.append(('BMI', bmi_contribution, latest_measurement['bmi']))
                    
                    # Glucose contribution
                    if latest_measurement['glucose'] >= 200:
                        glucose_contribution = 25
                    elif latest_measurement['glucose'] >= 126:
                        glucose_contribution = 18
                    elif latest_measurement['glucose'] >= 100:
                        glucose_contribution = 10
                    else:
                        glucose_contribution = 0
                    factor_contributions.append(('Glucose', glucose_contribution, latest_measurement['glucose']))
                    
                    # Cholesterol contribution
                    if latest_measurement['cholesterol'] >= 240:
                        chol_contribution = 18
                    elif latest_measurement['cholesterol'] >= 200:
                        chol_contribution = 12
                    else:
                        chol_contribution = 0
                    factor_contributions.append(('Cholesterol', chol_contribution, latest_measurement['cholesterol']))
                    
                    # Smoking contribution
                    smoking_map = {'Current Smoker': 25, 'Former Smoker': 12, 'Never Smoked': 0}
                    smoking_contribution = smoking_map.get(latest_measurement['smoking'], 0)
                    factor_contributions.append(('Smoking', smoking_contribution, latest_measurement['smoking']))
                    
                    # Hypertension
                    hypertension_contribution = 20 if latest_measurement['has_hypertension'] else 0
                    factor_contributions.append(('Hypertension', hypertension_contribution, 'Yes' if latest_measurement['has_hypertension'] else 'No'))
                    
                    # Diabetes
                    diabetes_contribution = 18 if latest_measurement['has_diabetes'] else 0
                    factor_contributions.append(('Diabetes', diabetes_contribution, 'Yes' if latest_measurement['has_diabetes'] else 'No'))
                    
                    # Heart Disease (if available)
                    if 'has_heart_disease' in latest_measurement:
                        heart_contribution = 30 if latest_measurement['has_heart_disease'] else 0
                        factor_contributions.append(('Heart Disease', heart_contribution, 'Yes' if latest_measurement['has_heart_disease'] else 'No'))
                    
                    # Sort by contribution (descending)
                    factor_contributions.sort(key=lambda x: x[1], reverse=True)
                    
                    # Create visualization
                    import matplotlib.pyplot as plt
                    
                    fig, ax = plt.subplots(figsize=(12, 8))
                    
                    factors = [f[0] for f in factor_contributions]
                    contributions = [f[1] for f in factor_contributions]
                    values = [f[2] for f in factor_contributions]
                    
                    # Color based on contribution level
                    colors = []
                    for contrib in contributions:
                        if contrib >= 20:
                            colors.append('#ef4444')  # Red for high
                        elif contrib >= 10:
                            colors.append('#f59e0b')  # Orange for moderate
                        elif contrib > 0:
                            colors.append('#fbbf24')  # Yellow for low
                        else:
                            colors.append('#10b981')  # Green for none
                    
                    bars = ax.barh(factors, contributions, color=colors, alpha=0.8)
                    
                    # Add value labels
                    for i, (bar, value) in enumerate(zip(bars, values)):
                        width = bar.get_width()
                        label = f'{value}'
                        if width > 0:
                            ax.text(width + 0.5, bar.get_y() + bar.get_height()/2, 
                                   f'{width:.0f}% ({label})', 
                                   ha='left', va='center', fontsize=10, fontweight='bold')
                        else:
                            ax.text(0.5, bar.get_y() + bar.get_height()/2, 
                                   f'Normal ({label})', 
                                   ha='left', va='center', fontsize=10, color='#059669')
                    
                    ax.set_xlabel('Risk Contribution (%)', fontsize=12, fontweight='bold')
                    ax.set_title('Individual Risk Factor Contributions to Stroke Risk', fontsize=14, fontweight='bold', pad=20)
                    ax.set_xlim(0, max(contributions) * 1.3 if max(contributions) > 0 else 30)
                    
                    # Add legend
                    from matplotlib.patches import Patch
                    legend_elements = [
                        Patch(facecolor='#ef4444', alpha=0.8, label='High Impact (≥20%)'),
                        Patch(facecolor='#f59e0b', alpha=0.8, label='Moderate Impact (10-20%)'),
                        Patch(facecolor='#fbbf24', alpha=0.8, label='Low Impact (<10%)'),
                        Patch(facecolor='#10b981', alpha=0.8, label='Normal Range')
                    ]
                    ax.legend(handles=legend_elements, loc='upper right', fontsize=9, framealpha=0.95)
                    
                    st.pyplot(fig)
                    plt.close()
                    
                    # Key insights
                    high_risk_factors = [f for f in factor_contributions if f[1] >= 15]
                    if high_risk_factors:
                        st.markdown(f"""
                        <div style="background: #fef2f2; 
                                    border-left: 4px solid #ef4444; 
                                    padding: 15px 20px; 
                                    border-radius: 8px; 
                                    margin-top: 15px;">
                            <strong style="color: #dc2626;">⚠️ High-Impact Factors Identified:</strong><br>
                            <span style="color: #4b5563;">
                                The following factors are significantly contributing to stroke risk: 
                                <strong>{', '.join([f[0] for f in high_risk_factors[:3]])}</strong>
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    st.markdown("---")
                    
                    # PDF REPORT DOWNLOAD
                    st.markdown("### 📄 Export Clinical Report")
                    
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write("Generate a comprehensive PDF report with stroke risk assessment, health metrics, and AI recommendations.")
                    with col2:
                        # Get recommendations
                        recs = database.get_recommendations_for_measurement(latest_measurement["id"])
                        
                        # Generate PDF
                        pdf_buffer = pdf_reports.generate_patient_risk_report(
                            patient=patient,
                            measurement=latest_measurement,
                            risk_score=risk_score,
                            confidence=confidence,
                            recommendations=recs
                        )
                        
                        # Offer download
                        st.download_button(
                            label="📥 Download PDF Report",
                            data=pdf_buffer,
                            file_name=f"stroke_risk_report_{patient['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                    
                    st.markdown("---")
                    
                    # CURRENT HEALTH STATUS - Separate Section
                    st.markdown("### 📊 Current Health Indicators")
                    
                    # Create health indicators in a grid format
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        # Blood pressure check
                        if latest_measurement['systolic'] >= 140 or latest_measurement['diastolic'] >= 90:
                            bp_status = "🔴 High Blood Pressure"
                            bp_color = "#e74c3c"
                        elif latest_measurement['systolic'] >= 120:
                            bp_status = "🟡 Elevated Blood Pressure"
                            bp_color = "#f39c12"
                        else:
                            bp_status = "🟢 Normal Blood Pressure"
                            bp_color = "#27ae60"
                        
                        st.markdown(f"""
                        <div style="background-color: {bp_color}; color: white; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 10px;">
                            <strong>{bp_status}</strong><br>
                            <small>{latest_measurement['systolic']}/{latest_measurement['diastolic']} mmHg</small>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col2:
                        # BMI check
                        bmi = latest_measurement['bmi']
                        if bmi >= 30:
                            bmi_status = "🔴 Obesity"
                            bmi_color = "#e74c3c"
                        elif bmi >= 25:
                            bmi_status = "🟡 Overweight"
                            bmi_color = "#f39c12"
                        else:
                            bmi_status = "🟢 Normal Weight"
                            bmi_color = "#27ae60"
                        
                        st.markdown(f"""
                        <div style="background-color: {bmi_color}; color: white; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 10px;">
                            <strong>{bmi_status}</strong><br>
                            <small>BMI: {bmi:.1f}</small>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col3:
                        # Glucose check
                        if latest_measurement['glucose'] >= 126:
                            glucose_status = "🔴 Diabetes Range"
                            glucose_color = "#e74c3c"
                        elif latest_measurement['glucose'] >= 100:
                            glucose_status = "🟡 Pre-diabetes Range"
                            glucose_color = "#f39c12"
                        else:
                            glucose_status = "🟢 Normal Glucose"
                            glucose_color = "#27ae60"
                        
                        st.markdown(f"""
                        <div style="background-color: {glucose_color}; color: white; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 10px;">
                            <strong>{glucose_status}</strong><br>
                            <small>{latest_measurement['glucose']} mg/dL</small>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    st.markdown("---")
                    
                    # AI-GENERATED RECOMMENDATIONS Section
                    st.markdown("### 💡 AI-Generated Recommendations")
                    
                    # Display saved recommendations
                    recommendations = database.get_recommendations_for_measurement(latest_measurement["id"])
                    if recommendations:
                        for rec in recommendations[:5]:  # Show top 5 recommendations
                            source_badge = "🤖 AI" if "GPT" in rec.get("source", "") or "OpenAI" in rec.get("source", "") else "📋"
                            st.markdown(f"""
                            <div style="background-color: #f8f9fa; 
                                        border-left: 3px solid #667eea; 
                                        padding: 12px 15px; 
                                        border-radius: 6px; 
                                        margin-bottom: 10px;">
                                <div style="color: #667eea; font-size: 12px; font-weight: 600; margin-bottom: 5px;">
                                    {source_badge} {rec.get("source", "Unknown Source")}
                                </div>
                                <div style="color: #2E4057; line-height: 1.5;">
                                    {rec.get("recommendation", "No recommendation text")}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No AI recommendations available yet. Add new measurements to generate AI insights.")
                    
                    st.markdown("---")
                    
                    # AI HEALTH ASSISTANT - Interactive Chat Interface
                    st.markdown("### 💬 AI Health Assistant")
                    
                    st.write("Ask me anything about this patient's health data:")
                    
                    # AI Chat input
                    user_question = st.text_area(
                        "Your question:",
                        placeholder="e.g., What lifestyle changes would you recommend? How can this patient reduce their stroke risk?",
                        height=80,
                        key=f"ai_question_{st.session_state.selected_patient}"
                    )
                    
                    if st.button("🤖 Ask AI Assistant", type="primary", key=f"ask_ai_{st.session_state.selected_patient}"):
                        if user_question.strip():
                            with st.spinner("AI is analyzing patient data..."):
                                # Get risk data for context
                                risk_scores = database.get_risk_scores_for_measurement(latest_measurement["id"])
                                risk_data = {}
                                if risk_scores:
                                    risk_data = {
                                        "ensemble": {
                                            "score": risk_scores[0]['score'],
                                            "confidence": risk_scores[0].get('confidence', 0.85)
                                        }
                                    }
                                
                                # Call AI with custom question
                                ai_response = ai_integration.ask_custom_question(
                                    patient_data=patient,
                                    measurement_data=latest_measurement,
                                    risk_data=risk_data,
                                    question=user_question
                                )
                                
                                if "error" in ai_response:
                                    st.error(ai_response["error"])
                                else:
                                    st.markdown(f"""
                                    <div style="background-color: #f0f4ff; 
                                                border-left: 4px solid #667eea; 
                                                padding: 15px 20px; 
                                                border-radius: 8px; 
                                                margin-top: 15px;">
                                        <div style="color: #667eea; font-weight: 600; margin-bottom: 8px;">
                                            ⚡ AI Assistant Response:
                                        </div>
                                        <div style="color: #2E4057; line-height: 1.6;">
                                            {ai_response.get("answer", "No response received")}
                                        </div>
                                    </div>
                                    """, unsafe_allow_html=True)
                        else:
                            st.warning("Please enter a question for the AI assistant.")

                
                with health_tab:
                    # Use the existing health dashboard with tooltips
                    current_measurement = measurements[0]
                    previous_measurement = measurements[1] if len(measurements) > 1 else None
                    
                    health_dashboard.create_simple_health_dashboard(
                        current_measurement=current_measurement,
                        previous_measurement=previous_measurement
                    )
                
                with analytics_tab:
                    # HISTORICAL RISK TRACKING
                    st.markdown("### 📊 Historical Risk Tracking")
                    st.markdown("""
                    <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                                 color: white; 
                                 padding: 4px 12px; 
                                 border-radius: 20px; 
                                 font-size: 11px; 
                                 font-weight: 600;">
                        ⚡ AI-POWERED
                    </span>
                    """, unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    if len(measurements) >= 2:
                        # Collect historical risk data
                        risk_history = []
                        for measurement in reversed(measurements):  # Oldest to newest
                            risk_scores = database.get_risk_scores_for_measurement(measurement["id"])
                            if risk_scores:
                                risk_history.append({
                                    'date': measurement['date'],
                                    'risk_score': risk_scores[0]['score'],
                                    'confidence': risk_scores[0].get('confidence', 0.85)
                                })
                        
                        if len(risk_history) >= 2:
                            # Create risk evolution chart
                            import matplotlib.pyplot as plt
                            import matplotlib.dates as mdates
                            from datetime import datetime
                            
                            # Parse dates - handle both ISO format and simple date format
                            dates = []
                            for r in risk_history:
                                date_str = r['date']
                                try:
                                    # Try ISO format first (with time)
                                    if 'T' in date_str:
                                        dates.append(datetime.fromisoformat(date_str.replace('Z', '+00:00')))
                                    else:
                                        dates.append(datetime.strptime(date_str, '%Y-%m-%d'))
                                except:
                                    # Fallback: extract just the date part
                                    dates.append(datetime.strptime(date_str[:10], '%Y-%m-%d'))
                            risk_scores = [r['risk_score'] for r in risk_history]
                            
                            fig, ax = plt.subplots(figsize=(12, 6))
                            
                            # Plot line with markers
                            ax.plot(dates, risk_scores, marker='o', linewidth=2.5, markersize=8, 
                                   color='#667eea', label='Stroke Risk')
                            
                            # Fill area under curve with gradient-like effect
                            ax.fill_between(dates, risk_scores, alpha=0.3, color='#667eea')
                            
                            # Add risk level zones
                            ax.axhspan(0, 20, alpha=0.1, color='green', label='Low Risk Zone')
                            ax.axhspan(20, 50, alpha=0.1, color='orange', label='Moderate Risk Zone')
                            ax.axhspan(50, 100, alpha=0.1, color='red', label='High Risk Zone')
                            
                            # Formatting
                            ax.set_xlabel('Date', fontsize=12, fontweight='bold')
                            ax.set_ylabel('Stroke Risk Score (%)', fontsize=12, fontweight='bold')
                            ax.set_title(f'Stroke Risk Evolution - {patient["name"]}', fontsize=14, fontweight='bold', pad=20)
                            ax.set_ylim(0, 100)
                            ax.grid(True, alpha=0.3, linestyle='--')
                            
                            # Format dates on x-axis
                            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d, %Y'))
                            plt.xticks(rotation=45)
                            
                            # Add value labels on points
                            for date, score in zip(dates, risk_scores):
                                ax.annotate(f'{score:.1f}%', 
                                           xy=(date, score), 
                                           xytext=(0, 10),
                                           textcoords='offset points',
                                           ha='center',
                                           fontsize=9,
                                           fontweight='bold',
                                           color='#2E4057')
                            
                            ax.legend(loc='upper right', fontsize=9)
                            plt.tight_layout()
                            
                            st.pyplot(fig)
                            plt.close()
                            
                            # Risk trend analysis
                            risk_change = risk_scores[-1] - risk_scores[0]
                            if risk_change > 10:
                                trend_color = "#ef4444"
                                trend_icon = "📈"
                                trend_message = f"Risk has increased by {risk_change:.1f}% since first assessment. Immediate attention recommended."
                            elif risk_change > 0:
                                trend_color = "#f59e0b"
                                trend_icon = "↗️"
                                trend_message = f"Risk has slightly increased by {risk_change:.1f}%. Continue monitoring closely."
                            elif risk_change > -10:
                                trend_color = "#10b981"
                                trend_icon = "↘️"
                                trend_message = f"Risk has improved by {abs(risk_change):.1f}%. Positive progress observed."
                            else:
                                trend_color = "#10b981"
                                trend_icon = "📉"
                                trend_message = f"Significant improvement! Risk has decreased by {abs(risk_change):.1f}%."
                            
                            st.markdown(f"""
                            <div style="background: white; 
                                        border-left: 4px solid {trend_color}; 
                                        padding: 15px 20px; 
                                        border-radius: 8px; 
                                        margin-top: 15px;
                                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                                <strong style="color: {trend_color};">{trend_icon} Trend Analysis:</strong><br>
                                <span style="color: #4b5563;">{trend_message}</span>
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.info("Need at least 2 measurements with risk scores to track historical trends.")
                    else:
                        st.info("Need at least 2 measurements to track risk over time. Add more health data to see trends.")
                    
                    st.markdown("---")
                    
                    # Move existing forecast functionality here
                    if len(measurements) >= 3:
                        st.markdown("""
                        <div style="display: flex; align-items: center; margin-bottom: 20px;">
                            <h3 style="margin: 0; color: #2E4057;">📈 Health Metrics Forecast</h3>
                            <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                                         color: white; 
                                         padding: 3px 10px; 
                                         border-radius: 10px; 
                                         font-size: 10px; 
                                         font-weight: 600; 
                                         margin-left: 12px;">
                                AI-POWERED
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Create forecasts
                        forecasts = sklearn_forecasting.forecast_all_metrics(measurements, forecast_months=6)
                        
                        if forecasts:
                            metric_options = list(forecasts.keys())
                            if metric_options:
                                selected_metric = st.selectbox(
                                    "Select Health Metric to Forecast",
                                    options=metric_options,
                                    format_func=lambda x: {
                                        'bmi': 'BMI',
                                        'systolic': 'Systolic Blood Pressure',
                                        'diastolic': 'Diastolic Blood Pressure',
                                        'glucose': 'Blood Glucose',
                                        'cholesterol': 'Cholesterol'
                                    }.get(x, x.capitalize())
                                )
                                
                                # Show forecast for selected metric
                                forecast_data = forecasts[selected_metric]
                                
                                # Create visualization
                                measurements_df = utils.measurements_to_dataframe(measurements)
                                historical_df = sklearn_forecasting.prepare_data_for_forecast(measurements, selected_metric)
                                
                                if not historical_df.empty and not forecast_data['forecast'].empty:
                                    fig = sklearn_forecasting.visualize_forecast(
                                        forecast_data['forecast'], 
                                        historical_df, 
                                        selected_metric,
                                        patient['name']
                                    )
                                    if fig:
                                        st.pyplot(fig)
                    else:
                        st.info("Need at least 3 measurements for forecasting analysis. Please add more health data.")
            else:
                st.info("No health measurements found for this patient. Add the first measurement to begin tracking.")
            
            # Compact measurement form
            form_expanded = not bool(measurements) or st.session_state.get('show_measurement_form', False)
            with st.expander("Add New Health Measurement", expanded=form_expanded):
                with st.form("health_measurement_form"):
                    st.write("Enter New Health Measurements")
                    
                    # Pre-fill with latest values if available
                    default_values = {
                        "age": age,
                        "bmi": 25.0,
                        "systolic": 120,
                        "diastolic": 80,
                        "glucose": 100,
                        "cholesterol": 180,
                        "smoking": "Never Smoked",
                        "has_hypertension": 0,
                        "has_diabetes": 0,
                        "has_heart_disease": 0
                    }
                    
                    if measurements:
                        latest_measurement = measurements[0]
                        for key in default_values:
                            if key in latest_measurement:
                                default_values[key] = latest_measurement[key]
                    
                    # Form inputs
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        bmi = st.number_input("BMI", min_value=10.0, max_value=50.0, value=float(default_values["bmi"]), step=0.1)
                        systolic = st.number_input("Systolic Blood Pressure (mmHg)", min_value=80, max_value=220, value=int(default_values["systolic"]))
                        diastolic = st.number_input("Diastolic Blood Pressure (mmHg)", min_value=40, max_value=140, value=int(default_values["diastolic"]))
                        glucose = st.number_input("Blood Glucose (mg/dL)", min_value=70, max_value=300, value=int(default_values["glucose"]))
                    
                    with col2:
                        cholesterol = st.number_input("Cholesterol (mg/dL)", min_value=100, max_value=300, value=int(default_values["cholesterol"]))
                        smoking = st.selectbox("Smoking Status", 
                                             options=["Never Smoked", "Former Smoker", "Current Smoker"],
                                             index=["Never Smoked", "Former Smoker", "Current Smoker"].index(default_values["smoking"]))
                        
                        # Risk factor checkboxes
                        has_hypertension = st.checkbox("Has Hypertension", value=bool(default_values["has_hypertension"]))
                        has_diabetes = st.checkbox("Has Diabetes", value=bool(default_values["has_diabetes"]))
                        has_heart_disease = st.checkbox("Has Heart Disease", value=bool(default_values["has_heart_disease"]))
                    
                    # Submit button
                    if st.form_submit_button("Save Measurements"):
                        # Create measurement record
                        measurement = {
                            "id": str(uuid.uuid4()),
                            "patient_id": patient["id"],
                            "date": datetime.now().isoformat(),
                            "age": age,
                            "bmi": bmi,
                            "systolic": systolic,
                            "diastolic": diastolic,
                            "glucose": glucose,
                            "cholesterol": cholesterol,
                            "smoking": smoking,
                            "has_hypertension": 1 if has_hypertension else 0,
                            "has_diabetes": 1 if has_diabetes else 0,
                            "has_heart_disease": 1 if has_heart_disease else 0
                        }
                        
                        # Save to database
                        measurement_id = database.save_measurement(measurement)
                        
                        # Calculate risk scores if models are available
                        if st.session_state.ml_models:
                            risk_data = models.predict_stroke_risk(measurement, st.session_state.ml_models)
                            
                            # Save risk predictions
                            models.save_risk_prediction(patient["id"], measurement_id, risk_data, database)
                            
                            # Generate AI recommendations
                            analysis = ai_integration.get_llm_analysis(patient, risk_data, measurement)
                            
                            # Save recommendations
                            ai_integration.save_ai_recommendations(patient["id"], measurement_id, analysis, database)
                        
                        st.session_state.notification = "Measurements saved successfully"
                        st.session_state.show_measurement_form = False
                        st.rerun()
        else:
            st.error("Patient not found.")
    else:
        # Show welcome page when no patient selected - Redesigned for better proportions
        st.markdown("<br><br>", unsafe_allow_html=True)
        
        # Center the logo with controlled size
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            st.image("static/logo.jpg", width=250)
        
        st.markdown("<br><br>", unsafe_allow_html=True)
        
        # Quick Patient Search Section - centered
        st.markdown("""
        <div style="text-align: center;">
            <h3 style="color: #2E4057; font-size: 22px; margin-bottom: 20px;">Quick Patient Access</h3>
        </div>
        """, unsafe_allow_html=True)
        
        # Create columns for better layout
        search_col1, search_col2, search_col3 = st.columns([1, 2, 1])
        
        with search_col2:
            # Patient search input
            search_query = st.text_input(
                "Enter patient name or hospital ID:", 
                placeholder="e.g. John Smith or H12345",
                help="Search for a patient by name or hospital ID to access their dashboard directly"
            )
            
            if search_query and len(search_query.strip()) >= 2:
                # Get all patients and search
                patients = database.get_patients()
                
                # Filter patients based on search query
                matching_patients = []
                search_lower = search_query.lower().strip()
                
                for patient in patients:
                    patient_name = patient['name'].lower()
                    hospital_id = str(patient.get('id', '')).lower()
                    
                    if search_lower in patient_name or search_lower in hospital_id:
                        matching_patients.append(patient)
                
                if matching_patients:
                    st.write("**Found patients:**")
                    for patient in matching_patients[:5]:  # Show max 5 results
                        patient_name = patient['name']
                        if st.button(f"📊 {patient_name} (ID: {patient['id']})", key=f"patient_{patient['id']}"):
                            st.session_state.selected_patient = patient['id']
                            st.session_state.page = 'dashboard'
                            st.rerun()
                elif search_query.strip():
                    st.info("No patients found matching your search.")
        
        st.markdown("---")
        
        # Feature cards layout
        st.markdown("""
        <div style="text-align: center; margin-bottom: 30px;">
            <h2 style="color: #2E4057; margin-bottom: 10px;">Advanced Healthcare Analytics Platform</h2>
            <p style="font-size: 18px; color: #666; margin-bottom: 40px;">
                Comprehensive patient monitoring with AI-powered stroke risk prediction and personalized health recommendations
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Feature cards in columns
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 30px 20px; border-radius: 10px; text-align: center; height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <h3 style="color: #2E4057; margin-bottom: 20px; font-size: 20px;">📊 Patient Analytics</h3>
                    <p style="color: #666; font-size: 15px; line-height: 1.5; margin: 0;">Comprehensive health data management with advanced visualization of patient metrics and trends</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 30px 20px; border-radius: 10px; text-align: center; height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <h3 style="color: #2E4057; margin-bottom: 20px; font-size: 20px;">🧠 AI Risk Assessment</h3>
                    <p style="color: #666; font-size: 15px; line-height: 1.5; margin: 0;">Machine learning-powered stroke risk prediction with ensemble modeling for accurate assessments</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 30px 20px; border-radius: 10px; text-align: center; height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <h3 style="color: #2E4057; margin-bottom: 20px; font-size: 20px; white-space: nowrap;">💡 Smart Recommendations</h3>
                    <p style="color: #666; font-size: 15px; line-height: 1.5; margin: 0;">AI-generated personalized health recommendations based on individual patient data and medical guidelines</p>
                </div>
            </div>
            """, unsafe_allow_html=True)

elif st.session_state.page == 'patient list':
    st.title("Patient Management")
    
    # CSV BULK IMPORT SECTION
    with st.expander("📤 Bulk Import Patients from CSV/Excel", expanded=False):
        st.markdown("""
        Upload a CSV or Excel file to import multiple patients at once. The file should have the following columns:
        - **name** (required)
        - **dob** (required, format: YYYY-MM-DD)
        - **gender** (required, Male/Female)
        """)
        
        uploaded_file = st.file_uploader("Choose a CSV or Excel file", type=['csv', 'xlsx'], key="bulk_import")
        
        if uploaded_file is not None:
            try:
                # Read file based on type
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                st.write(f"**Preview:** Found {len(df)} patients in file")
                st.dataframe(df.head(10))
                
                # Validate required columns
                required_cols = ['name', 'dob', 'gender']
                missing_cols = [col for col in required_cols if col not in df.columns]
                
                if missing_cols:
                    st.error(f"Missing required columns: {', '.join(missing_cols)}")
                else:
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.success(f"✅ File is valid and ready to import {len(df)} patients")
                    with col2:
                        if st.button("🚀 Import Patients", type="primary", use_container_width=True):
                            success_count = 0
                            error_count = 0
                            
                            with st.spinner(f"Importing {len(df)} patients..."):
                                for idx, row in df.iterrows():
                                    try:
                                        # Validate and normalize required fields
                                        name = str(row['name']).strip()
                                        gender = str(row['gender']).strip()
                                        
                                        # Handle DOB - convert pandas Timestamp to date string
                                        dob_value = row['dob']
                                        if pd.notna(dob_value):
                                            if isinstance(dob_value, pd.Timestamp):
                                                dob = dob_value.strftime('%Y-%m-%d')
                                            else:
                                                dob = str(dob_value).split()[0]  # Remove time if present
                                        else:
                                            raise ValueError("DOB is missing")
                                        
                                        # Validate required fields
                                        if not name or name == 'nan':
                                            raise ValueError("Name is missing or empty")
                                        if not gender or gender == 'nan':
                                            raise ValueError("Gender is missing or empty")
                                        if not dob or dob == 'nan':
                                            raise ValueError("DOB is missing or empty")
                                        
                                        # Create patient
                                        patient_id = database.save_patient({
                                            'name': name,
                                            'dob': dob,
                                            'gender': gender
                                        })
                                        
                                        # If health metrics are provided, add them
                                        if 'bmi' in df.columns and 'systolic' in df.columns:
                                            age = utils.calculate_age(dob)
                                            
                                            # Safely extract numeric values with NaN handling
                                            def safe_float(val, default):
                                                return float(val) if pd.notna(val) else default
                                            
                                            def safe_int(val, default):
                                                return int(val) if pd.notna(val) else default
                                            
                                            def safe_str(val, default):
                                                return str(val).strip() if pd.notna(val) and str(val).strip() != 'nan' else default
                                            
                                            measurement_data = {
                                                'age': age,
                                                'bmi': safe_float(row.get('bmi'), 25.0),
                                                'systolic': safe_int(row.get('systolic'), 120),
                                                'diastolic': safe_int(row.get('diastolic'), 80),
                                                'glucose': safe_int(row.get('glucose'), 100),
                                                'cholesterol': safe_int(row.get('cholesterol'), 180),
                                                'smoking': safe_str(row.get('smoking'), 'Never Smoked'),
                                                'has_hypertension': safe_int(row.get('has_hypertension'), 0),
                                                'has_diabetes': safe_int(row.get('has_diabetes'), 0),
                                                'has_heart_disease': safe_int(row.get('has_heart_disease'), 0),
                                                'gender': gender
                                            }
                                            
                                            # Add measurement
                                            measurement_data['patient_id'] = patient_id
                                            measurement_id = database.save_measurement(measurement_data)
                                            
                                            # Calculate and save risk score
                                            try:
                                                # Load models fresh if not in session state (for reliability)
                                                ml_models = st.session_state.ml_models or models.load_trained_models()
                                                risk_result = models.predict_stroke_risk(measurement_data, ml_models)
                                                ensemble_score = risk_result['ensemble']['score']
                                                ensemble_confidence = risk_result['ensemble']['confidence']
                                                
                                                database.save_risk_score({
                                                    'patient_id': patient_id,
                                                    'measurement_id': measurement_id,
                                                    'model_name': 'ensemble',
                                                    'model_version': '1.0',
                                                    'score': ensemble_score,
                                                    'confidence': ensemble_confidence
                                                })
                                                print(f"✓ Risk score saved for {name}: {ensemble_score}%")
                                            except Exception as risk_error:
                                                print(f"ERROR calculating/saving risk score for {name}: {risk_error}")
                                                import traceback
                                                traceback.print_exc()
                                        
                                        success_count += 1
                                    except Exception as e:
                                        error_count += 1
                                        st.warning(f"Error importing row {idx + 1}: {str(e)}")
                            
                            # Use toast for persistent notification across rerun
                            if error_count > 0:
                                st.toast(f"✅ Import completed! {success_count} patients imported, {error_count} errors.", icon="⚠️")
                            else:
                                st.toast(f"✅ Successfully imported {success_count} patients!", icon="✅")
                            st.rerun()
                            
            except Exception as e:
                st.error(f"Error reading file: {str(e)}")
    
    st.markdown("---")
    
    # Get all patients
    patients = database.get_patients()
    
    if patients:
        # Display patients as clickable list
        st.subheader("Click on a patient to view their dashboard:")
        
        for patient in patients:
            col1, col2, col3, col4 = st.columns([3, 1, 1, 2])
            
            with col1:
                if st.button(f"👤 {patient['name']}", key=f"select_patient_{patient['id']}"):
                    st.session_state.selected_patient = patient['id']
                    st.session_state.page = 'dashboard'
                    st.rerun()
            
            with col2:
                st.write(patient['gender'])
            
            with col3:
                age = utils.calculate_age(patient['dob'])
                st.write(f"{age} years")
            
            with col4:
                created_date = utils.format_date(patient['created_at'])
                st.write(f"Added: {created_date}")
        
        st.markdown("---")
        
        # Also show traditional table view for reference
        if st.checkbox("Show table view"):
            patient_df = pd.DataFrame(patients)
            patient_df['age'] = patient_df['dob'].apply(utils.calculate_age)
            patient_df['created_at'] = patient_df['created_at'].apply(utils.format_date)
            patient_df = patient_df[['name', 'gender', 'age', 'created_at']]
            patient_df.columns = ['Name', 'Gender', 'Age', 'Created At']
            
            st.dataframe(patient_df)
    else:
        st.info("No patients found. Add a new patient to begin.")

elif st.session_state.page == 'analytics':
    st.title("📊 Population Analytics Dashboard")
    
    # AI-Powered Badge
    st.markdown("""
    <span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                 color: white; 
                 padding: 6px 14px; 
                 border-radius: 20px; 
                 font-size: 12px; 
                 font-weight: 600;">
        ⚡ AI-POWERED ANALYTICS
    </span>
    """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # Get all patients and their data
    all_patients = database.get_patients()
    
    if not all_patients:
        st.info("No patient data available. Add patients to view analytics.")
    else:
        # Calculate population statistics
        total_patients = len(all_patients)
        
        # Collect all patient data with risk scores
        patient_data = []
        for patient in all_patients:
            measurements = database.get_measurements_for_patient(patient['id'])
            if measurements:
                latest_measurement = measurements[0]
                risk_scores = database.get_risk_scores_for_measurement(latest_measurement['id'])
                if risk_scores:
                    patient_data.append({
                        'patient': patient,
                        'measurement': latest_measurement,
                        'risk_score': risk_scores[0]['score'],
                        'confidence': risk_scores[0].get('confidence', 0.85)
                    })
        
        # Key metrics at the top
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                        padding: 25px; 
                        border-radius: 12px; 
                        text-align: center;">
                <div style="color: white; font-size: 36px; font-weight: 800; margin-bottom: 5px;">{total_patients}</div>
                <div style="color: rgba(255,255,255,0.9); font-size: 14px;">Total Patients</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            patients_with_risk = len(patient_data)
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); 
                        padding: 25px; 
                        border-radius: 12px; 
                        text-align: center;">
                <div style="color: white; font-size: 36px; font-weight: 800; margin-bottom: 5px;">{patients_with_risk}</div>
                <div style="color: rgba(255,255,255,0.9); font-size: 14px;">Risk Assessed</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            if patient_data:
                avg_risk = sum([p['risk_score'] for p in patient_data]) / len(patient_data)
                st.markdown(f"""
                <div style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); 
                            padding: 25px; 
                            border-radius: 12px; 
                            text-align: center;">
                    <div style="color: white; font-size: 36px; font-weight: 800; margin-bottom: 5px;">{avg_risk:.1f}%</div>
                    <div style="color: rgba(255,255,255,0.9); font-size: 14px;">Avg Risk Score</div>
                </div>
                """, unsafe_allow_html=True)
        
        with col4:
            high_risk_count = len([p for p in patient_data if p['risk_score'] >= 50])
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); 
                        padding: 25px; 
                        border-radius: 12px; 
                        text-align: center;">
                <div style="color: white; font-size: 36px; font-weight: 800; margin-bottom: 5px;">{high_risk_count}</div>
                <div style="color: rgba(255,255,255,0.9); font-size: 14px;">High Risk Patients</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Risk Distribution Section
        if patient_data:
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Risk Distribution")
                
                # Categorize patients by risk level
                low_risk = len([p for p in patient_data if p['risk_score'] < 20])
                moderate_risk = len([p for p in patient_data if 20 <= p['risk_score'] < 50])
                high_risk = len([p for p in patient_data if 50 <= p['risk_score'] < 80])
                critical_risk = len([p for p in patient_data if p['risk_score'] >= 80])
                
                # Create risk distribution visualization
                risk_categories = ['Low\n(<20%)', 'Moderate\n(20-50%)', 'High\n(50-80%)', 'Critical\n(≥80%)']
                risk_counts = [low_risk, moderate_risk, high_risk, critical_risk]
                risk_colors = ['#10b981', '#f59e0b', '#ef4444', '#dc2626']
                
                # Create bar chart using matplotlib
                import matplotlib.pyplot as plt
                
                fig, ax = plt.subplots(figsize=(10, 6))
                bars = ax.bar(risk_categories, risk_counts, color=risk_colors, alpha=0.8)
                
                # Add value labels on bars
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{int(height)}',
                           ha='center', va='bottom', fontsize=12, fontweight='bold')
                
                ax.set_ylabel('Number of Patients', fontsize=12, fontweight='bold')
                ax.set_title('Patient Risk Distribution', fontsize=14, fontweight='bold', pad=20)
                ax.set_ylim(0, max(risk_counts) * 1.2 if max(risk_counts) > 0 else 1)
                
                st.pyplot(fig)
                plt.close()
            
            with col2:
                st.subheader("Demographics Overview")
                
                # Gender distribution
                male_count = len([p for p in all_patients if p['gender'] == 'Male'])
                female_count = len([p for p in all_patients if p['gender'] == 'Female'])
                
                fig, ax = plt.subplots(figsize=(10, 6))
                
                gender_data = [male_count, female_count]
                gender_labels = [f'Male\n({male_count})', f'Female\n({female_count})']
                colors = ['#3b82f6', '#ec4899']
                
                ax.pie(gender_data, labels=gender_labels, colors=colors, autopct='%1.1f%%',
                      startangle=90, textprops={'fontsize': 12, 'fontweight': 'bold'})
                ax.set_title('Gender Distribution', fontsize=14, fontweight='bold', pad=20)
                
                st.pyplot(fig)
                plt.close()
        
        st.markdown("---")
        
        # High-Risk Patients Alert
        if high_risk_count > 0:
            st.subheader("🚨 High-Risk Patients Requiring Attention")
            
            high_risk_patients = [p for p in patient_data if p['risk_score'] >= 50]
            high_risk_patients.sort(key=lambda x: x['risk_score'], reverse=True)
            
            for patient_info in high_risk_patients[:10]:  # Show top 10 high-risk patients
                patient = patient_info['patient']
                risk_score = patient_info['risk_score']
                
                # Determine risk color
                if risk_score >= 80:
                    risk_color = "#dc2626"
                    risk_level = "CRITICAL"
                else:
                    risk_color = "#ef4444"
                    risk_level = "HIGH"
                
                st.markdown(f"""
                <div style="background: white; 
                            border-left: 4px solid {risk_color}; 
                            padding: 15px 20px; 
                            margin-bottom: 10px; 
                            border-radius: 8px; 
                            box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-weight: 700; color: #1f2937; font-size: 16px;">{patient['name']}</span>
                            <span style="color: #6b7280; margin-left: 10px;">•</span>
                            <span style="color: #6b7280; margin-left: 10px;">{patient['gender']}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 15px;">
                            <div style="text-align: right;">
                                <div style="color: {risk_color}; font-weight: 700; font-size: 18px;">{risk_score:.0f}%</div>
                                <div style="color: {risk_color}; font-size: 11px; font-weight: 600;">{risk_level} RISK</div>
                            </div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

elif st.session_state.page == 'settings':
    st.title("Settings")
    st.info("Settings panel coming soon...")

# Footer
st.markdown("---")
st.markdown("**PrescpHealth © 2025 Pentrest Global | Advanced stroke prediction platform with personalized treatment planning**")