# Running PrescpHealth Locally

This guide will help you set up and run the PrescpHealth application in a local environment.

## Prerequisites

1. Python 3.11 or higher
2. Git (to clone the repository)

## Step-by-Step Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd prescphealth
```

### 2. Create a Virtual Environment (Recommended)

#### On Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

#### On macOS/Linux:
```bash
python -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r local_requirements.txt
```

### 4. Set Up Environment Variables

You'll need an OpenAI API key for the health recommendations feature.

#### On Windows:
```bash
set OPENAI_API_KEY=your_api_key_here
```

#### On macOS/Linux:
```bash
export OPENAI_API_KEY=your_api_key_here
```

Alternatively, create a `.env` file in the root directory:
```
OPENAI_API_KEY=your_api_key_here
```

### 5. Run the Application

```bash
streamlit run app.py
```

The application will start and automatically open in your default web browser at `http://localhost:8501`.

## First Time Setup

1. When you first run the application, you'll need to train the ML models
2. Click the "Generate Sample Data & Train Models" button in the sidebar
3. This will create synthetic training data and train the prediction models

## Using the Application

1. Add a new patient using the sidebar "Add New Patient" button
2. Fill in patient details and save
3. Add health measurements for the patient
4. View risk predictions and AI-powered health recommendations
5. Track health metrics over time with visualizations

## Database Information

In your local environment, the application will automatically use SQLite (file: `prescphealth.db`) for data storage. No additional database setup is required.

## Troubleshooting

### Missing Dependency Errors
If you encounter missing dependency errors, make sure all packages are installed:
```bash
pip install -r local_requirements.txt
```

### OpenAI API Key Issues
If you see errors related to the OpenAI API:
1. Check that your API key is valid
2. Ensure the environment variable is set correctly
3. Try running the application again

### Model Training Issues
If model training fails, try:
1. Delete the `models` directory (if it exists)
2. Restart the application
3. Try the "Generate Sample Data & Train Models" button again