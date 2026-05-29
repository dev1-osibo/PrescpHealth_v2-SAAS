# PrescpHealth - AI-Powered Healthcare Platform

## Overview

PrescpHealth is a comprehensive healthcare platform that combines machine learning, time-series forecasting, and AI to provide stroke risk prediction, health trajectory analysis, and personalized health recommendations. The application monitors patient health metrics over time, predicts future health trends, and generates intelligent recommendations using OpenAI's API.

The platform is designed for cross-environment compatibility, running seamlessly on both Replit (with PostgreSQL) and local environments (with SQLite), making it flexible for development and deployment scenarios.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
**Technology**: Streamlit
- **Rationale**: Provides rapid development of interactive data applications with built-in state management
- **Design Pattern**: Single-page application with session state for navigation and data persistence
- **User Interface**: Multi-page navigation system with dashboard, patient list, analytics, and settings sections

### Database Architecture
**Dual Database Support**: PostgreSQL (Replit) / SQLite (Local)
- **Rationale**: Enables cross-environment deployment without code changes
- **Schema Design**: Three core tables - `patients`, `measurements`, and `risk_scores`
- **Data Model**: Relational structure with patient-centric design, one-to-many relationship between patients and measurements
- **Storage Strategy**: Automatic detection of environment to select appropriate database backend

### Machine Learning Pipeline
**Ensemble Model Approach**: XGBoost + Random Forest + Logistic Regression
- **Rationale**: Combines multiple algorithms to improve prediction accuracy and confidence
- **Primary Use Case**: Stroke risk prediction based on 11 health indicators
- **Model Persistence**: Pickle-based serialization stored in `/models` directory
- **Training Data**: Synthetic data generation with realistic correlations between health metrics (age, BMI, blood pressure, glucose, cholesterol, etc.)
- **Features**: Age, gender, BMI, blood pressure (systolic/diastolic), glucose, cholesterol, smoking status, hypertension, diabetes, heart disease

### Time-Series Forecasting System
**Dual Forecasting Approach**: Facebook Prophet + Scikit-learn
- **Rationale**: Prophet for seasonal patterns, scikit-learn for polynomial trends
- **Metrics Forecasted**: BMI, blood pressure (systolic/diastolic), glucose, cholesterol
- **Forecast Horizon**: Configurable periods (default: 6 months)
- **Visualization**: Matplotlib-based charts with confidence intervals and trend lines
- **Risk Trajectory**: Combines forecasted metrics with ML models to predict future stroke risk

### AI Integration Layer
**LLM Provider**: OpenAI API
- **Purpose**: Generate personalized health recommendations and analysis
- **Fallback Strategy**: Standard rule-based recommendations when API unavailable
- **Context Building**: Structured patient data including current measurements, risk scores, and confidence levels
- **Data Sanitization**: Converts numpy types to native Python types before API calls to prevent serialization issues

### Visualization Components
**Risk Gauge System**: Color-coded risk display (green/orange/red)
- **Thresholds**: Low (<20%), Moderate (20-50%), High (>50%)
- **Trend Analysis**: Delta calculations comparing current vs. previous measurements

**Health Dashboard**: Organized metric display
- **Categories**: Cardiovascular (BP, cholesterol) and Metabolic (glucose, BMI)
- **Status Indicators**: Clinical classification (normal, elevated, hypertension stages)
- **Change Tracking**: Visual indicators for metric improvements or deteriorations

**Forecasting Visualizations**: Interactive time-series charts
- **Components**: Historical data points, forecast line, confidence bands
- **Customization**: Matplotlib-based with date formatting and annotation support

### Data Generation Module
**Synthetic Patient Data**: Realistic health metric simulation
- **Rationale**: Enables demonstration and testing without real patient data
- **Statistical Modeling**: Age-based correlations, BMI influences on BP and cholesterol
- **Risk Profiles**: Varied distribution from low to high-risk patients
- **Temporal Patterns**: Multiple measurements per patient with realistic progression

**Demo Database Population** (`populate_demo_database_bulk.py`)
- **Purpose**: Rapidly populate database with 120+ diverse demo patients for client presentations
- **Performance**: Bulk insertion strategy - generates all data in memory, then batch inserts to minimize database round trips
- **Optimization**: Uses PostgreSQL `execute_values` for high-throughput inserts; falls back to SQLite `executemany`
- **Data Volume**: Each patient includes 3-6 months of historical measurements plus current assessment and AI risk scores
- **Usage**: `python populate_demo_database_bulk.py [num_patients]` (default: 120 patients)
- **Completion Time**: ~60-90 seconds for 120 patients with full historical data

### Session Management
**Streamlit Session State**: Persistent data across interactions
- **Navigation**: Page routing and state preservation
- **Patient Selection**: Active patient and measurement tracking
- **Model Cache**: Loaded ML models stored in session to avoid repeated disk I/O
- **Notifications**: User feedback system for actions and errors

## External Dependencies

### AI/ML Services
- **OpenAI API**: GPT-based health recommendations and analysis
  - Environment variable: `OPENAI_API_KEY`
  - Fallback: Rule-based recommendations when unavailable
  
### Database Systems
- **PostgreSQL**: Production database on Replit
  - Library: `psycopg2-binary`
  - Connection via environment detection
- **SQLite**: Local development database
  - Built-in Python support
  - File-based storage: `prescphealth.db`

### Machine Learning Libraries
- **XGBoost**: Gradient boosting for stroke risk prediction
- **Scikit-learn**: Random Forest, Logistic Regression, preprocessing, and polynomial forecasting
- **Prophet**: Facebook's time-series forecasting library for seasonal patterns

### Data Processing & Visualization
- **Pandas**: Data manipulation and time-series handling
- **NumPy**: Numerical computations and array operations
- **Matplotlib**: Chart generation for health metrics and forecasts

### Web Framework
- **Streamlit**: Application framework and UI components
  - Version: >=1.45.0
  - Port configuration: 5000 (Replit), default (local)

### Python Environment
- **Minimum Version**: Python 3.10+
- **Recommended**: Python 3.11
- **Package Management**: pip with `local_requirements.txt`

## Recent Updates

### October 17, 2025

#### AI-Powered Platform Enhancements
- **Prominent AI Branding**: Added "⚡ AI-POWERED PLATFORM" badge to sidebar with purple gradient design
- **Enhanced Stroke Risk Display**: Upgraded stroke risk assessment to H2 heading with "AI-POWERED" badge for maximum visibility
- **AI Health Assistant Chat Interface**: NEW interactive free-text chat allowing healthcare providers to ask custom questions about patient health data
  - Function: `ask_custom_question()` in ai_integration.py
  - Powered by GPT-4o model
  - Context-aware responses using patient data, measurements, and risk scores
  - Graceful fallback handling for API errors
- **AI-Generated Recommendations Display**: Prominently displays saved AI recommendations with GPT-4o badge and source attribution
- **AI-Powered Forecasting Indicators**: Added AI-POWERED badges to time-series forecasting section
- **Integrated AI Philosophy**: All features showcase AI capabilities while maintaining stroke prediction as flagship feature within comprehensive hospital platform

#### Demo Database Population Tool
- Created optimized bulk insertion script for client demonstrations
- Successfully generates 120 diverse patients with realistic health profiles
- Includes varied risk levels: Low (18.3%), Moderate (81.7%), High, Critical
- Gender-balanced distribution: ~48% Male, ~52% Female
- Age ranges from 18-90+ with realistic distribution weighted toward 60-80 age group
- Each patient has 3-6 months of historical health measurements for trend analysis
- Automated AI risk score calculation for all patients using ensemble ML models
- Performance: 60-90 seconds for complete 120-patient dataset with 670+ measurements

#### Advanced Platform Features (October 17, 2025)

**Modern Stroke Risk UI Redesign**
- Replaced basic gauge with sophisticated card-based design featuring:
  - Large color-coded risk score display (120px gradient box)
  - Risk level with icon-based visual indicators (✓, ⚠, !, !!)
  - Clinical interpretation and action messages
  - Animated progress bar with risk zones (0-20% Low, 20-50% Moderate, 50-100% High/Critical)
  - AI-POWERED badge with purple gradient branding

**Population Analytics Dashboard** (Analytics Page)
- Comprehensive overview of all patients with key metrics:
  - 4 gradient metric cards: Total Patients, Risk Assessed, Average Risk Score, High-Risk Count
  - Risk Distribution bar chart showing patient counts across Low/Moderate/High/Critical categories
  - Demographics pie chart with gender distribution
  - High-Risk Patient Alert List showing top 10 patients requiring immediate attention
  - Color-coded patient cards with risk scores and clinical status

**Risk Factor Analysis** (Patient Overview)
- Horizontal bar chart visualization showing individual factor contributions to stroke risk
- Analyzes 10+ health factors: Age, Blood Pressure (Systolic/Diastolic), BMI, Glucose, Cholesterol, Smoking, Hypertension, Diabetes, Heart Disease
- Color-coded impact levels: Red (High ≥20%), Orange (Moderate 10-20%), Yellow (Low <10%), Green (Normal)
- Intelligent alert box highlighting high-impact factors (≥15% contribution)
- Clinical value annotations showing actual metric values

**PDF Clinical Report Export** (`pdf_reports.py`)
- Professional PDF report generation using ReportLab library
- Comprehensive report sections:
  - Patient demographics table with all identifying information
  - AI-powered stroke risk assessment with color-coded level
  - Current health metrics table with clinical status indicators
  - AI-generated recommendations section
  - Clinical interpretation and action guidance
  - Professional branding and disclaimer footer
- One-click download button with auto-generated filename (patient_name_date.pdf)

**Historical Risk Tracking** (Analytics & Forecasting Tab)
- Time-series line chart showing stroke risk evolution over patient history
- Features:
  - Risk zone overlays (Green: 0-20%, Orange: 20-50%, Red: 50-100%)
  - Data point annotations with exact risk percentages
  - ISO 8601 date parsing for compatibility with database timestamps
  - Gradient area fill under risk curve
  - Intelligent trend analysis with color-coded alerts:
    - 📈 Rising risk (>10% increase) - Red alert for immediate attention
    - ↗️ Slight increase (0-10%) - Orange warning for close monitoring
    - ↘️ Improving (<10% decrease) - Green positive progress indicator
    - 📉 Significant improvement (>10% decrease) - Green success message
- Requires minimum 2 measurements with risk scores for visualization

**Bulk CSV/Excel Import** (Patient List Page)
- Mass patient upload functionality supporting CSV and Excel (.xlsx) formats
- Features:
  - File upload with instant preview (first 10 rows)
  - Automatic column validation (name, dob, gender required)
  - Robust data handling:
    - Pandas Timestamp to YYYY-MM-DD conversion for Excel dates
    - NaN/null value detection and validation for required fields
    - Safe numeric conversion with default fallbacks for optional health metrics
  - Optional health data import (BMI, BP, glucose, cholesterol, smoking, conditions)
  - Automatic AI risk score calculation for imported patients with health data
  - Import progress tracking with success/error counts
  - Error handling with summary reporting showing total successful and failed imports
- Supports both basic patient info and complete patient+health data workflows