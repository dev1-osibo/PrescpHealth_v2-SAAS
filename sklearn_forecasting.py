"""
Time-series forecasting module for PrescpHealth
Uses scikit-learn based models for health metric predictions
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline

def prepare_data_for_forecast(measurements, metric):
    """
    Prepare data for time-series forecasting
    
    Parameters:
    -----------
    measurements : list of dict
        Historical patient measurements
    metric : str
        The health metric to forecast ('bmi', 'systolic', 'diastolic', 'glucose', 'cholesterol')
        
    Returns:
    --------
    DataFrame: Data in forecast format (ds, y)
    """
    # Convert to pandas DataFrame
    if not measurements:
        return pd.DataFrame(columns=['ds', 'y'])
    
    # Sort by date
    sorted_measurements = sorted(measurements, key=lambda x: x['date'])
    
    # Extract dates and the specific metric values
    dates = []
    values = []
    
    for m in sorted_measurements:
        if metric in m and m[metric] is not None:
            try:
                # Handle different date formats gracefully
                try:
                    date = datetime.fromisoformat(m['date'].replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    date = pd.to_datetime(m['date'])
                
                # Convert metric value to float, skip if conversion fails
                value = float(m[metric])
                
                dates.append(date)
                values.append(value)
            except (ValueError, TypeError):
                # Skip this measurement if conversion fails
                pass
    
    # Create DataFrame in forecast format
    df = pd.DataFrame({
        'ds': dates,
        'y': values
    })
    
    # Sort by date
    df = df.sort_values('ds')
    
    return df

def train_forecast_model(data_df, model_type='polynomial', polynomial_degree=2):
    """
    Train a forecasting model using scikit-learn
    
    Parameters:
    -----------
    data_df : DataFrame
        Data with 'ds' (dates) and 'y' (values) columns
    model_type : str
        Type of forecasting model to use ('linear', 'polynomial', 'ridge')
    polynomial_degree : int
        Degree of polynomial features if using 'polynomial' model
        
    Returns:
    --------
    Dictionary with trained model and metadata
    """
    if data_df.empty or len(data_df) < 3:
        return None
    
    # Convert dates to numeric feature (days since first date)
    first_date = data_df['ds'].min()
    X = np.array([(date - first_date).total_seconds() / (24 * 3600) for date in data_df['ds']]).reshape(-1, 1)
    y = data_df['y'].values
    
    # Train the appropriate model
    if model_type == 'linear':
        model = LinearRegression()
    elif model_type == 'polynomial':
        model = make_pipeline(
            PolynomialFeatures(degree=polynomial_degree, include_bias=False),
            Ridge(alpha=0.5)
        )
    elif model_type == 'ridge':
        model = Ridge(alpha=0.5)
    else:
        model = LinearRegression()  # Default to linear
    
    # Fit the model
    model.fit(X, y)
    
    # Calculate model metrics for confidence intervals
    y_pred = model.predict(X)
    mse = np.mean((y - y_pred) ** 2)
    variance = np.var(y)
    
    return {
        'model': model,
        'first_date': first_date,
        'last_date': data_df['ds'].max(),  # Store the last date in training data
        'mse': mse,
        'variance': variance,
        'last_value': y[-1] if len(y) > 0 else None,
        'min_value': np.min(y),
        'max_value': np.max(y),
        'mean_value': np.mean(y),
        'model_type': model_type,
        'last_days': (data_df['ds'].max() - first_date).days  # Store days from first to last date
    }

def forecast_metric(model_data, periods=12, freq='M'):
    """
    Generate forecast for a health metric using the trained model
    
    Parameters:
    -----------
    model_data : dict
        Dictionary with trained model and metadata
    periods : int
        Number of periods to forecast
    freq : str
        Frequency of forecast ('M' for monthly, 'W' for weekly, 'D' for daily)
        
    Returns:
    --------
    DataFrame: Forecast including dates, predicted values, and confidence intervals
    """
    if model_data is None:
        return pd.DataFrame(columns=['ds', 'yhat', 'yhat_lower', 'yhat_upper'])
    
    # Extract model and metadata
    model = model_data['model']
    first_date = model_data['first_date']
    mse = model_data['mse']
    
    # Determine the frequency in days
    if freq == 'M':
        days_per_period = 30
    elif freq == 'W':
        days_per_period = 7
    else:  # Default to daily
        days_per_period = 1
    
    # Get the last date in the training data
    if 'last_date' in model_data:
        last_date = model_data['last_date']
    else:
        # Default to today if last_date not in model data
        last_date = datetime.now()
    
    # Generate future dates starting from today, not from the last historical date
    # This ensures we are always forecasting into the future
    current_date = datetime.now()
    future_dates = [current_date + timedelta(days=i * days_per_period) for i in range(1, periods + 1)]
    
    # Generate features for future dates
    X_future = np.array([(date - first_date).total_seconds() / (24 * 3600) for date in future_dates]).reshape(-1, 1)
    
    # Get predictions
    y_future = model.predict(X_future)
    
    # Calculate confidence intervals (95%)
    # Wider intervals for further future predictions
    confidence_multiplier = 1.96  # 95% confidence interval
    base_width = np.sqrt(mse) * confidence_multiplier
    
    # Increasing uncertainty over time
    uncertainty_factors = np.linspace(1.0, 2.0, periods)
    confidence_widths = base_width * uncertainty_factors
    
    # Calculate upper and lower bounds
    lower_bounds = y_future - confidence_widths
    upper_bounds = y_future + confidence_widths
    
    # Ensure bounds make sense for the metric (e.g., BMI can't be negative)
    if 'min_value' in model_data and model_data['min_value'] is not None:
        min_possible = max(0, model_data['min_value'] * 0.8)  # 20% below historical minimum, but not below 0
        lower_bounds = np.maximum(lower_bounds, min_possible)
    
    if 'max_value' in model_data and model_data['max_value'] is not None:
        max_possible = model_data['max_value'] * 1.2  # 20% above historical maximum
        upper_bounds = np.minimum(upper_bounds, max_possible)
    
    # Create forecast DataFrame
    forecast = pd.DataFrame({
        'ds': future_dates,
        'yhat': y_future,
        'yhat_lower': lower_bounds,
        'yhat_upper': upper_bounds
    })
    
    return forecast

def visualize_forecast(forecast, historical_df, metric_name, patient_name=None, figsize=(12, 6)):
    """
    Visualize forecast with historical data
    
    Parameters:
    -----------
    forecast : DataFrame
        Forecast dataframe with columns 'ds', 'yhat', 'yhat_lower', 'yhat_upper'
    historical_df : DataFrame
        Historical data with columns 'ds' and 'y'
    metric_name : str
        Name of the health metric being forecasted
    patient_name : str, optional
        Name of the patient
    figsize : tuple
        Figure size
        
    Returns:
    --------
    matplotlib figure
    """
    fig, ax = plt.subplots(figsize=figsize)
    
    # Plot historical data as points connected by lines
    ax.plot(historical_df['ds'], historical_df['y'], 'o-', color='black', markersize=5, 
           label='Historical Data')
    
    # Get the forecast start date (last historical date)
    last_historical_date = historical_df['ds'].max() if not historical_df.empty else None
    
    # Plot the forecast line
    if not forecast.empty:
        ax.plot(forecast['ds'], forecast['yhat'], '-', color='steelblue', linewidth=2,
               label='Forecast')
        
        # Plot confidence intervals
        ax.fill_between(forecast['ds'], forecast['yhat_lower'], forecast['yhat_upper'],
                       color='steelblue', alpha=0.2, label='95% Confidence Interval')
        
        # If we have historical data, connect the last historical point to the first forecast point
        if last_historical_date is not None and not historical_df.empty and not forecast.empty:
            # Get the last historical point
            last_historical_value = historical_df[historical_df['ds'] == last_historical_date]['y'].values
            if len(last_historical_value) > 0:
                last_historical_value = last_historical_value[0]
                
                # Get the first forecast point
                first_forecast_date = forecast['ds'].iloc[0]
                first_forecast_value = forecast['yhat'].iloc[0]
                
                # Draw a dotted line connecting them
                ax.plot([last_historical_date, first_forecast_date], 
                       [last_historical_value, first_forecast_value], 
                       '--', color='gray', alpha=0.7)
    
    # Skip the vertical line - it's not rendering properly and isn't essential
    # Instead, use a text annotation to mark the forecast start
    if not forecast.empty:
        forecast_start_date = forecast['ds'].iloc[0]
        ax.text(forecast_start_date, ax.get_ylim()[1] * 0.95, 
                '↓ Forecast Start', 
                ha='center', color='red', weight='bold')
    
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
    
    # Format x-axis with dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.xticks(rotation=45)
    
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.legend(loc='best')
    
    plt.tight_layout()
    return fig

def forecast_all_metrics(measurements, forecast_months=12, model_type='polynomial'):
    """
    Forecast all health metrics for a patient
    
    Parameters:
    -----------
    measurements : list of dict
        Historical patient measurements
    forecast_months : int
        Number of months to forecast
    model_type : str
        Type of model to use ('linear', 'polynomial', 'ridge')
        
    Returns:
    --------
    dict: Forecasts for each metric
    """
    if not measurements or len(measurements) < 3:
        return {}
        
    metrics = ['bmi', 'systolic', 'diastolic', 'glucose', 'cholesterol']
    forecasts = {}
    
    for metric in metrics:
        # Prepare data
        data_df = prepare_data_for_forecast(measurements, metric)
        
        if data_df is not None and not data_df.empty and len(data_df) >= 3:
            # Train model
            model_data = train_forecast_model(data_df, model_type=model_type)
            
            if model_data is not None:
                # Generate forecast
                forecast = forecast_metric(model_data, periods=forecast_months, freq='M')
                
                # Store forecast data
                forecasts[metric] = {
                    'forecast': forecast,
                    'historical': data_df,
                    'model_data': model_data
                }
    
    return forecasts

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
        
    # Import models module for risk prediction
    import models
        
    # Use future dates starting from today
    # This ensures we're always forecasting into the future
    current_date = datetime.now()
    future_dates = [current_date + timedelta(days=30 * i) for i in range(1, forecast_months + 1)]
    
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
    import numpy as np
    
    if not risk_forecast or 'dates' not in risk_forecast or len(risk_forecast['dates']) == 0:
        return None
        
    fig, ax = plt.subplots(figsize=figsize)
    
    # Convert dates to datetime if they're not already
    dates = [d if isinstance(d, datetime) else pd.to_datetime(d) for d in risk_forecast['dates']]
    
    # Convert dates to numpy arrays for matplotlib compatibility
    dates_np = np.array(dates, dtype='datetime64')
    
    # Plot the forecast data points
    ax.scatter(dates_np, np.array(risk_forecast['risk_scores']), color='red', s=30, zorder=5)
    
    # Connect points with straight lines to avoid vertical artifacts
    # Skip large gaps between dates to prevent vertical lines
    for i in range(1, len(dates_np)):
        date_diff = np.timedelta64(dates_np[i] - dates_np[i-1], 'D').astype(int)
        
        if date_diff < 120:  # If less than ~4 months apart
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
    
    # Format x-axis with dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.xticks(rotation=45)
    
    # Add a grid
    ax.grid(True, linestyle='--', alpha=0.6)
    
    # Add intervention scenarios
    
    # Get first and last dates and scores
    first_date = dates_np[0]
    last_date = dates_np[-1]
    first_score = risk_forecast['risk_scores'][0]
    last_score = risk_forecast['risk_scores'][-1]
    
    # Calculate improved scenario (with intervention)
    improved_dates = [first_date, last_date]
    improved_scores = [first_score, max(0, first_score * 0.8)]  # 20% improvement
    
    # Calculate worsened scenario (without intervention)
    worsened_dates = [first_date, last_date]
    worsened_scores = [first_score, min(100, first_score * 1.2)]  # 20% worse
    
    # Plot intervention scenarios
    ax.plot(improved_dates, improved_scores, 'o--', 
           color='green', linewidth=2, markersize=0,
           label='With Intervention')
    
    ax.plot(worsened_dates, worsened_scores, 'o--', 
           color='darkorange', linewidth=2, markersize=0,
           label='Without Intervention')
    
    # Add annotations
    ax.annotate(f"{improved_scores[1]:.1f}%", 
               xy=(improved_dates[1], improved_scores[1]),
               xytext=(10, -20),
               textcoords='offset points',
               arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=.2'),
               color='green')
    
    ax.annotate(f"{worsened_scores[1]:.1f}%", 
               xy=(worsened_dates[1], worsened_scores[1]),
               xytext=(10, 20),
               textcoords='offset points',
               arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=.2'),
               color='darkorange')
    
    ax.legend(loc='upper left')
    
    plt.tight_layout()
    return fig

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
    if not forecasts:
        return {}
        
    risk_indicators = {}
    
    for metric, data in forecasts.items():
        # Skip if data is not available
        if 'forecast' not in data or data['forecast'].empty or 'historical' not in data:
            continue
            
        forecast_df = data['forecast']
        historical_df = data['historical']
        
        # Skip if data is not available
        if forecast_df.empty or historical_df.empty:
            continue
            
        # Get current (most recent historical) value
        current_value = historical_df['y'].iloc[-1]
        
        # Get forecasted value at the end of the forecast period
        forecasted_end_value = forecast_df['yhat'].iloc[-1]
        
        # Calculate trend
        trend_absolute = forecasted_end_value - current_value
        trend_percentage = (trend_absolute / current_value) * 100 if current_value != 0 else 0
        
        # Calculate volatility
        if len(forecast_df) > 1:
            forecast_std = forecast_df['yhat'].std()
            volatility_percentage = (forecast_std / forecasted_end_value) * 100 if forecasted_end_value != 0 else 0
        else:
            volatility_percentage = 0
            
        # Determine if this is a risk factor
        is_risk_factor = False
        
        # Different thresholds for different metrics
        if metric == 'bmi':
            if current_value > 25 and trend_percentage > 0:
                is_risk_factor = True
            elif current_value > 30:
                is_risk_factor = True
        elif metric == 'systolic':
            if current_value > 140 and trend_percentage > 0:
                is_risk_factor = True
            elif current_value > 160:
                is_risk_factor = True
        elif metric == 'diastolic':
            if current_value > 90 and trend_percentage > 0:
                is_risk_factor = True
            elif current_value > 100:
                is_risk_factor = True
        elif metric == 'glucose':
            if current_value > 140 and trend_percentage > 0:
                is_risk_factor = True
            elif current_value > 180:
                is_risk_factor = True
        elif metric == 'cholesterol':
            if current_value > 200 and trend_percentage > 0:
                is_risk_factor = True
            elif current_value > 240:
                is_risk_factor = True
                
        # Store indicators
        risk_indicators[metric] = {
            'current_value': current_value,
            'forecasted_end_value': forecasted_end_value,
            'trend_absolute': trend_absolute,
            'trend_percentage': trend_percentage,
            'volatility_percentage': volatility_percentage,
            'is_risk_factor': is_risk_factor
        }
        
    return risk_indicators

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
    if not risk_indicators:
        return "Insufficient data for forecasting analysis."
        
    # Count risk factors
    risk_factor_count = sum(1 for metric, indicators in risk_indicators.items() 
                           if indicators.get('is_risk_factor', False))
    
    # Generate summary based on risk factors
    if risk_factor_count == 0:
        summary = "📊 **Forecast Summary: Positive Outlook**\n\n"
        summary += "Based on the forecast analysis, all your health metrics are projected to remain within or trend toward healthy ranges over the next 6 months. "
        summary += "Continue your current health behaviors to maintain this positive trajectory."
    elif risk_factor_count == 1:
        summary = "📊 **Forecast Summary: Minor Concern**\n\n"
        summary += "The forecast analysis shows one health metric that may require attention over the next 6 months. "
        
        # Identify the problematic metric
        for metric, indicators in risk_indicators.items():
            if indicators.get('is_risk_factor', False):
                metric_name = {
                    'bmi': 'Body Mass Index',
                    'systolic': 'Systolic Blood Pressure',
                    'diastolic': 'Diastolic Blood Pressure',
                    'glucose': 'Blood Glucose',
                    'cholesterol': 'Cholesterol'
                }.get(metric, metric.capitalize())
                
                trend = indicators.get('trend_percentage', 0)
                value = indicators.get('forecasted_end_value', 0)
                
                if trend > 0:
                    summary += f"Your {metric_name} is projected to increase by {trend:.1f}% to {value:.1f}, "
                else:
                    summary += f"Your {metric_name} is currently elevated at {value:.1f}, "
                
                summary += "which may increase your health risk. Consider discussing this with your healthcare provider."
                break
    else:
        summary = "📊 **Forecast Summary: Attention Needed**\n\n"
        summary += f"The forecast analysis identified {risk_factor_count} health metrics that may require attention over the next 6 months. "
        
        # List problematic metrics
        problem_metrics = []
        for metric, indicators in risk_indicators.items():
            if indicators.get('is_risk_factor', False):
                metric_name = {
                    'bmi': 'Body Mass Index',
                    'systolic': 'Systolic Blood Pressure',
                    'diastolic': 'Diastolic Blood Pressure',
                    'glucose': 'Blood Glucose',
                    'cholesterol': 'Cholesterol'
                }.get(metric, metric.capitalize())
                
                problem_metrics.append(metric_name)
        
        if problem_metrics:
            summary += "The following metrics show concerning trends: " + ", ".join(problem_metrics) + ". "
            summary += "Consider consulting with your healthcare provider to develop an intervention plan."
    
    return summary