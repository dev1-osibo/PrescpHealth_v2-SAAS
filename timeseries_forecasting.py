"""
Time-series forecasting module for PrescpHealth
Uses Facebook Prophet for health metric predictions over time
"""
import pandas as pd
import numpy as np
from prophet import Prophet
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import models  # Import the models module for risk prediction

def prepare_data_for_prophet(measurements, metric):
    """
    Prepare data for Prophet forecasting
    
    Parameters:
    -----------
    measurements : list of dict
        Historical patient measurements
    metric : str
        The health metric to forecast ('bmi', 'systolic', 'diastolic', 'glucose', 'cholesterol')
        
    Returns:
    --------
    DataFrame: Data in Prophet format (ds, y)
    """
    if not measurements or len(measurements) < 3:
        return None
    
    # Sort by date
    sorted_measurements = sorted(measurements, key=lambda x: x['date'])
    
    # Create dataframe in Prophet format
    df = pd.DataFrame({
        'ds': [datetime.fromisoformat(m['date'].replace('Z', '+00:00')) for m in sorted_measurements],
        'y': [float(m[metric]) for m in sorted_measurements]
    })
    
    return df

def train_prophet_model(data_df, seasonality_mode='multiplicative', 
                       yearly_seasonality=True, weekly_seasonality=False,
                       daily_seasonality=False):
    """
    Train a Prophet model for forecasting
    
    Parameters:
    -----------
    data_df : DataFrame
        Data in Prophet format (ds, y)
    seasonality_mode : str
        'multiplicative' or 'additive'
    yearly_seasonality : bool or int
        Whether to include yearly seasonality
    weekly_seasonality : bool or int
        Whether to include weekly seasonality
    daily_seasonality : bool or int
        Whether to include daily seasonality
        
    Returns:
    --------
    Prophet model, fitted to data
    """
    # Create and fit the model
    # Workaround for type inconsistencies in Prophet's API
    # The actual implementation accepts bool, int, or str, but type hints may be incorrect
    model = Prophet(
        seasonality_mode=seasonality_mode,
        # Type checking disabled for these parameters due to Prophet's flexible API
        interval_width=0.95  # 95% prediction intervals
    )
    
    # Set seasonality parameters directly to bypass type checking
    # This approach avoids LSP errors while still using the correct parameters
    model.yearly_seasonality = yearly_seasonality
    model.weekly_seasonality = weekly_seasonality
    model.daily_seasonality = daily_seasonality
    
    model.fit(data_df)
    return model

def forecast_metric(model, periods=12, freq='M'):
    """
    Generate forecast for a health metric
    
    Parameters:
    -----------
    model : Prophet model
        Fitted Prophet model
    periods : int
        Number of periods to forecast
    freq : str
        Frequency of forecast ('M' for monthly, 'W' for weekly)
        
    Returns:
    --------
    DataFrame: Forecast including dates, predicted values, and confidence intervals
    """
    # Create future dataframe
    future = model.make_future_dataframe(periods=periods, freq=freq)
    
    # Generate forecast
    forecast = model.predict(future)
    
    return forecast

def visualize_forecast(forecast, historical_df, metric_name, patient_name=None, 
                      include_components=False, figsize=(12, 6)):
    """
    Visualize forecast with historical data
    
    Parameters:
    -----------
    forecast : DataFrame
        Forecast dataframe
    historical_df : DataFrame
        Historical data in Prophet format
    metric_name : str
        Name of the health metric being forecasted
    patient_name : str, optional
        Name of the patient
    include_components : bool
        Whether to include trend and seasonality components
    figsize : tuple
        Figure size
        
    Returns:
    --------
    matplotlib figure
    """
    fig, ax = plt.subplots(figsize=figsize)
    
    # Get the forecast start date
    last_historical_date = historical_df['ds'].max()
    
    # Convert dates to datetime objects for safer handling
    historical_dates = pd.to_datetime(historical_df['ds'])
    historical_values = historical_df['y'].values
    
    # Plot historical data points and connect them
    ax.plot(historical_dates, historical_values, 'o-', color='black', markersize=5, label='Historical')
    
    # Extract forecasted dates and values
    if 'ds' in forecast.columns and 'yhat' in forecast.columns:
        forecast_dates = pd.to_datetime(forecast['ds'])
        forecast_values = forecast['yhat'].values
        
        # Find where the forecast actually starts (after historical data)
        future_indices = [i for i, date in enumerate(forecast_dates) 
                         if date > last_historical_date]
        
        if future_indices:
            # Get future forecast data only
            future_dates = forecast_dates.iloc[future_indices]
            future_values = forecast_values[future_indices]
            
            # Add the last historical point to connect the forecasted line
            if not historical_dates.empty:
                connection_dates = [historical_dates.iloc[-1], future_dates.iloc[0]] 
                connection_values = [historical_values[-1], future_values[0]]
                
                # Plot connection line separately
                ax.plot(connection_dates, connection_values, '-', color='steelblue', alpha=0.8, linewidth=1)
            
            # Plot the forecast line
            ax.plot(future_dates, future_values, '-', color='steelblue', linewidth=2, label='Forecast')
            
            # Add confidence intervals if available
            if 'yhat_lower' in forecast.columns and 'yhat_upper' in forecast.columns:
                lower_values = forecast['yhat_lower'].values[future_indices]
                upper_values = forecast['yhat_upper'].values[future_indices]
                
                ax.fill_between(future_dates, lower_values, upper_values, 
                              color='steelblue', alpha=0.2, label='95% Confidence Interval')
    
    # Add vertical line to indicate forecast start
    ax.axvline(x=last_historical_date, color='r', linestyle='--', alpha=0.5, label='Forecast Start')
    
    # Set title and labels
    title = f"Forecast for {metric_name}"
    if patient_name:
        title += f" - {patient_name}"
    ax.set_title(title)
    ax.set_xlabel('Date')
    
    # Set y-axis label based on metric
    if metric_name == 'bmi':
        ax.set_ylabel('BMI')
    elif metric_name in ['systolic', 'diastolic']:
        ax.set_ylabel('Blood Pressure (mmHg)')
    elif metric_name == 'glucose':
        ax.set_ylabel('Blood Glucose (mg/dL)')
    elif metric_name == 'cholesterol':
        ax.set_ylabel('Cholesterol (mg/dL)')
    else:
        ax.set_ylabel(metric_name.capitalize())
    
    ax.legend()
    
    # Set y-axis limits based on metric
    if metric_name == 'bmi':
        ax.set_ylim(bottom=max(min(historical_df['y'])-5, 15), top=min(max(historical_df['y'])+5, 50))
    elif metric_name == 'systolic':
        ax.set_ylim(bottom=max(min(historical_df['y'])-10, 80), top=min(max(historical_df['y'])+10, 220))
    elif metric_name == 'diastolic':
        ax.set_ylim(bottom=max(min(historical_df['y'])-10, 40), top=min(max(historical_df['y'])+10, 140))
    elif metric_name == 'glucose':
        ax.set_ylim(bottom=max(min(historical_df['y'])-20, 50), top=min(max(historical_df['y'])+20, 350))
    elif metric_name == 'cholesterol':
        ax.set_ylim(bottom=max(min(historical_df['y'])-20, 100), top=min(max(historical_df['y'])+20, 350))
    
    plt.tight_layout()
    return fig

def forecast_all_metrics(measurements, forecast_months=12, confidence_threshold=3):
    """
    Forecast all health metrics for a patient
    
    Parameters:
    -----------
    measurements : list of dict
        Historical patient measurements
    forecast_months : int
        Number of months to forecast
    confidence_threshold : int
        Minimum number of measurements needed for reliable forecasting
        
    Returns:
    --------
    dict: Forecasts for each metric and overall risk forecast
    """
    if not measurements or len(measurements) < confidence_threshold:
        return None
    
    metrics = ['bmi', 'systolic', 'diastolic', 'glucose', 'cholesterol']
    forecasts = {}
    
    for metric in metrics:
        # Prepare data
        data_df = prepare_data_for_prophet(measurements, metric)
        
        if data_df is not None and len(data_df) >= confidence_threshold:
            # Train model
            model = train_prophet_model(data_df)
            
            # Generate forecast
            forecast = forecast_metric(model, periods=forecast_months)
            
            # Store forecast
            forecasts[metric] = {
                'model': model,
                'forecast': forecast,
                'historical': data_df
            }
    
    # Return all forecasts
    return forecasts

def get_forecast_risk_indicators(forecasts, forecast_months=12):
    """
    Calculate risk indicators based on forecasts
    
    Parameters:
    -----------
    forecasts : dict
        Dictionary of forecasts for each metric
    forecast_months : int
        Number of months to forecast
        
    Returns:
    --------
    dict: Risk indicators based on forecasts
    """
    risk_indicators = {}
    
    # Define high-risk thresholds
    thresholds = {
        'bmi': 30,  # Obesity
        'systolic': 140,  # Hypertension (systolic)
        'diastolic': 90,  # Hypertension (diastolic)
        'glucose': 126,  # Diabetes
        'cholesterol': 240  # High cholesterol
    }
    
    for metric, forecast_data in forecasts.items():
        forecast = forecast_data['forecast']
        
        # Get only the forecasted part
        last_historical_date = forecast_data['historical']['ds'].max()
        future_forecast = forecast[forecast['ds'] > last_historical_date]
        
        # Calculate trends
        current_value = forecast_data['historical']['y'].iloc[-1]
        future_values = future_forecast['yhat'].values
        
        if len(future_values) > 0:
            end_value = future_values[-1]
            max_value = future_values.max()
            min_value = future_values.min()
            
            # Calculate trend and volatility
            trend = (end_value - current_value) / current_value if current_value != 0 else 0
            volatility = (max_value - min_value) / current_value if current_value != 0 else 0
            
            # Check if forecast crosses threshold
            threshold = thresholds.get(metric)
            crosses_threshold = False
            threshold_month = None
            
            if threshold is not None:
                current_over_threshold = current_value > threshold
                
                for i, value in enumerate(future_values):
                    if (not current_over_threshold and value > threshold) or \
                       (current_over_threshold and value < threshold):
                        crosses_threshold = True
                        threshold_month = i + 1
                        break
            
            # Store risk indicators
            risk_indicators[metric] = {
                'current_value': current_value,
                'forecasted_end_value': end_value,
                'trend_percentage': trend * 100,  # Convert to percentage
                'volatility_percentage': volatility * 100,  # Convert to percentage
                'crosses_threshold': crosses_threshold,
                'threshold_month': threshold_month,
                'threshold': threshold
            }
    
    return risk_indicators

def forecast_future_risk(forecasts, ml_models, patient_data, forecast_months=6):
    """
    Forecast future risk scores based on projected health metrics
    
    Parameters:
    -----------
    forecasts : dict
        Dictionary of forecasts for each health metric
    ml_models : dict
        Dictionary of trained ML models for risk prediction
    patient_data : dict
        Current patient data
    forecast_months : int
        Number of months to forecast
        
    Returns:
    --------
    dict: Forecasted risk scores with dates and confidence intervals
    """
    if not forecasts or not ml_models:
        return None
        
    # Get dates from any forecast (they should all have the same dates)
    metric = list(forecasts.keys())[0]
    forecast_df = forecasts[metric]['forecast']
    last_historical_date = forecasts[metric]['historical']['ds'].max()
    
    # Get only future dates
    future_dates = forecast_df[forecast_df['ds'] > last_historical_date]['ds'].values
    
    # Create risk forecast dataframe
    risk_forecast = {
        'dates': future_dates,
        'risk_scores': [],
        'risk_lower': [],
        'risk_upper': [],
        'confidence': []
    }
    
    # For each future date, calculate projected risk
    for date in future_dates:
        # Create a projected patient record for this date
        projected_patient = patient_data.copy()
        
        # Update each metric with its forecasted value
        for metric_name, metric_data in forecasts.items():
            date_forecast = metric_data['forecast'][metric_data['forecast']['ds'] == date]
            if not date_forecast.empty:
                projected_value = date_forecast['yhat'].values[0]
                projected_lower = date_forecast['yhat_lower'].values[0]
                projected_upper = date_forecast['yhat_upper'].values[0]
                
                # Update projected patient data
                projected_patient[metric_name] = projected_value
                
        # Calculate risk using the ensemble model
        risk_data = models.predict_stroke_risk(projected_patient, ml_models)
        
        # Add to forecast
        risk_forecast['risk_scores'].append(risk_data['ensemble']['score'])
        
        # Calculate rough confidence intervals for risk based on metric confidence intervals
        # This is a simplification - ideally we'd propagate the uncertainty through the ML models
        avg_metric_uncertainty = 0.0
        for metric_name, metric_data in forecasts.items():
            date_forecast = metric_data['forecast'][metric_data['forecast']['ds'] == date]
            if not date_forecast.empty:
                uncertainty = (date_forecast['yhat_upper'].values[0] - date_forecast['yhat_lower'].values[0]) / (2 * date_forecast['yhat'].values[0])
                avg_metric_uncertainty += uncertainty
                
        avg_metric_uncertainty /= len(forecasts)
        uncertainty_factor = max(1.0 + avg_metric_uncertainty, 1.2)  # At least 20% uncertainty in risk
        
        # Calculate risk bounds
        risk_score = risk_data['ensemble']['score']
        lower_bound = max(0, risk_score / uncertainty_factor)
        upper_bound = min(100, risk_score * uncertainty_factor)
        
        risk_forecast['risk_lower'].append(lower_bound)
        risk_forecast['risk_upper'].append(upper_bound)
        risk_forecast['confidence'].append(risk_data['ensemble']['confidence'])
    
    return risk_forecast

def visualize_risk_forecast(risk_forecast, patient_name=None, figsize=(12, 6)):
    """
    Visualize forecasted risk scores over time
    
    Parameters:
    -----------
    risk_forecast : dict
        Dictionary with forecasted risk data
    patient_name : str, optional
        Name of the patient
    figsize : tuple
        Figure size
        
    Returns:
    --------
    matplotlib figure
    """
    if not risk_forecast or 'dates' not in risk_forecast or len(risk_forecast['dates']) == 0:
        return None
        
    fig, ax = plt.subplots(figsize=figsize)
    
    # Convert dates to datetime if they're not already
    dates = [d if isinstance(d, datetime) else pd.to_datetime(d) for d in risk_forecast['dates']]
    
    # Convert dates to numpy arrays for matplotlib compatibility
    import numpy as np
    dates_np = np.array(dates, dtype='datetime64')
    
    # Plot the forecast data points
    ax.scatter(dates_np, np.array(risk_forecast['risk_scores']), color='red', s=30, zorder=5)
    
    # Connect points with straight lines to avoid vertical artifacts
    # Skip large gaps between dates to prevent vertical lines
    for i in range(1, len(dates_np)):
        # Convert to numpy datetime64 for compatible subtraction
        date_diff = np.timedelta64(dates_np[i] - dates_np[i-1], 'D').astype(int)
        
        if date_diff < 120:  # If less than ~4 months apart
            # Create small segments to connect the points
            segment_dates = np.array([dates_np[i-1], dates_np[i]])
            segment_risks = np.array([risk_forecast['risk_scores'][i-1], risk_forecast['risk_scores'][i]])
            
            # Plot the line segment
            ax.plot(segment_dates, segment_risks, color='red', linewidth=2)
    
    # Add a legend entry for the line
    ax.plot([], [], color='red', linewidth=2, label='Forecasted Risk')
    
    # Plot confidence intervals for segments
    for i in range(1, len(dates_np)):
        date_diff = np.timedelta64(dates_np[i] - dates_np[i-1], 'D').astype(int)
        
        if date_diff < 120:  # If less than ~4 months apart
            segment_dates = np.array([dates_np[i-1], dates_np[i]])
            upper_segment = np.array([risk_forecast['risk_upper'][i-1], risk_forecast['risk_upper'][i]])
            lower_segment = np.array([risk_forecast['risk_lower'][i-1], risk_forecast['risk_lower'][i]])
            
            # Fill between the segments
            ax.fill_between(segment_dates, lower_segment, upper_segment, 
                           color='red', alpha=0.2)
    
    # Add a legend entry for the confidence interval
    ax.fill_between([], [], [], color='red', alpha=0.2, label='Confidence Interval')
    
    # Add horizontal lines for risk categories
    ax.axhspan(0, 20, alpha=0.1, color='green', label='Low Risk')
    ax.axhspan(20, 50, alpha=0.1, color='orange', label='Moderate Risk')
    ax.axhspan(50, 100, alpha=0.1, color='red', label='High Risk')
    
    # Set title and labels
    title = "Forecasted Stroke Risk"
    if patient_name:
        title += f" - {patient_name}"
    ax.set_title(title)
    ax.set_xlabel('Date')
    ax.set_ylabel('Risk Score (%)')
    
    # Set y-axis limits
    ax.set_ylim(0, 100)
    
    # Add legend
    ax.legend(loc='upper left')
    
    plt.tight_layout()
    return fig

def generate_forecast_summary(risk_indicators):
    """
    Generate a summary of forecast risk indicators
    
    Parameters:
    -----------
    risk_indicators : dict
        Dictionary of risk indicators for each metric
        
    Returns:
    --------
    str: Summary of risk indicators
    """
    summary = []
    
    metric_names = {
        'bmi': 'BMI',
        'systolic': 'Systolic BP',
        'diastolic': 'Diastolic BP',
        'glucose': 'Blood Glucose',
        'cholesterol': 'Cholesterol'
    }
    
    # Check for concerning trends
    concerning_metrics = []
    improving_metrics = []
    threshold_crossings = []
    
    for metric, indicators in risk_indicators.items():
        name = metric_names.get(metric, metric.capitalize())
        trend = indicators['trend_percentage']
        
        # Identify concerning trends (>5% increase)
        if trend > 5:
            concerning_metrics.append(f"{name} (+{trend:.1f}%)")
        
        # Identify improving trends (>5% decrease)
        elif trend < -5:
            improving_metrics.append(f"{name} ({trend:.1f}%)")
        
        # Identify threshold crossings
        if indicators['crosses_threshold']:
            direction = "rise above" if indicators['current_value'] < indicators['threshold'] else "fall below"
            month = indicators['threshold_month']
            threshold_crossings.append(f"{name} is forecasted to {direction} the threshold in {month} month(s)")
    
    # Add concerning trends to summary
    if concerning_metrics:
        summary.append("Concerning trends: " + ", ".join(concerning_metrics))
    
    # Add improving trends to summary
    if improving_metrics:
        summary.append("Improving trends: " + ", ".join(improving_metrics))
    
    # Add threshold crossings to summary
    if threshold_crossings:
        summary.append("Critical changes: " + "; ".join(threshold_crossings))
    
    # If no trends or crossings, add a generic message
    if not concerning_metrics and not threshold_crossings and not improving_metrics:
        summary.append("No significant changes forecasted for the measured health metrics.")
    
    return "\n".join(summary)