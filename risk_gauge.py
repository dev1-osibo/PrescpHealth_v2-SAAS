"""
Risk gauge visualization module for PrescpHealth application
"""
import streamlit as st
import matplotlib.pyplot as plt
import numpy as np

def create_simple_risk_gauge(risk_score, previous_score=None):
    """
    Create a simple risk gauge visualization using native Streamlit components
    
    Parameters:
    -----------
    risk_score: float
        Current risk score (0-100)
    previous_score: float, optional
        Previous risk score for comparison
    """
    # Ensure risk_score is a number
    try:
        risk_score = float(risk_score)
        if previous_score is not None:
            previous_score = float(previous_score)
            delta = risk_score - previous_score
        else:
            delta = None
    except (ValueError, TypeError):
        risk_score = 0
        previous_score = None
        delta = None
    
    # Determine risk level and color
    if risk_score < 20:
        risk_level = "Low Risk"
        color = "green"
        
        # Display the risk gauge with native Streamlit components
        st.success(f"🔄 **{risk_level}**: {risk_score:.1f}%")
        
    elif risk_score < 50:
        risk_level = "Moderate Risk"
        color = "orange"
        
        # Display using warning
        st.warning(f"⚠️ **{risk_level}**: {risk_score:.1f}%")
        
    else:
        risk_level = "High Risk"
        color = "red"
        
        # Display using error
        st.error(f"🔴 **{risk_level}**: {risk_score:.1f}%")
    
    # Create a progress bar to visualize the risk score
    st.progress(risk_score/100.0)
    
    # Show trend if previous score is available
    if delta is not None:
        if abs(delta) < 2:
            st.info(f"Risk score is stable (Change: {delta:.1f}%)")
        elif delta > 0:
            st.error(f"Risk score increased by {delta:.1f}%")
        else:
            st.success(f"Risk score decreased by {abs(delta):.1f}%")
    
    # Create a simple gauge chart
    fig, ax = plt.subplots(figsize=(10, 2))
    
    # Set up the gauge
    gauge_colors = [(0, 0.4, 0), (1, 0.65, 0), (0.8, 0, 0)]  # green, orange, red
    positions = [0, 0.2, 0.5, 1]
    
    # Create a gradient for the gauge background
    cmap = plt.cm.RdYlGn_r
    norm = plt.Normalize(0, 100)
    
    # Create the gradient bar
    for i in range(100):
        ax.axvspan(i, i+1, ymin=0.1, ymax=0.9, color=cmap(norm(i)), alpha=0.7)
    
    # Add a marker for the risk score
    ax.scatter(risk_score, 0.5, s=300, marker='^', color='white', edgecolor='black', zorder=5)
    
    # Add labels
    ax.text(10, 0, 'Low Risk', ha='center', va='center', fontsize=10, fontweight='bold', color='white')
    ax.text(35, 0, 'Moderate Risk', ha='center', va='center', fontsize=10, fontweight='bold', color='white')
    ax.text(75, 0, 'High Risk', ha='center', va='center', fontsize=10, fontweight='bold', color='white')
    
    # Set limits and remove axes
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Display the plot
    st.pyplot(fig)