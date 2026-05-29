# PrescpHealth

A comprehensive healthcare platform leveraging AI and time-series forecasting for patient monitoring, stroke risk prediction, future health trajectory analysis, and intelligent health recommendations.

## Features

- Patient management and health metric tracking
- Machine learning-based stroke risk prediction
- Time-series forecasting of health metrics using scikit-learn models
- Future health risk trajectory analysis
- AI-powered personalized health recommendations
- Interactive data visualization with trend analysis
- Cross-environment compatibility (works in Replit and locally)

## Requirements

- Python 3.10+
- PostgreSQL database (on Replit) or SQLite (locally)
- OpenAI API key for AI recommendations
- Scikit-learn for time-series forecasting
- Matplotlib and Pandas for data visualization and manipulation

## Setup and Installation

### Running on Replit

1. The application is already configured to run on Replit
2. Make sure the environment has all required dependencies (listed in local_requirements.txt)
3. Add your OpenAI API key as an environment variable named `OPENAI_API_KEY`
4. Run the Streamlit app with: `streamlit run app.py --server.port 5000`

### Running Locally

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r local_requirements.txt
   ```
3. Set up your OpenAI API key as an environment variable:
   - On Windows: `set OPENAI_API_KEY=your_api_key`
   - On macOS/Linux: `export OPENAI_API_KEY=your_api_key`
4. Run the application:
   ```
   streamlit run app.py
   ```

## First Time Setup (Demonstration Mode)

1. When running the app for the first time, you'll need to train the ML models
2. Click the "Generate Sample Data & Train Models" button in the sidebar
3. This will create synthetic data and train the prediction models
4. **Note:** This synthetic data generation is for demonstration purposes only and would be replaced with real clinical data in production

## Usage

1. Add patients using the sidebar "Add New Patient" button
2. Enter health measurements for patients
3. Generate historical data (18 months) for time-series analysis
4. View risk predictions and AI-powered recommendations
5. Track health metrics over time with visualizations
6. Explore health metric forecasts for early risk detection
7. Analyze risk trajectory forecasts to see how risk might evolve over time
8. View automated simulations of standard interventions and their impact on future risk scores

## How It Works

### Database

The app uses PostgreSQL in Replit environments and automatically falls back to SQLite when running locally.

### Machine Learning

Three prediction models are used for stroke risk assessment:
- XGBoost classifier
- Random Forest classifier
- Logistic Regression classifier

These models are combined in an ensemble approach for more robust predictions.

### AI Recommendations

The app uses OpenAI's GPT-4o model to:
- Analyze patient health metrics
- Generate personalized health recommendations
- Identify key risk factors

### Time-Series Forecasting

The app uses scikit-learn models to forecast future health metrics:
- Predicts health metric trajectories over 6-12 month periods
- Creates smooth, professional visualizations for clinical settings
- Identifies when metrics will cross clinical thresholds
- Analyzes trend directions and volatility
- Provides early warning for developing health risks

This forecasting capability transforms the application from reactive monitoring to proactive health management by predicting future health states before they occur.

### Demonstration Data Generation (MVP Only)

The current MVP uses advanced synthetic data generation techniques to demonstrate system capabilities:
- Generates 18 months of historical health records for time-series analysis
- Models natural progression patterns in health metrics over time
- Incorporates seasonal effects (winter, holiday seasons) on metrics
- Simulates intervention effects and their impact on health trajectories
- Creates realistic correlation between risk factors and outcomes

**Note:** This synthetic data generation is for demonstration purposes only. In the production version, all data would come from authentic clinical sources through EHR integrations, as detailed in the "Production Vision" section below.

## How Risk Assessment Works

PrescpHealth uses a two-tiered approach to risk assessment:

### Current Risk Calculation

The system uses an ensemble of three machine learning models to assess stroke risk:
- XGBoost classifier
- Random Forest classifier
- Logistic Regression classifier

Each model independently analyzes patient data and produces a probability score. These scores are then combined using a weighted ensemble approach to generate a final risk score between 0-100%. This risk assessment represents the patient's current stroke risk based on their latest health measurements.

### Future Health Trajectory Forecasting

In addition to current risk assessment, the system uses scikit-learn models for time-series forecasting:
- **Health Metric Forecasting**: Predicts future values of individual health metrics (blood pressure, glucose, cholesterol, etc.)
- **Risk Score Trajectory**: Projects how stroke risk will evolve over time based on forecasted health metrics
- **Intervention Simulation**: Models the impact of different interventions on future risk trajectories
- **Early Warning System**: Identifies when metrics might cross clinical thresholds before problems develop
- **Risk Category Transitions**: Predicts if and when a patient might move between risk categories (low/moderate/high)
- **Visualization Clarity**: Produces smooth, professional visualizations without distracting artifacts

The system combines the power of machine learning classification with time-series forecasting to create a comprehensive view of both current risk and future risk trajectory. This dual approach transforms the application from reactive monitoring to proactive health management.

### New Patient Handling

For new patients without historical data:
1. The system calculates an initial risk assessment using only the data collected at the first visit
2. This provides an immediate starting point but with appropriately limited confidence
3. As new measurements are added during subsequent visits, the system builds the patient's health profile
4. With each new measurement, forecasting accuracy improves as real longitudinal data accumulates
5. The system clearly indicates confidence levels to ensure clinicians understand prediction reliability

## Production Vision: EHR Integration and Continuous Learning

This MVP demonstrates the core capabilities of the PrescpHealth platform. The production version will replace synthetic data generation with authentic clinical data and incorporate the following advanced features:

### Direct EHR Integration
- Connect to major Electronic Health Record (EHR) systems via FHIR APIs
- Import structured clinical data, lab results, and patient histories securely
- Set up automated synchronization to maintain up-to-date patient records
- Support for standard healthcare data formats (HL7, FHIR, DICOM)
- Secure, HIPAA-compliant data transfer protocols
- Replace all synthetic data with authentic clinical information

#### New Patient Onboarding in Production
- Search connected healthcare systems via FHIR APIs for existing patient records
- Request historical data from Health Information Exchanges where available
- Import records from patient's previous providers with appropriate consent
- Access public health registries and relevant population health databases
- Link to wearable device data and patient-reported outcomes platforms

### Continuous Learning System
- Implement automated ML pipeline for model retraining as new clinical data arrives
- Train models on real patient outcomes rather than synthetic patterns
- Apply transfer learning to maintain knowledge while incorporating new patterns
- Track model performance metrics to ensure improving accuracy over time
- Dynamic feature importance analysis to adapt to changing risk factors
- Automated model version control for reproducibility and auditability
- Validate predictions against actual clinical outcomes and readjust models accordingly

#### Progressive Confidence Enhancement
- Clearly indicate prediction confidence levels based on available data quantity
- Use similarity matching to compare new patients to established cohorts
- Apply Bayesian methods to update risk estimates as new measurements arrive
- Generate confidence intervals that narrow as more patient-specific data accumulates
- Implement continuous validation against clinical outcomes to refine models

### Enhanced Time-Series Forecasting
- Improve forecasting with real longitudinal patient data spanning years
- Develop patient-specific forecasting tailored to individual health histories
- Identify personalized intervention points based on predicted health trajectories
- Incorporate medication adherence and lifestyle data into predictions
- Calculate patient-specific risk thresholds based on comorbidities
- Include additional health metrics for more comprehensive risk assessment:
  - HbA1c (longer-term blood sugar control)
  - HDL/LDL cholesterol breakdown (good vs. bad cholesterol)
  - Triglycerides
  - Waist-to-hip ratio (often more predictive than BMI alone)
  - Physical activity level/cardiovascular fitness
  - Family history of stroke
  - Prior TIA (mini-stroke) history
  - Sleep quality and duration
  - Alcohol consumption patterns
  - Nutritional markers and diet quality

### Interactive Intervention Simulation
- Enable clinicians to modify specific health parameters (weight, BP, etc.) in real-time
- Immediately visualize impact of changes on projected risk trajectory
- Allow side-by-side comparison of different intervention strategies
- Provide both standardized intervention templates and fully customizable scenarios
- Generate printable intervention impact reports for patient education
- Calculate personalized risk reduction thresholds to set achievable goals

### Population-Level Insights
- Aggregate anonymized data to identify population-level trends and risk factors
- Generate benchmarks for different demographic groups and comorbidity profiles
- Enable comparative analysis between patient cohorts
- Develop specialized risk models for specific populations (geriatric, pediatric, etc.)
- Create regional health maps showing geographic distribution of risk factors

### Clinical Decision Support
- Integration with clinical workflows through EHR plugins
- Real-time alerts for patients approaching critical thresholds
- Evidence-based recommendation engine linked to medical literature
- Simplified visualizations optimized for clinical environments
- Compliance with clinical decision support certification requirements

This roadmap transforms PrescpHealth from a demonstration tool to a comprehensive clinical decision support system that continuously improves with more data, providing increasingly accurate predictions and personalized recommendations.