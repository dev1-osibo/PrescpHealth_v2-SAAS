import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime
import matplotlib.dates as mdates
from io import BytesIO
import base64
import time
import html
import matplotlib.animation as animation
from matplotlib.colors import LinearSegmentedColormap
import utils

def create_vital_sign_chart(measurements_df, vital_sign, label, normal_range=None, unit=""):
    """Create a chart for a vital sign over time"""
    if measurements_df.empty:
        return None
    
    fig, ax = plt.subplots(figsize=(8, 4))
    
    # Plot the data
    dates = measurements_df['date']
    values = measurements_df[vital_sign]
    
    ax.plot(dates, values, 'o-', color='#1f77b4', linewidth=2, markersize=8)
    
    # Add normal range if provided
    if normal_range:
        ax.axhspan(normal_range[0], normal_range[1], color='green', alpha=0.15)
    
    # Customize the chart
    ax.set_title(f'{label} Over Time', fontsize=16)
    ax.set_ylabel(f'{label} {unit}', fontsize=12)
    ax.grid(True, linestyle='--', alpha=0.7)
    
    # Format x-axis with dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    fig.autofmt_xdate()
    
    # Add data points
    for i, (d, v) in enumerate(zip(dates, values)):
        ax.annotate(f'{v}', (d, v), textcoords="offset points", 
                     xytext=(0,10), ha='center', fontsize=9)
    
    plt.tight_layout()
    return fig

def create_health_dashboard(measurements_df):
    """Create a comprehensive health dashboard with multiple metrics"""
    if measurements_df.empty:
        return None
    
    fig, axs = plt.subplots(2, 2, figsize=(12, 10))
    
    # Blood Pressure Plot
    ax1 = axs[0, 0]
    dates = measurements_df['date']
    systolic = measurements_df['systolic']
    diastolic = measurements_df['diastolic']
    
    ax1.plot(dates, systolic, 'o-', color='#d62728', label='Systolic', linewidth=2)
    ax1.plot(dates, diastolic, 'o-', color='#1f77b4', label='Diastolic', linewidth=2)
    ax1.set_title('Blood Pressure Over Time', fontsize=14)
    ax1.set_ylabel('mmHg', fontsize=12)
    ax1.axhspan(90, 120, color='green', alpha=0.15)  # Normal systolic range
    ax1.axhspan(60, 80, color='blue', alpha=0.15)    # Normal diastolic range
    ax1.legend()
    ax1.grid(True, linestyle='--', alpha=0.7)
    
    # Glucose Plot
    ax2 = axs[0, 1]
    glucose = measurements_df['glucose']
    
    ax2.plot(dates, glucose, 'o-', color='#ff7f0e', linewidth=2)
    ax2.set_title('Blood Glucose Over Time', fontsize=14)
    ax2.set_ylabel('mg/dL', fontsize=12)
    ax2.axhspan(70, 100, color='green', alpha=0.15)  # Normal range
    ax2.grid(True, linestyle='--', alpha=0.7)
    
    # Cholesterol Plot
    ax3 = axs[1, 0]
    cholesterol = measurements_df['cholesterol']
    
    ax3.plot(dates, cholesterol, 'o-', color='#9467bd', linewidth=2)
    ax3.set_title('Cholesterol Over Time', fontsize=14)
    ax3.set_ylabel('mg/dL', fontsize=12)
    ax3.axhspan(0, 200, color='green', alpha=0.15)  # Desirable range
    ax3.grid(True, linestyle='--', alpha=0.7)
    
    # BMI Plot
    ax4 = axs[1, 1]
    bmi = measurements_df['bmi']
    
    ax4.plot(dates, bmi, 'o-', color='#2ca02c', linewidth=2)
    ax4.set_title('BMI Over Time', fontsize=14)
    ax4.set_ylabel('kg/m²', fontsize=12)
    ax4.axhspan(18.5, 25, color='green', alpha=0.15)  # Normal range
    ax4.grid(True, linestyle='--', alpha=0.7)
    
    # Format x-axis dates for all subplots
    for ax in axs.flat:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    
    plt.tight_layout()
    fig.autofmt_xdate()
    
    return fig

def create_risk_score_chart(risk_scores, include_forecast=True):
    """
    Create a chart showing risk scores over time with optional forecast
    
    Parameters:
    -----------
    risk_scores : list of dict
        List of risk score dictionaries
    include_forecast : bool
        Whether to include forecasted risk points
    """
    if not risk_scores:
        return None
    
    # Convert to DataFrame
    df = pd.DataFrame(risk_scores)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(8, 5))
    
    # Convert dates
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    
    # For production - prioritize ensemble model and simplify visualization
    # First check if we're in development or production mode
    is_development_mode = False  # Set to True for development with model names
    
    if is_development_mode:
        # Development mode - show all models
        # Group by date and model
        dates = df['date'].unique()
        models = df['model_name'].unique()
        
        colors = {
            'xgboost': '#ff7f0e',        # Orange
            'random_forest': '#2ca02c',   # Green
            'logistic_regression': '#d62728',  # Red
            'ensemble': '#1f77b4'        # Blue
        }
        
        # Plot each model
        for model in models:
            model_data = df[df['model_name'] == model]
            if not model_data.empty:
                ax.plot(model_data['date'], model_data['score'], 'o-', 
                       label=model.replace('_', ' ').title(), 
                       color=colors.get(model, 'gray'),
                       linewidth=2,
                       markersize=8)
    else:
        # Production mode - only show ensemble model with a more professional label
        ensemble_data = df[df['model_name'] == 'ensemble']
        
        if not ensemble_data.empty:
            # Determine current date and latest assessment using safer methods
            try:
                # Convert DataFrame to basic Python types to avoid type errors
                # Get the latest date as a simple datetime object
                dates_list = [pd.to_datetime(d) for d in ensemble_data['date'].tolist()]
                latest_date = max(dates_list)
                
                # Find the row with the latest date
                latest_rows = [i for i, d in enumerate(dates_list) if d == latest_date]
                if latest_rows:
                    latest_idx = latest_rows[0]
                    latest_score = float(ensemble_data.iloc[latest_idx]['score'])
                    latest_confidence = 0.8  # Default confidence
                    
                    # Try to get confidence if it exists
                    if 'confidence' in ensemble_data.columns:
                        confidence_val = ensemble_data.iloc[latest_idx].get('confidence')
                        if confidence_val is not None and not pd.isna(confidence_val):
                            try:
                                latest_confidence = float(confidence_val)
                            except (ValueError, TypeError):
                                pass  # Keep default if we can't get a valid value
                else:
                    # Fallback if we can't find the latest date
                    latest_score = 50.0  # Middle risk score
                    latest_confidence = 0.8
            except Exception as e:
                print(f"Error getting latest assessment: {e}")
                latest_date = pd.Timestamp.now()
                latest_score = 50.0  # Default to middle risk
                latest_confidence = 0.8
            
            # Connect points with line segments for historical data
            ax.plot(ensemble_data['date'], ensemble_data['score'], 'o-', 
                   label='Current Assessment', 
                   color='#1f77b4',  # Professional blue
                   linewidth=2.5,
                   markersize=8)
            
            # Add forecast if requested and there's only one data point
            if include_forecast and len(ensemble_data) <= 1:
                # Generate forecast dates - 3, 6, and 12 months into the future
                from datetime import timedelta
                forecast_dates = [
                    latest_date + timedelta(days=90),  # 3 months
                    latest_date + timedelta(days=180), # 6 months
                    latest_date + timedelta(days=365)  # 12 months
                ]
                
                # Generate forecasted risk scores based on current score
                # This is a simple projection; in a real app this would come from the AI model
                # We're simulating a slight upward trend if no changes are made
                risk_change_factors = [1.1, 1.2, 1.35]  # Increase by 10%, 20%, 35% at each point
                forecast_scores = [min(100, latest_score * factor) for factor in risk_change_factors]
                
                # Plot forecasted points with different style to distinguish from actual data
                ax.plot(forecast_dates, forecast_scores, 'o--', 
                       label='Projected Risk (No Intervention)', 
                       color='#ff7f0e',  # Orange for forecast
                       linewidth=2,
                       markersize=7,
                       alpha=0.8)
                
                # Add projected improvement scenario
                improvement_factors = [0.95, 0.9, 0.85]  # Decrease by 5%, 10%, 15% at each point
                improvement_scores = [max(0, latest_score * factor) for factor in improvement_factors]
                
                ax.plot(forecast_dates, improvement_scores, 'o--', 
                       label='Projected Risk (With Intervention)', 
                       color='#2ca02c',  # Green for improvement
                       linewidth=2,
                       markersize=7,
                       alpha=0.8)
                
                # Add annotations to the last forecast point
                ax.annotate(f"{int(forecast_scores[-1])}%", 
                            (forecast_dates[-1], forecast_scores[-1]),
                            xytext=(5, 5),
                            textcoords="offset points",
                            ha='left',
                            fontsize=9,
                            alpha=0.8)
                
                ax.annotate(f"{int(improvement_scores[-1])}%", 
                            (forecast_dates[-1], improvement_scores[-1]),
                            xytext=(5, 5),
                            textcoords="offset points",
                            ha='left',
                            fontsize=9,
                            alpha=0.8)
            
            # Add confidence indicators to each actual assessment point
            for _, row in ensemble_data.iterrows():
                try:
                    # Show confidence as annotation - handle all types safely
                    date = pd.to_datetime(row['date'])
                    score = float(row['score'])
                    
                    # Get confidence with proper fallback
                    confidence = 0.8  # Default confidence
                    if 'confidence' in row:
                        try:
                            confidence_val = row['confidence']
                            if confidence_val is not None and not pd.isna(confidence_val):
                                confidence = float(confidence_val)
                        except (ValueError, TypeError):
                            pass  # Use default if conversion fails
                    
                    # Add confidence as small label
                    confidence_pct = int(confidence * 100)
                    ax.annotate(f"{confidence_pct}%", 
                                xy=(date, score),  # Using explicit parameter name
                                xytext=(0, 10),
                                textcoords="offset points",
                                ha='center',
                                fontsize=9,
                                alpha=0.8)
                except Exception as e:
                    # Skip this annotation if there are any errors
                    print(f"Skipping annotation due to error: {e}")
    
    # Add risk zones
    ax.axhspan(0, 20, color='green', alpha=0.15, label='Low Risk')
    ax.axhspan(20, 50, color='orange', alpha=0.15, label='Moderate Risk')
    ax.axhspan(50, 100, color='red', alpha=0.15, label='High Risk')
    
    # Customize chart
    ax.set_title('Stroke Risk Assessment Trend', fontsize=16)
    ax.set_ylabel('Risk Score', fontsize=12)
    ax.set_ylim(0, 100)
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.legend(loc='best')
    
    # Format x-axis with dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d, %Y'))
    fig.autofmt_xdate()
    
    plt.tight_layout()
    return fig

def fig_to_base64(fig):
    """Convert matplotlib figure to base64 string for embedding"""
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=100)
    buf.seek(0)
    img_str = base64.b64encode(buf.read()).decode('utf-8')
    return img_str

def create_animated_trend_indicator(trend_type, value, previous_value, metric_name, normal_range=None):
    """
    Create an animated HTML/CSS indicator showing the trend of a health metric
    
    Parameters:
    -----------
    trend_type: str
        'increasing', 'decreasing', or 'stable'
    value: float
        Current value of the metric
    previous_value: float
        Previous value of the metric
    metric_name: str
        Name of the health metric
    normal_range: tuple, optional
        (min, max) values for the normal range of this metric
        
    Returns:
    --------
    str: HTML string with the animated indicator
    """
    trend_icons = {
        'increasing': '↑',
        'decreasing': '↓',
        'stable': '→'
    }
    
    # Determine color based on value and normal range
    if normal_range is None:
        color = 'gray'
    else:
        if value < normal_range[0]:
            color = 'blue' # Below normal
        elif value > normal_range[1]:
            color = 'red'  # Above normal
        else:
            color = 'green' # Within normal range
    
    # Calculate percent change for animation speed
    if previous_value and previous_value != 0:
        percent_change = abs((value - previous_value) / previous_value * 100)
        # Clamp the animation speed between 0.5 and 3 seconds
        animation_speed = max(0.5, min(3, 3 - (percent_change / 10)))
    else:
        animation_speed = 2  # Default animation speed
    
    # Determine if the change is positive or negative for health
    if normal_range is None:
        indicator_class = 'neutral-change'
    elif metric_name in ['systolic', 'diastolic', 'glucose', 'cholesterol', 'bmi']:
        # For these metrics, lower is generally better (if above normal range)
        if value > normal_range[1] and trend_type == 'decreasing':
            indicator_class = 'positive-change'
        elif value > normal_range[1] and trend_type == 'increasing':
            indicator_class = 'negative-change'
        elif value < normal_range[0] and trend_type == 'increasing':
            indicator_class = 'positive-change'
        elif value < normal_range[0] and trend_type == 'decreasing':
            indicator_class = 'negative-change'
        elif normal_range[0] <= value <= normal_range[1]:
            indicator_class = 'neutral-change'
        else:
            indicator_class = 'neutral-change'
    else:
        # For other metrics, we'll use a neutral indicator
        indicator_class = 'neutral-change'
    
    # Icon with trend
    icon = trend_icons.get(trend_type, '→')
    
    # Create the HTML/CSS for the animated indicator
    html_str = f"""
    <div style="display: flex; align-items: center; margin-bottom: 10px;">
        <div style="font-size: 18px; font-weight: bold; margin-right: 10px;">{metric_name}: {value}</div>
        <div class="trend-indicator {indicator_class}" 
             style="color: {color}; font-size: 24px; font-weight: bold; animation: pulse {animation_speed}s infinite;">
            {icon}
        </div>
    </div>
    <style>
    @keyframes pulse {{
        0% {{ opacity: 0.5; transform: scale(1); }}
        50% {{ opacity: 1; transform: scale(1.2); }}
        100% {{ opacity: 0.5; transform: scale(1); }}
    }}
    .positive-change {{
        text-shadow: 0 0 10px rgba(0, 255, 0, 0.7);
    }}
    .negative-change {{
        text-shadow: 0 0 10px rgba(255, 0, 0, 0.7);
    }}
    .neutral-change {{
        text-shadow: 0 0 10px rgba(128, 128, 128, 0.7);
    }}
    </style>
    """
    
    return html_str

def create_animated_risk_gauge(risk_score, previous_score=None):
    """
    Create an animated risk gauge visualization
    
    Parameters:
    -----------
    risk_score: float
        Current risk score (0-100)
    previous_score: float, optional
        Previous risk score for comparison
        
    Returns:
    --------
    str: HTML string with the animated gauge
    """
    # Determine risk level and color
    if risk_score < 20:
        risk_level = "Low"
        color = "green"
        emoji = "✓"
    elif risk_score < 50:
        risk_level = "Moderate"
        color = "orange"
        emoji = "⚠️"
    else:
        risk_level = "High"
        color = "red"
        emoji = "⚠️⚠️"
    
    # Calculate the percentage for the gauge
    percentage = risk_score
    
    # Determine trend
    if previous_score is not None:
        if risk_score > previous_score + 5:
            trend = "↑"
            trend_color = "red"
            animation_class = "pulse-red"
        elif risk_score < previous_score - 5:
            trend = "↓"
            trend_color = "green"
            animation_class = "pulse-green"
        else:
            trend = "→"
            trend_color = "gray"
            animation_class = "pulse-gray"
        
        # Calculate percent change for animation speed
        percent_change = abs((risk_score - previous_score) / (previous_score if previous_score != 0 else 1) * 100)
        # Clamp animation speed
        animation_speed = max(0.5, min(3, 3 - (percent_change / 10)))
        
        trend_html = f'<div class="{animation_class}" style="color: {trend_color}; font-size: 24px; animation: pulse {animation_speed}s infinite;">{trend}</div>'
    else:
        trend_html = ""
        animation_class = ""
    
    # Create the HTML/CSS for the animated gauge
    gauge_background = """
    background: linear-gradient(90deg, 
        rgba(0,128,0,0.7) 0%, 
        rgba(0,128,0,0.7) 20%, 
        rgba(255,165,0,0.7) 20%, 
        rgba(255,165,0,0.7) 50%, 
        rgba(255,0,0,0.7) 50%, 
        rgba(255,0,0,0.7) 100%);
    """
    
    html_str = f"""
    <div style="margin: 20px 0;">
        <div style="display: flex; align-items: center; margin-bottom: 5px;">
            <h3 style="margin: 0; color: {color};">Risk Level: {risk_level} {emoji}</h3>
            {trend_html}
        </div>
        <div style="width: 100%; height: 30px; border-radius: 15px; {gauge_background}">
            <div style="width: {percentage}%; height: 100%; border-radius: 15px; background-color: rgba(255, 255, 255, 0.3); position: relative;">
                <div class="gauge-marker" style="position: absolute; top: -10px; right: 0; width: 10px; height: 50px; background-color: white; border-radius: 5px;"></div>
            </div>
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 5px;">
            <span>Low Risk (0-20%)</span>
            <span>Moderate Risk (20-50%)</span>
            <span>High Risk (50-100%)</span>
        </div>
    </div>
    <style>
    @keyframes pulse {{
        0% {{ opacity: 0.6; transform: scale(1); }}
        50% {{ opacity: 1; transform: scale(1.3); }}
        100% {{ opacity: 0.6; transform: scale(1); }}
    }}
    .pulse-red {{
        text-shadow: 0 0 10px rgba(255, 0, 0, 0.7);
    }}
    .pulse-green {{
        text-shadow: 0 0 10px rgba(0, 255, 0, 0.7);
    }}
    .pulse-gray {{
        text-shadow: 0 0 10px rgba(128, 128, 128, 0.7);
    }}
    .gauge-marker {{
        animation: pulse 2s infinite;
        box-shadow: 0 0 10px rgba(255, 255, 255, 0.8);
    }}
    </style>
    """
    
    return html_str

def create_health_metric_dashboard(current_measurement, previous_measurement=None):
    """
    Create an interactive dashboard with animated health metrics
    
    Parameters:
    -----------
    current_measurement: dict
        Current measurement data
    previous_measurement: dict, optional
        Previous measurement data for comparison
        
    Returns:
    --------
    str: HTML string with the animated health metrics dashboard
    """
    # Define normal ranges for different metrics
    normal_ranges = {
        'Systolic BP': (90, 120),
        'Diastolic BP': (60, 80),
        'Glucose': (70, 100),
        'Cholesterol': (0, 200),
        'BMI': (18.5, 25)
    }
    
    # Create simplified HTML trends directly
    systolic = current_measurement.get('systolic', 0)
    diastolic = current_measurement.get('diastolic', 0)
    glucose = current_measurement.get('glucose', 0)
    cholesterol = current_measurement.get('cholesterol', 0)
    bmi = current_measurement.get('bmi', 0)
    
    # Determine health colors
    systolic_color = 'green' if 90 <= systolic <= 120 else ('blue' if systolic < 90 else 'red')
    diastolic_color = 'green' if 60 <= diastolic <= 80 else ('blue' if diastolic < 60 else 'red')
    glucose_color = 'green' if 70 <= glucose <= 100 else ('blue' if glucose < 70 else 'red')
    cholesterol_color = 'green' if cholesterol <= 200 else 'red'
    bmi_color = 'green' if 18.5 <= bmi <= 25 else ('blue' if bmi < 18.5 else 'red')
    
    # Determine trends if previous measurement exists
    trend_symbols = {'increasing': '↑', 'decreasing': '↓', 'stable': '→'}
    
    if previous_measurement:
        prev_systolic = previous_measurement.get('systolic', systolic)
        prev_diastolic = previous_measurement.get('diastolic', diastolic)
        prev_glucose = previous_measurement.get('glucose', glucose)
        prev_cholesterol = previous_measurement.get('cholesterol', cholesterol)
        prev_bmi = previous_measurement.get('bmi', bmi)
        
        # Calculate trend directions
        systolic_trend = utils.calculate_trend(current_measurement, previous_measurement, 'systolic')[0]
        diastolic_trend = utils.calculate_trend(current_measurement, previous_measurement, 'diastolic')[0]
        glucose_trend = utils.calculate_trend(current_measurement, previous_measurement, 'glucose')[0]
        cholesterol_trend = utils.calculate_trend(current_measurement, previous_measurement, 'cholesterol')[0]
        bmi_trend = utils.calculate_trend(current_measurement, previous_measurement, 'bmi')[0]
    else:
        systolic_trend = 'stable'
        diastolic_trend = 'stable'
        glucose_trend = 'stable'
        cholesterol_trend = 'stable'
        bmi_trend = 'stable'
    
    # Create HTML indicators
    def create_indicator(name, value, color, trend):
        trend_icon = trend_symbols.get(trend, '→')
        trend_color = 'gray'
        if trend == 'increasing':
            trend_color = 'red' if color == 'red' else 'green'
        elif trend == 'decreasing':
            trend_color = 'green' if color == 'red' else 'red'
        
        return f"""
        <div style="display: flex; align-items: center; margin-bottom: 10px;">
            <div style="font-size: 18px; font-weight: bold; margin-right: 10px;">{name}: <span style="color: {color};">{value}</span></div>
            <div style="color: {trend_color}; font-size: 24px; font-weight: bold; animation: pulse 2s infinite;">
                {trend_icon}
            </div>
        </div>
        """
    
    # Create the HTML layout with two columns and animation style
    html_str = """
    <style>
    @keyframes pulse {
        0% { opacity: 0.5; transform: scale(1); }
        50% { opacity: 1; transform: scale(1.2); }
        100% { opacity: 0.5; transform: scale(1); }
    }
    </style>
    <div style="display: flex; flex-wrap: wrap; gap: 20px; margin-top: 20px;">
        <div style="flex: 1; min-width: 300px; background-color: #f8f9fa; padding: 15px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
    """
    
    # Add cardiovascular metrics to left column
    html_str += "<h3 style='margin-top: 0;'>Cardiovascular Metrics</h3>"
    html_str += create_indicator('Systolic BP', systolic, systolic_color, systolic_trend)
    html_str += create_indicator('Diastolic BP', diastolic, diastolic_color, diastolic_trend)
    html_str += create_indicator('Cholesterol', cholesterol, cholesterol_color, cholesterol_trend)
    
    # Close left column, start right column
    html_str += """
        </div>
        <div style="flex: 1; min-width: 300px; background-color: #f8f9fa; padding: 15px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
    """
    
    # Add metabolic metrics to right column
    html_str += "<h3 style='margin-top: 0;'>Metabolic Metrics</h3>"
    html_str += create_indicator('Glucose', glucose, glucose_color, glucose_trend)
    html_str += create_indicator('BMI', bmi, bmi_color, bmi_trend)
    
    # Add additional info about smoking, etc.
    smoking_status = current_measurement.get('smoking', 'Unknown')
    smoking_color = 'green' if smoking_status == 'Never Smoked' else ('orange' if smoking_status == 'Former Smoker' else 'red')
    
    html_str += f"""
    <div style="margin-top: 20px;">
        <div style="font-size: 16px; font-weight: bold;">Smoking Status: <span style="color: {smoking_color};">{smoking_status}</span></div>
        <div style="font-size: 16px; font-weight: bold; margin-top: 10px;">Conditions:</div>
        <ul style="margin-top: 5px;">
            <li>Hypertension: <span style="color: {'red' if current_measurement.get('has_hypertension', 0) == 1 else 'green'};">
                {'Yes' if current_measurement.get('has_hypertension', 0) == 1 else 'No'}</span>
            </li>
            <li>Diabetes: <span style="color: {'red' if current_measurement.get('has_diabetes', 0) == 1 else 'green'};">
                {'Yes' if current_measurement.get('has_diabetes', 0) == 1 else 'No'}</span>
            </li>
            <li>Heart Disease: <span style="color: {'red' if current_measurement.get('has_heart_disease', 0) == 1 else 'green'};">
                {'Yes' if current_measurement.get('has_heart_disease', 0) == 1 else 'No'}</span>
            </li>
        </ul>
    </div>
    """
    
    # Close right column and main container
    html_str += """
        </div>
    </div>
    """
    
    return html_str
