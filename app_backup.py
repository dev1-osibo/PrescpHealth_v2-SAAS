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

# Page configuration
st.set_page_config(
    page_title="PrescpHealth",
    page_icon="🩺",
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
if 'page' not in st.session_state:
    st.session_state.page = 'dashboard'
if 'show_new_patient_form' not in st.session_state:
    st.session_state.show_new_patient_form = False
if 'notification' not in st.session_state:
    st.session_state.notification = None

# Create a sidebar for navigation with logo
st.sidebar.image("static/logo.jpg", width=200)
st.sidebar.markdown("**Predict • Prescribe • Protect**")

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
                    # Risk Score Prominently Displayed
                    risk_scores = database.get_risk_scores_for_measurement(latest_measurement["id"])
                    if risk_scores:
                        risk_score = risk_scores[0]['score']
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            # Risk gauge
                            risk_gauge.create_simple_risk_gauge(risk_score)
                        
                        with col2:
                            # Quick health summary
                            st.markdown("#### Current Health Status")
                            
                            # Health indicators in a compact format
                            health_indicators = []
                            
                            # Blood pressure check
                            if latest_measurement['systolic'] >= 140 or latest_measurement['diastolic'] >= 90:
                                health_indicators.append("🔴 High Blood Pressure")
                            elif latest_measurement['systolic'] >= 120:
                                health_indicators.append("🟡 Elevated Blood Pressure")
                            else:
                                health_indicators.append("🟢 Normal Blood Pressure")
                            
                            # BMI check
                            bmi = latest_measurement['bmi']
                            if bmi >= 30:
                                health_indicators.append("🔴 Obesity")
                            elif bmi >= 25:
                                health_indicators.append("🟡 Overweight")
                            else:
                                health_indicators.append("🟢 Normal Weight")
                            
                            # Glucose check
                            if latest_measurement['glucose'] >= 126:
                                health_indicators.append("🔴 Diabetes Range")
                            elif latest_measurement['glucose'] >= 100:
                                health_indicators.append("🟡 Pre-diabetes Range")
                            else:
                                health_indicators.append("🟢 Normal Glucose")
                            
                            # Display indicators
                            for indicator in health_indicators:
                                st.write(indicator)
                    
                    # Quick actions
                    st.markdown("#### Quick Actions")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("📊 Add New Measurement", use_container_width=True):
                            st.session_state.show_measurement_form = True
                    with col2:
                        if st.button("📈 View Trends", use_container_width=True):
                            st.session_state.active_tab = 1
                    with col3:
                        if st.button("🔮 View Forecast", use_container_width=True):
                            st.session_state.active_tab = 2
                
                with health_tab:
                    # Use the existing health dashboard with tooltips
                    current_measurement = measurements[0]
                    previous_measurement = measurements[1] if len(measurements) > 1 else None
                    
                    health_dashboard.create_simple_health_dashboard(
                        current_measurement=current_measurement,
                        previous_measurement=previous_measurement
                    )
                
                with analytics_tab:
                    # Move existing forecast functionality here
                    if len(measurements) >= 3:
                        st.subheader("Health Metrics Forecast")
                        
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
                                
                                if not historical_df.empty and len(forecast_data['dates']) > 0:
                                    fig = sklearn_forecasting.visualize_forecast(
                                        forecast_data, 
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
        # Landing page with centered branding
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Center the logo using empty columns
        _, center_col, _ = st.columns([1, 3, 1])
        with center_col:
            st.image("static/logo.jpg", use_container_width=True)
            st.markdown("""
            <div style="text-align: center; margin-top: -10px;">
                <h3 style="color: #666; font-weight: 500; font-size: 22px; margin: 0; white-space: nowrap;">Predict • Prescribe • Protect</h3>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Quick Patient Search Section
        st.markdown("### Quick Patient Access")
        
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
    st.title("Healthcare Analytics")
    st.info("Analytics dashboard coming soon...")

elif st.session_state.page == 'settings':
    st.title("Settings")
    st.info("Settings panel coming soon...")

# Footer
st.markdown("---")
st.markdown("**PrescpHealth © 2025 Pentrest Global | Advanced stroke prediction platform with personalized treatment planning**")