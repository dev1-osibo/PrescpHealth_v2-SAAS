from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.platypus import Image as RLImage
from datetime import datetime
import io


def generate_patient_risk_report(patient, measurement, risk_score, confidence, recommendations=None):
    """
    Generate a comprehensive PDF report for patient stroke risk assessment.
    
    Args:
        patient: Patient data dictionary
        measurement: Latest measurement data dictionary
        risk_score: Calculated risk score (0-100)
        confidence: Model confidence (0-1)
        recommendations: List of AI recommendations
    
    Returns:
        BytesIO object containing the PDF
    """
    buffer = io.BytesIO()
    
    # Create PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2E4057'),
        spaceAfter=30,
        alignment=1  # Center
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2E4057'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    normal_style = styles['Normal']
    
    # Header
    elements.append(Paragraph("PrescpHealth", title_style))
    elements.append(Paragraph("Stroke Risk Assessment Report", styles['Heading2']))
    elements.append(Spacer(1, 20))
    
    # Report metadata
    report_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    elements.append(Paragraph(f"<b>Report Generated:</b> {report_date}", normal_style))
    elements.append(Spacer(1, 20))
    
    # Patient Information Section
    elements.append(Paragraph("Patient Information", heading_style))
    
    patient_data = [
        ["Name:", patient['name']],
        ["Date of Birth:", patient['dob']],
        ["Gender:", patient['gender']],
        ["Patient ID:", patient['id']],
    ]
    
    patient_table = Table(patient_data, colWidths=[2*inch, 4*inch])
    patient_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    
    elements.append(patient_table)
    elements.append(Spacer(1, 20))
    
    # Stroke Risk Assessment
    elements.append(Paragraph("AI-Powered Stroke Risk Assessment", heading_style))
    
    # Determine risk level
    if risk_score < 20:
        risk_level = "Low Risk"
        risk_color = colors.HexColor('#10b981')
    elif risk_score < 50:
        risk_level = "Moderate Risk"
        risk_color = colors.HexColor('#f59e0b')
    elif risk_score < 80:
        risk_level = "High Risk"
        risk_color = colors.HexColor('#ef4444')
    else:
        risk_level = "Critical Risk"
        risk_color = colors.HexColor('#dc2626')
    
    risk_data = [
        ["Risk Score:", f"{risk_score:.1f}%"],
        ["Risk Level:", risk_level],
        ["Confidence:", f"{confidence*100:.0f}%"],
    ]
    
    risk_table = Table(risk_data, colWidths=[2*inch, 4*inch])
    risk_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
        ('BACKGROUND', (1, 1), (1, 1), risk_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('TEXTCOLOR', (1, 1), (1, 1), colors.white),
        ('TEXTCOLOR', (0, 2), (-1, 2), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 1), (1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    
    elements.append(risk_table)
    elements.append(Spacer(1, 20))
    
    # Health Metrics Section
    elements.append(Paragraph("Current Health Metrics", heading_style))
    
    health_data = [
        ["Metric", "Value", "Status"],
        ["BMI", f"{measurement['bmi']:.1f}", get_bmi_status(measurement['bmi'])],
        ["Blood Pressure", f"{measurement['systolic']}/{measurement['diastolic']} mmHg", 
         get_bp_status(measurement['systolic'], measurement['diastolic'])],
        ["Glucose", f"{measurement['glucose']} mg/dL", get_glucose_status(measurement['glucose'])],
        ["Cholesterol", f"{measurement['cholesterol']} mg/dL", get_cholesterol_status(measurement['cholesterol'])],
        ["Smoking Status", measurement['smoking'], ""],
        ["Hypertension", "Yes" if measurement['has_hypertension'] else "No", ""],
        ["Diabetes", "Yes" if measurement['has_diabetes'] else "No", ""],
    ]
    
    health_table = Table(health_data, colWidths=[2*inch, 1.5*inch, 2.5*inch])
    health_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E4057')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    
    elements.append(health_table)
    elements.append(Spacer(1, 20))
    
    # AI Recommendations Section
    if recommendations:
        elements.append(Paragraph("AI-Generated Recommendations", heading_style))
        
        for i, rec in enumerate(recommendations[:5], 1):
            rec_text = rec.get('recommendation', rec.get('text', 'No recommendation available'))
            elements.append(Paragraph(f"{i}. {rec_text}", normal_style))
            elements.append(Spacer(1, 8))
        
        elements.append(Spacer(1, 20))
    
    # Clinical Notes Section
    elements.append(Paragraph("Clinical Interpretation", heading_style))
    
    if risk_score < 20:
        interpretation = "The patient demonstrates low stroke risk based on current health metrics. Continue regular monitoring and encourage maintenance of healthy lifestyle habits."
    elif risk_score < 50:
        interpretation = "The patient has moderate stroke risk. Close monitoring is recommended with consideration of preventive measures and lifestyle modifications."
    elif risk_score < 80:
        interpretation = "The patient presents high stroke risk. Immediate intervention is recommended, including treatment plan initiation and specialist consultation."
    else:
        interpretation = "The patient has critical stroke risk requiring urgent medical attention. Emergency protocols should be considered."
    
    elements.append(Paragraph(interpretation, normal_style))
    elements.append(Spacer(1, 30))
    
    # Footer
    elements.append(Paragraph("__________________________________________", normal_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("<i>This report was generated using AI-powered stroke risk assessment models. " +
                             "All clinical decisions should be made by qualified healthcare professionals " +
                             "considering the complete clinical picture.</i>", 
                             ParagraphStyle('Footer', parent=normal_style, fontSize=8, textColor=colors.grey)))
    
    # Build PDF
    doc.build(elements)
    
    buffer.seek(0)
    return buffer


def get_bmi_status(bmi):
    """Get BMI status classification"""
    if bmi < 18.5:
        return "Underweight"
    elif bmi < 25:
        return "Normal"
    elif bmi < 30:
        return "Overweight"
    else:
        return "Obese"


def get_bp_status(systolic, diastolic):
    """Get blood pressure status"""
    if systolic >= 180 or diastolic >= 120:
        return "Hypertensive Crisis"
    elif systolic >= 140 or diastolic >= 90:
        return "Hypertension"
    elif systolic >= 130 or diastolic >= 80:
        return "Stage 1 Hypertension"
    elif systolic >= 120:
        return "Elevated"
    else:
        return "Normal"


def get_glucose_status(glucose):
    """Get glucose status"""
    if glucose >= 200:
        return "Diabetes (Severe)"
    elif glucose >= 126:
        return "Diabetes Range"
    elif glucose >= 100:
        return "Pre-diabetes"
    else:
        return "Normal"


def get_cholesterol_status(cholesterol):
    """Get cholesterol status"""
    if cholesterol >= 240:
        return "High"
    elif cholesterol >= 200:
        return "Borderline High"
    else:
        return "Desirable"
