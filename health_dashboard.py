"""
Health metrics dashboard visualization for PrescpHealth application
"""
import streamlit as st
import utils

def create_simple_health_dashboard(current_measurement, previous_measurement=None):
    """
    Create a compact health dashboard with organized metrics layout
    """
    # Extract values with defaults
    systolic = current_measurement.get('systolic', 0)
    diastolic = current_measurement.get('diastolic', 0)
    glucose = current_measurement.get('glucose', 0)
    cholesterol = current_measurement.get('cholesterol', 0)
    bmi = current_measurement.get('bmi', 0)
    
    # Calculate trends if previous measurement exists
    if previous_measurement:
        prev_systolic = previous_measurement.get('systolic', systolic)
        prev_diastolic = previous_measurement.get('diastolic', diastolic)
        prev_glucose = previous_measurement.get('glucose', glucose)
        prev_cholesterol = previous_measurement.get('cholesterol', cholesterol)
        prev_bmi = previous_measurement.get('bmi', bmi)
        
        systolic_delta = systolic - prev_systolic
        diastolic_delta = diastolic - prev_diastolic
        glucose_delta = glucose - prev_glucose
        cholesterol_delta = cholesterol - prev_cholesterol
        bmi_delta = round(bmi - prev_bmi, 1)
    else:
        systolic_delta = None
        diastolic_delta = None
        glucose_delta = None
        cholesterol_delta = None
        bmi_delta = None
    
    # Compact metrics in a grid layout
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**Cardiovascular**")
        
        # Combined blood pressure display
        bp_change = ""
        if systolic_delta is not None and diastolic_delta is not None:
            if systolic_delta != 0 or diastolic_delta != 0:
                bp_change = f" ({systolic_delta:+}/{diastolic_delta:+})"
        
        st.markdown(f"""
        <div style="background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
            <strong>Blood Pressure</strong><br>
            {systolic}/{diastolic} mmHg{bp_change}
        </div>
        """, unsafe_allow_html=True)
        
        st.metric(
            label="Cholesterol", 
            value=f"{cholesterol} mg/dL",
            delta=cholesterol_delta,
            delta_color="inverse",
            help="Total cholesterol. Desirable: <200 | Borderline: 200-239 | High: 240+"
        )
        
    with col2:
        st.markdown("**Metabolic**")
        
        st.metric(
            label="Blood Glucose", 
            value=f"{glucose} mg/dL",
            delta=glucose_delta,
            delta_color="inverse",
            help="Blood sugar level. Normal: 70-99 | Pre-diabetes: 100-125 | Diabetes: 126+"
        )
        
        st.metric(
            label="BMI", 
            value=f"{bmi:.1f}",
            delta=bmi_delta,
            delta_color="inverse",
            help="Body Mass Index. Normal: 18.5-24.9 | Overweight: 25-29.9 | Obese: 30+"
        )
        
    with col3:
        st.markdown("**Risk Factors**")
        
        # Smoking status with color coding
        smoking_status = current_measurement.get('smoking', 'Unknown')
        if smoking_status == 'Current Smoker':
            smoking_color = "#e74c3c"
        elif smoking_status == 'Former Smoker':
            smoking_color = "#f39c12"
        else:
            smoking_color = "#27ae60"
        
        st.markdown(f"""
        <div style="background-color: {smoking_color}; color: white; padding: 8px; border-radius: 5px; text-align: center; margin-bottom: 10px;">
            <strong>Smoking</strong><br>
            {smoking_status}
        </div>
        """, unsafe_allow_html=True)
        
        # Medical conditions
        conditions = []
        if current_measurement.get('has_hypertension', 0):
            conditions.append("Hypertension")
        if current_measurement.get('has_diabetes', 0):
            conditions.append("Diabetes")
        if current_measurement.get('has_heart_disease', 0):
            conditions.append("Heart Disease")
        
        if conditions:
            st.markdown("**Conditions:**")
            for condition in conditions:
                st.write(f"• {condition}")
        else:
            st.markdown(f"""
            <div style="background-color: #27ae60; color: white; padding: 8px; border-radius: 5px; text-align: center;">
                <strong>No Known<br>Conditions</strong>
            </div>
            """, unsafe_allow_html=True)